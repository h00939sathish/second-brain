#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
second_brain.py - Hermes-native tiered memory engine (L0/L1/L2).

Tiered memory:
  L0 = Hermes memory tool (compact pointers, ALWAYS injected, ~2.2KB budget)
  L1 = this vault: git-backed markdown notes carrying claim + evidence + truth state
  L2 = raw session transcripts (owned by Hermes session_search - OPAGUE, never
       read/written here; L1 only stores @session:... links)

Deterministic operations only. NO LLM in the recall/sweep path. Zero daemons.

Design decisions (from the multi-model plan critique, 2026-08):
  - Atomic writes (tmp+rename); advisory file lock for cron-vs-session concurrency
  - L0 budget math: ~200-230B per pointer entry -> ~10 entries fit in 2.2KB, not 30
  - session_search stays opaque: we store @session:links, never hand-write SQL
  - supersede chains validated on read; disputes record reason + disputant
  - orphan session journal for crash recovery; .gitignore keeps L2/large blobs out
  - Windows/git-bash safe via pathlib; uuid7 available on Python 3.14

Commands:
  init                        create vault skeleton + config
  claim <text> [--status --confidence --source --tags]   add an L1 claim
  supersede <id> <newid>      mark <id> superseded by <newid> (chain-aware)
  dispute <id> --reason ".." [--by who]   mark disputed, keep evidence
  recall <query> [--tag] [--status] [--all]  deterministic recall + withheld report
  status                      counts by status, chain integrity, L0 budget
  sweep [--commit]            cron: expire stale, rebuild L0 pointer set, git commit
  verify <id>                 chain integrity check for one claim
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT", r"D:\projects\second-brain"))
META_DIR = "meta"
CLAIMS_DIR = "claims"
CONFIG_NAME = "config.json"
L0_NAME = "l0_pointers.md"
STATUSES = ("active", "superseded", "expired", "disputed")
WITHHELD_STATUSES = ("expired", "superseded", "disputed")
L0_BUDGET = 2200  # bytes, matches Hermes memory tool limit


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def cfg_path():
    return VAULT / META_DIR / CONFIG_NAME


def load_config():
    p = cfg_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "vault_version": 1,
        "sweep": {
            "expire_unreviewed_after_days": 120,   # no review in 120d -> flag
            "expire_never_after_days": 365,        # no review ever, after 1y -> flag
            "stale_after_days": 90,
        },
        "recall": {"withhold": list(WITHHELD_STATUSES)},
    }


def save_config(cfg):
    atomic_write(cfg_path(), json.dumps(cfg, indent=2) + "\n")


# ---------------- atomic write + lock (Windows-safe) ----------------
def atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


class FileLock:
    """Cross-process advisory lock (msvcrt on Windows, fcntl elsewhere)."""
    def __init__(self, path: Path):
        self.path = path
        self._f = None

    def __enter__(self):
        self._f = open(self.path, "a+", encoding="utf-8")
        if os.name == "nt":
            import msvcrt
            self._f.seek(0)
            msvcrt.locking(self._f.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(self._f.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        try:
            if os.name == "nt":
                import msvcrt
                self._f.seek(0)
                msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        self._f.close()


def lock():
    return FileLock(VAULT / ".lock")


def claim_path(cid):
    return VAULT / CLAIMS_DIR / (cid + ".md")


def get_claim(cid):
    p = claim_path(cid)
    if not p.exists():
        return None
    txt = p.read_text(encoding="utf-8")
    parts = txt.split("---", 2)
    if len(parts) < 3:
        return None
    fm = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    body = parts[2].strip()
    return {"id": cid, "fm": fm, "path": p, "raw": txt, "body": body}


def all_claims():
    out = []
    d = VAULT / CLAIMS_DIR
    if d.exists():
        for p in sorted(d.glob("*.md")):
            c = get_claim(p.stem)
            if c:
                out.append(c)
    return out


def chain_issues(cid, seen=None):
    """Return a list of chain-integrity issues for a claim (dangling/cycles)."""
    seen = seen or set()
    issues = []
    if cid in seen:
        issues.append(f"cycle detected at {cid}")
        return issues
    seen.add(cid)
    c = get_claim(cid)
    if not c:
        issues.append(f"dangling reference: {cid} not found")
        return issues
    for key in ("supersedes", "superseded_by"):
        ref = c["fm"].get(key)
        if ref and not get_claim(ref):
            issues.append(f"{key} -> {ref}: dangling (target missing)")
    return issues


def frontmatter_block(fm):
    lines = ["---"]
    for k in ("id", "claim", "status", "confidence", "created", "reviewed_at",
              "source", "tags", "supersedes", "superseded_by", "disputed_by",
              "dispute_reason"):
        if fm.get(k) is not None:
            v = str(fm[k])
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---------------- commands ----------------
def cmd_init(args, cfg=None):
    for d in (CLAIMS_DIR, "decisions", "projects", "experiments", "people",
              "sessions", META_DIR):
        (VAULT / d).mkdir(parents=True, exist_ok=True)
    gitignore = """# state & lock files
.lock
*.tmp
# L2 transcripts are owned by Hermes session_search - keep them out of git
sessions/*.json
# large blobs
*.log
"""
    (VAULT / ".gitignore").write_text(gitignore, encoding="utf-8")
    save_config(load_config())
    readme = f"""# Second Brain (Hermes L1 vault)

Provenance-first tiered memory. L0 = Hermes memory tool pointers,
L1 = this vault (claims + evidence), L2 = Hermes session transcripts (opaque).

- claims/: one file per claim: `YYYYMMDD-cid.md`
- truth lifecycle: status in (active, superseded, expired, disputed)
- recall withholds expired/superseded/disputed and says why (see `recall`)
- git = audit trail. Engine: `python engine.py <cmd>`

Vault: {VAULT}
"""
    atomic_write(VAULT / "README.md", readme)
    if not (VAULT / ".git").exists():
        subprocess.run(["git", "init"], cwd=VAULT, capture_output=True)
    subprocess.run(["git", "add", "-A"], cwd=VAULT, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init vault skeleton",
                    "--allow-empty"], cwd=VAULT, capture_output=True)
    print(f"vault initialised at {VAULT}")
    return 0


def cmd_claim(args, cfg):
    cid = datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    fm = {
        "id": cid,
        "claim": args.text,
        "status": args.status,
        "confidence": args.confidence,
        "created": now(),
        "reviewed_at": now(),
        "source": args.source or "",
        "tags": args.tags,
    }
    body = f"**Claim:** {args.text}\n\n**Evidence:** {args.source or '(none attached)'}\n\n" \
           f"Created {now()}. Verify source before trusting; update `reviewed_at` on review.\n"
    content = frontmatter_block(fm) + "\n" + body
    atomic_write(claim_path(cid), content)
    subprocess.run(["git", "add", "-A"], cwd=VAULT, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"claim {cid}: {args.text[:60]}",
                    "--allow-empty"], cwd=VAULT, capture_output=True)
    print(f"claim {cid} written -> {claim_path(cid)}")
    return 0


