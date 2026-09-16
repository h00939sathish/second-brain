#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
second_brain.py - Multi-agent coordination hub + autonomous execution pipeline (v4.3).

Tiered memory:
  L0 = compact pointers ALWAYS injected into agent sessions (~2.2KB budget)
  L1 = this vault: git-backed markdown (claims, specs, tasks, sessions, context)
  L2 = raw session transcripts (opaque, never read/written here)

Autonomous Role Pipeline:
  GPT 5.6 (Codex)          = LEAD ARCHITECT & ARBITER (Dense invariants, spec drafting, signoff)
  Gemini 3.7 Flash (AGY)   = CONTEXT ANALYST & FINAL REVIEWER (1M context critique, diff audit, test verification)
  opencode / Claude Code   = CORE BUILDERS & HEAVY LIFTERS (Phased code edits, file reservations, unit tests)

Automated Execution:
  dispatch <task_id> [--tab]     Directly invoke the assigned agent CLI (headless or in a terminal tab)
  auto-cycle [--project <p>]     Check Kanban board and dispatch the next actionable pipeline task
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

VAULT = Path(os.environ.get("SECOND_BRAIN_VAULT", str(Path(__file__).resolve().parent)))
META_DIR = "meta"
CLAIMS_DIR = "claims"
SPECS_DIR = "specs"
TASKS_DIR = "tasks"
LOGS_DIR = "tasks/logs"
SESSIONS_DIR = "sessions"
CONTEXT_DIR = "context"
CONTEXT_ARCHIVE_DIR = "context/archive"
CONFIG_NAME = "config.json"
L0_NAME = "l0_pointers.md"
DB_NAME = "search_index.db"

STATUSES = ("active", "superseded", "expired", "disputed")
WITHHELD_STATUSES = ("expired", "superseded", "disputed")
TASK_STATUSES = ("backlog", "planning", "running", "review", "done")

AGENT_ROLES = {
    "codex": "planner",
    "opencode": "builder",
    "claude": "builder",
    "claude-code": "builder",
    "antigravity": "reviewer",
    "agy": "reviewer",
    "hermes": "orchestrator",
}

L0_BUDGET = 2200
SESSION_STALE_HOURS = 24
DEFAULT_LEASE_MINS = 30
CONTEXT_TTL_DAYS = 7
L0_MAX_LINE = 120


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def time_ago(ts_str):
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
        "vault_version": 4,
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
        "pipeline": {
            "roles": AGENT_ROLES,
            "complex_keywords": [
                "refactor", "migrate", "architecture", "implement", "build",
                "feature", "pipeline", "database", "redesign", "endpoint", "oauth", "jwt"
            ],
            "complexity_threshold": 3,
        },
        "search": {
            "engine": "sqlite_fts5",
            "algorithm": "bm25",
        },
    }


def save_config(cfg):
    atomic_write(cfg_path(), json.dumps(cfg, indent=2) + "\n")


def atomic_write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, path)


class FileLock:
    def __init__(self, path: Path, timeout: float = 10.0):
        self.path = path
        self.timeout = timeout
        self._f = None
        self._locked = False

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Ensure file exists and has non-zero length for OS lock
        if not self.path.exists() or self.path.stat().st_size == 0:
            try:
                with open(self.path, "wb") as init_f:
                    init_f.write(b"0")
            except Exception:
                pass

        self._f = open(self.path, "r+b")
        start = time.time()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._f.seek(0)
                    msvcrt.locking(self._f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self._locked = True
                break
            except (OSError, IOError):
                if time.time() - start > self.timeout:
                    if self._f:
                        try:
                            self._f.close()
                        except Exception:
                            pass
                        self._f = None
                    raise TimeoutError(f"Could not acquire lock on {self.path} within {self.timeout}s")
                time.sleep(0.05)
        return self

    def __exit__(self, *a):
        if self._locked and self._f:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._f.seek(0)
                    msvcrt.locking(self._f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self._f.fileno(), fcntl.LOCK_UN)
            except (OSError, IOError):
                pass
            finally:
                self._locked = False
        if self._f:
            try:
                self._f.close()
            except Exception:
                pass
            self._f = None



def lock():
    return FileLock(VAULT / ".lock")


def parse_frontmatter(path: Path):
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
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS specs_fts USING fts5(
            id UNINDEXED,
            title,
            project,
            created UNINDEXED,
            body
        );
    """)
    cur.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
            id UNINDEXED,
            title,
            project,
            spec_id UNINDEXED,
            agent,
            status UNINDEXED,
            body
        );
    """)
    conn.commit()
    return conn


def reindex_all_search():
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

    cur.execute("DELETE FROM specs_fts;")
    for s in all_specs():
        fm = s["fm"]
        cur.execute(
            "INSERT INTO specs_fts (id, title, project, created, body) VALUES (?, ?, ?, ?, ?);",
            (s["id"], fm.get("title", ""), fm.get("project", ""), fm.get("created", ""), s["body"])
        )

    cur.execute("DELETE FROM tasks_fts;")
    for t in all_tasks():
        fm = t["fm"]
        cur.execute(
            "INSERT INTO tasks_fts (id, title, project, spec_id, agent, status, body) VALUES (?, ?, ?, ?, ?, ?, ?);",
            (t["id"], fm.get("title", ""), fm.get("project", ""), fm.get("spec_id", ""),
             fm.get("agent", ""), fm.get("status", "backlog"), t["body"])
        )

    conn.commit()
    conn.close()


