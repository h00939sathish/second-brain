# -*- coding: utf-8 -*-
"""Upstream specs and the Kanban board, plus the pipeline router.

The board is where the protocol is *enforced* rather than described:

* `move(..., "done")` refuses without review evidence (a finished session for that
  task that recorded a handoff or a test result) — this is the ReviewGate.
* `move(..., "running")` refuses without an assigned agent, because an unowned
  running card is indistinguishable from a stalled one.
* A card's `agent:` is the agent that *did* the work, never the agent that last ran
  `move` — see `may_speak_for`, which is the same question a lease asks.
"""

import os

from . import const, events, index, store, workspaces as ws_mod
from .errors import (BrainError, CycleDetectedError, DeliberationGate, DependencyBlockedError,
                    NotFound, ReviewGate, UnverifiedEvidenceError)
from .paths import now

REVIEWER_ROLES = {"reviewer"}
DONE = "done"
RUNNING = "running"
REVIEW = "review"
BLOCKED = "blocked"
READY = "ready"

SEAT_ENV = "BRAIN_AGENT"
OPERATOR = "operator"
OWNERSHIP_EVENT = "OWNERSHIP_CONFLICT_REFUSED"


def _as_phases(phases) -> list:
    if not phases:
        return []
    if isinstance(phases, str):
        return [p.strip() for p in phases.split(",") if p.strip()]
    return [str(p).strip() for p in phases if str(p).strip()]


# ---- specs ---------------------------------------------------------------


def create_spec(title: str, spec: str, workspace: str = "", project: str = "",
                phases="") -> dict:
    title = (title or "").strip()
    if not title:
        raise BrainError("a spec needs a title")
    slug = workspace or ws_mod.default_workspace()
    spec_id = store.new_id("specs")
    stamp = now()
    phase_list = _as_phases(phases)
    fm = {
        "id": spec_id,
        "title": title,
        "project": project or "",
        "workspace": slug,
        "phases": phase_list,
        "created": stamp,
        "updated": stamp,
    }
    body = [f"# Spec: {title}", "", "## Overview", (spec or "").strip(), ""]
    if phase_list:
        body += ["## Execution Phases"]
        body += [f"- [ ] **Phase {i}:** {p}" for i, p in enumerate(phase_list, 1)]
        body += [""]
    path = store.write_record("specs", fm, "\n".join(body), workspace=slug)
    return {"id": spec_id, "workspace": slug, "path": str(path)}


def get_spec(spec_id: str, workspace: str = ""):
    return store.find_record("specs", spec_id, [workspace] if workspace else None)


def list_specs(workspace: str = "", project: str = "", all_workspaces: bool = False) -> list:
    slugs = ws_mod.all_slugs() if all_workspaces else ws_mod.read_scope(workspace or ws_mod.default_workspace())
    specs = store.all_records("specs", slugs)
    if project:
        specs = [s for s in specs if str(s["fm"].get("project")) == project]
    return sorted(specs, key=lambda s: str(s["fm"].get("created") or ""), reverse=True)


def update_phases(spec_id: str, done_phase: str, workspace: str = "") -> dict:
    """Tick a phase checkbox off in the spec body and stamp `updated`."""
    found = get_spec(spec_id, workspace)
    if not found:
        raise NotFound(f"spec {spec_id} not found")
    slug, spec = found
    marker = f"**Phase {done_phase}:**"
    if marker in spec["body"]:
        spec["body"] = spec["body"].replace(f"- [ ] {marker}", f"- [x] {marker}")
    spec["fm"]["updated"] = now()
    store.update_record("specs", spec, workspace=slug)
    return {"id": spec_id, "workspace": slug}


def _as_list(val) -> list:
    if not val:
        return []
    if isinstance(val, (list, tuple)):
        return [str(v).strip() for v in val if str(v).strip()]
    return [str(v).strip() for v in str(val).split(",") if str(v).strip()]


