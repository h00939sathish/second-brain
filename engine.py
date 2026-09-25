#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Second Brain legacy entry point.

The implementation now lives in the `brain` package (one module per concern).
This file stays as:

  * the CLI entry point                -> `python engine.py <command>` / `brain <command>`
  * a compatibility shim               -> the old module-level helpers
                                          (`all_claims`, `get_active_file_locks`,
                                          `lock`, `cmd_*`, ...) keep working for
                                          scripts and editor plugins written earlier.

New code should import `brain.<module>` directly.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from brain import (board, const, coordination, daemon, dispatch, frontmatter, index,  # noqa: E402
                   knowledge, l0, maintenance, store, vcs, workspaces as ws_mod)
from brain import agents, cli  # noqa: E402
from brain.errors import BrainError, LeaseConflict, NotFound, ReviewGate  # noqa: E402
from brain.paths import (FileLock, VAULT, atomic_write, lock, l0_path, now,  # noqa: E402
                         parse_ts, stdout_utf8, time_ago)

# ---- legacy constants ----------------------------------------------------
META_DIR = const.META_DIR
CLAIMS_DIR = "claims"
SPECS_DIR = "specs"
TASKS_DIR = "tasks"
SESSIONS_DIR = "sessions"
CONTEXT_DIR = "context"
LOGS_DIR = "logs"
CONFIG_NAME = const.CONFIG_NAME
L0_NAME = const.L0_NAME
DB_NAME = const.DB_NAME
STATUSES = const.STATUSES
WITHHELD_STATUSES = const.WITHHELD_STATUSES
TASK_STATUSES = const.TASK_STATUSES
AGENT_ROLES = const.AGENT_ROLES
L0_BUDGET = const.L0_BUDGET
L0_MAX_LINE = const.L0_MAX_LINE
SESSION_STALE_HOURS = const.SESSION_STALE_HOURS
DEFAULT_LEASE_MINS = const.DEFAULT_LEASE_MINS
CONTEXT_TTL_DAYS = const.CONTEXT_TTL_DAYS


# ---- legacy helpers ------------------------------------------------------


def load_config():
    return store.config()


def save_config(cfg):
    store.save_config(cfg)


def reindex_all_search():
    """Kept for compatibility. Writes reindex one document; this forces a rebuild."""
    return index.reindex_all()


def parse_frontmatter(path):
    return frontmatter.parse_file(Path(path))


def frontmatter_block(fm, key_order=None):
    return frontmatter.dumps(fm, key_order)


def git_commit(msg, paths=None):
    """Was `git add -A` + commit --allow-empty. Now scoped to brain data dirs."""
    targets = paths or [str(ws_mod.workspaces_root()), str(VAULT / "meta")]
    return vcs.commit(msg, paths=targets)


def all_claims(workspaces=None):
    return store.all_records("claims", workspaces)


def all_specs(workspaces=None):
    return store.all_records("specs", workspaces)


def all_tasks(workspaces=None):
    return store.all_records("tasks", workspaces)


def all_sessions(workspaces=None):
    return store.all_records("sessions", workspaces)


def all_context_notes(include_archived=False, workspaces=None):
    records = store.all_records("context", workspaces)
    if include_archived:
        for slug in (workspaces or ws_mod.all_slugs()):
            archive = ws_mod.subdir(slug, "context/archive")
            if not archive.is_dir():
                continue
            for path in sorted(archive.glob("*.md")):
                record = store.read_record("context", path.stem, workspace=slug)
                if record:
                    records.append(record)
    return records


def get_claim(cid, workspace=""):
    return (store.find_record("claims", cid) or (None, None))[1]


def get_spec(spec_id, workspace=""):
    return (store.find_record("specs", spec_id) or (None, None))[1]


def get_task(task_id, workspace=""):
    return (store.find_record("tasks", task_id) or (None, None))[1]


def get_session(sid, workspace=""):
    return (store.find_record("sessions", sid) or (None, None))[1]


def get_context_note(nid, workspace=""):
    return (store.find_record("context", nid) or (None, None))[1]


def get_active_file_locks(workspaces=None):
    return store.build_locks(workspaces)


