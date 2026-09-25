# -*- coding: utf-8 -*-
"""Goal decomposition and Task DAG compilation for high-level planners (Phase 6).

Interfaces JARVIS / orchestration agents directly with the Control Plane as an
untrusted high-level planner. JARVIS proposes intent graphs; the Control Plane validates
acyclicity, resource conflicts, and authorizes task creation into the DAG.
"""

from typing import Dict, List, Optional

from . import board, const, coordination, events, store, workspaces as ws_mod
from .errors import BrainError, CycleDetectedError, LeaseConflict, NotFound
from .paths import now


def validate_goal_dag(tasks: List[dict]) -> None:
    """Check task list for internal cycles and conflicting concurrent file leases."""
    # 1. Cycle detection on symbolic keys
    task_keys = {t.get("key", f"t_{i}"): t for i, t in enumerate(tasks)}
    adj = {k: [] for k in task_keys}
    for k, t in task_keys.items():
        deps = t.get("depends_on") or []
        if isinstance(deps, str):
            deps = [d.strip() for d in deps.split(",") if d.strip()]
        for d in deps:
            if d in adj:
                adj[k].append(d)

    # DFS cycle check
    visited = {}  # 0=unvisited, 1=visiting, 2=visited
    for node in adj:
        visited[node] = 0

    def dfs(n, path):
        visited[n] = 1
        for parent in adj.get(n, []):
            if visited.get(parent) == 1:
                cycle_str = " -> ".join(path + [parent])
                raise CycleDetectedError(f"cycle detected in proposed goal DAG: {cycle_str}")
            if visited.get(parent) == 0:
                dfs(parent, path + [parent])
        visited[n] = 2

    for node in adj:
        if visited[node] == 0:
            dfs(node, [node])

    # 2. Check for conflicting file leases among unsequenced parallel tasks
    # Two tasks that do NOT depend on each other cannot claim the same files
    def reaches(a, b):
        """Does task a depend directly or indirectly on b?"""
        frontier = list(adj.get(a, []))
        seen = set(frontier)
        while frontier:
            curr = frontier.pop(0)
            if curr == b:
                return True
            for nxt in adj.get(curr, []):
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return False

    keys = list(task_keys.keys())
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            k1, k2 = keys[i], keys[j]
            t1, t2 = task_keys[k1], task_keys[k2]
            f1 = set(t1.get("files") or ([] if not isinstance(t1.get("files"), str) else [f.strip() for f in t1.get("files").split(",") if f.strip()]))
            f2 = set(t2.get("files") or ([] if not isinstance(t2.get("files"), str) else [f.strip() for f in t2.get("files").split(",") if f.strip()]))
            overlap = f1 & f2
            if overlap:
                # If neither reaches the other, they are concurrent and will conflict!
                if not reaches(k1, k2) and not reaches(k2, k1):
                    raise LeaseConflict(
                        list(overlap),
                        holder=f"concurrent proposed tasks '{k1}' and '{k2}'"
                    )


def propose_goal(goal: str, tasks: List[dict], spec: Optional[dict] = None,
                 workspace: str = "", project: str = "",
                 actor: str = "agent:jarvis") -> dict:
    """Decompose a high-level goal into an authorized spec and Task DAG.

    Validates acyclicity and lease concurrency before creating durable records.
    """
    goal = (goal or "").strip()
    if not goal:
        raise BrainError("a goal proposal requires a goal description")
    if not tasks:
        raise BrainError("a goal proposal must include at least one task")

    slug = workspace or ws_mod.default_workspace()
    proj = project or slug

    events.emit("GOAL_PROPOSED", stage="PROPOSE", actor=actor, workspace=slug,
                payload={"goal": goal, "task_count": len(tasks), "project": proj})

    # Validate graph topology and lease isolation
    validate_goal_dag(tasks)

    # 1. Create Spec if requested
    spec_id = ""
    if spec:
        spec_title = spec.get("title") or goal[:60]
        spec_body = spec.get("description") or spec.get("spec") or f"Goal: {goal}"
        spec_phases = spec.get("phases") or ""
        created_spec = board.create_spec(
            title=spec_title,
            spec=spec_body,
            workspace=slug,
            project=proj,
            phases=spec_phases,
        )
        spec_id = created_spec["id"]

    # 2. Allocate real task IDs and resolve dependencies
    symbolic_map = {}
    for i, t in enumerate(tasks):
        key = t.get("key") or f"task_{i+1}"
        new_id = store.new_id("tasks")
        symbolic_map[key] = new_id

    created_tasks = []
    for i, t in enumerate(tasks):
        key = t.get("key") or f"task_{i+1}"
        task_id = symbolic_map[key]
        raw_deps = t.get("depends_on") or []
        if isinstance(raw_deps, str):
            raw_deps = [d.strip() for d in raw_deps.split(",") if d.strip()]

        # Map symbolic keys or preserve existing task IDs
        resolved_deps = [symbolic_map.get(d, d) for d in raw_deps]

        # Determine initial status
        # If task has unmet dependencies, it becomes blocked; otherwise ready or backlog
        raw_status = t.get("status", "")
        if not raw_status:
            status = "blocked" if resolved_deps else "ready"
        else:
            status = raw_status

        ct = board.create_task(
            title=t.get("title", f"Subtask {i+1}"),
            workspace=slug,
            project=proj,
            spec_id=spec_id or t.get("spec_id", ""),
            agent=t.get("agent", "opencode"),
            phase=t.get("phase", ""),
            files=t.get("files", ""),
            status=status,
            depends_on=resolved_deps,
            task_id=task_id,
        )
        created_tasks.append({
            "id": ct["id"],
            "key": key,
            "title": t.get("title"),
            "agent": t.get("agent", "opencode"),
            "status": ct["status"],
            "files": ct.get("files", []),
            "depends_on": resolved_deps,
        })

    events.emit("GOAL_ACCEPTED", stage="AUTHORIZE", actor=actor, workspace=slug,
                payload={
                    "goal": goal,
                    "spec_id": spec_id,
                    "tasks": [t["id"] for t in created_tasks],
                })

    return {
        "ok": True,
        "goal": goal,
        "workspace": slug,
        "project": proj,
        "spec_id": spec_id,
        "tasks": created_tasks,
    }
