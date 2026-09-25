# -*- coding: utf-8 -*-
"""Directed inter-agent messaging with inbox/outbox.

Every message is a markdown file with YAML frontmatter, stored in the workspace
under ``messages/inbox-<agent>/`` and ``messages/outbox-<agent>/``. This gives
agents a durable, per-agent mailbox that survives session restarts.

Unlike ``brain post`` (a broadcast scratchpad), directed messages have an explicit
sender, recipient, and acknowledgement state.

Who a message comes *from* is not the caller's to decide. Every agent on this host runs
as the same unix user, so a name typed into ``--agent`` proves nothing: the sender is
the seat this process was started as (``$BRAIN_AGENT``), the route has to exist in the
workspace topology, and the record is signed — so a hand-edited inbox file comes back
labelled forged instead of reading like a colleague. Once the operator installs a trust
root an agent process cannot sign at all, which is what makes "unsigned" on a message
an admission rather than a label indistinguishable from a seal.
"""

import hashlib
import os
from pathlib import Path

from . import attest, board, events, topology, workspaces as ws_mod
from .errors import BrainError, NotFound, TopologyError
from .frontmatter import dumps as fm_dump, parse as fm_parse
from .paths import atomic_write, now, read_text


MESSAGES_DIR = "messages"

# What the attestation covers. `read` is bookkeeping the recipient flips, so it is
# deliberately outside the signed set; everything naming a party or the payload is not.
SIGNED_FIELDS = ("id", "from", "to", "kind", "task_id", "created", "body_sha256")


def _inbox_dir(agent: str, workspace: str = "") -> Path:
    slug = workspace or ws_mod.default_workspace()
    ws_root = ws_mod.workspace_dir(slug)
    d = ws_root / MESSAGES_DIR / f"inbox-{agent}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _outbox_dir(agent: str, workspace: str = "") -> Path:
    slug = workspace or ws_mod.default_workspace()
    ws_root = ws_mod.workspace_dir(slug)
    d = ws_root / MESSAGES_DIR / f"outbox-{agent}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---- identity ------------------------------------------------------------


def _caller() -> str:
    """The seat this process is running as. Not overridable by an argument."""
    return board.resolve_agent(os.environ.get("BRAIN_AGENT", "").strip())


def _refuse(kind: str, slug: str, actor: str, task_id: str, why: str,
            payload: dict = None, error: type = BrainError) -> None:
    """The event stream sees a refusal before the exception does, so an agent cannot
    make one disappear by retrying with different arguments."""
    events.emit(kind, stage="AUTHORIZE", workspace=slug, actor=actor, task_id=task_id,
                payload={"reason": why, **(payload or {})})
    raise error(why)


def _authenticate(claimed: str, slug: str, target: str, task_id: str = "") -> str:
    """Bind the claimed sender to the caller's own seat, or refuse.

    Fails closed with no `$BRAIN_AGENT` rather than falling back to the unix user name:
    all the agents here share one uid, so the user identifies the machine and lets any
    of them post as any other — which is the hole this closes.
    """
    caller, claimed = _caller(), board.resolve_agent(claimed)
    if not caller:
        _refuse("MESSAGE_FORGERY_REFUSED", slug, "agent:unknown", task_id,
                f"refusing to act as {claimed!r} with no $BRAIN_AGENT in this process: "
                "there is no seat to attribute this to, and the unix user is deliberately "
                "not a fallback because every agent on this host shares it. Re-run with "
                "BRAIN_AGENT=<your seat> set — failing closed, not guessing.",
                {"claimed_sender": claimed, "to": target, "mode": "fail-closed"})
    if claimed and claimed != caller:
        _refuse("MESSAGE_FORGERY_REFUSED", slug, f"agent:{caller}", task_id,
                f"{caller} cannot act as {claimed!r}: the sender of a directed message "
                "is the seat this process runs as ($BRAIN_AGENT), not the name passed to "
                "--agent. A grant buys a route past topology, never someone else's name.",
                {"claimed_sender": claimed, "to": target})
    return claimed or caller


