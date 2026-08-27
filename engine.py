#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
second_brain.py - Multi-agent coordination hub + tiered memory engine.

Tiered memory:
  L0 = compact pointers ALWAYS injected into agent sessions (~2.2KB budget)
  L1 = this vault: git-backed markdown (claims, sessions, context notes)
  L2 = raw session transcripts (opaque, never read/written here)

Coordination layer:
  Sessions = agent presence, branch/worktree tracking, file reservations & handoffs
  Context  = shared discoveries/decisions/blockers (with TTL & promotion to claims)
  Claims   = long-term knowledge with truth lifecycle & SQLite FTS5 (BM25) search

Deterministic operations only. Zero external dependencies (uses standard library).

Commands:
  # Knowledge & Claims
  init                        create vault skeleton + config
  claim <text> [--status --confidence --source --tags]   add an L1 claim
  supersede <id> <newid>      mark <id> superseded by <newid> (chain-aware)
  dispute <id> --reason ".." [--by who]   mark disputed, keep evidence
  recall <query> [--tag] [--status] [--all]  deterministic BM25 recall + withheld report
  promote <context-id> [--confidence --tags]  promote context note to permanent claim
  status                      counts by status, chain integrity, L0 budget
  sweep [--commit]            cron: expire stale, archive TTL notes, rebuild L0, git commit
  verify <id>                 chain integrity check for one claim
  related <id>                graph traversal for one claim

  # Coordination & Concurrency
  session-start --agent <name> [--project <p>] [--task <t>] [--branch <b>] [--worktree <w>] [--files <f1,f2>] [--lease <mins>]
  session-update <id> [--progress <text>] [--files <f1,f2>] [--extend-lease <mins>]
  session-end <id> [--summary <text>] [--target-agent <a>] [--next-steps <s>] [--modified-files <f1,f2>] [--test-status <t>]
  sessions [--agent <a>] [--project <p>] [--active]
  reserve <session-id> --files <f1,f2> [--lease <mins>]
  check-files --files <f1,f2> [--project <p>]
  post <text> [--project <p>] [--tags <t>] [--agent <a>]
  read [--query <q>] [--project <p>] [--agent <a>] [--tag <t>] [--limit N]
  dashboard                   full multi-agent status view
