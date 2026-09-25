# -*- coding: utf-8 -*-
"""Sessions, file leases and the shared scratchpad.

This is the module that makes concurrency real instead of advisory. `start` and
`reserve` raise LeaseConflict when another live session holds a target file, so two
agents cannot silently rewrite the same file. `BRAIN_BYPASS=1` or `--force` is the
documented break-glass path.
"""

import time

from . import board, const, events, index, store, workspaces as ws_mod
from .errors import BrainError, LeaseConflict, NotFound
from .paths import VAULT, now, parse_ts, stamp

ACTIVE = "active"
ENDED = "ended"
STALE = "stale"


def _split(files) -> list:
    if not files:
        return []
    if isinstance(files, (list, tuple)):
        raw = files
    else:
        raw = str(files).split(",")
    return [str(f).strip() for f in raw if str(f).strip()]


def _conflicts(files, slugs, exclude_session: str = "") -> list:
    """Which of `files` fall inside another live session's lease.

    `store.check_files` compares lease strings verbatim, so a session that leased `src/`
    left every file underneath it looking free, and a lease taken on `src/a` was answered
    by a request for `src/anything`. Matching goes through `board.lease_covers` — the same
    rule the evidence gate uses — so one path rule governs both.
    """
    return board.lease_conflicts(_split(files), store.build_locks(slugs),
                                 exclude_session=exclude_session)


def _may_touch(session, slug: str, action: str = "") -> None:
    """Refuse to act inside a session the caller's seat does not hold.

    A session id names somebody else's lease; it is not a credential, and until now
    knowing one was enough to extend it, re-lease files under it, or end it with a handoff
    of your own invention. The same `board.may_speak_for` answer governs cards and leases.
    """
    holder = str(session["fm"].get("agent") or "")
    ok, why = board.may_speak_for(holder)
    if not ok:
        board.refuse_ownership(slug, f"{action or 'this action'} on session {session['id']}: {why}",
                               task_id=str(session["fm"].get("task_id") or ""),
                               session=session["id"], holder=holder)


# ---- sessions ------------------------------------------------------------


def start(agent: str, workspace: str = "", project: str = "", task: str = "",
          task_id: str = "", files="", branch: str = "", worktree: str = "",
          lease_mins: int = 0, force: bool = False, cfg=None) -> dict:
    agent = board.resolve_agent(agent)
    if not agent:
        raise BrainError("a session needs an agent name")
    slug = workspace or ws_mod.default_workspace()
    if not ws_mod.exists(slug):
        ws_mod.register(slug, path=str(VAULT))

    # A lease is a claim about who is working, so it is checked against the seat the
    # caller declared rather than against the name it typed: an uncorroborated `--agent`
    # is what every downstream gate used to trust.
    ok, why = board.may_speak_for(agent)
    if not ok:
        board.refuse_ownership(slug, f"cannot open a session as {agent}: {why}",
                               task_id=task_id, claimed=agent)

    targets = _split(files)
    if targets and not force:
        conflicts = _conflicts(targets, [slug])
        if conflicts:
            holder = conflicts[0][1]["agent"]
            events.emit("LEASE_DENIED", stage="AUTHORIZE", actor=f"agent:{agent}",
                        workspace=slug, task_id=task_id,
                        payload={"requested_files": targets, "conflicts": [path for path, _ in conflicts], "holder": holder})
            raise LeaseConflict([path for path, _ in conflicts], holder)

    lease_mins = int(lease_mins or (cfg or {}).get("session", {}).get(
        "default_lease_mins", const.DEFAULT_LEASE_MINS))
    lease_expires = stamp(minutes=lease_mins) if targets else ""
    if branch == "":
        from . import vcs
        branch = vcs.current_branch()

    session_id = store.new_id("sessions")
    started = now()
    fm = {
        "id": session_id,
        "agent": agent,
        "project": project or slug,
        "workspace": slug,
        "task": task or "",
        "task_id": task_id or "",
        "branch": branch or "",
        "worktree": worktree or "",
        "status": ACTIVE,
        "files": targets,
        "lease_expires": lease_expires,
        "started": started,
        "updated": started,
        "ended": "",
    }
    body = [
        "## Progress",
        f"- [{started[11:16]}] session opened"
        + (f" for {task_id}" if task_id else "")
        + (f" on {project}" if project else ""),
    ]
    if targets:
        body.append(f"- [{started[11:16]}] leased {len(targets)} file(s) for {lease_mins}m")
    body += ["", "## Outcomes", "(pending)"]
    path = store.write_record("sessions", fm, "\n".join(body), workspace=slug)
    events.emit("LEASE_GRANTED", stage="AUTHORIZE", actor=f"agent:{agent}",
                workspace=slug, task_id=task_id,
                payload={"session_id": session_id, "files": targets, "lease_expires": lease_expires})

    # A builder session implies its card is running. Keep them consistent.
    if task_id:
        try:
            board.move(task_id, "running", workspace=slug, agent=agent,
                       notes=f"session {session_id} opened")
        except (BrainError, NotFound):
            pass
    return {"id": session_id, "workspace": slug, "path": str(path),
            "files": targets, "lease_expires": lease_expires}