def search_claims_fts(query: str, status: str = "", tag: str = ""):
    if not query and not status and not tag:
        return all_claims()

    conn = init_search_db()
    cur = conn.cursor()
    results = []

    clean_q = query.strip()
    if clean_q:
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
            hay = (fm.get("claim", "") + " " + fm.get("tags", "") + " " + fm.get("source", "") + " " + c["body"]).lower()
            if clean_q.lower() in hay:
                results.append((c, 0.0))
        else:
            results.append((c, 0.0))

    if id_ranks is not None:
        results.sort(key=lambda x: x[1])
    return [r[0] for r in results]


def search_context_fts(query: str, project: str = "", agent: str = "", tag: str = ""):
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
        results.reverse()
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


# ---- spec helpers (Traycer pattern) ----
SPEC_FM_ORDER = ("id", "title", "project", "phases", "created", "updated")


def spec_path(spec_id):
    return VAULT / SPECS_DIR / (spec_id + ".md")


def get_spec(spec_id):
    p = spec_path(spec_id)
    rec = parse_frontmatter(p)
    if rec:
        rec["id"] = spec_id
    return rec


def all_specs():
    out = []
    d = VAULT / SPECS_DIR
    if d.exists():
        for p in sorted(d.glob("spec-*.md")):
            s = get_spec(p.stem)
            if s:
                out.append(s)
    return out


# ---- task helpers (agtx Kanban pattern) ----
TASK_FM_ORDER = ("id", "title", "project", "spec_id", "phase", "agent",
                 "status", "files", "created", "updated")


def task_path(task_id):
    return VAULT / TASKS_DIR / (task_id + ".md")


def get_task(task_id):
    p = task_path(task_id)
    rec = parse_frontmatter(p)
    if rec:
        rec["id"] = task_id
    return rec


def all_tasks():
    out = []
    d = VAULT / TASKS_DIR
    if d.exists():
        for p in sorted(d.glob("t-*.md")):
            t = get_task(p.stem)
            if t:
                out.append(t)
    return out