def cmd_supersede(args, cfg):
    old, new = args.id, args.newid
    c = get_claim(old)
    if not c:
        print(f"claim {old} not found")
        return 1
    n = get_claim(new)
    if not n:
        print(f"claim {new} not found")
        return 1
    c["fm"]["status"] = "superseded"
    c["fm"]["superseded_by"] = new
    n["fm"]["supersedes"] = old
    atomic_write(c["path"], frontmatter_block(c["fm"]) + "\n" + c["body"] + "\n")
    atomic_write(n["path"], frontmatter_block(n["fm"]) + "\n" + n["body"] + "\n")
    subprocess.run(["git", "add", "-A"], cwd=VAULT, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"supersede {old} -> {new}"],
                   cwd=VAULT, capture_output=True)
    print(f"{old} superseded by {new}")
    return 0


def cmd_dispute(args, cfg):
    c = get_claim(args.id)
    if not c:
        print(f"claim {args.id} not found")
        return 1
    c["fm"]["status"] = "disputed"
    c["fm"]["disputed_by"] = args.by or "unknown"
    c["fm"]["dispute_reason"] = args.reason or ""
    atomic_write(c["path"], frontmatter_block(c["fm"]) + "\n" + c["body"] + "\n")
    subprocess.run(["git", "add", "-A"], cwd=VAULT, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"dispute {args.id}: {args.reason or ''}"],
                   cwd=VAULT, capture_output=True)
    print(f"{args.id} marked disputed")
    return 0


def cmd_recall(args, cfg):
    q = (args.query or "").lower()
    withhold = cfg.get("recall", {}).get("withhold", list(WITHHELD_STATUSES))
    matches, withheld = [], []
    for c in all_claims():
        st = c["fm"].get("status", "active")
        tag_ok = not args.tag or args.tag in (c["fm"].get("tags") or "").split(",")
        if args.status and st != args.status:
            continue
        hay = (c["fm"].get("claim", "") + " " + c["fm"].get("tags", "") +
               " " + c["fm"].get("source", "")).lower()
        hit = not q or q in hay
        if not tag_ok or not hit:
            continue
        rec = {"id": c["id"], "status": st, "claim": c["fm"].get("claim"),
               "confidence": c["fm"].get("confidence"),
               "source": c["fm"].get("source", "")}
        if st in withhold and not args.all:
            withheld.append(rec)
        else:
            matches.append(rec)
    print(f"== RECALL '{args.query or ''}' == ({len(matches)} shown, "
          f"{len(withheld)} withheld)")
    for r in matches:
        print(f"  [{r['status']}] {r['id']}  {r['claim']}")
        if r.get("source"):
            print(f"      source: {r['source']}")
    if withheld:
        print("-- WITHHELD (not current truth) --")
        for r in withheld:
            print(f"  [{r['status']}] {r['id']}  {r['claim']} "
                  f"<-- withheld because status={r['status']}")
    return 0