def get(session_id: str, workspace: str = ""):
    return store.find_record("sessions", session_id, [workspace] if workspace else None)


def update(session_id: str, progress: str = "", files="", extend_lease: int = 0,
           workspace: str = "") -> dict:
    found = get(session_id, workspace)
    if not found:
        raise NotFound(f"session {session_id} not found")
    slug, session = found
    if session["fm"].get("status") != ACTIVE:
        raise BrainError(f"session {session_id} is {session['fm'].get('status')}, not active")
    _may_touch(session, slug, "update")

    targets = _split(files)
    if targets:
        conflicts = _conflicts(targets, [slug], exclude_session=session_id)
        if conflicts:
            raise LeaseConflict([path for path, _ in conflicts], conflicts[0][1]["agent"])
        session["fm"]["files"] = targets
    # Extending the lease must not require re-declaring the files you already hold.
    if extend_lease:
        if not session["fm"].get("files"):
            raise BrainError(
                f"session {session_id} holds no files, so there is nothing to extend "
                "(pass --files to lease some first)"
            )
        session["fm"]["lease_expires"] = stamp(minutes=int(extend_lease))

    stamp_now = now()
    session["fm"]["updated"] = stamp_now
    line = f"- [{stamp_now[11:16]}] "
    if progress:
        line += progress
    else:
        line += "updated"
    if targets:
        line += f" (leased: {', '.join(targets)})"
    session["body"] = _insert_before_outcomes(session["body"], line)
    store.update_record("sessions", session, workspace=slug)
    return {"id": session_id, "workspace": slug}


def reserve(session_id: str, files, lease_mins: int = 0, workspace: str = "",
            force: bool = False, cfg=None) -> dict:
    found = get(session_id, workspace)
    if not found:
        raise NotFound(f"session {session_id} not found")
    slug, session = found
    if session["fm"].get("status") != ACTIVE:
        raise BrainError(f"session {session_id} is not active")
    _may_touch(session, slug, "reserve")
    targets = _split(files)
    if not targets:
        raise BrainError("nothing to reserve")
    if not force:
        conflicts = _conflicts(targets, [slug], exclude_session=session_id)
        if conflicts:
            holder = conflicts[0][1]["agent"]
            events.emit("LEASE_DENIED", stage="AUTHORIZE",
                        actor=f"agent:{session['fm'].get('agent', '')}",
                        workspace=slug, task_id=str(session['fm'].get('task_id') or ''),
                        payload={"requested_files": targets, "conflicts": [path for path, _ in conflicts], "holder": holder})
            raise LeaseConflict([path for path, _ in conflicts], conflicts[0][1]["agent"])
    lease_mins = int(lease_mins or (cfg or {}).get("session", {}).get(
        "default_lease_mins", const.DEFAULT_LEASE_MINS))
    session["fm"]["files"] = targets
    session["fm"]["lease_expires"] = stamp(minutes=lease_mins)
    session["fm"]["updated"] = now()
    session["body"] = _insert_before_outcomes(
        session["body"], f"- [{now()[11:16]}] leased {len(targets)} file(s) for {lease_mins}m"
    )
    store.update_record("sessions", session, workspace=slug)
    events.emit("LEASE_GRANTED", stage="AUTHORIZE",
                actor=f"agent:{session['fm'].get('agent', '')}",
                workspace=slug, task_id=str(session['fm'].get('task_id') or ''),
                payload={"session_id": session_id, "files": targets, "lease_expires": session["fm"]["lease_expires"]})
    return {"id": session_id, "workspace": slug, "files": targets,
            "lease_expires": session["fm"]["lease_expires"]}