# ---- session helpers ----
SESSION_FM_ORDER = ("id", "agent", "project", "task", "task_id", "branch", "worktree", "status",
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


# ================ AUTONOMOUS PIPELINE ROUTER & DISPATCHER ================

def estimate_workload_complexity(prompt: str, cfg: dict):
    p_cfg = cfg.get("pipeline", {})
    keywords = p_cfg.get("complex_keywords", [
        "refactor", "migrate", "architecture", "implement", "build",
        "feature", "pipeline", "database", "redesign", "endpoint", "oauth", "jwt"
    ])
    threshold = int(p_cfg.get("complexity_threshold", 3))

    score = 0
    clean_p = prompt.lower()
    for kw in keywords:
        if kw in clean_p:
            score += 1

    if len(prompt.split()) > 35:
        score += 2
    if "\n" in prompt.strip():
        score += 1
    if any(sep in prompt for sep in (",", ";", " and then ", " also ")):
        score += 1

    is_complex = score >= threshold
    return is_complex, score


def cmd_cycle_route(args, cfg):
    agent = (args.agent or "unknown").lower()
    project = args.project or "default"
    prompt = args.prompt or ""

    is_complex, score = estimate_workload_complexity(prompt, cfg)
    role = AGENT_ROLES.get(agent, "builder")

    print(f"== CYCLE ROUTER (agent={agent}, role={role}, score={score}) ==")

    if not is_complex:
        print("[ROUTE: DIRECT EXECUTION]")
        print("Workload is lightweight. You may execute and complete this task directly in this session.")
        return 0

    print("[ROUTE: AUTONOMOUS 4-STAGE PIPELINE ACTIVATED]")
    print(f"Workload is complex (score={score}).")
    print("Enforcing: GPT 5.6 (Codex) <-> Gemini 3.7 (AGY) Planning Debate -> opencode/Claude (Builders) -> Gemini 3.7 (AGY) Final Review.")
    print("* Rule: Neither Codex nor AGY performs heavy file generation; heavy lifting is offloaded to Builders.")
    print()

    if role == "planner":  # Codex (GPT 5.6)
        print("YOUR ROLE: LEAD ARCHITECT & ARBITER (Codex / GPT 5.6)")
        print("Actions required:")
        print(f"  1. Formulate core architectural invariants & constraints (keep concise to conserve tokens).")
        print(f"  2. Incorporate Gemini 3.7 Flash repo context & critique into the spec.")
        print(f"  3. Save spec: brain_spec_create(project='{project}', title='...', spec='...', phases='...')")
        print(f"  4. Decompose into Kanban tasks: brain_task_create(project='{project}', title='...', agent='opencode'|'claude')")
        print(f"  5. Advance task to [running] for builders. (DO NOT write code directly).")

    elif role == "builder":  # opencode / Claude Code
        print(f"YOUR ROLE: CORE BUILDER & HEAVY LIFTER ({agent})")
        tasks = [t for t in all_tasks() if t["fm"].get("status") in ("planning", "running")]
        if tasks:
            t = tasks[0]
            print(f"Active Task Available: [{t['id']}] {t['fm'].get('title')}")
            print(f"  1. Claim task to running: brain_task_move(task_id='{t['id']}', status='running')")
            print(f"  2. Start session & reserve files: brain_session_start(agent='{agent}', project='{project}', task_id='{t['id']}', files='...', lease_mins=30)")
            print("  3. Implement code phase & run unit tests.")
            print(f"  4. End session with handoff to Antigravity: brain_session_end(..., target_agent='antigravity') and brain_task_move(task_id='{t['id']}', status='review').")
        else:
            ts = now()
            tid = "t-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
            title = prompt.split("\n")[0][:80]
            tfm = {
                "id": tid,
                "title": title,
                "project": project,
                "spec_id": "",
                "phase": "",
                "agent": "codex",
                "status": "planning",
                "files": "",
                "created": ts,
                "updated": ts,
            }
            body = f"# Task: {title}\n\nUser Request: {prompt}\n\n## Activity Log\n- [{ts[11:16]}] Created by {agent} (routed to Codex & AGY for planning debate)\n"
            atomic_write(task_path(tid), frontmatter_block(tfm, TASK_FM_ORDER) + "\n" + body)
            reindex_all_search()
            git_commit(f"task {tid}: created by {agent} for planning debate")
            print(f"Created Task [{tid}] in [planning] assigned to Codex/AGY.")
            print("Next step: Codex & AGY must debate and finalize the architectural spec before code implementation.")

    elif role == "reviewer":  # Antigravity (Gemini 3.7 Flash)
        print("YOUR ROLE: CONTEXT ANALYST & FINAL REVIEWER (Antigravity CLI / Gemini 3.7 Flash)")
        review_tasks = [t for t in all_tasks() if t["fm"].get("status") == "review"]
        if review_tasks:
            t = review_tasks[0]
            print(f"Task Ready for Final Review: [{t['id']}] {t['fm'].get('title')}")
            print("Actions required:")
            print("  1. Ingest full repo & audit git diffs vs upstream spec (zero drift).")
            print("  2. Run comprehensive test suites (pytest/cargo/npm).")
            print(f"  3. Post verification report: brain_post(text='Verification report...', tags='review,report')")
            print(f"  4. Mark task done: brain_task_move(task_id='{t['id']}', status='done')")
        else:
            print("No tasks currently awaiting review in [review] column. If planning, critique Codex's spec using full repo context.")

    return 0


def cmd_cycle_next(args, cfg):
    agent = (args.agent or "unknown").lower()
    project = args.project or ""
    role = AGENT_ROLES.get(agent, "builder")

    tasks = all_tasks()
    if project:
        tasks = [t for t in tasks if t["fm"].get("project") == project]

    print(f"== NEXT ACTION FOR {agent.upper()} (role: {role}) ==")

    if role == "planner":  # Codex (GPT 5.6)
        pending_plan = [t for t in tasks if t["fm"].get("status") in ("backlog", "planning")]
        if pending_plan:
            t = pending_plan[0]
            print(f"ACTION REQUIRED: Plan & debate task [{t['id']}] {t['fm'].get('title')}")
            print(f"  -> Formulate invariants, synthesize with Gemini 3.7 repo critique, and create spec for builders.")
        else:
            print("All tasks planned. Monitoring builder progress.")

    elif role == "builder":  # opencode / Claude
        running = [t for t in tasks if t["fm"].get("status") == "running"]
        planning = [t for t in tasks if t["fm"].get("status") == "planning"]
        if running:
            t = running[0]
            print(f"ACTION REQUIRED: Heavy Lifting on Task [{t['id']}] {t['fm'].get('title')}")
            print("  -> Claim file lease, implement code phase, run tests, and hand off to Antigravity for review.")
        elif planning:
            t = planning[0]
            print(f"WAITING: Task [{t['id']}] is in [planning]. Awaiting Codex & AGY spec debate.")
        else:
            print("No active build tasks in [running]. Check backlog or request new feature.")

    elif role == "reviewer":  # Antigravity (Gemini 3.7 Flash)
        in_review = [t for t in tasks if t["fm"].get("status") == "review"]
        if in_review:
            t = in_review[0]
            print(f"ACTION REQUIRED: Final Review of Task [{t['id']}] {t['fm'].get('title')}")
            print("  -> Audit diffs vs spec, run test suites, post report, and mark done.")
        else:
            print("No tasks pending review in [review].")

    return 0


def build_agent_prompt(task_dict):
    """Constructs a comprehensive, role-aware prompt for the dispatched CLI agent."""
    fm = task_dict["fm"]
    tid = task_dict["id"]
    title = fm.get("title", "")
    project = fm.get("project", "")
    spec_id = fm.get("spec_id", "")
    status = fm.get("status", "backlog")
    agent = fm.get("agent", "opencode").lower()

    spec_text = ""
    if spec_id:
        sp = get_spec(spec_id)
        if sp:
            spec_text = f"\nLinked Upstream Spec [[{spec_id}]]:\n{sp['body']}\n"

    prompt = f"""You have been dispatched by the Second Brain Autonomous Pipeline.

Task ID: {tid}
Project: {project or 'Default'}
Task Title: {title}
Current Status: [{status}]
{spec_text}

Protocol Instructions for {agent.upper()}:
1. Use second-brain MCP tools (brain_session_start, brain_check_files, brain_recall).
2. If you are Codex (Planner): Draft invariants and approve spec/tasks. Do NOT write repetitive code.
3. If you are opencode/Claude (Builder): Reserve target files (brain_reserve), implement code phase, run tests, and hand off to Antigravity (brain_session_end with target_agent="antigravity", brain_task_move to "review").
4. If you are Antigravity (Reviewer): Audit diffs against spec, run tests, post report (brain_post), and move task to "done".

Begin execution now.
"""
    return prompt.strip()


def cmd_dispatch(args, cfg):
    """Invokes the assigned agent CLI for a specific task."""
    t = get_task(args.id)
    if not t:
        print(f"task {args.id} not found")
        return 1

    fm = t["fm"]
    target_agent = (args.agent or fm.get("agent") or "opencode").lower()
    prompt = build_agent_prompt(t)

    # Determine working directory
    project_name = fm.get("project", "")
    cwd = VAULT
    if "TITAN" in project_name.upper():
        titan_path = Path(r"D:\projects\Project TITAN")
        if titan_path.exists():
            cwd = titan_path

    print(f"== DISPATCHING TASK [{t['id']}] to {target_agent.upper()} ==")
    print(f"  Project: {project_name or 'Default'} (cwd: {cwd})")
    print(f"  Task: {fm.get('title')}")

    # Advance task status to 'running' (or 'planning' if architect) upon dispatch
    current_status = fm.get("status", "backlog")
    new_status = "planning" if target_agent == "codex" and current_status == "backlog" else "running"
    if current_status != new_status and current_status != "done":
        ts = now()
        fm["status"] = new_status
        fm["updated"] = ts
        fm["agent"] = target_agent
        body = t["body"] + f"\n- [{ts[11:16]}] Dispatched to {target_agent} -> [{new_status}]\n"
        atomic_write(t["path"], frontmatter_block(fm, TASK_FM_ORDER) + "\n" + body)
        reindex_all_search()
        git_commit(f"task {t['id']}: dispatched to {target_agent} [{new_status}]")

    log_dir = VAULT / LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = log_dir / f"{t['id']}.prompt.txt"
    log_file = log_dir / f"{t['id']}.log"

    prompt_file.write_text(prompt, encoding="utf-8")

    # Command map
    cli_map = {
        "codex": f"Get-Content -Raw '{prompt_file}' | codex.cmd exec -",
        "codex-cli": f"Get-Content -Raw '{prompt_file}' | codex.cmd exec -",
        "claude": f"Get-Content -Raw '{prompt_file}' | claude.exe -p",
        "claude-code": f"Get-Content -Raw '{prompt_file}' | claude.exe -p",
        "opencode": f"Get-Content -Raw '{prompt_file}' | opencode.cmd run",
        "antigravity": f"Get-Content -Raw '{prompt_file}' | agy.exe exec",
        "agy": f"Get-Content -Raw '{prompt_file}' | agy.exe exec",
    }
    pwsh_body = cli_map.get(target_agent, f"Get-Content -Raw '{prompt_file}' | opencode.cmd run")

    if args.tab:
        print(f"Opening interactive tab for {target_agent}...")
        try:
            wt_cmd = ["wt.exe", "-w", "0", "new-tab", "-d", str(cwd), "pwsh", "-NoExit", "-Command", pwsh_body]
            subprocess.Popen(wt_cmd)
            print("Tab opened in Windows Terminal.")
            return 0
        except Exception:
            ps_cmd = ["start", "pwsh", "-NoExit", "-Command", f"cd '{cwd}'; {pwsh_body}"]
            os.system(" ".join(ps_cmd))
            print("Opened in PowerShell window.")
            return 0

    # Headless background execution
    print(f"Running {target_agent} headlessly in background...")
    try:
        cmd = ["pwsh.exe", "-NoProfile", "-Command", f"cd '{cwd}'; {pwsh_body}"]
        with open(log_file, "w", encoding="utf-8") as lf:
            proc = subprocess.Popen(
                cmd,
                cwd=cwd,
                stdout=lf,
                stderr=subprocess.STDOUT
            )
            print(f"Process started (PID {proc.pid}). Output streamed to: {log_file}")
            return 0
    except Exception as e:
        print(f"Error dispatching {target_agent}: {e}")
        return 1



def cmd_auto_cycle(args, cfg):
    """Inspects the Kanban board and dispatches the highest-priority actionable task."""
    project = args.project or ""
    tasks = all_tasks()
    if project:
        tasks = [t for t in tasks if t["fm"].get("project") == project]

    # Priority 1: Tasks in [review] -> dispatch to Antigravity
    in_review = [t for t in tasks if t["fm"].get("status") == "review"]
    if in_review:
        t = in_review[0]
        print(f"Found task in [review]: [{t['id']}] {t['fm'].get('title')}")
        args.id = t["id"]
        args.agent = "antigravity"
        return cmd_dispatch(args, cfg)

    # Priority 2: Tasks in [running] -> dispatch to assigned builder (opencode/Claude)
    running = [t for t in tasks if t["fm"].get("status") == "running"]
    if running:
        t = running[0]
        print(f"Found task in [running]: [{t['id']}] {t['fm'].get('title')}")
        args.id = t["id"]
        args.agent = t["fm"].get("agent") or "opencode"
        return cmd_dispatch(args, cfg)

    # Priority 3: Tasks in [planning] -> dispatch to Codex for debate
    planning = [t for t in tasks if t["fm"].get("status") == "planning"]
    if planning:
        t = planning[0]
        print(f"Found task in [planning]: [{t['id']}] {t['fm'].get('title')}")
        args.id = t["id"]
        args.agent = "codex"
        return cmd_dispatch(args, cfg)

    # Priority 4: Tasks in [backlog] -> advance to planning
    backlog = [t for t in tasks if t["fm"].get("status") == "backlog"]
    if backlog:
        t = backlog[0]
        print(f"Found task in [backlog]: [{t['id']}] {t['fm'].get('title')} -> Moving to planning")
        t["fm"]["status"] = "planning"
        t["fm"]["updated"] = now()
        atomic_write(t["path"], frontmatter_block(t["fm"], TASK_FM_ORDER) + "\n" + t["body"] + "\n")
        args.id = t["id"]
        args.agent = "codex"
        return cmd_dispatch(args, cfg)

    print("No actionable tasks pending on the Kanban board.")
    return 0


def cmd_daemon(args, cfg):
    """Continuous background worker that polls the Kanban board and auto-chains task execution."""
    interval = getattr(args, "interval", 15) or 15
    project = getattr(args, "project", "") or ""
    max_retries = getattr(args, "max_retries", 3) or 3

    print("=" * 55, flush=True)
    print("        SECOND BRAIN -- AUTONOMOUS DAEMON (v4.4)", flush=True)
    print(f"  Polling: every {interval}s | Project Scope: {project or 'ALL'}", flush=True)
    print("=" * 55, flush=True)

    task_attempts = {}

    try:
        while True:
            target_task = None
            target_agent = None

            with lock():
                tasks = all_tasks()
                if project:
                    tasks = [t for t in tasks if t["fm"].get("project") == project]

                # Priority 1: Tasks in [review] -> Antigravity
                in_review = [t for t in tasks if t["fm"].get("status") == "review"]
                running = [t for t in tasks if t["fm"].get("status") == "running"]
                planning = [t for t in tasks if t["fm"].get("status") == "planning"]

                if in_review:
                    target_task = in_review[0]
                    target_agent = "antigravity"
                elif running:
                    target_task = running[0]
                    target_agent = target_task["fm"].get("agent") or "opencode"
                elif planning:
                    target_task = planning[0]
                    target_agent = "codex"

                if target_task:
                    tid = target_task["id"]
                    curr_status = target_task["fm"].get("status", "backlog")

                    t_info = task_attempts.get(tid, {"attempts": 0, "last_status": curr_status})
                    if t_info["last_status"] == curr_status:
                        t_info["attempts"] += 1
                    else:
                        t_info["attempts"] = 1
                        t_info["last_status"] = curr_status
                    task_attempts[tid] = t_info

                    if t_info["attempts"] > max_retries:
                        print(f"[{now()[11:19]}] [CIRCUIT BREAKER] Task {tid} stuck in [{curr_status}] ({max_retries} attempts). Pausing.", flush=True)
                        target_task = None

            if target_task:
                tid = target_task["id"]
                title = target_task["fm"].get("title", "")
                print(f"[{now()[11:19]}] [DISPATCH] [{tid}] ({title}) -> {target_agent.upper()} (Attempt {t_info['attempts']}/{max_retries})", flush=True)

                log_dir = VAULT / LOGS_DIR
                log_dir.mkdir(parents=True, exist_ok=True)
                prompt_file = log_dir / f"{tid}.prompt.txt"
                log_file = log_dir / f"{tid}.log"
                prompt = build_agent_prompt(target_task)
                prompt_file.write_text(prompt, encoding="utf-8")

                project_name = target_task["fm"].get("project", "")
                cwd = VAULT
                if "TITAN" in project_name.upper():
                    titan_path = Path(r"D:\projects\Project TITAN")
                    if titan_path.exists():
                        cwd = titan_path

                cli_map = {
                    "codex": f"Get-Content -Raw '{prompt_file}' | codex.cmd exec -",
                    "codex-cli": f"Get-Content -Raw '{prompt_file}' | codex.cmd exec -",
                    "claude": f"Get-Content -Raw '{prompt_file}' | claude.exe -p",
                    "claude-code": f"Get-Content -Raw '{prompt_file}' | claude.exe -p",
                    "opencode": f"Get-Content -Raw '{prompt_file}' | opencode.cmd run",
                    "antigravity": f"Get-Content -Raw '{prompt_file}' | agy.exe exec",
                    "agy": f"Get-Content -Raw '{prompt_file}' | agy.exe exec",
                }
                pwsh_body = cli_map.get(target_agent, f"Get-Content -Raw '{prompt_file}' | opencode.cmd run")
                cmd = ["pwsh.exe", "-NoProfile", "-Command", f"cd '{cwd}'; {pwsh_body}"]

                with open(log_file, "a", encoding="utf-8") as lf:
                    res = subprocess.run(cmd, cwd=cwd, stdout=lf, stderr=subprocess.STDOUT)
                print(f"[{now()[11:19]}] [FINISHED] {target_agent.upper()} turn complete (exit {res.returncode}). Log: {log_file}", flush=True)

            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n[DAEMON] Stopped gracefully.", flush=True)
        return 0


# ================ KNOWLEDGE & CLAIMS COMMANDS ================

def cmd_init(args, cfg=None):
    for d in (CLAIMS_DIR, SPECS_DIR, TASKS_DIR, LOGS_DIR, SESSIONS_DIR,
              CONTEXT_DIR, CONTEXT_ARCHIVE_DIR, META_DIR,
              "decisions", "projects", "experiments", "people"):
        (VAULT / d).mkdir(parents=True, exist_ok=True)
    gitignore = """# state & lock files
.lock
*.tmp
meta/search_index.db
sessions/*.json
tasks/logs/
*.log
"""
    (VAULT / ".gitignore").write_text(gitignore, encoding="utf-8")
    save_config(load_config())
    readme_path = VAULT / "README.md"
    if not readme_path.exists():
        atomic_write(readme_path, f"# Second Brain (v4.3)\n\nMulti-agent coordination hub. Vault: {VAULT}\n")
    if not (VAULT / ".git").exists():
        subprocess.run(["git", "init"], cwd=VAULT, capture_output=True)
    reindex_all_search()
    git_commit("init vault skeleton v4.3")
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
        "claim": claim_text.split("\n")[0][:200],
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
    nfm["promoted_to"] = cid
    atomic_write(note["path"], frontmatter_block(nfm, CONTEXT_FM_ORDER) + "\n" + note["body"] + f"\n\n> Promoted to claim [[{cid}]] on {ts}\n")

    reindex_all_search()
    git_commit(f"promote {note['id']} -> claim {cid}")
    print(f"context note {note['id']} promoted to claim {cid} -> {claim_path(cid)}")
    return 0


def cmd_recall(args, cfg):
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
    specs = all_specs()
    tasks = all_tasks()

    print(f"claims: {len(claims)}  by status: {dict(counts)}")
    print(f"specs: {len(specs)} | tasks: {len(tasks)} ({sum(1 for t in tasks if t['fm'].get('status') == 'running')} running, {sum(1 for t in tasks if t['fm'].get('status') == 'review')} in review)")
    print(f"sessions: {len(sessions)} total, {len(active_sessions)} active | file locks: {len(file_locks)}")
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


# ================ UPSTREAM SPECS (Traycer Pattern) ================

def cmd_spec_create(args, cfg):
    ts = now()
    spec_id = "spec-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    fm = {
        "id": spec_id,
        "title": args.title,
        "project": args.project or "",
        "phases": args.phases or "",
        "created": ts,
        "updated": ts,
    }
    body = f"# Spec: {args.title}\n\n## Overview\n{args.spec}\n\n"
    if args.phases:
        body += "## Execution Phases\n"
        for i, ph in enumerate([p.strip() for p in args.phases.split(",") if p.strip()], 1):
            body += f"- [ ] **Phase {i}:** {ph}\n"
        body += "\n"

    atomic_write(spec_path(spec_id), frontmatter_block(fm, SPEC_FM_ORDER) + "\n" + body)
    reindex_all_search()
    git_commit(f"spec {spec_id}: {args.title[:60]}")
    print(f"spec {spec_id} created -> {spec_path(spec_id)}")
    return 0