"""
import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Force UTF-8 on Windows console
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT", r"D:\projects\second-brain"))
META_DIR = "meta"
CLAIMS_DIR = "claims"
SESSIONS_DIR = "sessions"
CONTEXT_DIR = "context"
CONTEXT_ARCHIVE_DIR = "context/archive"
CONFIG_NAME = "config.json"
L0_NAME = "l0_pointers.md"
DB_NAME = "search_index.db"

STATUSES = ("active", "superseded", "expired", "disputed")
WITHHELD_STATUSES = ("expired", "superseded", "disputed")
L0_BUDGET = 2200  # bytes, matches Hermes memory tool limit
SESSION_STALE_HOURS = 24  # mark active sessions stale after this
DEFAULT_LEASE_MINS = 30  # default file lease duration in minutes
CONTEXT_TTL_DAYS = 7  # auto-archive context notes older than this
L0_MAX_LINE = 120  # max bytes per L0 pointer line


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
        "vault_version": 3,
        "sweep": {
            "expire_unreviewed_after_days": 120,
            "stale_after_days": 90,
        },
        "recall": {"withhold": list(WITHHELD_STATUSES)},
        "session": {
            "stale_after_hours": SESSION_STALE_HOURS,
            "default_lease_mins": DEFAULT_LEASE_MINS,
        },
        "context": {
            "default_limit": 20,
            "ttl_days": CONTEXT_TTL_DAYS,
        },
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
    """Build a ---frontmatter--- block from a dict."""
    if key_order is None:
        key_order = list(fm.keys())
    lines = ["---"]
    for k in key_order:
        if fm.get(k) is not None:
            lines.append(f"{k}: {fm[k]}")
    for k in fm:
        if k not in key_order and fm[k] is not None:
            lines.append(f"{k}: {fm[k]}")
    lines.append("---")
    return "\n".join(lines) + "\n"


# ---- SQLite FTS5 (BM25) Fast Search Engine ----
def get_db_path():
    return VAULT / META_DIR / DB_NAME


def init_search_db():
    """Initializes SQLite FTS5 virtual tables."""
    db_path = get_db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS claims_fts USING fts5(
            id UNINDEXED,
            claim,
            tags,
            source,
            status UNINDEXED,
            confidence UNINDEXED,
            body
        );
    """)
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS context_fts USING fts5(
            id UNINDEXED,
            agent,
            project,
            tags,
            created UNINDEXED,
            body
        );
    """)
    conn.commit()
    return conn


def reindex_all_search():
    """Syncs the SQLite FTS5 index from the markdown files (Markdown is source of truth)."""
    conn = init_search_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM claims_fts;")
    for c in all_claims():
        fm = c["fm"]
        cur.execute(
            "INSERT INTO claims_fts (id, claim, tags, source, status, confidence, body) VALUES (?, ?, ?, ?, ?, ?, ?);",
            (c["id"], fm.get("claim", ""), fm.get("tags", ""), fm.get("source", ""),
             fm.get("status", "active"), fm.get("confidence", "0.9"), c["body"])
        )
    cur.execute("DELETE FROM context_fts;")
    for n in all_context_notes(include_archived=False):
        fm = n["fm"]
        cur.execute(
            "INSERT INTO context_fts (id, agent, project, tags, created, body) VALUES (?, ?, ?, ?, ?, ?);",
            (n["id"], fm.get("agent", ""), fm.get("project", ""), fm.get("tags", ""),
             fm.get("created", ""), n["body"])
        )
    conn.commit()
    conn.close()


def search_claims_fts(query: str, status: str = "", tag: str = ""):
    """Searches claims using FTS5 BM25 ranking. Falls back to substring scan if FTS syntax error."""
    if not query and not status and not tag:
        return all_claims()

    conn = init_search_db()
    cur = conn.cursor()
    results = []

    # Clean query for FTS5 (escape quotes or split tokens)
    clean_q = query.strip()
    if clean_q:
        # wrap individual tokens if not containing special operators
        tokens = [t for t in re.split(r'\s+', clean_q) if t]
        fts_query = " ".join(f'"{t}"' if not any(op in t for op in ("AND", "OR", "NOT", "*")) else t for t in tokens)
    else:
        fts_query = ""

    try:
        if fts_query:
            cur.execute("""
                SELECT id, rank FROM claims_fts
                WHERE claims_fts MATCH ?
                ORDER BY rank;
            """, (fts_query,))
            rows = cur.fetchall()
            id_ranks = {r[0]: r[1] for r in rows}
        else:
            id_ranks = None
    except sqlite3.OperationalError:
        # Fallback to simple matching if syntax error in query
        id_ranks = None

    conn.close()

    for c in all_claims():
        cid = c["id"]
        fm = c["fm"]
        st = fm.get("status", "active")
        tags_list = [t.strip() for t in (fm.get("tags") or "").split(",") if t.strip()]

        if status and st != status:
            continue
        if tag and tag not in tags_list:
            continue

        if id_ranks is not None:
            if cid in id_ranks:
                results.append((c, id_ranks[cid]))
        elif clean_q:
            # Fallback substring search
            hay = (fm.get("claim", "") + " " + fm.get("tags", "") + " " + fm.get("source", "") + " " + c["body"]).lower()
            if clean_q.lower() in hay:
                results.append((c, 0.0))
        else:
            results.append((c, 0.0))

    if id_ranks is not None:
        results.sort(key=lambda x: x[1])
    return [r[0] for r in results]


def search_context_fts(query: str, project: str = "", agent: str = "", tag: str = ""):
    """Searches context notes using FTS5 BM25 ranking."""
    conn = init_search_db()
    cur = conn.cursor()
    results = []
    clean_q = query.strip()

    id_ranks = None
    if clean_q:
        tokens = [t for t in re.split(r'\s+', clean_q) if t]
        fts_query = " ".join(f'"{t}"' if not any(op in t for op in ("AND", "OR", "NOT", "*")) else t for t in tokens)
        try:
            cur.execute("""
                SELECT id, rank FROM context_fts
                WHERE context_fts MATCH ?
                ORDER BY rank;
            """, (fts_query,))
            rows = cur.fetchall()
            id_ranks = {r[0]: r[1] for r in rows}
        except sqlite3.OperationalError:
            id_ranks = None
    conn.close()

    for n in all_context_notes(include_archived=False):
        nid = n["id"]
        fm = n["fm"]
        note_tags = [t.strip() for t in (fm.get("tags") or "").split(",") if t.strip()]

        if agent and fm.get("agent") != agent:
            continue
        if project and fm.get("project") != project:
            continue
        if tag and tag not in note_tags:
            continue

        if id_ranks is not None:
            if nid in id_ranks:
                results.append((n, id_ranks[nid]))
        elif clean_q:
            hay = (fm.get("agent", "") + " " + fm.get("project", "") + " " + fm.get("tags", "") + " " + n["body"]).lower()
            if clean_q.lower() in hay:
                results.append((n, 0.0))
        else:
            results.append((n, 0.0))

    if id_ranks is not None:
        results.sort(key=lambda x: x[1])
    else:
        results.reverse()  # Newest first when no query ranking
    return [r[0] for r in results]


# ---- claim helpers ----
CLAIM_FM_ORDER = ("id", "claim", "status", "confidence", "created", "reviewed_at",
                  "source", "tags", "supersedes", "superseded_by", "disputed_by",
                  "dispute_reason", "promoted_from")


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
SESSION_FM_ORDER = ("id", "agent", "project", "task", "branch", "worktree", "status",
                    "files", "lease_expires", "started", "updated", "ended",
                    "target_agent", "test_status")


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


def get_active_file_locks():
    """Returns a map of {file_path: {session_id, agent, project, expires, remaining_mins}}."""
    locks = {}
    now_utc = datetime.now(timezone.utc)
    for s in all_sessions():
        if s["fm"].get("status") != "active":
            continue
        files_str = s["fm"].get("files", "")
        if not files_str:
            continue
        lease_str = s["fm"].get("lease_expires", "")
        if not lease_str:
            continue
        try:
            expires_at = datetime.strptime(lease_str, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if expires_at > now_utc:
            remaining_mins = int((expires_at - now_utc).total_seconds() // 60)
            file_list = [f.strip() for f in files_str.split(",") if f.strip()]
            for fpath in file_list:
                locks[fpath] = {
                    "session_id": s["id"],
                    "agent": s["fm"].get("agent", "?"),
                    "project": s["fm"].get("project", ""),
                    "expires": lease_str,
                    "remaining_mins": remaining_mins,
                }
    return locks


# ---- context helpers ----
CONTEXT_FM_ORDER = ("id", "agent", "project", "tags", "created", "promoted_to")


def context_path(nid):
    return VAULT / CONTEXT_DIR / (nid + ".md")


def get_context_note(nid):
    p = context_path(nid)
    if not p.exists():
        p = VAULT / CONTEXT_ARCHIVE_DIR / (nid + ".md")
    rec = parse_frontmatter(p)
    if rec:
        rec["id"] = nid
    return rec


def all_context_notes(include_archived=False):
    out = []
    d = VAULT / CONTEXT_DIR
    if d.exists():
        for p in sorted(d.glob("ctx-*.md")):
            n = get_context_note(p.stem)
            if n:
                out.append(n)
    if include_archived:
        arch_dir = VAULT / CONTEXT_ARCHIVE_DIR
        if arch_dir.exists():
            for p in sorted(arch_dir.glob("ctx-*.md")):
                n = get_context_note(p.stem)
                if n:
                    out.append(n)
    return out


# ---- git helpers ----
def git_commit(msg):
    subprocess.run(["git", "add", "-A"], cwd=VAULT, capture_output=True)
    subprocess.run(["git", "commit", "-m", msg, "--allow-empty"],
                   cwd=VAULT, capture_output=True)


# ================ KNOWLEDGE & CLAIMS COMMANDS ================

def cmd_init(args, cfg=None):
    for d in (CLAIMS_DIR, "decisions", "projects", "experiments", "people",
              SESSIONS_DIR, CONTEXT_DIR, CONTEXT_ARCHIVE_DIR, META_DIR):
        (VAULT / d).mkdir(parents=True, exist_ok=True)
    gitignore = """# state & lock files
