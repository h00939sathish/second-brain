#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
second_brain.py - Multi-agent coordination hub + tiered memory engine.

Tiered memory:
  L0 = compact pointers ALWAYS injected into agent sessions (~2.2KB budget)
  L1 = this vault: git-backed markdown (claims, sessions, context notes)
  L2 = raw session transcripts (opaque, never read/written here)

Coordination layer:
  Sessions = agent presence + progress tracking (who's doing what)
  Context  = shared discoveries/decisions/blockers (lightweight notes)
  Claims   = long-term knowledge with truth lifecycle

Deterministic operations only. NO LLM. Zero daemons.

Design decisions (2026-08):
  - Atomic writes (tmp+rename); advisory file lock for concurrency
  - L0 budget: sessions first, then context, then claims (truncated)
  - session_search stays opaque: we store @session: links only
  - supersede chains validated on read; disputes record reason
  - Sweep: expire stale sessions (>24h), flag unreviewed claims
  - Windows/git-bash safe via pathlib

Commands:
  # Knowledge
  init                        create vault skeleton + config
  claim <text> [--status --confidence --source --tags]   add an L1 claim
  supersede <id> <newid>      mark <id> superseded by <newid> (chain-aware)
  dispute <id> --reason ".." [--by who]   mark disputed, keep evidence
  recall <query> [--tag] [--status] [--all]  deterministic recall + withheld report
  status                      counts by status, chain integrity, L0 budget
  sweep [--commit]            cron: expire stale, rebuild L0, git commit
  verify <id>                 chain integrity check for one claim
  related <id>                graph traversal for one claim

  # Coordination
  session-start --agent <name> [--project <p>] [--task <t>]
  session-update <id> --progress <text>
  session-end <id> [--summary <text>]
  sessions [--agent <a>] [--project <p>] [--active]
  post <text> [--project <p>] [--tags <t>] [--agent <a>]
  read [--project <p>] [--agent <a>] [--tag <t>] [--limit N]
  dashboard                   full multi-agent status view
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT", r"D:\projects\second-brain"))
META_DIR = "meta"
CLAIMS_DIR = "claims"
SESSIONS_DIR = "sessions"
CONTEXT_DIR = "context"
CONFIG_NAME = "config.json"
L0_NAME = "l0_pointers.md"
STATUSES = ("active", "superseded", "expired", "disputed")
WITHHELD_STATUSES = ("expired", "superseded", "disputed")
L0_BUDGET = 2200  # bytes, matches Hermes memory tool limit
SESSION_STALE_HOURS = 24  # mark active sessions stale after this
L0_MAX_LINE = 120  # max bytes per L0 pointer line (truncate beyond)


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def time_ago(ts_str):
    """Human-readable 'Xh ago' / 'Xm ago' from a timestamp string."""
    try:
        ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        delta = datetime.now(timezone.utc) - ts
        hours = int(delta.total_seconds() // 3600)
        mins = int(delta.total_seconds() // 60)
        if hours >= 24:
            return f"{hours // 24}d ago"
        if hours >= 1:
            return f"{hours}h ago"
        return f"{mins}m ago"
    except (ValueError, TypeError):
        return "?"


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
        "vault_version": 2,
        "sweep": {
            "expire_unreviewed_after_days": 120,
            "stale_after_days": 90,
        },
        "recall": {"withhold": list(WITHHELD_STATUSES)},
        "session": {"stale_after_hours": SESSION_STALE_HOURS},
        "context": {"default_limit": 20},
    }


def save_config(cfg):
    atomic_write(cfg_path(), json.dumps(cfg, indent=2) + "\n")


# ---- atomic write + lock (Windows-safe) ----
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


# ---- generic frontmatter parser ----
def parse_frontmatter(path: Path):
    """Parse a frontmatter markdown file. Returns {fm, body, raw, path} or None."""
    if not path.exists():
        return None
    txt = path.read_text(encoding="utf-8")
    parts = txt.split("---", 2)
    if len(parts) < 3:
        return None
    fm = {}
    for line in parts[1].strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip()
    body = parts[2].strip()
    return {"fm": fm, "body": body, "raw": txt, "path": path}


def frontmatter_block(fm, key_order=None):
    """Build a ---frontmatter--- block from a dict. key_order controls output order."""
    if key_order is None:
        key_order = list(fm.keys())
    lines = ["---"]
    for k in key_order:
        if fm.get(k) is not None:
            lines.append(f"{k}: {fm[k]}")
    # any keys not in key_order
    for k in fm:
        if k not in key_order and fm[k] is not None:
            lines.append(f"{k}: {fm[k]}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---- claim helpers ----
CLAIM_FM_ORDER = ("id", "claim", "status", "confidence", "created", "reviewed_at",
                  "source", "tags", "supersedes", "superseded_by", "disputed_by",
                  "dispute_reason")


def claim_path(cid):
    return VAULT / CLAIMS_DIR / (cid + ".md")


def get_claim(cid):
    p = claim_path(cid)
    rec = parse_frontmatter(p)
    if rec:
        rec["id"] = cid
    return rec


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


# ---- session helpers ----
SESSION_FM_ORDER = ("id", "agent", "project", "task", "status", "started", "updated", "ended")


def session_path(sid):
    return VAULT / SESSIONS_DIR / (sid + ".md")


def get_session(sid):
    p = session_path(sid)
    rec = parse_frontmatter(p)
    if rec:
        rec["id"] = sid
    return rec


def all_sessions():
    out = []
    d = VAULT / SESSIONS_DIR
    if d.exists():
        for p in sorted(d.glob("s-*.md")):
            s = get_session(p.stem)
            if s:
                out.append(s)
    return out


# ---- context helpers ----
CONTEXT_FM_ORDER = ("id", "agent", "project", "tags", "created")


def context_path(nid):
    return VAULT / CONTEXT_DIR / (nid + ".md")


def get_context_note(nid):
    p = context_path(nid)
    rec = parse_frontmatter(p)
    if rec:
        rec["id"] = nid
    return rec


def all_context_notes():
    out = []
    d = VAULT / CONTEXT_DIR
    if d.exists():
        for p in sorted(d.glob("ctx-*.md")):
            n = get_context_note(p.stem)
            if n:
                out.append(n)
    return out


# ---- git helpers ----
def git_commit(msg):
    subprocess.run(["git", "add", "-A"], cwd=VAULT, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg, "--allow-empty"],
                   cwd=VAULT, capture_output=True)


# ================ KNOWLEDGE COMMANDS ================

def cmd_init(args, cfg=None):
    for d in (CLAIMS_DIR, "decisions", "projects", "experiments", "people",
              SESSIONS_DIR, CONTEXT_DIR, META_DIR):
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
    readme_path = VAULT / "README.md"
    # only write README on first init, don't overwrite user edits
    if not readme_path.exists():
        atomic_write(readme_path, f"# Second Brain\n\nMulti-agent coordination hub. Vault: {VAULT}\n")
    if not (VAULT / ".git").exists():
        subprocess.run(["git", "init"], cwd=VAULT, capture_output=True)
    git_commit("init vault skeleton")
    print(f"vault initialised at {VAULT}")
    return 0


def cmd_claim(args, cfg):
    ts = now()  # capture once to avoid drift
    cid = datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    fm = {
        "id": cid,
        "claim": args.text,
        "status": args.status,
        "confidence": args.confidence,
        "created": ts,
        "reviewed_at": ts,
        "source": args.source or "",
        "tags": args.tags,
    }
    body = (f"**Claim:** {args.text}\n\n"
            f"**Evidence:** {args.source or '(none attached)'}\n\n"
            f"Created {ts}. Verify source before trusting; update `reviewed_at` on review.\n")
    # auto-link to existing claims sharing a tag (associative graph edges)
    if args.tags:
        mine = set(t.strip() for t in args.tags.split(",") if t.strip())
        rel = []
        for other in all_claims():
            if other["id"] == cid:
                continue
            their_tags = set(t.strip() for t in
                             (other["fm"].get("tags") or "").split(",") if t.strip())
            if mine & their_tags:
                rel.append(other["id"])
        if rel:
            body += "\n**Related:** " + " ".join(f"[[{r}]]" for r in sorted(rel)) + "\n"
    content = frontmatter_block(fm, CLAIM_FM_ORDER) + "\n" + body
    atomic_write(claim_path(cid), content)
    git_commit(f"claim {cid}: {args.text[:60]}")
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
    ts = now()
    old_body = c["body"] + f"\n\nSuperseded by [[{new}]] on {ts}.\n"
    new_body = n["body"] + f"\n\nSupersedes [[{old}]] (see superseded chain).\n"
    atomic_write(c["path"], frontmatter_block(c["fm"], CLAIM_FM_ORDER) + "\n" + old_body + "\n")
    atomic_write(n["path"], frontmatter_block(n["fm"], CLAIM_FM_ORDER) + "\n" + new_body + "\n")
    git_commit(f"supersede {old} -> {new}")
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
    atomic_write(c["path"], frontmatter_block(c["fm"], CLAIM_FM_ORDER) + "\n" + c["body"] + "\n")
    git_commit(f"dispute {args.id}: {args.reason or ''}")
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
    # L0 budget estimate
    l0_path = VAULT / META_DIR / L0_NAME
    l0_size = l0_path.stat().st_size if l0_path.exists() else 0
    # sessions
    sessions = all_sessions()
    active_sessions = [s for s in sessions if s["fm"].get("status") == "active"]
    # context
    notes = all_context_notes()
    print(f"claims: {len(claims)}  by status: {dict(counts)}")
    print(f"sessions: {len(sessions)} total, {len(active_sessions)} active")
    print(f"context notes: {len(notes)}")
    print(f"L0 pointer file: {l0_size}B / {L0_BUDGET}B budget "
          f"({'OK' if l0_size <= L0_BUDGET else 'OVER BUDGET'})")
    if issues:
        print("CHAIN ISSUES:")
        for i in issues:
            print("  " + i)
    else:
        print("chain integrity: OK")
    return 0


def cmd_verify(args, cfg):
    """Chain integrity check for one claim."""
    issues = chain_issues(args.id, set())
    if not issues:
        print("OK - chain clean")
        return 0
    for i in issues:
        print(i)
    return 1


def cmd_related(args, cfg):
    """Graph traversal: claims sharing a tag, a supersede edge, or a body [[link]]."""
    c = get_claim(args.id)
    if not c:
        print(f"claim {args.id} not found")
        return 1
    my_tags = set(t.strip() for t in (c["fm"].get("tags") or "").split(",") if t.strip())
    links = set(re.findall(r"\[\[([^\]|]+)", c["raw"])) | set(re.findall(r"\[\[([^\]|]+)", c["body"]))
    hits = {}
    for other in all_claims():
        if other["id"] == args.id:
            continue
        their_tags = set(t.strip() for t in (other["fm"].get("tags") or "").split(",") if t.strip())
        why = []
        if my_tags & their_tags:
            why.append("shared-tag:" + ",".join(sorted(my_tags & their_tags)))
        if other["id"] in links or other["id"] in (c["fm"].get("superseded_by") or ""):
            why.append("wikilink")
        if c["id"] in re.findall(r"\[\[([^\]|]+)\]\]", other["body"]):
            why.append("backlink")
        if why:
            hits[other["id"]] = why
    if not hits:
        print(f"no related claims to {args.id}")
        return 0
    print(f"== RELATED: {args.id} ==")
    for cid in sorted(hits):
        oc = get_claim(cid)
        print(f"  [[{cid}]]  ({', '.join(hits[cid])})  {oc['fm'].get('claim','')[:80]}")
    return 0


# ================ COORDINATION COMMANDS ================

def cmd_session_start(args, cfg):
    ts = now()
    sid = "s-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    fm = {
        "id": sid,
        "agent": args.agent,
        "project": args.project or "",
        "task": args.task or "",
        "status": "active",
        "started": ts,
        "updated": ts,
        "ended": "",
    }
    body = "## Progress\n"
    task_desc = args.task or "session started"
    body += f"- [{ts[11:16]}] {task_desc}\n"
    body += "\n## Outcomes\n(pending)\n"
    content = frontmatter_block(fm, SESSION_FM_ORDER) + "\n" + body
    atomic_write(session_path(sid), content)
    git_commit(f"session {sid}: {args.agent} starts on {args.project or 'unscoped'}")
    print(f"session {sid} started (agent={args.agent}, project={args.project or 'none'})")
    return 0


def cmd_session_update(args, cfg):
    s = get_session(args.id)
    if not s:
        print(f"session {args.id} not found")
        return 1
    if s["fm"].get("status") != "active":
        print(f"session {args.id} is not active (status={s['fm'].get('status')})")
        return 1
    ts = now()
    s["fm"]["updated"] = ts
    # append progress line before "## Outcomes"
    body = s["body"]
    progress_line = f"- [{ts[11:16]}] {args.progress}\n"
    if "## Outcomes" in body:
        body = body.replace("## Outcomes", progress_line + "\n## Outcomes", 1)
    else:
        body += "\n" + progress_line
    atomic_write(s["path"], frontmatter_block(s["fm"], SESSION_FM_ORDER) + "\n" + body + "\n")
    # no git commit for updates — too noisy. sweep or session-end commits.
    print(f"session {args.id} updated")
    return 0


def cmd_session_end(args, cfg):
    s = get_session(args.id)
    if not s:
        print(f"session {args.id} not found")
        return 1
    ts = now()
    s["fm"]["status"] = "ended"
    s["fm"]["updated"] = ts
    s["fm"]["ended"] = ts
    body = s["body"]
    summary = args.summary or "(no summary)"
    if "## Outcomes" in body:
        body = body.replace("## Outcomes\n(pending)", f"## Outcomes\n{summary}")
        body = body.replace("## Outcomes", f"## Outcomes\n{summary}", 1)
    else:
        body += f"\n## Outcomes\n{summary}\n"
    atomic_write(s["path"], frontmatter_block(s["fm"], SESSION_FM_ORDER) + "\n" + body + "\n")
    git_commit(f"session-end {args.id}: {s['fm'].get('agent', '?')}")
    print(f"session {args.id} ended")
    return 0


def cmd_sessions(args, cfg):
    sessions = all_sessions()
    filtered = []
    for s in sessions:
        if args.agent and s["fm"].get("agent") != args.agent:
            continue
        if args.project and s["fm"].get("project") != args.project:
            continue
        if args.active and s["fm"].get("status") != "active":
            continue
        filtered.append(s)
    # show newest first
    filtered.reverse()
    print(f"== SESSIONS == ({len(filtered)} shown)")
    for s in filtered:
        fm = s["fm"]
        age = time_ago(fm.get("started", ""))
        status = fm.get("status", "?")
        agent = fm.get("agent", "?")
        project = fm.get("project", "") or "unscoped"
        task = fm.get("task", "")
        marker = "🟢" if status == "active" else "⚪" if status == "ended" else "🟡"
        print(f"  {marker} [{status}] {agent} → {project}: {task} ({age})")
        print(f"      id: {s['id']}")
    return 0


def cmd_post(args, cfg):
    ts = now()
    nid = "ctx-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    fm = {
        "id": nid,
        "agent": args.agent or "unknown",
        "project": args.project or "",
        "tags": args.tags or "",
        "created": ts,
    }
    body = args.text + "\n"
    content = frontmatter_block(fm, CONTEXT_FM_ORDER) + "\n" + body
    atomic_write(context_path(nid), content)
    git_commit(f"context {nid}: {args.text[:60]}")
    print(f"context note {nid} posted (agent={args.agent or 'unknown'}, project={args.project or 'none'})")
    return 0