def check_cycle(task_id: str, depends_on: list, workspace: str = "") -> None:
    """Ensure adding depends_on edges does not introduce a directed cycle into the task graph."""
    visited = set()
    queue = list(depends_on)
    while queue:
        curr = queue.pop()
        if curr == task_id:
            raise CycleDetectedError(f"cycle detected: task {task_id} depends on {curr} which leads back to {task_id}")
        if curr in visited:
            continue
        visited.add(curr)
        found = get_task(curr, workspace)
        if found:
            curr_deps = _as_list(found[1]["fm"].get("depends_on") or [])
            queue.extend(curr_deps)


def unmet_dependencies(task_id: str, workspace: str = "") -> list:
    """Return list of prerequisite task IDs that have not reached DONE."""
    found = get_task(task_id, workspace)
    if not found:
        return []
    slug, task = found
    deps = _as_list(task["fm"].get("depends_on") or [])
    unmet = []
    for dep_id in deps:
        dep_found = get_task(dep_id, workspace or slug)
        if not dep_found or str(dep_found[1]["fm"].get("status") or "") != DONE:
            unmet.append(dep_id)
    return unmet


def create_task(title: str, workspace: str = "", project: str = "", spec_id: str = "",
                agent: str = "", phase: str = "", files="", status: str = "",
                depends_on="", task_id: str = "", coordination_required: bool = False) -> dict:
    title = (title or "").strip()
    if not title:
        raise BrainError("a task needs a title")
    slug = workspace or ws_mod.default_workspace()
    if spec_id and not store.find_record("specs", spec_id, [slug]):
        raise NotFound(f"spec {spec_id} not found in workspace '{slug}'")

    dep_list = _as_list(depends_on)
    task_id = task_id or store.new_id("tasks")
    if dep_list:
        check_cycle(task_id, dep_list, slug)

    # Initial status resolution:
    # If not explicitly provided:
    #   if has dependencies and any not done -> BLOCKED
    #   if coordination_required -> COORDINATING
    #   if no dependencies -> BACKLOG
    if not status:
        if dep_list:
            unmet = [d for d in dep_list if not (get_task(d, slug) and get_task(d, slug)[1]["fm"].get("status") == DONE)]
            status = BLOCKED if unmet else ("coordinating" if coordination_required else READY)
        elif coordination_required:
            status = "coordinating"
        else:
            status = "backlog"
    elif status not in const.TASK_STATUSES:
        raise BrainError(f"invalid task status {status!r}")
    elif status in ("backlog", READY, RUNNING) and dep_list:
        unmet = [d for d in dep_list if not (get_task(d, slug) and get_task(d, slug)[1]["fm"].get("status") == DONE)]
        if unmet and status in (READY, RUNNING):
            raise DependencyBlockedError(task_id, unmet)
        elif unmet and status == "backlog":
            status = BLOCKED

    stamp = now()
    file_list = [f.strip() for f in (files if isinstance(files, (list, tuple))
                                     else str(files or "").split(",")) if str(f).strip()]
    fm = {
        "id": task_id,
        "title": title,
        "project": project or slug,
        "workspace": slug,
        "spec_id": spec_id or "",
        "phase": phase or "",
        "agent": resolve_agent(agent) if agent else "",
        "status": status,
        "files": file_list,
        "depends_on": dep_list,
        "coordination_required": bool(coordination_required),
        "created": stamp,
        "updated": stamp,
    }
    body = [f"# Task: {title}", ""]
    if spec_id:
        body += [f"Linked Spec: [[{spec_id}]]", ""]
    if dep_list:
        body += [f"Depends on: {', '.join(dep_list)}", ""]
    body += ["## Activity Log", f"- [{stamp[11:16]}] Created in [{status}]"]
    path = store.write_record("tasks", fm, "\n".join(body), workspace=slug)
    events.emit("TASK_CREATED", stage="AUTHORIZE", workspace=slug, task_id=task_id,
                payload={"title": title, "status": status, "agent": agent, "files": file_list,
                         "depends_on": dep_list})
    return {"id": task_id, "workspace": slug, "path": str(path), "status": status,
            "depends_on": dep_list}


def get_task(task_id: str, workspace: str = ""):
    return store.find_record("tasks", task_id, [workspace] if workspace else None)