def cmd_specs(args, cfg):
    specs = all_specs()
    if args.project:
        specs = [s for s in specs if s["fm"].get("project") == args.project]
    specs.reverse()
    print(f"== SPECS == ({len(specs)} shown)")
    for s in specs:
        fm = s["fm"]
        age = time_ago(fm.get("created", ""))
        proj = f" ({fm.get('project')})" if fm.get("project") else ""
        print(f"  [{s['id']}]{proj} {fm.get('title')} [{age}]")
        if fm.get("phases"):
            print(f"      phases: {fm.get('phases')}")
    return 0


# ================ KANBAN TASKS (agtx Pattern) ================

def cmd_task_create(args, cfg):
    ts = now()
    task_id = "t-" + datetime.now().strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:6]
    fm = {
        "id": task_id,
        "title": args.title,
        "project": args.project or "",
        "spec_id": args.spec or "",
        "phase": args.phase or "",
        "agent": args.agent or "",
        "status": "backlog",
        "files": args.files or "",
        "created": ts,
        "updated": ts,
    }
    body = f"# Task: {args.title}\n\n"
    if args.spec:
        body += f"Linked Spec: [[{args.spec}]]\n\n"
    body += "## Activity Log\n"
    body += f"- [{ts[11:16]}] Created in backlog\n"

    atomic_write(task_path(task_id), frontmatter_block(fm, TASK_FM_ORDER) + "\n" + body)
    reindex_all_search()
    git_commit(f"task {task_id}: {args.title[:60]} (backlog)")
    print(f"task {task_id} created in backlog -> {task_path(task_id)}")
    return 0