def cmd_read(args, cfg):
    notes = all_context_notes()
    filtered = []
    for n in notes:
        if args.agent and n["fm"].get("agent") != args.agent:
            continue
        if args.project and n["fm"].get("project") != args.project:
            continue
        if args.tag:
            note_tags = set(t.strip() for t in (n["fm"].get("tags") or "").split(",") if t.strip())
            if args.tag not in note_tags:
                continue
        filtered.append(n)
    # newest first
    filtered.reverse()
    limit = args.limit or cfg.get("context", {}).get("default_limit", 20)
    filtered = filtered[:limit]
    print(f"== CONTEXT == ({len(filtered)} shown)")
    for n in filtered:
        fm = n["fm"]
        age = time_ago(fm.get("created", ""))
        agent = fm.get("agent", "?")
        project = fm.get("project", "") or "—"
        tags = fm.get("tags", "")
        # show first line of body as preview
        preview = n["body"].split("\n")[0][:100] if n["body"] else ""
        print(f"  [{agent}] ({project}) {preview} [{age}]")
        if tags:
            print(f"      tags: {tags}")
        print(f"      id: {n['id']}")
    return 0


def cmd_dashboard(args, cfg):
    """Full multi-agent situational awareness."""
    # active sessions
    sessions = all_sessions()
    active = [s for s in sessions if s["fm"].get("status") == "active"]
    recent_ended = [s for s in sessions if s["fm"].get("status") == "ended"][-5:]

    # recent context
    notes = all_context_notes()
    recent_notes = list(reversed(notes))[:10]

    # vault health
    claims = all_claims()
    active_claims = [c for c in claims if c["fm"].get("status", "active") == "active"]

    print("╔══════════════════════════════════════╗")
    print("║      SECOND BRAIN — DASHBOARD        ║")
    print("╚══════════════════════════════════════╝")
    print()

    # active sessions
    print(f"▸ ACTIVE SESSIONS ({len(active)})")
    if active:
        for s in active:
            fm = s["fm"]
            age = time_ago(fm.get("started", ""))
            print(f"  🟢 {fm.get('agent','?')} → {fm.get('project','') or 'unscoped'}: "
                  f"{fm.get('task','')} ({age})")
    else:
        print("  (none)")
    print()

    # recently ended
    if recent_ended:
        print(f"▸ RECENTLY ENDED ({len(recent_ended)})")
        for s in reversed(recent_ended):
            fm = s["fm"]
            age = time_ago(fm.get("ended", fm.get("updated", "")))
            print(f"  ⚪ {fm.get('agent','?')} → {fm.get('project','') or 'unscoped'}: "
                  f"{fm.get('task','')} (ended {age})")
        print()

    # recent context
    print(f"▸ RECENT CONTEXT ({len(recent_notes)})")
    if recent_notes:
        for n in recent_notes[:5]:
            fm = n["fm"]
            age = time_ago(fm.get("created", ""))
            preview = n["body"].split("\n")[0][:80] if n["body"] else ""
            print(f"  [{fm.get('agent','?')}] {preview} ({age})")
    else:
        print("  (none)")
    print()

    # vault health
    l0_path = VAULT / META_DIR / L0_NAME
    l0_size = l0_path.stat().st_size if l0_path.exists() else 0
    print(f"▸ VAULT: {len(active_claims)} active claims, "
          f"L0={l0_size}B/{L0_BUDGET}B")
    print()
    return 0