def list_tasks(workspace: str = "", project: str = "", status: str = "", agent: str = "",
               all_workspaces: bool = False) -> list:
    slugs = ws_mod.all_slugs() if all_workspaces else ws_mod.read_scope(workspace or ws_mod.default_workspace())
    tasks = store.all_records("tasks", slugs)
    if project:
        tasks = [t for t in tasks if str(t["fm"].get("project")) == project]
    if status:
        tasks = [t for t in tasks if str(t["fm"].get("status")) == status]
    if agent:
        wanted = resolve_agent(agent)
        tasks = [t for t in tasks if resolve_agent(t["fm"].get("agent")) == wanted]
    return tasks


def finished_sessions(task_id: str, slugs=None) -> list:
    """Sessions linked to this card that have ended, oldest first.

    Ordered on the clock rather than the path: the newest one is the session that
    justifies a transition, and record ids carry a random suffix, so file order is not
    time order.
    """
    rows = [s for s in store.all_records("sessions", slugs)
            if str(s["fm"].get("task_id") or "") == task_id
            and s["fm"].get("status") in ("ended", "stale")]
    return sorted(rows, key=lambda s: str(s["fm"].get("ended") or s["fm"].get("updated")
                                           or s["fm"].get("started") or ""))


def review_evidence(task_id: str, workspace: str = "") -> tuple:
    """(ok, detail) — is there a finished session proving this task was reviewed?"""
    slugs = [workspace] if workspace else None
    ended = finished_sessions(task_id, slugs)
    if not ended:
        return False, "no finished session is linked to this task (task_id on a session)"
    for session in ended:
        handoff = str(session["fm"].get("target_agent") or "")
        tests = str(session["fm"].get("test_status") or "")
        role = const.AGENT_ROLES.get(resolve_agent(handoff), "")
        if role in REVIEWER_ROLES and tests:
            return True, f"reviewed by {handoff} ({tests}) via {session['id']}"
        if tests:
            return True, f"tests recorded on {session['id']}: {tests}"
    return False, (
        f"{len(ended)} finished session(s) linked, but none recorded a review handoff or a "
        "test result"
    )


# ---- ownership: one rule, asked the same way for cards and for leases ------

def seat() -> str:
    """Who is asking, as this process declared it ($BRAIN_AGENT). Empty when unseated."""
    return resolve_agent(os.environ.get(SEAT_ENV, ""))


def may_speak_for(agent, handoffs=()) -> tuple:
    """(ok, why) — may the calling seat act as, or on the work of, `agent`?

    THE ownership rule, and it lives in one place because cards and leases used to decide
    it separately, each trusting the caller's own word: `move` wrote whatever `--agent` was
    typed into the card, so B closing A's card became the recorded author of A's work, and
    a session's `agent` was self-reported at `start`, so `end` "verified" a handoff against
    the very claim it was supposed to check.

    A seat may speak for itself, for an unowned record, and for work a finished session
    handed to it. The operator seat is exempt: it is the escalation path the protocol
    documents for a human. No seat at all is answered with True — a card still gets its
    author from the session that produced the work, not from the caller.
    """
    wanted = resolve_agent(agent)
    asker = seat()
    if not asker or not wanted or asker == wanted:
        return True, ""
    if asker == OPERATOR:
        return True, f"operator seat acting for {wanted}"
    if asker in {resolve_agent(h) for h in handoffs if h}:
        return True, f"{wanted} handed this work to {asker}"
    return False, (f"{asker} is not {wanted}, and no finished session handed this work to "
                   f"{asker}; identity is a seat, not a flag to pick")


def refuse_ownership(workspace: str, why: str, task_id: str = "", **payload) -> None:
    """Audit an ownership refusal, then stop. A refusal nobody can find later is a bug."""
    events.emit(OWNERSHIP_EVENT, stage="AUTHORIZE", workspace=workspace, task_id=task_id,
                actor=f"agent:{seat() or '?'}", payload={"reason": why, **payload})
    raise BrainError(f"ownership refused{' on task ' + task_id if task_id else ''}: {why}")


def normalise_path(path) -> str:
    return str(path or "").replace("\\", "/").lstrip("./").strip("/")


