# -*- coding: utf-8 -*-
"""L0 pointers: the compact brief injected at the start of an agent session.

Fixes over the previous generator:

* ranking. The old file dumped the 12 newest claims ordered by id and cut them
  mid-sentence (`...sqrt(365...`), so the always-injected context was mostly noise and
  the one durable operational fact — the machine's OS and GPU — was buried. Claims now
  rank by scope (global first) then review recency, and truncation happens on a word
  boundary.
* counting. It printed `and 40 more` after already listing 12 of 40. The remainder is
  now computed from what was actually written.
* scoping. There is one brief per workspace, so a JARVIS session is not handed TITAN's
  research findings, plus a small cross-workspace brief for global configs.
"""

import re

from . import board, const, coordination, dispatch, store, workspaces as ws_mod
from .paths import VAULT, atomic_write, l0_path, now, parse_ts, time_ago


def clip(text: str, limit: int = const.L0_MAX_LINE) -> str:
    """Truncate on a word boundary. Never splits a token in half."""
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut:
        cut = cut[: cut.rfind(" ")]
    return cut.rstrip(" ,;:-") + "…"


def _size(lines) -> int:
    return len(("\n".join(lines) + "\n").encode("utf-8"))


def shown_within(records, record) -> int:
    """How many of `records` precede `record` (i.e. were written before the cut)."""
    for index, candidate in enumerate(records):
        if candidate is record:
            return index
    return len(records)


def _claim_rank(record, slug: str):
    """This workspace first, then shared truth, then reviewed, then newest.

    Ordering global first looked reasonable until shared truth accumulated legacy facts
    from every project, at which point a JARVIS brief opened with TITAN research. What
    you are working on now outranks what everyone shares.
    """
    workspace = record["workspace"]
    score = 0
    if workspace == slug and slug:
        score += 30
    if workspace == const.GLOBAL_WORKSPACE:
        score += 20
    if parse_ts(record["fm"].get("reviewed_at")):
        score += 5
    try:
        score += min(4, float(record["fm"].get("confidence") or 0) * 4)
    except (TypeError, ValueError):
        pass
    return (score, str(record["fm"].get("created") or ""))