# ================ SWEEP ================

def cmd_sweep(args, cfg):
    ts = now()
    sweep_cfg = cfg.get("sweep", {})
    exp_unreviewed = int(sweep_cfg.get("expire_unreviewed_after_days", 120))
    changed = []

    # ---- 1. Stale session expiry ----
    stale_hours = int(cfg.get("session", {}).get("stale_after_hours", SESSION_STALE_HOURS))
    cutoff = datetime.now(timezone.utc) - timedelta(hours=stale_hours)
    for s in all_sessions():
        if s["fm"].get("status") != "active":
            continue
        try:
            updated = datetime.strptime(s["fm"].get("updated", s["fm"].get("started", "")),
                                        "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            updated = None
        if updated and updated < cutoff:
            s["fm"]["status"] = "stale"
            s["fm"]["updated"] = ts
            body = s["body"]
            if "## Outcomes" in body:
                body = body.replace("## Outcomes\n(pending)",
                                    f"## Outcomes\n(stale — auto-expired by sweep {ts})")
            atomic_write(s["path"], frontmatter_block(s["fm"], SESSION_FM_ORDER) + "\n" + body + "\n")
            changed.append((s["id"], f"session stale (agent={s['fm'].get('agent','?')})"))

    # ---- 2. Claim staleness flags ----
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
            # check if already flagged to avoid accumulation
            if "> sweep" not in c["body"]:
                body = c["body"] + f"\n\n> sweep {ts}: unreviewed {age_days}d - needs review\n"
                atomic_write(c["path"], frontmatter_block(c["fm"], CLAIM_FM_ORDER) + "\n" + body + "\n")
            changed.append((c["id"], f"stale ({age_days}d) - flagged for review"))

    # ---- 3. Rebuild L0 pointer set (3 sections, budget-aware) ----
    l0_lines = [
        f"# Brain (auto-generated {ts})",
        "# Call brain_session_start on session begin. brain_recall for knowledge.",
        "",
    ]

    # Section 1: Active sessions
    active_sessions = [s for s in all_sessions() if s["fm"].get("status") == "active"]
    if active_sessions:
        l0_lines.append("## Active")
        for s in active_sessions[:5]:
            fm = s["fm"]
            agent = fm.get("agent", "?")
            proj = fm.get("project", "") or "unscoped"
            task = fm.get("task", "")[:60]
            age = time_ago(fm.get("started", ""))
            l0_lines.append(f"- {agent} → {proj}: {task} ({age})")
        l0_lines.append("")

    # Section 2: Recent context (newest first, up to 5)
    recent_ctx = list(reversed(all_context_notes()))[:5]
    if recent_ctx:
        l0_lines.append("## Context")
        for n in recent_ctx:
            fm = n["fm"]
            agent = fm.get("agent", "?")
            proj = fm.get("project", "")
            preview = n["body"].split("\n")[0][:80] if n["body"] else ""
            proj_tag = f" ({proj})" if proj else ""
            l0_lines.append(f"- [{agent}] {preview}{proj_tag}")
        l0_lines.append("")

    # Section 3: Active claims (truncated to fit budget)
    active_claims = [c for c in all_claims()
                     if c["fm"].get("status", "active") == "active"]
    header_size = len("\n".join(l0_lines).encode("utf-8"))
    remaining = L0_BUDGET - header_size - 50  # 50B margin
    l0_lines.append(f"## Knowledge ({len(active_claims)} active)")
    for c in sorted(active_claims, key=lambda x: x["id"], reverse=True):
        claim_text = c["fm"].get("claim", "")
        if len(claim_text) > L0_MAX_LINE:
            claim_text = claim_text[:L0_MAX_LINE - 3] + "..."
        line = f"- [{c['fm'].get('status')}] {claim_text} [[{c['id']}]]"
        line_size = len(line.encode("utf-8")) + 1  # +1 for newline
        if remaining - line_size < 0:
            l0_lines.append(f"- ... and {len(active_claims)} more (run brain_recall)")
            break
        l0_lines.append(line)
        remaining -= line_size

    atomic_write(VAULT / META_DIR / L0_NAME, "\n".join(l0_lines) + "\n")

    # ---- report ----
    print(f"sweep: {len(changed)} items flagged")
    for cid, why in changed:
        print(f"  {cid}: {why}")
    l0_size = (VAULT / META_DIR / L0_NAME).stat().st_size
    print(f"L0 pointer set rebuilt: {l0_size}B / {L0_BUDGET}B "
          f"({'OK' if l0_size <= L0_BUDGET else 'OVER'})")
    if args.commit:
        git_commit(f"sweep {ts}: {len(changed)} flagged")
        print("committed")
    return 0


# ================ CLI ================

def main():
    ap = argparse.ArgumentParser(description="Second Brain — multi-agent coordination hub")
    sub = ap.add_subparsers(dest="cmd")

    # -- knowledge commands --
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

    p_rel = sub.add_parser("related")
    p_rel.add_argument("id")

    p_sw = sub.add_parser("sweep")
    p_sw.add_argument("--commit", action="store_true")

    # -- coordination commands --
    p_ss = sub.add_parser("session-start")
    p_ss.add_argument("--agent", required=True)
    p_ss.add_argument("--project", default="")
    p_ss.add_argument("--task", default="")

    p_su = sub.add_parser("session-update")
    p_su.add_argument("id")
    p_su.add_argument("--progress", required=True)

    p_se = sub.add_parser("session-end")
    p_se.add_argument("id")
    p_se.add_argument("--summary", default="")

    p_sl = sub.add_parser("sessions")
    p_sl.add_argument("--agent", default="")
    p_sl.add_argument("--project", default="")
    p_sl.add_argument("--active", action="store_true")

    p_post = sub.add_parser("post")
    p_post.add_argument("text")
    p_post.add_argument("--project", default="")
    p_post.add_argument("--tags", default="")
    p_post.add_argument("--agent", default="")

    p_read = sub.add_parser("read")
    p_read.add_argument("--project", default="")
    p_read.add_argument("--agent", default="")
    p_read.add_argument("--tag", default="")
    p_read.add_argument("--limit", type=int, default=0)

    sub.add_parser("dashboard")

    args = ap.parse_args()
    if not args.cmd:
        ap.print_help()
        return 1

    if args.cmd != "init" and not (VAULT / META_DIR).exists():
        print(f"vault not initialised: {VAULT} (run: python engine.py init)")
        return 1

    # INVARIANT: Handlers are called under lock() by both main() and MCP _run().
    # Handlers MUST NOT acquire lock() themselves — msvcrt.locking is not reentrant
    # on Windows, so nested lock() calls will deadlock.
    with lock():
        cfg = load_config()
        handlers = {
            "init": cmd_init, "claim": cmd_claim, "supersede": cmd_supersede,
            "dispute": cmd_dispute, "recall": cmd_recall, "status": cmd_status,
            "sweep": cmd_sweep, "verify": cmd_verify, "related": cmd_related,
            "session-start": cmd_session_start, "session-update": cmd_session_update,
            "session-end": cmd_session_end, "sessions": cmd_sessions,
            "post": cmd_post, "read": cmd_read, "dashboard": cmd_dashboard,
        }
        return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