def end(session_id: str, summary: str = "", target_agent: str = "", next_steps: str = "",
        modified_files="", test_status: str = "", workspace: str = "",
        status: str = ENDED, closure_reason: str = "", closure_target: str = "") -> dict:
    found = get(session_id, workspace)
    if not found:
        raise NotFound(f"session {session_id} not found")
    slug, session = found
    # Before anything is mutated: ending somebody else's session used to release their
    # lease and let the caller invent the handoff that follows it.
    _may_touch(session, slug, "end")
    finished = now()
    session["fm"]["status"] = status
    session["fm"]["updated"] = finished
    session["fm"]["ended"] = finished
    session["fm"]["lease_expires"] = ""
    current_agent = board.resolve_agent(session["fm"].get("agent", ""))

    if target_agent:
        resolved_target = board.resolve_agent(target_agent)
        from . import topology
        # `current_agent` is no longer the claim this check has to trust: `start` bound it
        # to a seat and `_may_touch` re-checked it, so the route is audited from an
        # identity the caller cannot type into existence.
        allowed, reason = topology.can_route(current_agent, resolved_target, workspace=slug)
        if not allowed:
            raise topology.TopologyError(f"handoff denied: {reason}")
        session["fm"]["target_agent"] = resolved_target

    if test_status:
        session["fm"]["test_status"] = test_status

    outcomes = ["## Outcomes", summary or "(completed)"]
    extras = []
    if session["fm"].get("target_agent"):
        extras.append(f"- **Handoff to:** `{session['fm']['target_agent']}`")
    if modified_files:
        extras.append(f"- **Modified:** `{', '.join(_split(modified_files))}`")
    if test_status:
        extras.append(f"- **Tests:** `{test_status}`")
    if next_steps:
        extras.append(f"- **Next:** {next_steps}")
    if extras:
        outcomes += ["", "### Handoff Details", *extras]

    session["body"] = _replace_outcomes(session["body"], "\n".join(outcomes))
    store.update_record("sessions", session, workspace=slug)

    task_id = str(session["fm"].get("task_id") or "")
    events.emit("LEASE_RELEASED", stage="AUTHORIZE",
                actor=f"agent:{session['fm'].get('agent', '')}",
                workspace=slug, task_id=task_id,
                payload={"session_id": session_id, "status": status,
                         "target_agent": session['fm'].get("target_agent", ""),
                         "test_status": test_status})

    # Auto-post handoff notification to recipient inbox
    if session["fm"].get("target_agent"):
        try:
            from . import messaging
            msg_body = (
                f"Handoff from session `{session_id}` (Task: `{task_id or 'none'}`).\n\n"
                f"**Summary:** {summary or '(completed)'}\n"
                f"**Tests:** {test_status or '(none recorded)'}\n"
                f"**Next Steps:** {next_steps or '(none specified)'}"
            )
            messaging.send(
                body=msg_body,
                sender=current_agent or "unknown",
                recipient=session["fm"]["target_agent"],
                workspace=slug,
                task_id=task_id,
                kind="handoff",
            )
        except Exception as exc:
            # The handoff itself is recorded on the session; the inbox note is a
            # convenience. Dropping a refusal into a black hole is how a forgery
            # complaint turns into a missing-message mystery.
            events.emit("MESSAGE_NOT_DELIVERED", stage="AUTHORIZE", workspace=slug,
                        task_id=task_id, actor=f"agent:{current_agent or 'unknown'}",
                        payload={"to": session["fm"]["target_agent"],
                                 "kind": "handoff", "reason": str(exc)[:240]})

    # Record closure intent on task if specified
    if task_id and (closure_reason or closure_target):
        found_task = board.get_task(task_id, slug)
        if found_task:
            _, task_rec = found_task
            if closure_reason:
                task_rec["fm"]["closure_reason"] = closure_reason
            if closure_target or session["fm"].get("target_agent"):
                task_rec["fm"]["closure_target"] = closure_target or session["fm"].get("target_agent", "")
            store.update_record("tasks", task_rec, workspace=slug)

    # Route the card forward so the board reflects reality without a second command.
    if task_id:
        try:
            if board.role_of(session["fm"]["target_agent"] if session["fm"].get("target_agent")
                             else "") == "reviewer":
                board.move(task_id, "review", workspace=slug,
                           notes=f"handed off by session {session_id}")
            elif status == ENDED and not session["fm"].get("target_agent"):
                board.move(task_id, "review", workspace=slug,
                           notes=f"session {session_id} finished")
        except (BrainError, NotFound):
            pass
    return {"id": session_id, "workspace": slug, "status": status}


