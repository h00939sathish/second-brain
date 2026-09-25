# -*- coding: utf-8 -*-
"""Declarative agent squads (OpenRig RigSpec pods).

Manages `squad.yaml` in the workspace ``meta/`` directory. Defines the active
team structure (lead, builder, reviewer, qa) and provides automatic routing
for kanban card transitions and multi-agent coordination.
"""

from pathlib import Path
import yaml

from . import board, const, coordination, store, workspaces as ws_mod
from .errors import BrainError
from .paths import VAULT


def squad_path(workspace: str = "") -> Path:
    """Return the filesystem path for squad.yaml in the given workspace."""
    slug = workspace or ws_mod.default_workspace()
    ws_root = ws_mod.workspace_dir(slug)
    meta_dir = ws_root / const.META_DIR
    meta_dir.mkdir(parents=True, exist_ok=True)
    return meta_dir / const.SQUAD_FILE


def load_squad(workspace: str = "") -> dict:
    """Load the declared squad for the workspace, or return default structure if none exists."""
    slug = workspace or ws_mod.default_workspace()
    path = squad_path(slug)
    if not path.exists():
        # Fallback to root meta if global/default
        root_path = VAULT / const.META_DIR / const.SQUAD_FILE
        if root_path.exists():
            path = root_path
        else:
            return {
                "name": f"{slug}-squad",
                "workspace": slug,
                "roles": dict(const.DEFAULT_SQUAD_ROLES),
                "configured": False,
                "path": str(path),
            }

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise BrainError(f"failed to read squad file at {path}: {exc}")

    if not isinstance(data, dict):
        raise BrainError(f"squad.yaml must be a YAML mapping, got {type(data).__name__}")

    raw_roles = data.get("roles") or {}
    roles = dict(const.DEFAULT_SQUAD_ROLES)
    if isinstance(raw_roles, dict):
        for r, a in raw_roles.items():
            if r in const.SQUAD_ROLES and a:
                resolved = board.resolve_agent(str(a))
                roles[r] = resolved or str(a)

    return {
        "name": data.get("name", f"{slug}-squad"),
        "workspace": slug,
        "roles": roles,
        "configured": True,
        "path": str(path),
    }


def save_squad(data: dict, workspace: str = "") -> dict:
    """Validate and write squad configuration to squad.yaml."""
    slug = workspace or ws_mod.default_workspace()
    path = squad_path(slug)

    roles = data.get("roles") or {}
    if not isinstance(roles, dict):
        raise BrainError("squad 'roles' must be a mapping of role -> agent")

    clean_roles = {}
    for r in const.SQUAD_ROLES:
        val = roles.get(r, const.DEFAULT_SQUAD_ROLES.get(r, ""))
        if val:
            clean_roles[r] = board.resolve_agent(str(val)) or str(val)

    payload = {
        "name": str(data.get("name") or f"{slug}-squad"),
        "workspace": slug,
        "roles": clean_roles,
    }

    try:
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    except OSError as exc:
        raise BrainError(f"failed to write squad configuration to {path}: {exc}")

    return {**payload, "configured": True, "path": str(path)}


def set_role(role: str, agent: str, workspace: str = "") -> dict:
    """Assign or reassign an agent to a specific squad role."""
    role = role.strip().lower()
    if role not in const.SQUAD_ROLES:
        raise BrainError(f"unknown squad role '{role}'; choose from {', '.join(const.SQUAD_ROLES)}")

    resolved = board.resolve_agent(agent) or agent.strip()
    if not resolved:
        raise BrainError("agent name cannot be empty")

    squad = load_squad(workspace)
    squad["roles"][role] = resolved
    return save_squad(squad, workspace)


def get_agent(role: str, workspace: str = "") -> str:
    """Return the agent assigned to the given role in the workspace."""
    squad = load_squad(workspace)
    return squad["roles"].get(role, "")


def route_stage(status: str, workspace: str = "") -> str:
    """Return the squad agent designated for a given kanban status stage."""
    status = (status or "").lower().strip()
    squad = load_squad(workspace)
    roles = squad["roles"]

    if status in ("planning", "backlog", "coordinating"):
        return roles.get("lead") or roles.get("builder", "")
    if status in ("running", "ready"):
        return roles.get("builder") or roles.get("lead", "")
    if status in ("review", "blocked"):
        return roles.get("reviewer") or roles.get("lead", "")
    if status == "done":
        return roles.get("qa") or roles.get("reviewer", "")
    return roles.get("lead", "")


def squad_status(workspace: str = "") -> dict:
    """Collect squad loadout together with live presence and session data."""
    slug = workspace or ws_mod.default_workspace()
    squad = load_squad(slug)
    active_sessions = coordination.list_sessions(workspace=slug, active_only=True)

    session_by_agent = {}
    for s in active_sessions:
        ag = s["fm"].get("agent")
        if ag:
            session_by_agent[ag] = {
                "session_id": s["fm"].get("id"),
                "task": s["fm"].get("task", ""),
                "task_id": s["fm"].get("task_id", ""),
                "files": s["fm"].get("files", []),
            }

    members = []
    for role in const.SQUAD_ROLES:
        agent = squad["roles"].get(role, "")
        info = session_by_agent.get(agent)
        members.append({
            "role": role,
            "agent": agent,
            "active": info is not None,
            "session": info,
        })

    return {
        "name": squad["name"],
        "workspace": slug,
        "configured": squad["configured"],
        "path": squad["path"],
        "roles": squad["roles"],
        "members": members,
    }