def render(workspace: str = "", budget: int = const.L0_BUDGET) -> str:
    """Build the brief for one workspace (empty string = cross-workspace summary)."""
    slug = workspace or ""
    scoped = bool(slug)
    session_scope = [slug] if scoped else None
    active_sessions = coordination.list_sessions(
        workspace=slug, active_only=True, all_workspaces=not scoped)
    active_tasks = board.list_tasks(workspace=slug, all_workspaces=not scoped)
    step = board.actionable(workspace=slug) if scoped else {}
    runs = [r for r in dispatch.all_run_records(slug)
            if r.get("mode") == "background" and r.get("returncode") is None][:3]

    lines = [
        f"# Second Brain — {'workspace ' + slug if scoped else 'all workspaces'} "
        f"({now()})",
        "# Start here: `brain brief` | `brain start --agent <you> --files ...` | "
        "`brain recall \"...\"`",
        "",
    ]

    if active_sessions:
        lines.append("## Live sessions")
        for session in active_sessions[:4]:
            fm = session["fm"]
            lease = f" [leases: {clip(fm.get('files'), 60)}]" if fm.get("files") else ""
            lines.append(
                f"- {fm.get('agent', '?')} → {session['workspace']}: "
                f"{clip(fm.get('task') or fm.get('task_id') or 'session', 60)}{lease} "
                f"({time_ago(fm.get('started'))})"
            )
        lines.append("")

    if runs:
        lines.append("## Dispatched right now")
        for run in runs:
            lines.append(f"- {run.get('agent')} on {run.get('task_id')} "
                         f"(pid {run.get('pid')}, {time_ago(run.get('started'))})")
        lines.append("")

    if active_tasks:
        counts = {status: 0 for status in const.TASK_STATUSES}
        for task in active_tasks:
            status = str(task["fm"].get("status") or "backlog")
            counts[status] = counts.get(status, 0) + 1
        summary = " | ".join(f"{status}: {counts[status]}" for status in const.TASK_STATUSES
                            if counts[status])
        lines.append(f"## Board ({summary})")
        for task in [t for t in active_tasks
                     if str(t["fm"].get("status")) in ("review", "running", "planning")][:4]:
            fm = task["fm"]
            lines.append(f"- [{str(fm.get('status')).upper()}] {task['id']}: "
                         f"{clip(fm.get('title'), 70)}")
        lines.append("")

    if step:
        lines += [f"## Next action — {step['agent']}",
                  f"- {step['task_id']} [{step['status']}] {clip(step['title'], 80)}", ""]

    notes = coordination.read_notes(workspace=slug, limit=3,
                                    all_workspaces=not scoped)
    if notes:
        lines.append("## Recent context")
        for note in notes:
            body = clip((note.get("body") or "").splitlines()[0] if note.get("body") else "", 90)
            lines.append(f"- [{note.get('agent', '?')}] {body} ({note.get('workspace', '')})")
        lines.append("")

    # ---- knowledge, budgeted ----
    all_claims = [c for c in store.all_records("claims")
                  if c["fm"].get("status") == "active"]
    if scoped:
        all_claims = [c for c in all_claims
                      if c["workspace"] in (slug, const.GLOBAL_WORKSPACE)]
    all_claims.sort(key=lambda c: _claim_rank(c, slug), reverse=True)

    # Two labelled buckets instead of one ranked list. A JARVIS session needs to see at a
    # glance which facts are its own work and which are shared truth: the separation is
    # the feature, so it should not be implicit in an ordering.
    if scoped:
        buckets = [(f"## Knowledge — {slug} ({sum(1 for c in all_claims if c['workspace'] == slug)})",
                    [c for c in all_claims if c["workspace"] == slug]),
                   (f"## Shared truth — from `{const.GLOBAL_WORKSPACE}` "
                    f"({sum(1 for c in all_claims if c['workspace'] != slug)})",
                    [c for c in all_claims if c["workspace"] != slug])]
    else:
        buckets = [(f"## Knowledge ({len(all_claims)} active claims across "
                    f"{len(ws_mod.all_slugs())} workspaces)", all_claims)]

    # Reserve room for the remainder line before filling.
    placeholder = "- … and 0000 more — run `brain recall \"<question>\"`"
    reserved = len(placeholder.encode("utf-8")) + 1
    shown = 0
    leftover = 0
    for heading, records in buckets:
        if not records:
            continue
        # Only append a heading once we know a line can follow it, or the brief ends on
        # an empty section that looks like data loss.
        if _size(lines + [heading, "- placeholder"]) + reserved > budget:
            leftover += len(records)
            continue
        lines.append(heading)
        for record in records:
            text = record["fm"].get("claim", "")
            line = f"- {clip(text, const.L0_MAX_LINE)} [[{record['id']}]]"
            if _size(lines + [line]) + reserved > budget:
                leftover += len(records) - shown_within(records, record)
                break
            lines.append(line)
            shown += 1
        lines.append("")
    remaining = max(leftover, len(all_claims) - shown)
    if remaining > 0:
        while lines and not lines[-1]:
            lines.pop()
        lines.append(f"- … and {remaining} more — run `brain recall \"<question>\"`")

    return "\n".join(lines).rstrip("\n") + "\n"


def write(workspace: str = "") -> str:
    """Regenerate the brief. Scoped workspaces get their own file, plus the shared one."""
    text = render(workspace)
    if workspace:
        target = ws_mod.workspace_dir(workspace) / const.L0_NAME
    else:
        target = l0_path()
    atomic_write(target, text)
    return text


def write_all() -> list:
    generated = []
    for slug in ws_mod.all_slugs():
        write(slug)
        generated.append(slug)
    write("")
    return generated


def read(workspace: str = "") -> str:
    if workspace:
        path = ws_mod.workspace_dir(workspace) / const.L0_NAME
    else:
        path = l0_path()
    if not path.exists():
        write(workspace)
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def budget_state(workspace: str = "") -> dict:
    text = render(workspace)
    return {"bytes": len(text.encode("utf-8")), "budget": const.L0_BUDGET,
            "workspace": workspace or "all",
            "over": len(text.encode("utf-8")) > const.L0_BUDGET}