def lease_covers(leased, path) -> bool:
    """Does the lease on `leased` cover `path`?

    The rule `evidence.check_working_tree` uses — equality, or a directory prefix with the
    separator in it. `endswith` let a lease on `x/auth.py` answer for `src/auth.py`, and a
    bare prefix let `src/a` cover `src/anything`, so ownership was decided by substring.
    """
    needle, target = normalise_path(leased), normalise_path(path)
    return bool(needle) and (target == needle or target.startswith(needle + "/"))


def lease_conflicts(requested, locks, exclude_session: str = "") -> list:
    """Which of `requested` fall inside somebody else's live lease.

    `locks` is `store.build_locks` output, so an expired or abandoned lease stops counting
    here exactly where it does everywhere else.
    """
    hits = []
    for want in _as_list(requested):
        for leased, info in (locks or {}).items():
            if exclude_session and info.get("session_id") == exclude_session:
                continue
            if lease_covers(leased, want):
                hits.append((want, info))
                break
    return hits


def live_leases_on(slug: str, task_id: str, files=(), asker: str = "") -> list:
    """Live leases over this card's work that a *different* seat is holding.

    "Another seat still has a live lease on" is the whole question: relabelling a card
    nobody is inside is a chore, and taking one over while somebody is writing it is a
    theft.
    """
    locks = store.build_locks([slug])
    card_files = _as_list(files)
    offenders = []
    for session in store.active_sessions([slug]):
        held = [path for path, info in locks.items() if info.get("session_id") == session["id"]]
        if not held:
            continue
        holder = resolve_agent(session["fm"].get("agent"))
        if not holder or holder in (asker, OPERATOR):
            continue
        hits = [f for f in card_files
                if any(lease_covers(p, f) or lease_covers(f, p) for p in held)]
        if str(session["fm"].get("task_id") or "") == task_id or hits:
            offenders.append({"holder": holder, "session": session["id"],
                              "paths": sorted(set(hits)) or sorted(held)})
    return offenders