def list_sessions(agent: str = "", workspace: str = "", project: str = "",
                  active_only: bool = False, all_workspaces: bool = False) -> list:
    slugs = ws_mod.all_slugs() if all_workspaces else (
        ws_mod.read_scope(workspace or ws_mod.default_workspace()))
    sessions = store.all_records("sessions", slugs)
    if agent:
        wanted = board.resolve_agent(agent)
        sessions = [s for s in sessions if board.resolve_agent(s["fm"].get("agent")) == wanted]
    if project:
        sessions = [s for s in sessions if str(s["fm"].get("project")) == project]
    if active_only:
        sessions = [s for s in sessions if s["fm"].get("status") == ACTIVE]
    return sorted(sessions, key=lambda s: str(s["fm"].get("started") or ""), reverse=True)


def check_files(files, workspace: str = "", exclude_session: str = "") -> list:
    slug = workspace or ws_mod.default_workspace()
    return _conflicts(files, ws_mod.read_scope(slug), exclude_session)


OPERATOR = board.OPERATOR


def admit(agent: str, files=(), workspace: str = "") -> dict:
    """Decide whether `agent` may mutate files right now, and say why not.

    The previous rule was `any active session in this workspace`, which meant one agent
    could write freely under another agent's session and the leases protected nothing.
    Clearance is now per-agent, and when the agent is not the lease holder the specific
    paths decide: touching somebody else's leased file is refused, working in parallel
    on different files is allowed (and reported).
    """
    slug = workspace or ws_mod.detect()
    who = board.resolve_agent(agent) if agent else "unknown"
    files = _split(files)
    active = list_sessions(workspace=slug, active_only=True)
    decision = {"ok": False, "agent": who, "workspace": slug, "session": None,
                "files": files, "conflict": [], "reason": ""}
    if not active:
        decision["reason"] = f"no active session for workspace '{slug}'"
        return decision
    # A session opened by the agent itself (or by the human operator) is full clearance.
    for session in active:
        holder = board.resolve_agent(session["fm"].get("agent"))
        if holder in (who, OPERATOR) or not agent:
            decision.update(ok=True, session=session["id"],
                            reason=f"session {session['id']} held by {holder}")
            return decision
    holders = sorted({str(s["fm"].get("agent", "?")) for s in active})
    if files:
        conflicts = check_files(files, workspace=slug)
        if not conflicts:
            decision.update(ok=True, reason=f"no lease conflict with {', '.join(holders)} "
                                            f"(no session opened by {who})")
            return decision
        decision["conflict"] = [{"path": path, "holder": info.get("agent", "?")}
                                for path, info in conflicts]
        decision["reason"] = (
            f"{len(conflicts)} file(s) leased by {', '.join(holders)}: "
            + ", ".join(f"{c['path']} ({c['holder']})" for c in decision["conflict"]))
        return decision
    decision["reason"] = (f"workspace '{slug}' is held by {', '.join(holders)} and "
                          f"{who} has no session of its own")
    return decision


