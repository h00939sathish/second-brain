# -*- coding: utf-8 -*-
"""Terminal User Interface for Second Brain (OpenRig rig tui).

Provides a live, zero-dependency terminal dashboard displaying active agent sessions,
file leases, kanban board columns, squad loadout, and recent chatroom notes.
Supports both interactive curses loop and one-shot snapshot rendering.
"""

import sys
import time
from datetime import datetime

from . import board, coordination, knowledge, squad, workspaces as ws_mod
from .paths import now


def collect_state(workspace: str = "") -> dict:
    """Collect current snapshot of workspace status for TUI display."""
    slug = workspace or ws_mod.default_workspace()
    ws_info = ws_mod.entry(slug) or {}

    # Squad status
    sq_info = squad.squad_status(slug)

    # Active sessions
    active_sessions = coordination.list_sessions(workspace=slug, active_only=True)

    # Board tasks grouped by status
    all_tasks = board.list_tasks(workspace=slug)
    tasks_by_status = {"backlog": [], "planning": [], "running": [], "review": [], "done": []}
    for t in all_tasks:
        st = t.get("status", "backlog")
        if st in tasks_by_status:
            tasks_by_status[st].append(t)
        elif st == "coordinating":
            tasks_by_status["planning"].append(t)
        elif st in ("blocked", "ready"):
            tasks_by_status["backlog"].append(t)

    # Recent chat notes
    notes = coordination.read_notes(workspace=slug, limit=6)

    # Top claims
    claims, _ = knowledge.recall(workspace=slug, limit=4)

    return {
        "workspace": slug,
        "path": ws_info.get("path") or "(unbound)",
        "timestamp": now(),
        "squad": sq_info,
        "sessions": active_sessions,
        "tasks": tasks_by_status,
        "total_tasks": len(all_tasks),
        "notes": notes,
        "claims": claims,
    }


def render_snapshot(state: dict) -> str:
    """Render a text/ANSI formatted dashboard snapshot."""
    slug = state["workspace"]
    ts = state["timestamp"]
    lines = []

    width = 78
    sep = "=" * width
    subsep = "-" * width

    # Header
    lines.append(sep)
    lines.append(f" SECOND BRAIN TERMINAL DASHBOARD — [{slug}]".ljust(55) + f"{ts[:19]} ".rjust(23))
    lines.append(f" Project Root: {state['path']}")
    lines.append(sep)

    # Squad Loadout
    sq = state["squad"]
    lines.append(" [SQUAD MEMBERS]")
    sq_items = []
    for m in sq["members"]:
        role_label = m["role"].capitalize()
        agent_label = m["agent"] or "(unassigned)"
        status = "[ACTIVE]" if m["active"] else "[IDLE]"
        sq_items.append(f"  {role_label}: {agent_label} {status}")
    lines.append("  |  ".join(sq_items))
    lines.append(subsep)

    # Active Sessions & Leases
    sessions = state["sessions"]
    lines.append(f" [ACTIVE SESSIONS & FILE LEASES] ({len(sessions)} active)")
    if not sessions:
        lines.append("  (no active sessions - files are free)")
    else:
        for s in sessions:
            fm = s["fm"]
            ag = fm.get("agent", "unknown")
            t_id = fm.get("task_id") or "no-task"
            t_desc = fm.get("task", "")
            files = fm.get("files") or []
            files_str = f" leasing: {', '.join(files)}" if files else " (no files leased)"
            lines.append(f"  * {ag:<10} session {fm.get('id')} -> {t_id} [{t_desc[:30]}]{files_str}")
    lines.append(subsep)

    # Kanban Board
    tasks = state["tasks"]
    lines.append(f" [KANBAN BOARD] (Total: {state['total_tasks']})")
    col_str = (
        f"  BACKLOG ({len(tasks['backlog'])}) | "
        f"PLANNING ({len(tasks['planning'])}) | "
        f"RUNNING ({len(tasks['running'])}) | "
        f"REVIEW ({len(tasks['review'])}) | "
        f"DONE ({len(tasks['done'])})"
    )
    lines.append(col_str)

    # Show active and review tasks
    notable = tasks["running"] + tasks["review"] + tasks["planning"][:2]
    if notable:
        for t in notable[:5]:
            ag = t.get("agent") or "unassigned"
            lines.append(f"    - [{t.get('status').upper():<7}] {t['id']} ({ag}): {t.get('title', '')[:45]}")
    else:
        lines.append("    (board idle)")
    lines.append(subsep)

    # Recent Chatroom / Coordination Notes
    notes = state["notes"]
    lines.append(f" [AGENT CHATROOM & RECENT NOTES] (Latest {len(notes)})")
    if not notes:
        lines.append("  (no recent notes)")
    else:
        for n in reversed(notes):
            fm = n.get("fm") if isinstance(n.get("fm"), dict) else {}
            ag = n.get("agent") or fm.get("agent") or "anon"
            top_val = n.get("topic") or fm.get("topic") or ""
            top = f" #{top_val}" if top_val else ""
            body = (n.get("body") or "").splitlines()[0][:50]
            lines.append(f"  [{ag}{top}] {body}")
    lines.append(sep)

    return "\n".join(lines)


def run_curses(stdscr, workspace: str = "", interval: float = 2.0):
    """Interactive curses TUI loop."""
    import curses

    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(int(interval * 1000))

    while True:
        state = collect_state(workspace)
        text = render_snapshot(state)

        stdscr.erase()
        max_y, max_x = stdscr.getmaxyx()

        lines = text.splitlines()
        for idx, line in enumerate(lines[:max_y - 1]):
            stdscr.addstr(idx, 0, line[:max_x - 1])

        # Status prompt at bottom
        footer = " [Q] Quit  |  [R] Refresh  |  Auto-refreshing every 2s"
        if max_y > 1:
            try:
                stdscr.addstr(max_y - 1, 0, footer[:max_x - 1], curses.A_REVERSE)
            except curses.error:
                pass

        stdscr.refresh()

        try:
            ch = stdscr.getch()
            if ch in (ord('q'), ord('Q')):
                break
            if ch in (ord('r'), ord('R')):
                continue
        except (KeyboardInterrupt, curses.error):
            break