def move(task_id: str, status: str, workspace: str = "", agent: str = "", notes: str = "",
         force: bool = False, tests: str = "", closure_reason: str = "",
         closure_target: str = "") -> dict:
    status = (status or "").strip().lower()
    if status not in const.TASK_STATUSES:
        raise BrainError(f"invalid status {status!r}; expected one of {', '.join(const.TASK_STATUSES)}")
    found = get_task(task_id, workspace)
    if not found:
        raise NotFound(f"task {task_id} not found")
    slug, task = found
    current = str(task["fm"].get("status") or "backlog")
    if current == status:
        return {"id": task_id, "workspace": slug, "status": status, "changed": False,
                "detail": f"already in [{status}]"}

    asker = seat()
    if force:
        # `--force` opens the evidence and ownership gates, so it cannot be something a
        # process grants itself by typing a flag. Before trust is installed the only
        # authority is BRAIN_BYPASS=1, which is at least audited as self-granted.
        from . import grants
        authorised, why = grants.bypass(seat=asker, action=f"force-move:{status}",
                                        workspace=slug)
        if not authorised:
            raise BrainError(
                f"--force is a human decision, not a flag an agent may set: {why}")
    claimed = resolve_agent(agent)
    card_agent = resolve_agent(task["fm"].get("agent"))
    finished = finished_sessions(task_id, [slug])
    handoffs = [str(s["fm"].get("target_agent") or "") for s in finished]
    worker = resolve_agent(finished[-1]["fm"].get("agent")) if finished else ""
    # Who did the work is a fact about the sessions, not a field the caller gets to type.
    # A review/done move therefore credits the agent of the finished session that
    # justifies it; the caller's `--agent` only ever assigns work nobody has done yet.
    if status in (REVIEW, DONE):
        credited = worker or card_agent or claimed
    else:
        credited = claimed or card_agent

    if not force:
        # card_agent joins the loop once the work has been declared finished, because a
        # sideways move was the one hole left: a seat may always speak for itself, so
        # `--agent gemini` moved opencode's reviewed card and rewrote its authorship
        # without claiming to be anyone else. Before that point the live lease is what
        # protects a card, and an expired lease must not freeze the board forever.
        custodian = card_agent if current in (REVIEW, DONE) else ""
        for speaks_for in [name for name in (claimed, credited, custodian) if name]:
            granted, why = may_speak_for(speaks_for, handoffs)
            if not granted:
                refuse_ownership(slug, why, task_id=task_id, card_agent=card_agent,
                                 worker=worker, claimed=claimed, credited=credited,
                                 handoffs=sorted({h for h in handoffs if h}))
        if credited and credited != card_agent:
            held = live_leases_on(slug, task_id, task["fm"].get("files"), asker)
            if held:
                refuse_ownership(
                    slug,
                    f"{credited} would take this card from the seat still working it "
                    f"({', '.join(h['holder'] for h in held)})",
                    task_id=task_id, card_agent=card_agent, credited=credited, leased_by=held)

    if credited:
        task["fm"]["agent"] = credited
    if status == RUNNING and not task["fm"].get("agent"):
        raise BrainError(
            f"task {task_id} cannot enter [running] without an assigned agent "
            "(pass --agent or set it on the card)"
        )

    if status in (RUNNING, READY) and not force:
        unmet = unmet_dependencies(task_id, workspace=slug)
        if unmet:
            raise DependencyBlockedError(task_id, unmet)
        from . import deliberation
        ok, reason = deliberation.verify_deliberation_record(task_id, workspace=slug)
        if not ok:
            raise DeliberationGate(task_id, reason)

    detail = ""
    if status == DONE and not force:
        ok, why = review_evidence(task_id, workspace=slug)
        if not ok:
            raise ReviewGate(
                f"task {task_id} cannot reach [done]: {why}. "
                "Reach [review] from a builder session with a handoff/tests, or pass --force."
            )

        # Machine-verified evidence check (INV-002)
        from . import evidence
        latest_session = finished[-1] if finished else None
        leased = []
        claimed_tests = tests or ""
        target_agent = ""
        if latest_session:
            leased = latest_session["fm"].get("files") or []
            if not claimed_tests:
                claimed_tests = str(latest_session["fm"].get("test_status") or "")
            target_agent = str(latest_session["fm"].get("target_agent") or "")

        v_ok, v_why = evidence.verify_task(
            task_id, workspace=slug,
            test_status_claimed=claimed_tests,
            leased_files=leased,
            target_agent=target_agent,
        )
        if not v_ok:
            raise UnverifiedEvidenceError(
                f"task {task_id} cannot reach [done]: {v_why}. "
                "Execute tests with `brain test` or attach a verified execution receipt, or pass --force."
            )

        # Hot-potato closure contract
        c_reason = closure_reason or str(task["fm"].get("closure_reason") or "")
        c_target = closure_target or str(task["fm"].get("closure_target") or "") or target_agent
        if not c_reason:
            if target_agent:
                c_reason = "handed_off"
                c_target = target_agent
            elif claimed_tests or tests:
                c_reason = "completed"
            else:
                valid_reasons = ", ".join(const.CLOSURE_REASONS)
                raise BrainError(
                    f"task {task_id} cannot enter [done] without a closure_reason. "
                    f"Must be one of: {valid_reasons}. Pass --closure <reason>."
                )

        if c_reason not in const.CLOSURE_REASONS:
            valid_reasons = ", ".join(const.CLOSURE_REASONS)
            raise BrainError(
                f"invalid closure_reason '{c_reason}'; expected one of: {valid_reasons}"
            )

        if c_reason in ("handed_off", "escalation") and not c_target:
            raise BrainError(
                f"closure_reason '{c_reason}' requires a closure_target (pass --closure-target or assign target agent)"
            )

        task["fm"]["closure_reason"] = c_reason
        if c_target:
            task["fm"]["closure_target"] = c_target

        detail = f" ({why}; {v_why}; closure: {c_reason})"

    if closure_reason:
        task["fm"]["closure_reason"] = closure_reason
    if closure_target:
        task["fm"]["closure_target"] = closure_target

    stamp = now()
    task["fm"]["status"] = status
    task["fm"]["updated"] = stamp
    if tests:
        task["fm"]["test_status"] = tests
    who = f" by {asker or claimed}" if (asker or claimed) else ""
    if claimed and credited and claimed != credited:
        who += f" (author recorded as {credited}, not {claimed})"
    log = f"- [{stamp[11:16]}] Moved: {current} -> {status}{who}"
    if notes:
        log += f" — {notes}"
    if detail:
        log += detail
    task["body"] = task["body"].rstrip() + "\n" + log
    store.update_record("tasks", task, workspace=slug)
    index.reindex_doc("tasks", slug, task["path"], task["fm"], task["body"])

    # Cascade unblock dependent tasks in the same workspace when reaching DONE
    if status == DONE:
        for candidate in store.all_records("tasks", [slug]):
            cand_deps = _as_list(candidate["fm"].get("depends_on") or [])
            if task_id in cand_deps and candidate["fm"].get("status") == BLOCKED:
                cand_unmet = [d for d in cand_deps if d != task_id and not (get_task(d, slug) and get_task(d, slug)[1]["fm"].get("status") == DONE)]
                if not cand_unmet:
                    candidate["fm"]["status"] = READY
                    candidate["fm"]["updated"] = stamp
                    unblock_log = f"- [{stamp[11:16]}] Unblocked: all dependencies satisfied (prerequisite {task_id} completed)"
                    candidate["body"] = candidate["body"].rstrip() + "\n" + unblock_log
                    store.update_record("tasks", candidate, workspace=slug)
                    index.reindex_doc("tasks", slug, candidate["path"], candidate["fm"], candidate["body"])
                    events.emit("TASK_UNBLOCKED", stage="AUTHORIZE", workspace=slug, task_id=candidate["id"],
                                payload={"prerequisite": task_id})

    events.emit("TASK_MOVED", stage="AUTHORIZE", workspace=slug, task_id=task_id,
                payload={"from": current, "to": status, "agent": credited, "notes": notes,
                         "asked_by": asker or "unseated", "claimed": claimed})
    if status == DONE:
        events.emit("TASK_COMPLETED", stage="AUTHORIZE", workspace=slug, task_id=task_id,
                    payload={"detail": detail, "tests": tests})

    return {"id": task_id, "workspace": slug, "status": status, "from": current,
            "changed": True, "detail": detail, "agent": credited,
            "path": str(task["path"])}


