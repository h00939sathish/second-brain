# -*- coding: utf-8 -*-
"""Stable seat identity for the Second Brain.

Borrowing OpenRig's stable seat concept: a seat represents a role/address in a
workspace (e.g. `codex-planner@default`), which remains stable even as underlying
conversations/sessions change.
"""

from typing import Optional

from . import board, const, coordination, messaging, store, topology, workspaces as ws_mod


def seat_id(agent: str, workspace: str = "") -> str:
    """Derive stable seat ID: {agent}-{role}@{workspace}."""
    slug = workspace or ws_mod.default_workspace()
    canonical = board.resolve_agent(agent) or agent
    role = board.role_of(canonical)
    return f"{canonical}-{role}@{slug}"


def parse_seat_id(seat_identifier: str) -> tuple[str, str, str]:
    """Parse seat ID into (agent, role, workspace).

    Accepts formats:
    - agent-role@workspace
    - agent@workspace
    - agent
    """
    workspace = ""
    target = seat_identifier
    if "@" in target:
        target, workspace = target.split("@", 1)
    
    agent = target
    role = ""
    if "-" in target:
        parts = target.split("-", 1)
        agent, role = parts[0], parts[1]
    
    canonical = board.resolve_agent(agent) or agent
    role = role or board.role_of(canonical)
    workspace = workspace or ws_mod.default_workspace()
    return canonical, role, workspace


def get_seat(agent: str, workspace: str = "") -> dict:
    """Inspect the status of a specific seat."""
    slug = workspace or ws_mod.default_workspace()
    canonical = board.resolve_agent(agent) or agent
    role = board.role_of(canonical)
    s_id = seat_id(canonical, slug)

    # Active sessions for this agent in workspace
    active_sessions = [
        s for s in coordination.list_sessions(workspace=slug, active_only=True)
        if board.resolve_agent(s["fm"].get("agent", "")) == canonical
    ]

    # Topology edges if available
    topo = topology.load(slug)
    edges = []
    if topo and "seats" in topo and canonical in topo["seats"]:
        edges = topo["seats"][canonical].get("edges", [])

    # Unread messages
    unread = messaging.unread_count(canonical, slug)

    return {
        "seat_id": s_id,
        "agent": canonical,
        "role": role,
        "workspace": slug,
        "active_sessions": [s["id"] for s in active_sessions],
        "active_session_count": len(active_sessions),
        "unread_messages": unread,
        "edges": edges,
    }


def list_seats(workspace: str = "") -> list[dict]:
    """List all declared or known seats in the workspace."""
    slug = workspace or ws_mod.default_workspace()
    topo = topology.load(slug)

    agents = set()
    if topo and "seats" in topo:
        agents.update(topo["seats"].keys())
    else:
        # Default fallback to standard known agent roles
        agents.update(const.AGENT_ROLES.keys())

    seats = []
    for ag in sorted(agents):
        seats.append(get_seat(ag, slug))
    return seats