def task_path(task_id):
    found = store.find_record("tasks", task_id)
    return found[1]["path"] if found else ws_mod.subdir(
        ws_mod.default_workspace(), "tasks") / f"{task_id}.md"


def chain_issues(cid, seen=None):
    return knowledge.chain_issues(cid)


def current_workspace(explicit=""):
    return ws_mod.detect(explicit=explicit)


# ---- legacy command adapters --------------------------------------------
# The old handlers took an argparse Namespace plus a config dict. The new ones take
# the same shape, so one adapter covers every command and keeps field names aligned.

_LEGACY_DEFAULTS = {
    "workspace": "",
    "json": False,
    "all_workspaces": False,
    "tab": False,
    "wait": False,
    "timeout": 0,
    "force": False,
    "tests": "",
    "limit": 0,
    "all": False,
    "commit": False,
    "global_scope": False,
    "note": "",
    "description": "",
    "default": False,
    "no_git": False,
    "agent": "",
    "project": "",
    "task": "",
    "task_id": "",
    "files": "",
    "branch": "",
    "worktree": "",
    "lease": 0,
    "status": "",
    "reason": "",
    "by": "",
    "summary": "",
    "target_agent": "",
    "next_steps": "",
    "modified_files": "",
    "test_status": "",
    "progress": "",
    "extend_lease": 0,
    "active": False,
    "tags": "",
    "confidence": 0.9,
    "source": "",
    "spec": "",
    "phases": "",
    "title": "",
    "text": "",
    "query": "",
    "tag": "",
    "id": "",
    "newid": "",
    "prompt": "",
    "action": "list",
    "name": "",
    "path": "",
    "verbose": False,
    "write": False,
    "dry_run": False,
    "no_shim": False,
    "bind": "",
    "pointer": False,
    "keywords": [],
    "fix": False,
    "display_name": "",
    "alias": [],
    "no_commit": False,
    "once": False,
    "max_retries": daemon.MAX_ATTEMPTS,
    "interval": 15,
    "port": 8000,
    "host": "127.0.0.1",
}


def _adapter(handler):
    def call(args=None, cfg=None):
        merged = dict(_LEGACY_DEFAULTS)
        if args is not None:
            merged.update({k: v for k, v in vars(args).items() if v is not None})
        ns = SimpleNamespace(**merged)
        out = cli.Out(as_json=bool(ns.json))
        try:
            if handler in (cli.cmd_daemon, cli.cmd_serve, cli.cmd_guard, cli.cmd_brief):
                return handler(ns, out, cfg or store.config())
            with lock():
                return handler(ns, out, cfg or store.config())
        except ReviewGate as exc:
            print(f"REFUSED (review gate): {exc}", file=sys.stderr)
            return 2
        except LeaseConflict as exc:
            print(f"REFUSED (lease conflict): {exc}", file=sys.stderr)
            return 2
        except NotFound as exc:
            print(f"not found: {exc}", file=sys.stderr)
            return 1
        except BrainError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
    call.__name__ = getattr(handler, "__name__", "command")
    return call