def board(workspace: str = "", all_workspaces: bool = False) -> dict:
    tasks = list_tasks(workspace=workspace, all_workspaces=all_workspaces)
    columns = {status: [] for status in const.TASK_STATUSES}
    for task in tasks:
        columns.setdefault(str(task["fm"].get("status") or "backlog"), []).append(task)
    return {
        "columns": columns,
        "counts": {status: len(items) for status, items in columns.items()},
        "total": len(tasks),
    }


def actionable(workspace: str = "", project: str = "") -> dict:
    """The next pipeline step, matching the documented review -> build -> plan order."""
    tasks = list_tasks(workspace=workspace, project=project)
    for status, agent in ((REVIEW, "agy"), (RUNNING, ""), (READY, "opencode"),
                          ("planning", "codex"), ("backlog", "codex")):
        candidates = [t for t in tasks if str(t["fm"].get("status")) == status]
        for task in candidates:
            if unmet_dependencies(task["id"], workspace=task["workspace"]):
                continue
            return {
                "task_id": task["id"],
                "workspace": task["workspace"],
                "status": status,
                "agent": agent or resolve_agent(task["fm"].get("agent")) or "opencode",
                "title": str(task["fm"].get("title") or ""),
                "from_backlog": status in ("backlog", READY),
            }
    return {}


# ---- agents and routing --------------------------------------------------


def resolve_agent(name) -> str:
    """Map aliases (`antigravity`, `claude-code`) onto one canonical slug."""
    raw = str(name or "").strip().lower()
    if not raw:
        return ""
    return const.AGENT_ALIASES.get(raw, raw)


def role_of(name) -> str:
    return const.AGENT_ROLES.get(resolve_agent(name), "builder")


def agent_meta(name) -> dict:
    canonical = resolve_agent(name)
    meta = dict(const.AGENT_META.get(canonical, const.DEFAULT_AGENT_META))
    if canonical not in const.AGENT_META and canonical:
        meta["name"] = str(name)
    return meta