def handoffs(workspace: str = "", limit: int = 10) -> list:
    sessions = [s for s in list_sessions(workspace=workspace, all_workspaces=not workspace)
                if s["fm"].get("target_agent")]
    return sorted(sessions, key=lambda s: str(s["fm"].get("ended") or ""), reverse=True)[:limit]


def expire_stale(workspace: str = "", hours: int = 0, cfg=None) -> list:
    """Close abandoned sessions. Called by sweep; never by a read path."""
    hours = int(hours or (cfg or {}).get("session", {}).get(
        "stale_after_hours", const.SESSION_STALE_HOURS))
    changed = []
    for session in list_sessions(workspace=workspace, all_workspaces=not workspace,
                                 active_only=True):
        last = parse_ts(session["fm"].get("updated") or session["fm"].get("started"))
        if last is None:
            continue
        if (parse_ts(now()) - last).total_seconds() < hours * 3600:
            continue
        end(session["id"], summary=f"auto-closed by sweep after {hours}h without an update",
            workspace=session["workspace"], status=STALE)
        changed.append((session["id"], f"session stale (agent={session['fm'].get('agent')})"))
    return changed


# ---- context notes -------------------------------------------------------


def post(text: str, workspace: str = "", project: str = "", tags="", agent: str = "",
         topic: str = "") -> dict:
    text = (text or "").strip()
    if not text:
        raise BrainError("a context note needs text")
    slug = workspace or ws_mod.default_workspace()
    note_id = store.new_id("context")
    created = now()
    all_tags = _split(tags)
    topic = (topic or "").strip()
    if topic and f"topic:{topic}" not in all_tags:
        all_tags.append(f"topic:{topic}")
    fm = {
        "id": note_id,
        "agent": board.resolve_agent(agent) or "unknown",
        "project": project or slug,
        "workspace": slug,
        "tags": ",".join(all_tags),
        "created": created,
    }
    if topic:
        fm["topic"] = topic
    path = store.write_record("context", fm, text, workspace=slug)
    res = {"id": note_id, "workspace": slug, "path": str(path)}
    if topic:
        res["topic"] = topic
    return res


def read_notes(query: str = "", workspace: str = "", project: str = "", agent: str = "",
               tag: str = "", topic: str = "", limit: int = 0, all_workspaces: bool = False) -> list:
    slug = workspace or ws_mod.default_workspace()
    scope = ws_mod.all_slugs() if all_workspaces else ws_mod.read_scope(slug)
    index.sync(kinds=("context",))
    topic = (topic or "").strip()
    search_tag = f"topic:{topic}" if topic else tag
    rows = index.search("context", query=query, workspace=scope, limit=limit,
                        filters={"project": project, "agent": board.resolve_agent(agent),
                                 "tags": search_tag},
                        order="rank" if query.strip() else "recent")
    results = []
    for row in rows:
        tags_str = row.get("tags", "") or ""
        row_topic = ""
        for t in tags_str.split(","):
            t = t.strip()
            if t.startswith("topic:"):
                row_topic = t[6:]
                break
        if topic and row_topic != topic:
            continue
        results.append({
            "id": row["id"],
            "workspace": row.get("workspace", ""),
            "agent": row.get("agent", ""),
            "project": row.get("project", ""),
            "tags": tags_str,
            "topic": row_topic,
            "created": row.get("created", ""),
            "path": row.get("path", ""),
            "body": row.get("body", ""),
        })
    return results