cmd_init = _adapter(cli.cmd_init)
cmd_status = _adapter(cli.cmd_status)
cmd_doctor = _adapter(cli.cmd_doctor)
cmd_migrate = _adapter(cli.cmd_migrate)
cmd_brief = _adapter(cli.cmd_brief)
cmd_whoami = _adapter(cli.cmd_whoami)
cmd_claim = _adapter(cli.cmd_claim)
cmd_review = _adapter(cli.cmd_review)
cmd_supersede = _adapter(cli.cmd_supersede)
cmd_dispute = _adapter(cli.cmd_dispute)
cmd_promote = _adapter(cli.cmd_promote)
cmd_recall = _adapter(cli.cmd_recall)
cmd_related = _adapter(cli.cmd_related)
cmd_verify = _adapter(cli.cmd_verify)
cmd_sweep = _adapter(cli.cmd_sweep)
cmd_workspaces = _adapter(cli.cmd_workspaces)
cmd_spec_create = _adapter(cli.cmd_spec_create)
cmd_specs = _adapter(cli.cmd_specs)
cmd_task_create = _adapter(cli.cmd_task_create)
cmd_task_move = _adapter(cli.cmd_move)
cmd_move = _adapter(cli.cmd_move)
cmd_tasks = _adapter(cli.cmd_tasks)
cmd_cycle_route = _adapter(cli.cmd_route)
cmd_route = _adapter(cli.cmd_route)
cmd_cycle_next = _adapter(cli.cmd_next)
cmd_next = _adapter(cli.cmd_next)
cmd_session_start = _adapter(cli.cmd_start)
cmd_start = _adapter(cli.cmd_start)
cmd_session_update = _adapter(cli.cmd_update)
cmd_session_end = _adapter(cli.cmd_end)
cmd_end = _adapter(cli.cmd_end)
cmd_reserve = _adapter(cli.cmd_reserve)
cmd_check_files = _adapter(cli.cmd_check_files)
cmd_sessions = _adapter(cli.cmd_sessions)
cmd_post = _adapter(cli.cmd_post)
cmd_read = _adapter(cli.cmd_read)
cmd_guard = _adapter(cli.cmd_guard)
cmd_setup = _adapter(cli.cmd_setup)
cmd_bootstrap = _adapter(cli.cmd_bootstrap)
cmd_dispatch = _adapter(cli.cmd_dispatch)
cmd_auto_cycle = _adapter(cli.cmd_auto_cycle)
cmd_runs = _adapter(cli.cmd_runs)
cmd_daemon = _adapter(cli.cmd_daemon)
cmd_serve = _adapter(cli.cmd_serve)
cmd_reindex = _adapter(cli.cmd_reindex)
cmd_repair = _adapter(cli.cmd_repair)
cmd_reclassify = _adapter(cli.cmd_reclassify)


def cmd_dashboard(args=None, cfg=None):
    """Legacy human dashboard. The live version of this is the HTTP API at /."""
    workspace = getattr(args, "workspace", "") or ""
    slug = ws_mod.detect(explicit=workspace)
    board_data = board.board(workspace=slug)
    locks = store.build_locks(ws_mod.read_scope(slug))
    sessions = coordination.list_sessions(workspace=slug, active_only=True)
    dstatus = daemon.daemon_status()
    budget = l0.budget_state(slug)

    print("=" * 60)
    print(f"  SECOND BRAIN — workspace '{slug}'")
    print("=" * 60)
    print("\n> BOARD")
    print("  " + " | ".join(f"{k}: {v}" for k, v in board_data["counts"].items()))
    for status in ("planning", "running", "review"):
        for task in board_data["columns"].get(status, []):
            print(f"  [{status.upper()}] {task['id']} -> {task['fm'].get('title')}")
    print(f"\n> LIVE SESSIONS ({len(sessions)})")
    for session in sessions:
        fm = session["fm"]
        print(f"  [LIVE] {fm.get('agent')} -> {fm.get('project') or 'unscoped'}: "
              f"{fm.get('task') or fm.get('task_id') or ''} "
              f"({time_ago(fm.get('started'))})")
        if fm.get("files"):
            print(f"         leases: {', '.join(fm['files'])}")
    if not sessions:
        print("  (none)")
    if locks:
        print(f"\n> FILE LEASES ({len(locks)})")
        for target, info in locks.items():
            print(f"  [LOCK] {target} -> {info['agent']} ({info['remaining_mins']}m left)")
    handoffs = coordination.handoffs(workspace=slug, limit=5)
    if handoffs:
        print(f"\n> RECENT HANDOFFS ({len(handoffs)})")
        for session in handoffs:
            fm = session["fm"]
            print(f"  {fm.get('agent')} -> {fm.get('target_agent')}"
                  f"{' (' + str(fm.get('test_status')) + ')' if fm.get('test_status') else ''}")
    stats = knowledge.stats()
    print(f"\n> VAULT: {stats['total']} claims ({stats['by_status'].get('active', 0)} active), "
          f"L0={budget['bytes']}B/{budget['budget']}B, "
          f"daemon={'up' if dstatus['active'] else 'down'}")
    return 0


def main(argv=None):
    return cli.main(argv)


if __name__ == "__main__":
    stdout_utf8()
    sys.exit(main())