def complexity(prompt: str, cfg=None) -> tuple:
    """(is_complex, score, signals). Deliberately boring and explainable.

    The previous heuristic scored `any(sep in prompt for sep in (",", ";", ...))`,
    so almost every prompt earned a pipeline. Each signal below is named in the
    output, which makes `brain route --explain` auditable and testable.
    """
    text = str(prompt or "")
    lowered = text.lower()
    threshold = const.ROUTING_THRESHOLD
    keywords = const.COMPLEX_KEYWORDS
    if cfg:
        pipeline = cfg.get("pipeline", {})
        threshold = int(pipeline.get("complexity_threshold", threshold))
        keywords = tuple(pipeline.get("complex_keywords", keywords))

    signals = []
    matched = sorted({kw for kw in keywords if kw in lowered})
    if matched:
        signals.append(f"keywords({len(matched)}): {', '.join(matched[:6])}")
    words = len(text.split())
    if words > 60:
        signals.append(f"long prompt ({words} words)")
    if text.count("\n") >= 3:
        signals.append("multi-line brief")
    if any(marker in lowered for marker in ("migrate", "breaking", "all agents", "protocol")):
        signals.append("cross-cutting change")

    score = len(matched) + (2 if words > 60 else 0)
    return score >= threshold, score, signals


def route(agent: str, prompt: str, workspace: str = "", project: str = "", cfg=None) -> dict:
    canonical = resolve_agent(agent) or "unknown"
    role = role_of(canonical)
    slug = workspace or ws_mod.default_workspace()
    is_complex, score, signals = complexity(prompt, cfg)

    from . import telemetry
    recommendations = telemetry.rank_agents(prompt=prompt, workspace=slug)

    if not is_complex:
        return {"action": "direct", "agent": canonical, "role": role, "score": score,
                "signals": signals, "recommendations": recommendations,
                "brief": "Lightweight request: execute here, then record one claim if you "
                         "learned something durable."}

    lines = [
        f"Complex request (score {score}) -> full pipeline.",
        "",
        f"1. PLAN — codex drafts invariants and creates the spec + cards:",
        f"     brain spec-create --title '...' --project '{project or slug}' --phases 'a,b,c'",
        f"     brain task-create --title '...' --spec <spec-id> --agent opencode",
        "2. BUILD — opencode/claude claim the card, lease files, implement, run tests:",
        f"     brain start --agent opencode --task-id <task-id> --files a.py,b.py",
        "     brain end <session-id> --target-agent agy --test-status 'pytest: N passed'",
        "3. REVIEW — agy audits the diff against the spec, records tests, closes the card:",
        "     brain move <task-id> --status done",
        "",
        "Empirical Worker Recommendations (observed repository pass-rates):",
    ]
    for r in recommendations[:3]:
        pct = f"{int(r['first_pass_rate'] * 100)}%" if r['has_data'] else "prior"
        lines.append(f"  • {r['agent']:<12} [score: {r['score']:.2f}, pass-rate: {pct}] — {r['reason']}")

    lines += [
        "",
        "Invariant: only builders edit code; planners and reviewers stay out of bulk edits.",
    ]
    return {"action": "pipeline", "agent": canonical, "role": role, "score": score,
            "signals": signals, "workspace": slug, "recommendations": recommendations,
            "brief": "\n".join(lines)}


def next_action(agent: str, workspace: str = "", project: str = "") -> dict:
    canonical = resolve_agent(agent) or "unknown"
    role = role_of(canonical)
    step = actionable(workspace=workspace, project=project)
    if not step:
        return {"agent": canonical, "role": role, "action": "idle",
                "brief": "Board is clear. Nothing to dispatch."}
    verb = {
        "planner": "Draft invariants and split this into cards.",
        "builder": "Claim the card, lease files, implement, run tests, hand off to agy.",
        "reviewer": "Audit the diff against the spec, run the suite, close the card.",
        "orchestrator": "Route this card to the right owner.",
    }.get(role, "Claim the card and proceed.")
    return {
        "agent": canonical, "role": role, "action": "work",
        "task_id": step["task_id"], "workspace": step["workspace"],
        "status": step["status"], "title": step["title"],
        "brief": f"[{step['status']}] {step['task_id']} — {step['title']}\n{verb}",
    }