def wait_for_notes(workspace: str = "", topic: str = "", agent: str = "", after: str = "",
                   timeout: int = 60, poll_interval: float = 1.0,
                   all_workspaces: bool = False) -> list:
    """Block execution until new notes matching filters arrive, or timeout.

    Returns a list of matching new notes. Returns empty list [] on timeout.
    """
    from pathlib import Path
    start_time = time.time()
    cutoff_ts = ""
    cutoff_mtime_ns = 0
    if after:
        found = store.find_record("context", after, [workspace] if workspace else None)
        if found:
            _, note_rec = found
            cutoff_ts = str(note_rec["fm"].get("created") or "")
            p = note_rec.get("path")
            if p and Path(p).exists():
                cutoff_mtime_ns = Path(p).stat().st_mtime_ns
        else:
            cutoff_ts = str(after).strip()
    if not cutoff_ts:
        cutoff_ts = now()

    while True:
        elapsed = time.time() - start_time
        if elapsed >= timeout:
            break

        notes = read_notes(workspace=workspace, topic=topic, agent=agent,
                           all_workspaces=all_workspaces)
        new_notes = []
        for n in notes:
            if after and n["id"] == after:
                continue
            if cutoff_mtime_ns and n.get("path") and Path(n["path"]).exists():
                if Path(n["path"]).stat().st_mtime_ns > cutoff_mtime_ns:
                    new_notes.append(n)
            elif str(n.get("created", "")) > cutoff_ts:
                new_notes.append(n)
        if new_notes:
            return sorted(new_notes, key=lambda n: str(n.get("created", "")))

        remaining = timeout - elapsed
        if remaining <= 0:
            break
        time.sleep(min(poll_interval, remaining))

    return []


def watch_notes(workspace: str = "", topic: str = "", agent: str = "",
                callback=None, poll_interval: float = 1.0,
                all_workspaces: bool = False) -> None:
    """Stream live notes as they arrive. Invokes callback(note) or prints to stdout."""
    initial = read_notes(workspace=workspace, topic=topic, agent=agent,
                         limit=50, all_workspaces=all_workspaces)
    seen = {n["id"] for n in initial}
    while True:
        notes = read_notes(workspace=workspace, topic=topic, agent=agent,
                           limit=20, all_workspaces=all_workspaces)
        new_notes = [n for n in notes if n["id"] not in seen]
        if new_notes:
            for note in sorted(new_notes, key=lambda n: str(n.get("created", ""))):
                seen.add(note["id"])
                if callback:
                    callback(note)
                else:
                    topic_str = f" ({note['topic']})" if note.get("topic") else ""
                    print(f"[{note['created'][11:19]}] [{note['agent']}]{topic_str}: {note['body']}")
        time.sleep(poll_interval)


def archive_old_notes(days: int = 0, cfg=None) -> list:
    """Move context notes past their TTL into `context/archive/`."""
    days = int(days or (cfg or {}).get("context", {}).get(
        "ttl_days", const.CONTEXT_TTL_DAYS))
    cutoff = stamp(days=-days)
    changed = []
    for note in store.all_records("context"):
        created = str(note["fm"].get("created") or "")
        if note["fm"].get("promoted_to") or not created or created >= cutoff:
            continue
        archive = ws_mod.subdir(note["workspace"], "context/archive")
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / note["path"].name
        note["path"].rename(target)
        index.reindex_doc("context", note["workspace"], target, note["fm"], note["body"])
        changed.append((note["id"], f"context note archived (>{days}d old)"))
    return changed


# ---- helpers -------------------------------------------------------------


def _insert_before_outcomes(body: str, line: str) -> str:
    if "## Outcomes" in body:
        return body.replace("## Outcomes", line + "\n\n## Outcomes", 1)
    return body.rstrip() + "\n" + line


def _replace_outcomes(body: str, block: str) -> str:
    """## Outcomes is always the final section, so replacing to EOF is exact."""
    if "## Outcomes" not in body:
        return body.rstrip() + "\n\n" + block + "\n"
    head = body.split("## Outcomes", 1)[0].rstrip()
    return head + "\n\n" + block.rstrip() + "\n"