def cmd_task_move(args, cfg):
    target_status = args.status.lower()
    if target_status not in TASK_STATUSES:
        print(f"Invalid status '{target_status}'. Must be one of: {', '.join(TASK_STATUSES)}")
        return 1

    t = get_task(args.id)
    if not t:
        print(f"task {args.id} not found")
        return 1

    ts = now()
    old_status = t["fm"].get("status", "backlog")
    t["fm"]["status"] = target_status
    t["fm"]["updated"] = ts
    if args.agent:
        t["fm"]["agent"] = args.agent

    body = t["body"]
    agent_tag = f" by {args.agent}" if args.agent else ""
    notes_tag = f" — {args.notes}" if args.notes else ""
    log_line = f"- [{ts[11:16]}] Moved: {old_status} -> {target_status}{agent_tag}{notes_tag}\n"
    body += "\n" + log_line

    atomic_write(t["path"], frontmatter_block(t["fm"], TASK_FM_ORDER) + "\n" + body + "\n")
    reindex_all_search()
    git_commit(f"task {args.id}: {old_status} -> {target_status}")
    print(f"task {args.id} moved to [{target_status}]")
    return 0


def cmd_tasks(args, cfg):
    tasks = all_tasks()
    filtered = []
    for t in tasks:
        if args.project and t["fm"].get("project") != args.project:
            continue
        if args.status and t["fm"].get("status") != args.status:
            continue
        if args.agent and t["fm"].get("agent") != args.agent:
            continue
        filtered.append(t)

    print(f"== TASKS ({len(filtered)} total) ==")
    by_col = {col: [] for col in TASK_STATUSES}
    for t in filtered:
        col = t["fm"].get("status", "backlog")
        if col in by_col:
            by_col[col].append(t)

    for col in TASK_STATUSES:
        col_tasks = by_col[col]
        print(f"\n--- {col.upper()} ({len(col_tasks)}) ---")
        if not col_tasks:
            print("  (empty)")
        for t in col_tasks:
            fm = t["fm"]
            agent_str = f" [{fm.get('agent')}]" if fm.get("agent") else ""
            proj_str = f" ({fm.get('project')})" if fm.get("project") else ""
            spec_str = f" spec:[[{fm.get('spec_id')}]]" if fm.get("spec_id") else ""
            print(f"  * {t['id']}{proj_str}{agent_str}: {fm.get('title')}{spec_str}")
    return 0