.lock
*.tmp
# Search index SQLite database
meta/search_index.db
# L2 transcripts are owned by Hermes session_search - keep them out of git
sessions/*.json
# large blobs
*.log
"""
    (VAULT / ".gitignore").write_text(gitignore, encoding="utf-8")
    save_config(load_config())
    readme_path = VAULT / "README.md"
    if not readme_path.exists():
        atomic_write(readme_path, f"# Second Brain\n\nMulti-agent coordination hub. Vault: {VAULT}\n")
    if not (VAULT / ".git").exists():
        subprocess.run(["git", "init"], cwd=VAULT, capture_output=True)
    reindex_all_search()
    git_commit("init vault skeleton")
    print(f"vault initialised at {VAULT}")
    return 0


def cmd_claim(args, cfg):
    ts = now()
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
    reindex_all_search()
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
    reindex_all_search()
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
    reindex_all_search()
    git_commit(f"dispute {args.id}: {args.reason or ''}")
    print(f"{args.id} marked disputed")
    return 0


def cmd_promote(args, cfg):
    """Promotes a context note into a permanent claim."""
    note = get_context_note(args.id)
    if not note:
        print(f"context note {args.id} not found")
        return 1
    ts = now()
    cid = datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    nfm = note["fm"]
    claim_text = note["body"].strip()
    tags = args.tags or nfm.get("tags", "")
    source = f"context:{note['id']} (by {nfm.get('agent', 'unknown')})"

    cfm = {
        "id": cid,
        "claim": claim_text.split("\n")[0][:200],  # first line as summary
        "status": "active",
        "confidence": args.confidence,
        "created": ts,
        "reviewed_at": ts,
        "source": source,
        "tags": tags,
        "promoted_from": note["id"],
    }
    body = (f"**Claim:** {cfm['claim']}\n\n"
            f"**Evidence:** {claim_text}\n\n"
            f"Promoted from [[{note['id']}]] on {ts}. Original agent: {nfm.get('agent', 'unknown')}.\n")

    atomic_write(claim_path(cid), frontmatter_block(cfm, CLAIM_FM_ORDER) + "\n" + body)

    # Mark original note as promoted
    nfm["promoted_to"] = cid
    atomic_write(note["path"], frontmatter_block(nfm, CONTEXT_FM_ORDER) + "\n" + note["body"] + f"\n\n> Promoted to claim [[{cid}]] on {ts}\n")

    reindex_all_search()
    git_commit(f"promote {note['id']} -> claim {cid}")
    print(f"context note {note['id']} promoted to claim {cid} -> {claim_path(cid)}")
    return 0


def cmd_recall(args, cfg):
    """BM25 full-text recall over claims using SQLite FTS5."""
    withhold = cfg.get("recall", {}).get("withhold", list(WITHHELD_STATUSES))
    matched_claims = search_claims_fts(args.query or "", status=args.status or "", tag=args.tag or "")

    matches, withheld = [], []
    for c in matched_claims:
        st = c["fm"].get("status", "active")
        rec = {
            "id": c["id"],
            "status": st,
            "claim": c["fm"].get("claim"),
            "confidence": c["fm"].get("confidence"),
            "source": c["fm"].get("source", ""),
        }
        if st in withhold and not args.all:
            withheld.append(rec)
        else:
            matches.append(rec)

    print(f"== RECALL '{args.query or ''}' (BM25) == ({len(matches)} shown, {len(withheld)} withheld)")
    for r in matches:
        print(f"  [{r['status']}] {r['id']}  {r['claim']}")
        if r.get("source"):
            print(f"      source: {r['source']}")
    if withheld:
        print("-- WITHHELD (not current truth) --")
        for r in withheld:
            print(f"  [{r['status']}] {r['id']}  {r['claim']} <-- withheld because status={r['status']}")
    return 0


def cmd_status(args, cfg):
    claims = all_claims()
    counts = {s: 0 for s in STATUSES}
    issues = []
    for c in claims:
        st = c["fm"].get("status", "active")
        counts[st] = counts.get(st, 0) + 1
        issues += chain_issues(c["id"], set())

    l0_path = VAULT / META_DIR / L0_NAME
    l0_size = l0_path.stat().st_size if l0_path.exists() else 0
    sessions = all_sessions()
    active_sessions = [s for s in sessions if s["fm"].get("status") == "active"]
    notes = all_context_notes(include_archived=False)
    file_locks = get_active_file_locks()

    print(f"claims: {len(claims)}  by status: {dict(counts)}")
    print(f"sessions: {len(sessions)} total, {len(active_sessions)} active")
    print(f"active file locks: {len(file_locks)}")
    print(f"context notes: {len(notes)}")
    print(f"L0 pointer file: {l0_size}B / {L0_BUDGET}B budget ({'OK' if l0_size <= L0_BUDGET else 'OVER BUDGET'})")
    if issues:
        print("CHAIN ISSUES:")
        for i in issues:
            print("  " + i)
    else:
        print("chain integrity: OK")
    return 0


def cmd_verify(args, cfg):
    issues = chain_issues(args.id, set())
    if not issues:
        print("OK - chain clean")
        return 0
    for i in issues:
        print(i)
    return 1


def cmd_related(args, cfg):
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


# ================ COORDINATION & CONCURRENCY COMMANDS ================

def cmd_check_files(args, cfg):
    """Check if specified files are currently reserved/locked by another agent."""
    if not args.files:
        print("No files specified.")
        return 0
    target_files = [f.strip() for f in args.files.split(",") if f.strip()]
    locks = get_active_file_locks()
    conflicts = []
    for tf in target_files:
        if tf in locks:
            l = locks[tf]
            conflicts.append((tf, l))

    if conflicts:
        print(f"WARNING: {len(conflicts)} file conflict(s) detected:")
        for fpath, l in conflicts:
            print(f"  [LOCKED] {fpath} reserved by {l['agent']} in session {l['session_id']} (expires in {l['remaining_mins']}m)")
        return 1
    else:
        print(f"OK - all {len(target_files)} file(s) available for edit.")
        return 0


def cmd_session_start(args, cfg):
    ts = now()
    sid = "s-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]

    # Calculate lease expiration if files are specified
    lease_mins = args.lease or cfg.get("session", {}).get("default_lease_mins", DEFAULT_LEASE_MINS)
    lease_expires = ""
    if args.files:
        exp_dt = datetime.now(timezone.utc) + timedelta(minutes=lease_mins)
        lease_expires = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Conflict check
        target_files = [f.strip() for f in args.files.split(",") if f.strip()]
        locks = get_active_file_locks()
        conflicts = [f for f in target_files if f in locks]
        if conflicts:
            print(f"WARNING: File reservation conflict! Files already locked: {', '.join(conflicts)}")

    # Auto-detect git branch if not provided
    branch = args.branch or ""
    if not branch:
        try:
            res = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                branch = res.stdout.strip()
        except Exception:
            pass

    fm = {
        "id": sid,
        "agent": args.agent,
        "project": args.project or "",
        "task": args.task or "",
        "branch": branch,
        "worktree": args.worktree or "",
        "status": "active",
        "files": args.files or "",
        "lease_expires": lease_expires,
        "started": ts,
        "updated": ts,
        "ended": "",
    }
    body = "## Progress\n"
    task_desc = args.task or "session started"
    body += f"- [{ts[11:16]}] {task_desc}\n"
    if args.files:
        body += f"- [{ts[11:16]}] Reserved files (lease {lease_mins}m): {args.files}\n"
    body += "\n## Outcomes\n(pending)\n"

    content = frontmatter_block(fm, SESSION_FM_ORDER) + "\n" + body
    atomic_write(session_path(sid), content)
    git_commit(f"session {sid}: {args.agent} starts on {args.project or 'unscoped'}")
    print(f"session {sid} started (agent={args.agent}, project={args.project or 'none'})")
    if lease_expires:
        print(f"  files reserved: {args.files} (expires {lease_expires})")
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

    # Update / extend files and lease
    if args.files:
        s["fm"]["files"] = args.files
    if args.extend_lease:
        exp_dt = datetime.now(timezone.utc) + timedelta(minutes=args.extend_lease)
        s["fm"]["lease_expires"] = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    body = s["body"]
    if args.progress:
        progress_line = f"- [{ts[11:16]}] {args.progress}\n"
        if "## Outcomes" in body:
            body = body.replace("## Outcomes", progress_line + "\n## Outcomes", 1)
        else:
            body += "\n" + progress_line

    atomic_write(s["path"], frontmatter_block(s["fm"], SESSION_FM_ORDER) + "\n" + body + "\n")
    print(f"session {args.id} updated")
    return 0


def cmd_reserve(args, cfg):
    """Claim or update file reservations on an active session."""
    s = get_session(args.id)
    if not s:
        print(f"session {args.id} not found")
        return 1
    if s["fm"].get("status") != "active":
        print(f"session {args.id} is not active")
        return 1

    lease_mins = args.lease or cfg.get("session", {}).get("default_lease_mins", DEFAULT_LEASE_MINS)
    exp_dt = datetime.now(timezone.utc) + timedelta(minutes=lease_mins)
    lease_expires = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    # Conflict check with other sessions
    target_files = [f.strip() for f in args.files.split(",") if f.strip()]
    locks = get_active_file_locks()
    conflicts = [f for f in target_files if f in locks and locks[f]["session_id"] != args.id]
    if conflicts:
        print(f"WARNING: File reservation conflict with another session! Files: {', '.join(conflicts)}")

    s["fm"]["files"] = args.files
    s["fm"]["lease_expires"] = lease_expires
    s["fm"]["updated"] = now()

    ts = now()
    body = s["body"]
    prog_line = f"- [{ts[11:16]}] Reserved files ({lease_mins}m lease): {args.files}\n"
    if "## Outcomes" in body:
        body = body.replace("## Outcomes", prog_line + "\n## Outcomes", 1)
    else:
        body += "\n" + prog_line

    atomic_write(s["path"], frontmatter_block(s["fm"], SESSION_FM_ORDER) + "\n" + body + "\n")
    print(f"files reserved on session {args.id}: {args.files} (expires in {lease_mins}m)")
    return 0


def cmd_session_end(args, cfg):
    """End a session with optional structured handoff metadata."""
    s = get_session(args.id)
    if not s:
        print(f"session {args.id} not found")
        return 1
    ts = now()
    s["fm"]["status"] = "ended"
    s["fm"]["updated"] = ts
    s["fm"]["ended"] = ts
    s["fm"]["lease_expires"] = ""  # Release file lease immediately

    # Structured handoff fields
    if args.target_agent:
        s["fm"]["target_agent"] = args.target_agent
    if args.test_status:
        s["fm"]["test_status"] = args.test_status

    body = s["body"]
    summary = args.summary or "(completed)"

    outcomes_block = f"## Outcomes\n{summary}\n"
    if args.target_agent or args.next_steps or args.modified_files or args.test_status:
        outcomes_block += "\n### Handoff Details\n"
        if args.target_agent:
            outcomes_block += f"- **Target Agent:** `{args.target_agent}`\n"
        if args.modified_files:
            outcomes_block += f"- **Modified Files:** `{args.modified_files}`\n"
        if args.test_status:
            outcomes_block += f"- **Tests:** `{args.test_status}`\n"
        if args.next_steps:
            outcomes_block += f"- **Next Steps:** {args.next_steps}\n"

    if "## Outcomes" in body:
        body = re.sub(r"## Outcomes(\s*\((pending|no summary)\))?", outcomes_block.strip(), body)
    else:
        body += f"\n{outcomes_block}\n"

    atomic_write(s["path"], frontmatter_block(s["fm"], SESSION_FM_ORDER) + "\n" + body + "\n")
    git_commit(f"session-end {args.id}: {s['fm'].get('agent', '?')}")
    print(f"session {args.id} ended (lease released)")
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
    filtered.reverse()
    print(f"== SESSIONS == ({len(filtered)} shown)")
    for s in filtered:
        fm = s["fm"]
        age = time_ago(fm.get("started", ""))
        status = fm.get("status", "?")
        agent = fm.get("agent", "?")
        project = fm.get("project", "") or "unscoped"
        task = fm.get("task", "")
        branch = f" [{fm.get('branch')}]" if fm.get("branch") else ""
        marker = "*" if status == "active" else "." if status == "ended" else "?"
        print(f"  {marker} [{status}] {agent} -> {project}{branch}: {task} ({age})")
        if fm.get("files") and status == "active":
            print(f"      reserved files: {fm.get('files')}")
        if fm.get("target_agent"):
            print(f"      handoff -> {fm.get('target_agent')}")
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
    reindex_all_search()
    git_commit(f"context {nid}: {args.text[:60]}")
    print(f"context note {nid} posted (agent={args.agent or 'unknown'}, project={args.project or 'none'})")
    return 0


def cmd_read(args, cfg):
    """Reads context notes with optional BM25 search."""
    limit = args.limit or cfg.get("context", {}).get("default_limit", 20)
    notes = search_context_fts(args.query or "", project=args.project or "", agent=args.agent or "", tag=args.tag or "")
    filtered = notes[:limit]

    print(f"== CONTEXT == ({len(filtered)} shown)")
    for n in filtered:
        fm = n["fm"]
        age = time_ago(fm.get("created", ""))
        agent = fm.get("agent", "?")
        project = fm.get("project", "") or "-"
        tags = fm.get("tags", "")
        preview = n["body"].split("\n")[0][:100] if n["body"] else ""
        promoted = f" [Promoted -> [[{fm.get('promoted_to')}]]]" if fm.get("promoted_to") else ""
        print(f"  [{agent}] ({project}) {preview} [{age}]{promoted}")
        if tags:
            print(f"      tags: {tags}")
        print(f"      id: {n['id']}")
    return 0


def cmd_dashboard(args, cfg):
    """Full multi-agent situational awareness with file locks and handoffs."""
    sessions = all_sessions()
    active = [s for s in sessions if s["fm"].get("status") == "active"]
    recent_ended = [s for s in sessions if s["fm"].get("status") == "ended"][-5:]

    notes = all_context_notes(include_archived=False)
    recent_notes = list(reversed(notes))[:5]
    claims = all_claims()
    active_claims = [c for c in claims if c["fm"].get("status", "active") == "active"]
    locks = get_active_file_locks()

    print("=" * 46)
    print("        SECOND BRAIN -- DASHBOARD")
    print("=" * 46)
    print()

    # Active Sessions
    print(f"> ACTIVE SESSIONS ({len(active)})")
    if active:
        for s in active:
            fm = s["fm"]
            age = time_ago(fm.get("started", ""))
            branch = f" [branch: {fm.get('branch')}]" if fm.get("branch") else ""
            print(f"  [LIVE] {fm.get('agent','?')} -> {fm.get('project','') or 'unscoped'}{branch}: {fm.get('task','')} ({age})")
            if fm.get("files"):
                print(f"         files locked: {fm.get('files')}")
    else:
        print("  (none)")
    print()

    # Active File Locks
    if locks:
        print(f"> ACTIVE FILE LEASES ({len(locks)})")
        for fpath, l in locks.items():
            print(f"  [LOCK] {fpath} -> {l['agent']} ({l['project']}) [expires in {l['remaining_mins']}m]")
        print()

    # Recent Handoffs & Completed
    if recent_ended:
        print(f"> RECENT SESSIONS & HANDOFFS ({len(recent_ended)})")
        for s in reversed(recent_ended):
            fm = s["fm"]
            age = time_ago(fm.get("ended", fm.get("updated", "")))
            handoff = f" -> handoff to [{fm.get('target_agent')}]" if fm.get("target_agent") else ""
            print(f"  [done] {fm.get('agent','?')} -> {fm.get('project','') or 'unscoped'}: {fm.get('task','')}{handoff} (ended {age})")
        print()

    # Recent Context
    print(f"> RECENT CONTEXT ({len(recent_notes)})")
    if recent_notes:
        for n in recent_notes:
            fm = n["fm"]
            age = time_ago(fm.get("created", ""))
            preview = n["body"].split("\n")[0][:80] if n["body"] else ""
            print(f"  [{fm.get('agent','?')}] {preview} ({age})")
    else:
        print("  (none)")
    print()

    # Vault Health
    l0_path = VAULT / META_DIR / L0_NAME
    l0_size = l0_path.stat().st_size if l0_path.exists() else 0
    print(f"> VAULT: {len(active_claims)} active claims, L0={l0_size}B/{L0_BUDGET}B (FTS5 active)")
    print()
    return 0


# ================ SWEEP & HOUSEKEEPING ================

def cmd_sweep(args, cfg):
    ts = now()
    sweep_cfg = cfg.get("sweep", {})
    exp_unreviewed = int(sweep_cfg.get("expire_unreviewed_after_days", 120))
    changed = []

    # 1. Stale session expiry & release leases
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
            s["fm"]["lease_expires"] = ""  # clear lease
            body = s["body"]
            if "## Outcomes" in body:
                body = body.replace("## Outcomes\n(pending)", f"## Outcomes\n(stale — auto-expired by sweep {ts})")
            atomic_write(s["path"], frontmatter_block(s["fm"], SESSION_FM_ORDER) + "\n" + body + "\n")
            changed.append((s["id"], f"session stale (agent={s['fm'].get('agent','?')})"))

    # 2. Context Note TTL Archival
    ttl_days = int(cfg.get("context", {}).get("ttl_days", CONTEXT_TTL_DAYS))
    ttl_cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    for n in all_context_notes(include_archived=False):
        try:
            created = datetime.strptime(n["fm"].get("created", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            created = None
        if created and created < ttl_cutoff:
            # Move to archive directory
            arch_dir = VAULT / CONTEXT_ARCHIVE_DIR
            arch_dir.mkdir(parents=True, exist_ok=True)
            target_path = arch_dir / (n["id"] + ".md")
            os.replace(n["path"], target_path)
            changed.append((n["id"], f"context note archived (>{ttl_days}d old)"))

    # 3. Claim staleness flags
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
            if "> sweep" not in c["body"]:
                body = c["body"] + f"\n\n> sweep {ts}: unreviewed {age_days}d - needs review\n"
                atomic_write(c["path"], frontmatter_block(c["fm"], CLAIM_FM_ORDER) + "\n" + body + "\n")
            changed.append((c["id"], f"stale ({age_days}d) - flagged for review"))

    # 4. Rebuild FTS5 Index
    reindex_all_search()

    # 5. Rebuild L0 Pointer Set (Budget-Aware)
    l0_lines = [
        f"# Brain (auto-generated {ts})",
        "# Call brain_session_start on session begin. brain_recall for knowledge.",
        "",
    ]

    # Section 1: Active sessions & file locks
    active_sessions = [s for s in all_sessions() if s["fm"].get("status") == "active"]
    if active_sessions:
        l0_lines.append("## Active")
        for s in active_sessions[:5]:
            fm = s["fm"]
            agent = fm.get("agent", "?")
            proj = fm.get("project", "") or "unscoped"
            task = fm.get("task", "")[:50]
            age = time_ago(fm.get("started", ""))
            locks = f" [locks: {fm.get('files')[:30]}..]" if fm.get("files") else ""
            l0_lines.append(f"- {agent} -> {proj}: {task}{locks} ({age})")
        l0_lines.append("")

    # Section 2: Recent context notes
    recent_ctx = list(reversed(all_context_notes(include_archived=False)))[:5]
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

    # Section 3: Active claims (truncated to fit remaining budget)
    active_claims = [c for c in all_claims() if c["fm"].get("status", "active") == "active"]
    header_size = len("\n".join(l0_lines).encode("utf-8"))
    remaining = L0_BUDGET - header_size - 50
    l0_lines.append(f"## Knowledge ({len(active_claims)} active)")
    for c in sorted(active_claims, key=lambda x: x["id"], reverse=True):
        claim_text = c["fm"].get("claim", "")
        if len(claim_text) > L0_MAX_LINE:
            claim_text = claim_text[:L0_MAX_LINE - 3] + "..."
        line = f"- [{c['fm'].get('status')}] {claim_text} [[{c['id']}]]"
        line_size = len(line.encode("utf-8")) + 1
        if remaining - line_size < 0:
            l0_lines.append(f"- ... and {len(active_claims)} more (run brain_recall)")
            break
        l0_lines.append(line)
        remaining -= line_size

    atomic_write(VAULT / META_DIR / L0_NAME, "\n".join(l0_lines) + "\n")

    print(f"sweep: {len(changed)} items flagged/archived")
    for cid, why in changed:
        print(f"  {cid}: {why}")
    l0_size = (VAULT / META_DIR / L0_NAME).stat().st_size
    print(f"L0 pointer set rebuilt: {l0_size}B / {L0_BUDGET}B ({'OK' if l0_size <= L0_BUDGET else 'OVER'})")
    if args.commit:
        git_commit(f"sweep {ts}: {len(changed)} items processed")
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

    p_prom = sub.add_parser("promote")
    p_prom.add_argument("id")
    p_prom.add_argument("--confidence", type=float, default=0.9)
    p_prom.add_argument("--tags", default="")

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

    # -- coordination & concurrency commands --
    p_ss = sub.add_parser("session-start")
    p_ss.add_argument("--agent", required=True)
    p_ss.add_argument("--project", default="")
    p_ss.add_argument("--task", default="")
    p_ss.add_argument("--branch", default="")
    p_ss.add_argument("--worktree", default="")
    p_ss.add_argument("--files", default="")
    p_ss.add_argument("--lease", type=int, default=0)

    p_su = sub.add_parser("session-update")
    p_su.add_argument("id")
    p_su.add_argument("--progress", default="")
    p_su.add_argument("--files", default="")
    p_su.add_argument("--extend-lease", type=int, default=0)

    p_res = sub.add_parser("reserve")
    p_res.add_argument("id")
    p_res.add_argument("--files", required=True)
    p_res.add_argument("--lease", type=int, default=0)

    p_chk = sub.add_parser("check-files")
    p_chk.add_argument("--files", required=True)
    p_chk.add_argument("--project", default="")

    p_se = sub.add_parser("session-end")
    p_se.add_argument("id")
    p_se.add_argument("--summary", default="")
    p_se.add_argument("--target-agent", default="")
    p_se.add_argument("--next-steps", default="")
    p_se.add_argument("--modified-files", default="")
    p_se.add_argument("--test-status", default="")

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
    p_read.add_argument("--query", default="")
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

    with lock():
        cfg = load_config()
        handlers = {
            "init": cmd_init, "claim": cmd_claim, "supersede": cmd_supersede,
            "dispute": cmd_dispute, "promote": cmd_promote, "recall": cmd_recall,
            "status": cmd_status, "sweep": cmd_sweep, "verify": cmd_verify,
            "related": cmd_related, "session-start": cmd_session_start,
            "session-update": cmd_session_update, "session-end": cmd_session_end,
            "reserve": cmd_reserve, "check-files": cmd_check_files,
            "sessions": cmd_sessions, "post": cmd_post, "read": cmd_read,
            "dashboard": cmd_dashboard,
        }
        return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