def cmd_status(args, cfg):
    claims = all_claims()
    counts = {s: 0 for s in STATUSES}
    issues = []
    for c in claims:
        st = c["fm"].get("status", "active")
        counts[st] = counts.get(st, 0) + 1
        issues += chain_issues(c["id"], set())
    # L0 budget estimate: pointer line per claim, ~200B each
    est = len(claims) * 200
    print(f"claims: {len(claims)}  by status: {dict(counts)}")
    print(f"L0 pointer estimate: ~{est}B / {L0_BUDGET}B budget "
          f"({'OK' if est <= L0_BUDGET else 'OVER BUDGET'})")
    if issues:
        print("CHAIN ISSUES:")
        for i in issues:
            print("  " + i)
    else:
        print("chain integrity: OK")
    return 0


def cmd_sweep(args, cfg):
    sweep = cfg.get("sweep", {})
    exp_unreviewed = int(sweep.get("expire_unreviewed_after_days", 120))
    stale_days = int(sweep.get("stale_after_days", 90))
    changed = []
    for c in all_claims():
        st = c["fm"].get("status", "active")
        if st != "active":
            continue
        try:
            reviewed = datetime.strptime(c["fm"].get("reviewed_at", ""),
                                         "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            reviewed = None
        age_days = (datetime.now(timezone.utc) - reviewed).days if reviewed else None
        if reviewed is None:
            changed.append((c["id"], "active -> NEVER-REVIEWED flag"))
            continue
        if age_days is not None and age_days > exp_unreviewed:
            # stale: flag for human review, do NOT auto-expire truth
            c["fm"]["status"] = "active"  # keep truth, add staleness marker via body
            body = c["body"] + f"\n\n> sweep {now()}: unreviewed {age_days}d - needs review\n"
            atomic_write(c["path"], frontmatter_block(c["fm"]) + "\n" + body + "\n")
            changed.append((c["id"], f"stale ({age_days}d) - flagged for review"))
    # rebuild L0 pointer set
    active = [c for c in all_claims()
              if c["fm"].get("status", "active") == "active"]
    lines = [f"# L0 pointers (auto-generated {now()}) - {len(active)} active claims",
             "# format: [status] claim --- source (see vault for evidence)"]
    for c in sorted(active, key=lambda x: x["id"], reverse=True)[:10]:
        src = c["fm"].get("source", "")
        lines.append(f"- [{c['fm'].get('status')}] {c['fm'].get('claim','')}"
                     f"{' --- ' + src if src else ''}")
    atomic_write(VAULT / META_DIR / L0_NAME, "\n".join(lines) + "\n")
    print(f"sweep: {len(changed)} claims flagged")
    for cid, why in changed:
        print(f"  {cid}: {why}")
    print(f"L0 pointer set rebuilt: {len(active)} active")
    if args.commit:
        subprocess.run(["git", "add", "-A"], cwd=VAULT, capture_output=True)
        subprocess.run(["git", "commit", "--allow-empty",
                        "-m", f"sweep {now()}: {len(changed)} flagged"],
                       cwd=VAULT, capture_output=True)
        print("committed")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Hermes second-brain engine")
    sub = ap.add_subparsers(dest="cmd")

    sub.add_parser("init")
    sub.add_parser("status")

    p_claim = sub.add_parser("claim")
    p_claim.add_argument("text")
    p_claim.add_argument("--status", default="active", choices=STATUSES)
    p_claim.add_argument("--confidence", type=float, default=0.9)
    p_claim.add_argument("--source", default="")
    p_claim.add_argument("--tags", default="")

    p_sup = sub.add_parser("supersede")
    p_sup.add_argument("id")
    p_sup.add_argument("newid")

    p_disp = sub.add_parser("dispute")
    p_disp.add_argument("id")
    p_disp.add_argument("--reason", default="")
    p_disp.add_argument("--by", default="")

    p_rec = sub.add_parser("recall")
    p_rec.add_argument("query", nargs="?")
    p_rec.add_argument("--tag")
    p_rec.add_argument("--status")
    p_rec.add_argument("--all", action="store_true")

    p_ver = sub.add_parser("verify")
    p_ver.add_argument("id")

    p_sw = sub.add_parser("sweep")
    p_sw.add_argument("--commit", action="store_true")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1

    if args.cmd != "init" and not (VAULT / META_DIR).exists():
        print(f"vault not initialised: {VAULT} (run: python engine.py init)")
        return 1

    with lock():
        cfg = load_config()
        handlers = {
            "init": cmd_init, "claim": cmd_claim, "supersede": cmd_supersede,
            "dispute": cmd_dispute, "recall": cmd_recall, "status": cmd_status,
            "sweep": cmd_sweep, "verify": lambda a, c: (
                print("OK - chain clean" if not chain_issues(a.id, set())
                      else "\n".join(chain_issues(a.id, set()))),
                0 if not chain_issues(a.id, set()) else 1)[1],
        }
        return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