# ================ SESSIONS & CONCURRENCY COMMANDS ================

def cmd_check_files(args, cfg):
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

    lease_mins = args.lease or cfg.get("session", {}).get("default_lease_mins", DEFAULT_LEASE_MINS)
    lease_expires = ""
    if args.files:
        exp_dt = datetime.now(timezone.utc) + timedelta(minutes=lease_mins)
        lease_expires = exp_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        target_files = [f.strip() for f in args.files.split(",") if f.strip()]
        locks = get_active_file_locks()
        conflicts = [f for f in target_files if f in locks]
        if conflicts:
            print(f"WARNING: File reservation conflict! Files already locked: {', '.join(conflicts)}")

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
        "task_id": args.task_id or "",
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
    s = get_session(args.id)
    if not s:
        print(f"session {args.id} not found")
        return 1
    ts = now()
    s["fm"]["status"] = "ended"
    s["fm"]["updated"] = ts
    s["fm"]["ended"] = ts
    s["fm"]["lease_expires"] = ""

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
    sessions = all_sessions()
    active = [s for s in sessions if s["fm"].get("status") == "active"]
    recent_ended = [s for s in sessions if s["fm"].get("status") == "ended"][-5:]

    tasks = all_tasks()
    notes = all_context_notes(include_archived=False)
    recent_notes = list(reversed(notes))[:5]
    claims = all_claims()
    active_claims = [c for c in claims if c["fm"].get("status", "active") == "active"]
    locks = get_active_file_locks()

    print("=" * 50)
    print("         SECOND BRAIN -- DASHBOARD (v4.3)")
    print("=" * 50)
    print()

    print("> KANBAN TASK BOARD")
    kanban_counts = {st: sum(1 for t in tasks if t['fm'].get('status') == st) for st in TASK_STATUSES}
    print(f"  Backlog: {kanban_counts['backlog']} | Planning: {kanban_counts['planning']} | Running: {kanban_counts['running']} | Review: {kanban_counts['review']} | Done: {kanban_counts['done']}")

    running_tasks = [t for t in tasks if t['fm'].get('status') == 'running']
    review_tasks = [t for t in tasks if t['fm'].get('status') == 'review']
    planning_tasks = [t for t in tasks if t['fm'].get('status') == 'planning']

    if planning_tasks:
        for t in planning_tasks:
            fm = t["fm"]
            agent = f" ({fm.get('agent')})" if fm.get("agent") else ""
            print(f"  [PLANNING]{agent} {t['id']} -> {fm.get('title')}")
    if running_tasks:
        for t in running_tasks:
            fm = t["fm"]
            agent = f" ({fm.get('agent')})" if fm.get("agent") else ""
            print(f"  [RUNNING]{agent} {t['id']} -> {fm.get('title')}")
    if review_tasks:
        for t in review_tasks:
            fm = t["fm"]
            agent = f" ({fm.get('agent')})" if fm.get("agent") else ""
            print(f"  [REVIEW]{agent} {t['id']} -> {fm.get('title')}")
    print()

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

    if locks:
        print(f"> ACTIVE FILE LEASES ({len(locks)})")
        for fpath, l in locks.items():
            print(f"  [LOCK] {fpath} -> {l['agent']} ({l['project']}) [expires in {l['remaining_mins']}m]")
        print()

    if recent_ended:
        print(f"> RECENT SESSIONS & HANDOFFS ({len(recent_ended)})")
        for s in reversed(recent_ended):
            fm = s["fm"]
            age = time_ago(fm.get("ended", fm.get("updated", "")))
            handoff = f" -> handoff to [{fm.get('target_agent')}]" if fm.get("target_agent") else ""
            print(f"  [done] {fm.get('agent','?')} -> {fm.get('project','') or 'unscoped'}: {fm.get('task','')}{handoff} (ended {age})")
        print()

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
            s["fm"]["lease_expires"] = ""
            body = s["body"]
            if "## Outcomes" in body:
                body = body.replace("## Outcomes\n(pending)", f"## Outcomes\n(stale — auto-expired by sweep {ts})")
            atomic_write(s["path"], frontmatter_block(s["fm"], SESSION_FM_ORDER) + "\n" + body + "\n")
            changed.append((s["id"], f"session stale (agent={s['fm'].get('agent','?')})"))

    ttl_days = int(cfg.get("context", {}).get("ttl_days", CONTEXT_TTL_DAYS))
    ttl_cutoff = datetime.now(timezone.utc) - timedelta(days=ttl_days)
    for n in all_context_notes(include_archived=False):
        try:
            created = datetime.strptime(n["fm"].get("created", ""), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        except ValueError:
            created = None
        if created and created < ttl_cutoff:
            arch_dir = VAULT / CONTEXT_ARCHIVE_DIR
            arch_dir.mkdir(parents=True, exist_ok=True)
            target_path = arch_dir / (n["id"] + ".md")
            os.replace(n["path"], target_path)
            changed.append((n["id"], f"context note archived (>{ttl_days}d old)"))

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

    reindex_all_search()

    l0_lines = [
        f"# Brain (auto-generated {ts})",
        "# Call brain_session_start on session begin. brain_recall for knowledge.",
        "",
    ]

    active_sessions = [s for s in all_sessions() if s["fm"].get("status") == "active"]
    if active_sessions:
        l0_lines.append("## Active Sessions")
        for s in active_sessions[:5]:
            fm = s["fm"]
            agent = fm.get("agent", "?")
            proj = fm.get("project", "") or "unscoped"
            task = fm.get("task", "")[:50]
            age = time_ago(fm.get("started", ""))
            locks = f" [locks: {fm.get('files')[:30]}..]" if fm.get('files') else ""
            l0_lines.append(f"- {agent} -> {proj}: {task}{locks} ({age})")
        l0_lines.append("")

    active_tasks = [t for t in all_tasks() if t["fm"].get("status") in ("running", "review", "planning")][:3]
    if active_tasks:
        l0_lines.append("## Active Tasks")
        for t in active_tasks:
            fm = t["fm"]
            st = fm.get("status", "").upper()
            agent = f" [{fm.get('agent')}]" if fm.get("agent") else ""
            l0_lines.append(f"- [{st}]{agent} {t['id']}: {fm.get('title')[:60]}")
        l0_lines.append("")

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

    active_claims = [c for c in all_claims() if c["fm"].get("status", "active") == "active"]
    l0_lines.append(f"## Knowledge ({len(active_claims)} active)")
    current_size = len(("\n".join(l0_lines) + "\n").encode("utf-8"))
    remaining = L0_BUDGET - current_size - 60  # safety reserve for trailing message

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
    ap = argparse.ArgumentParser(description="Second Brain — multi-agent coordination hub (v4.3)")
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

    # -- autonomous pipeline & dispatch commands --
    p_cr = sub.add_parser("cycle-route")
    p_cr.add_argument("--agent", required=True)
    p_cr.add_argument("--prompt", required=True)
    p_cr.add_argument("--project", default="")

    p_cn = sub.add_parser("cycle-next")
    p_cn.add_argument("--agent", required=True)
    p_cn.add_argument("--project", default="")

    p_disp = sub.add_parser("dispatch")
    p_disp.add_argument("id")
    p_disp.add_argument("--agent", default="")
    p_disp.add_argument("--tab", action="store_true", help="Launch in a new Windows Terminal tab")

    p_auto = sub.add_parser("auto-cycle")
    p_auto.add_argument("--project", default="")
    p_auto.add_argument("--tab", action="store_true", help="Launch in a new Windows Terminal tab")

    p_daemon = sub.add_parser("daemon")
    p_daemon.add_argument("--interval", type=int, default=15, help="Polling interval in seconds")
    p_daemon.add_argument("--project", default="", help="Scope daemon to a specific project")
    p_daemon.add_argument("--max-retries", type=int, default=3, help="Max attempts before circuit breaker")

    # -- upstream specs commands (Traycer) --
    p_spec_c = sub.add_parser("spec-create")
    p_spec_c.add_argument("--title", required=True)
    p_spec_c.add_argument("--spec", required=True)
    p_spec_c.add_argument("--project", default="")
    p_spec_c.add_argument("--phases", default="")

    p_specs = sub.add_parser("specs")
    p_specs.add_argument("--project", default="")

    # -- kanban tasks commands (agtx) --
    p_task_c = sub.add_parser("task-create")
    p_task_c.add_argument("--title", required=True)
    p_task_c.add_argument("--project", default="")
    p_task_c.add_argument("--spec", default="")
    p_task_c.add_argument("--agent", default="")
    p_task_c.add_argument("--phase", default="")
    p_task_c.add_argument("--files", default="")

    p_task_m = sub.add_parser("task-move")
    p_task_m.add_argument("id")
    p_task_m.add_argument("--status", required=True)
    p_task_m.add_argument("--agent", default="")
    p_task_m.add_argument("--notes", default="")

    p_tasks = sub.add_parser("tasks")
    p_tasks.add_argument("--project", default="")
    p_tasks.add_argument("--status", default="")
    p_tasks.add_argument("--agent", default="")

    # -- sessions & concurrency commands --
    p_ss = sub.add_parser("session-start")
    p_ss.add_argument("--agent", required=True)
    p_ss.add_argument("--project", default="")
    p_ss.add_argument("--task", default="")
    p_ss.add_argument("--task-id", default="")
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

    if args.cmd == "daemon":
        cfg = load_config()
        return cmd_daemon(args, cfg)

    with lock():
        cfg = load_config()
        handlers = {
            "init": cmd_init, "claim": cmd_claim, "supersede": cmd_supersede,
            "dispute": cmd_dispute, "promote": cmd_promote, "recall": cmd_recall,
            "status": cmd_status, "sweep": cmd_sweep, "verify": cmd_verify,
            "related": cmd_related, "cycle-route": cmd_cycle_route, "cycle-next": cmd_cycle_next,
            "dispatch": cmd_dispatch, "auto-cycle": cmd_auto_cycle,
            "spec-create": cmd_spec_create, "specs": cmd_specs,
            "task-create": cmd_task_create, "task-move": cmd_task_move, "tasks": cmd_tasks,
            "session-start": cmd_session_start, "session-update": cmd_session_update,
            "session-end": cmd_session_end, "reserve": cmd_reserve,
            "check-files": cmd_check_files, "sessions": cmd_sessions,
            "post": cmd_post, "read": cmd_read, "dashboard": cmd_dashboard,
        }
        return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