def _authorize_route(sender: str, recipient: str, slug: str, task_id: str = "") -> str:
    """Ask the declared graph. `can_route` is fail-closed inside a declared topology and
    already logs an undeclared one as ungoverned, so this only reports its answer."""
    allowed, reason = topology.can_route(sender, recipient, workspace=slug)
    if not allowed:
        _refuse("MESSAGE_ROUTE_DENIED", slug, f"agent:{sender}", task_id,
                f"message to {recipient} refused by topology: {reason}",
                {"to": recipient}, error=TopologyError)
    return reason


# ---- attestation ---------------------------------------------------------


def _digest(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def _signed(fm: dict) -> dict:
    """The projection the seal covers — the same fields at write time and at read."""
    data = {k: str(fm.get(k) or "") for k in SIGNED_FIELDS}
    att = fm.get(attest.ATTEST_FIELD)
    if isinstance(att, dict):
        data[attest.ATTEST_FIELD] = att
    return data


def _seal(record: dict, slug: str, sender: str, recipient: str,
          task_id: str = "") -> dict:
    """Attach an attestation, or admit in the event stream that none could be made.

    With a trust root installed the signing key is root-owned and this process is
    refused: the message still goes out, unsigned and visibly so, because a lost handoff
    is not a safer outcome than an honest gap — and `unsigned` is auditable.
    """
    try:
        return attest.sign(_signed(record)).get(attest.ATTEST_FIELD) or {}
    except (OSError, RuntimeError) as exc:
        events.emit("MESSAGE_UNSIGNED", stage="AUTHORIZE", workspace=slug,
                    actor=f"agent:{sender}", task_id=task_id,
                    payload={"to": recipient, "detail": str(exc)})
        return {}


def attestation_of(fm: dict, body: str) -> str:
    """VERIFIED / FORGED / UNSIGNED / NO_TRUST_ROOT for one message record."""
    state = attest.verify(_signed(fm))
    if state != attest.VERIFIED:
        return state
    claimed = str(fm.get("body_sha256") or "")
    if claimed and claimed != _digest(body):
        # The seal covers the hash, so the body has to be re-hashed here — the same way
        # evidence.py recomputes its transcript instead of trusting what was written.
        return attest.FORGED
    return state


def _record_at(path: Path) -> tuple:
    """(fm, body, state) for one file: what is on disk is what gets judged."""
    text = read_text(path)
    try:
        fm, body = fm_parse(text)
        return fm, body, attestation_of(fm, body)
    except BrainError:
        # A header that no longer parses is a destroyed record, not an absent one.
        return {}, text, attest.FORGED


# ---- send / read / ack ---------------------------------------------------


def send(body: str, sender: str, recipient: str, workspace: str = "",
         task_id: str = "", kind: str = "message") -> dict:
    """Send a directed message. Creates inbox entry + outbox audit mirror.

    `sender` is a claim, and it is checked against the seat this process was started as
    before anything is written; a mismatch is refused, not relabelled.
    """
    slug = workspace or ws_mod.default_workspace()
    recipient = board.resolve_agent(recipient) or recipient
    if not body or not body.strip():
        raise BrainError("message body cannot be empty")
    if not recipient:
        raise BrainError("recipient is required (use --to <agent>)")

    sender = _authenticate(sender, slug, recipient, task_id)
    _authorize_route(sender, recipient, slug, task_id)

    stamp = now()
    msg_id = f"msg-{stamp.replace(':', '').replace('-', '').replace('T', '')[:15]}-{sender}"
    content = f"{body.strip()}\n"

    fm = {
        "id": msg_id,
        "from": sender,
        "to": recipient,
        "kind": kind,
        "task_id": task_id or "",
        "read": False,
        "created": stamp,
        "body_sha256": _digest(content),
    }
    att = _seal(fm, slug, sender, recipient, task_id)
    if att:
        fm[attest.ATTEST_FIELD] = att

    record = fm_dump(fm) + content
    path = _inbox_dir(recipient, slug) / f"{msg_id}.md"
    atomic_write(path, record)
    # Audit mirror in the sender's outbox carries the identical bytes, so the two copies
    # cannot be made to disagree about who said what.
    atomic_write(_outbox_dir(sender, slug) / f"{msg_id}.md", record)

    # Judged on the way out of the file, not from memory: a seal that does not survive the
    # round trip must be reported as broken here rather than at somebody's review.
    _, _, state = _record_at(path)
    trust_mode = att.get("trust_mode", "unknown")
    events.emit("MESSAGE_SENT", stage="RECORD", actor=f"agent:{sender}",
                workspace=slug, task_id=task_id,
                payload={"msg_id": msg_id, "from": sender, "to": recipient, "kind": kind,
                         "attestation": state, "trust_mode": trust_mode})

    return {"id": msg_id, "from": sender, "to": recipient, "workspace": slug,
            "path": str(path), "_attestation": state, "_trust_mode": trust_mode}


def read_inbox(agent: str, workspace: str = "", unread_only: bool = True) -> list[dict]:
    """Read messages in an agent's inbox. Returns newest-first.

    Every record comes back with its attestation state attached and tampered ones are
    labelled rather than dropped, mirroring `evidence.get_receipts`: whoever forged into
    a mailbox has to leave something a reviewer can point at.
    """
    agent = board.resolve_agent(agent) or agent
    slug = workspace or ws_mod.default_workspace()
    inbox = _inbox_dir(agent, slug)

    messages = []
    for path in sorted(inbox.glob("msg-*.md"), reverse=True):
        fm, body, state = _record_at(path)
        if unread_only and fm.get("read"):
            continue
        messages.append({
            "id": fm.get("id", path.stem),
            "from": fm.get("from", ""),
            "to": fm.get("to", ""),
            "kind": fm.get("kind", "message"),
            "task_id": fm.get("task_id", ""),
            "read": fm.get("read", False),
            "created": fm.get("created", ""),
            "body": body.strip(),
            "path": str(path),
            "_attestation": state,
            "_trust_mode": (fm.get(attest.ATTEST_FIELD) or {}).get("trust_mode", "unknown"),
        })
    return messages


def inbox_states(agent: str, workspace: str = "") -> dict:
    """How much of this mailbox can actually be trusted: {state: count}."""
    counts: dict = {}
    for msg in read_inbox(agent, workspace, unread_only=False):
        state = str(msg.get("_attestation") or "")
        counts[state] = counts.get(state, 0) + 1
    return counts


def acknowledge(msg_id: str, agent: str, workspace: str = "") -> dict:
    """Mark a message as read — by the seat whose inbox holds it, and only if it is not
    forged: acknowledging tampered content is how a forgery becomes part of the record."""
    slug = workspace or ws_mod.default_workspace()
    agent = _authenticate(agent, slug, agent)
    inbox = _inbox_dir(agent, slug)

    for path in inbox.glob("msg-*.md"):
        fm, body, state = _record_at(path)
        if fm.get("id") != msg_id:
            continue
        if state == attest.FORGED:
            _refuse("MESSAGE_FORGERY_REFUSED", slug, f"agent:{agent}", "",
                    f"message {msg_id} in {agent}'s inbox is {state}: its seal does not "
                    "hold, so it will not be marked as seen. Someone edited "
                    f"{path.name} after it was delivered.",
                    {"msg_id": msg_id, "attestation": state})
        # `read` is outside the signed set, so flipping it keeps the seal intact.
        fm["read"] = True
        atomic_write(path, fm_dump(fm) + body)
        return {"id": msg_id, "acknowledged": True, "_attestation": state}

    raise NotFound(f"message {msg_id} not found in {agent}'s inbox")


def unread_count(agent: str, workspace: str = "") -> int:
    """Count unread messages for an agent."""
    return len(read_inbox(agent, workspace, unread_only=True))
