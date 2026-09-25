# -*- coding: utf-8 -*-
"""Agent Deliberation Layer (INV-008).

Enforces: "A task requiring coordination cannot enter execution until the required
deliberation protocol has completed with zero unresolved blocking objections."

Agents do not directly coordinate authority with each other. They exchange proposals,
questions, objections, and evidence through the Control Plane. The Control Plane acts
as the meeting room, moderator, presence monitor, and gatekeeper.
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import board, const, events, store, telemetry, workspaces as ws_mod
from .errors import BrainError, DeliberationGate, NotFound
from .paths import now


def deliberation_dir(workspace: str = "") -> Path:
    slug = workspace or ws_mod.default_workspace()
    directory = ws_mod.subdir(slug, const.DELIBERATION_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def room_dir(task_id: str, workspace: str = "") -> Path:
    slug = workspace or ws_mod.default_workspace()
    return deliberation_dir(slug) / task_id


def has_room(task_id: str, workspace: str = "") -> bool:
    slug = workspace or ws_mod.default_workspace()
    d = room_dir(task_id, slug)
    return d.is_dir() and (d / "context.json").exists()


def open_room(task_id: str, workspace: str = "", risk: str = "normal",
              mode: str = "normal", participants: Optional[List[str]] = None,
              domains: Optional[List[str]] = None, max_rounds: int = 3,
              actor: str = "control-plane") -> dict:
    """Initialize a Deliberation Room for a task."""
    slug = workspace or ws_mod.default_workspace()
    found = board.get_task(task_id, slug)
    if not found:
        raise NotFound(f"task {task_id} not found in workspace '{slug}'")
    slug, task = found

    rdir = room_dir(task_id, slug)
    rdir.mkdir(parents=True, exist_ok=True)

    task_title = str(task["fm"].get("title") or "")
    task_files = task["fm"].get("files") or []
    detected_domains = domains or telemetry._detect_domains(task_title, task_files)

    # Determine required participants if not explicitly provided
    if not participants:
        if mode == "council" or risk in ("high", "critical"):
            participants = ["codex", "claude", "opencode", "antigravity"]
        else:
            participants = ["codex", "claude", "opencode"]
    # Canonical seats only: "antigravity" is an alias, and every message records the
    # resolved "agy", so a room that asked for the alias could never reach its own quorum.
    participants = sorted({board.resolve_agent(p) or p for p in participants})

    context = {
        "task_id": task_id,
        "title": task_title,
        "workspace": slug,
        "project": str(task["fm"].get("project") or slug),
        "risk": risk,
        "mode": mode,
        "domains": detected_domains,
        "status": "OPEN",
        "current_round": 1,
        "max_rounds": max_rounds,
        "required_participants": sorted(set(participants)),
        "required_acknowledgements": 1 if len(participants) <= 2 else 2,
        "created_at": now(),
        "updated_at": now(),
    }

    (rdir / "context.json").write_text(json.dumps(context, indent=2), encoding="utf-8")
    if not (rdir / "messages.jsonl").exists():
        (rdir / "messages.jsonl").touch()
    if not (rdir / "proposals.json").exists():
        (rdir / "proposals.json").write_text("[]\n", encoding="utf-8")
    if not (rdir / "presence.json").exists():
        (rdir / "presence.json").write_text("{}\n", encoding="utf-8")

    # Update task frontmatter in board: mark coordination_required = True
    task["fm"]["coordination_required"] = True
    # If task is backlog or planning, update status to coordinating
    curr_status = str(task["fm"].get("status") or "")
    if curr_status in ("backlog", "planning"):
        task["fm"]["status"] = "coordinating"
    store.update_record("tasks", task, workspace=slug)

    events.emit("DELIBERATION_OPENED", stage="AUTHORIZE", actor=actor,
                workspace=slug, task_id=task_id,
                payload={"risk": risk, "mode": mode, "participants": participants,
                         "domains": detected_domains})

    return context


def get_room(task_id: str, workspace: str = "") -> dict:
    """Return full state of a Deliberation Room."""
    slug = workspace or ws_mod.default_workspace()
    rdir = room_dir(task_id, slug)
    if not (rdir / "context.json").exists():
        raise NotFound(f"no deliberation room found for task {task_id}")

    ctx = json.loads((rdir / "context.json").read_text(encoding="utf-8"))

    proposals = []
    if (rdir / "proposals.json").exists():
        try:
            proposals = json.loads((rdir / "proposals.json").read_text(encoding="utf-8"))
        except (ValueError, OSError):
            proposals = []

    presence = {}
    if (rdir / "presence.json").exists():
        try:
            presence = json.loads((rdir / "presence.json").read_text(encoding="utf-8"))
        except (ValueError, OSError):
            presence = {}

    messages = []
    if (rdir / "messages.jsonl").exists():
        with open(rdir / "messages.jsonl", "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        messages.append(json.loads(line))
                    except ValueError:
                        continue

    decision = None
    if (rdir / "decision.json").exists():
        try:
            decision = json.loads((rdir / "decision.json").read_text(encoding="utf-8"))
        except (ValueError, OSError):
            decision = None

    return {
        "context": ctx,
        "proposals": proposals,
        "presence": presence,
        "messages": messages,
        "decision": decision,
    }


def update_presence(task_id: str, agent: str, state: str = "ANALYZING",
                    focus: str = "", files: Optional[List[str]] = None,
                    workspace: str = "") -> dict:
    """Record live status/focus/files for an agent in the room."""
    slug = workspace or ws_mod.default_workspace()
    rdir = room_dir(task_id, slug)
    if not (rdir / "presence.json").exists():
        raise NotFound(f"deliberation room not found for task {task_id}")

    state = state.upper()
    if state not in const.DELIBERATION_PRESENCE_STATES:
        state = "ANALYZING"

    presence = {}
    try:
        presence = json.loads((rdir / "presence.json").read_text(encoding="utf-8"))
    except (ValueError, OSError):
        presence = {}

    stamp = now()
    presence[agent] = {
        "agent": agent,
        "state": state,
        "focus": focus or "",
        "files": files or [],
        "updated_at": stamp,
    }
    (rdir / "presence.json").write_text(json.dumps(presence, indent=2), encoding="utf-8")
    return presence[agent]


def post_message(task_id: str, sender: str, msg_type: str, body: str,
                 recipient: str = "", severity: str = "medium",
                 references: Optional[List[str]] = None,
                 workspace: str = "") -> dict:
    """Post a structured deliberation message to the room."""
    slug = workspace or ws_mod.default_workspace()
    rdir = room_dir(task_id, slug)
    if not (rdir / "context.json").exists():
        raise NotFound(f"deliberation room not found for task {task_id}")

    ctx = json.loads((rdir / "context.json").read_text(encoding="utf-8"))
    msg_type = (msg_type or "").upper()
    if msg_type not in const.DELIBERATION_MESSAGE_TYPES:
        raise BrainError(f"invalid message type {msg_type!r}; allowed: {const.DELIBERATION_MESSAGE_TYPES}")

    severity = (severity or "medium").lower()
    if severity not in const.DELIBERATION_SEVERITIES:
        severity = "medium"

    stamp = now()
    # Count existing messages for ID sequence
    count = 0
    with open(rdir / "messages.jsonl", "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1

    msg_id = f"msg_{stamp[:10].replace('-', '')}_{count + 1:04d}"
    record = {
        "message_id": msg_id,
        "task_id": task_id,
        "round": ctx.get("current_round", 1),
        "timestamp": stamp,
        "sender": sender,
        "recipient": recipient or "",
        "type": msg_type,
        "severity": severity,
        "body": body.strip(),
        "references": references or [],
    }

    with open(rdir / "messages.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")

    evt_type = "OBJECTION_RAISED" if msg_type == "OBJECTION" else "DELIBERATION_MESSAGE"
    events.emit(evt_type, stage="PROPOSE" if msg_type in ("PROPOSAL", "QUESTION", "OBJECTION") else "RECORD",
                actor=f"agent:{sender}", workspace=slug, task_id=task_id,
                payload={"message_id": msg_id, "type": msg_type, "severity": severity,
                         "recipient": recipient, "summary": body[:120]})

    return record


def submit_proposal(task_id: str, agent: str, plan: List[str],
                    files_expected: Optional[List[str]] = None,
                    risks: Optional[List[str]] = None,
                    questions: Optional[List[str]] = None,
                    workspace: str = "") -> dict:
    """Submit a pre-task technical plan proposal to the deliberation room."""
    slug = workspace or ws_mod.default_workspace()
    rdir = room_dir(task_id, slug)
    if not (rdir / "context.json").exists():
        raise NotFound(f"deliberation room not found for task {task_id}")

    ctx = json.loads((rdir / "context.json").read_text(encoding="utf-8"))

    proposals = []
    if (rdir / "proposals.json").exists():
        try:
            proposals = json.loads((rdir / "proposals.json").read_text(encoding="utf-8"))
        except (ValueError, OSError):
            proposals = []

    prop_id = f"prop_{len(proposals) + 1:02d}"
    prop_record = {
        "proposal_id": prop_id,
        "task_id": task_id,
        "round": ctx.get("current_round", 1),
        "agent": agent,
        "timestamp": now(),
        "plan": plan if isinstance(plan, list) else [plan],
        "files_expected": files_expected or [],
        "risks": risks or [],
        "questions": questions or [],
        "status": "PROPOSED",
    }
    proposals.append(prop_record)
    (rdir / "proposals.json").write_text(json.dumps(proposals, indent=2), encoding="utf-8")

    # Mirror as a structured PROPOSAL message
    body = "Plan:\n" + "\n".join(f"- {p}" for p in prop_record["plan"])
    if prop_record["risks"]:
        body += "\nRisks:\n" + "\n".join(f"- {r}" for r in prop_record["risks"])
    post_message(task_id, sender=agent, msg_type="PROPOSAL", body=body,
                 references=prop_record["files_expected"], workspace=slug)

    events.emit("PROPOSAL_SUBMITTED", stage="PROPOSE", actor=f"agent:{agent}",
                workspace=slug, task_id=task_id,
                payload={"proposal_id": prop_id, "files": prop_record["files_expected"]})

    return prop_record


def raise_objection(task_id: str, sender: str, body: str,
                    proposal_id: str = "", severity: str = "high",
                    references: Optional[List[str]] = None,
                    workspace: str = "") -> dict:
    """Raise a technical objection to a proposal or direction."""
    slug = workspace or ws_mod.default_workspace()
    rdir = room_dir(task_id, slug)
    if not (rdir / "context.json").exists():
        raise NotFound(f"deliberation room not found for task {task_id}")

    # Mark proposal as OBJECTED if specified
    if proposal_id and (rdir / "proposals.json").exists():
        try:
            proposals = json.loads((rdir / "proposals.json").read_text(encoding="utf-8"))
            for p in proposals:
                if p["proposal_id"] == proposal_id:
                    p["status"] = "OBJECTED"
            (rdir / "proposals.json").write_text(json.dumps(proposals, indent=2), encoding="utf-8")
        except (ValueError, OSError):
            pass

    full_body = f"[{proposal_id}] {body}" if proposal_id else body
    return post_message(task_id=task_id, sender=sender, msg_type="OBJECTION",
                        body=full_body, severity=severity, references=references,
                        workspace=slug)


def resolve_objection(task_id: str, resolver: str, message_id_or_ref: str,
                      resolution_notes: str, workspace: str = "") -> dict:
    """Acknowledge or provide resolution evidence for a prior objection."""
    slug = workspace or ws_mod.default_workspace()
    body = f"Resolved objection {message_id_or_ref}: {resolution_notes}"
    msg = post_message(task_id=task_id, sender=resolver, msg_type="ACKNOWLEDGEMENT",
                       body=body, severity="low", references=[message_id_or_ref],
                       workspace=slug)
    events.emit("OBJECTION_RESOLVED", stage="RECORD", actor=f"agent:{resolver}",
                workspace=slug, task_id=task_id,
                payload={"objection_ref": message_id_or_ref, "resolved_by": resolver})
    return msg


def adjudicate(task_id: str, workspace: str = "", actor: str = "control-plane",
               force: bool = False) -> dict:
    """Adjudicate deliberation room: verify consensus, zero blocking objections, and produce Decision Record.

    If consensus is reached and all objections are resolved, creates `decision.json`
    (status: AUTHORIZED), and advances task to READY.
    """
    slug = workspace or ws_mod.default_workspace()
    room = get_room(task_id, slug)
    ctx = room["context"]
    proposals = room["proposals"]
    messages = room["messages"]

    # 1. Proposal requirement: at least one proposal must exist
    if not proposals and not force:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": "no technical proposals were submitted during deliberation",
        }

    # 2. Check for unresolved blocking/high objections
    objections = [m for m in messages if m["type"] == "OBJECTION" and m["severity"] in ("high", "blocking")]
    resolutions = [m for m in messages if m["type"] in ("ACKNOWLEDGEMENT", "ANSWER", "EVIDENCE")]

    unresolved = []
    for obj in objections:
        # Check if an acknowledgement or answer references this objection
        obj_id = obj["message_id"]
        resolved = any(
            obj_id in m.get("references", []) or obj_id in m.get("body", "")
            for m in resolutions
        )
        if not resolved:
            unresolved.append(obj)

    if unresolved and not force:
        events.emit("DELIBERATION_BLOCKED", stage="AUTHORIZE", actor=actor,
                    workspace=slug, task_id=task_id,
                    payload={"unresolved_count": len(unresolved),
                             "blocking_objections": [u["body"][:80] for u in unresolved]})
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": f"{len(unresolved)} unresolved blocking objection(s) remain",
            "unresolved_objections": unresolved,
        }

    # 3. Check required participants
    active_senders = {m["sender"] for m in messages} | {p["agent"] for p in proposals}
    required = set(ctx.get("required_participants", []))
    missing = required - active_senders
    if missing and not force:
        return {
            "ok": False,
            "status": "BLOCKED",
            "reason": f"required participants did not contribute: {', '.join(sorted(missing))}",
        }

    # 4. Consensus reached: synthesize agreed plan and authorized files
    agreed_plan = []
    authorized_files = set()
    for p in proposals:
        if p.get("status") != "SUPERSEDED":
            agreed_plan.extend(p.get("plan", []))
            authorized_files.update(p.get("files_expected", []))

    stamp = now()
    decision_id = f"dec_{stamp[:10].replace('-', '')}_{task_id[-6:]}"
    decision = {
        "decision_id": decision_id,
        "task_id": task_id,
        "status": "AUTHORIZED",
        "timestamp": stamp,
        "round": ctx.get("current_round", 1),
        "participants": sorted(active_senders),
        "agreed_plan": agreed_plan,
        "authorized_files": sorted(authorized_files),
        "resolved_objections": [o["message_id"] for o in objections if o not in unresolved],
        "unresolved_objections": [],
        "adjudicator": actor,
    }

    rdir = room_dir(task_id, slug)
    (rdir / "decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")

    ctx["status"] = "AUTHORIZED"
    ctx["updated_at"] = stamp
    (rdir / "context.json").write_text(json.dumps(ctx, indent=2), encoding="utf-8")

    events.emit("DELIBERATION_RESOLVED", stage="AUTHORIZE", actor=actor,
                workspace=slug, task_id=task_id,
                payload={"decision_id": decision_id, "files": sorted(authorized_files),
                         "participants": sorted(active_senders)})

    # Advance task to ready if currently coordinating
    found = board.get_task(task_id, slug)
    if found:
        task_slug, task = found
        if task["fm"].get("status") in ("coordinating", "planning", "backlog"):
            board.move(task_id, "ready", workspace=task_slug, agent=actor,
                       notes="deliberation authorized; moved to ready")

    return {
        "ok": True,
        "status": "AUTHORIZED",
        "decision": decision,
    }


def verify_deliberation_record(task_id: str, workspace: str = "") -> Tuple[bool, str]:
    """Verify that a task requiring coordination holds an AUTHORIZED Deliberation Record (INV-008)."""
    slug = workspace or ws_mod.default_workspace()
    found = board.get_task(task_id, slug)
    if not found:
        return False, f"task {task_id} not found"
    slug, task = found

    needs_deliberation = bool(task["fm"].get("coordination_required")) or has_room(task_id, slug)
    if not needs_deliberation:
        return True, "coordination not required"

    rdir = room_dir(task_id, slug)
    decision_file = rdir / "decision.json"
    if not decision_file.exists():
        return False, f"task {task_id} requires coordination but no Deliberation Record exists"

    try:
        dec = json.loads(decision_file.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return False, f"invalid Deliberation Record: {exc}"

    if dec.get("status") != "AUTHORIZED":
        return False, f"Deliberation Record status is {dec.get('status')!r}, not 'AUTHORIZED'"

    if not dec.get("participants"):
        return False, "Deliberation Record missing participants"
    if not dec.get("agreed_plan"):
        return False, "Deliberation Record missing agreed plan"

    return True, "valid Deliberation Record"
