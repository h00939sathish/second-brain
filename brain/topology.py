# -*- coding: utf-8 -*-
"""Enforced agent topology graph.

Loads a `topology.yaml` from the workspace ``meta/`` directory and validates
routing constraints on dispatch and handoff. Unlike OpenRig where edges are
"aspirational capabilities", here edges are **enforced** at the transaction
boundary: inside a declared topology, anything not permitted is denied.

A workspace with no `topology.yaml` has no policy to enforce, so routing is allowed and
each use is written to the event stream as ungoverned (`ROUTING_UNGOVERNED`) and reported
by `brain doctor`. That is a configuration gap being announced, not a hole being papered over.

Where a signed pin exists (``meta/topology.pin.json``, written only by the privileged
witness) the file on disk has to hash to it, so an agent cannot rewrite its own routing
rules and have them believed.
"""

import hashlib
import json
import yaml
from pathlib import Path

from . import const, store, workspaces as ws_mod
from .errors import BrainError, TopologyError
from .paths import bypass_enabled

TOPOLOGY_FILE = "topology.yaml"
PIN_FILE = "topology.pin.json"
_UNGOVERNED_SEEN: set = set()

# The 5 edge kinds (borrowed from OpenRig's taxonomy)
EDGE_KINDS = frozenset({
    "delegates_to",       # source gives work to target (primary workflow)
    "can_observe",        # source can observe target's output (review)
    "collaborates_with",  # peer relationship (bidirectional)
    "escalates_to",       # source escalates decisions to target
    "spawned_by",         # parent→child creation relationship
})

# Which edge kinds allow the *source* to route work *to* the target
ROUTING_EDGES = frozenset({"delegates_to", "collaborates_with", "escalates_to"})


def _topo_path(workspace: str = "") -> Path:
    slug = workspace or ws_mod.default_workspace()
    ws_root = ws_mod.workspace_dir(slug)
    return ws_root / const.META_DIR / TOPOLOGY_FILE


def pin_path(workspace: str = "") -> Path:
    slug = workspace or ws_mod.default_workspace()
    return ws_mod.workspace_dir(slug) / const.META_DIR / PIN_FILE


def pin_status(workspace: str = "") -> tuple[str, str]:
    """(state, detail) for the topology file against the witness's signed pin.

    `pinned` / `drifted` / `unpinned` — never raises, because `doctor` and `brief` ask
    about every workspace including the ones with nothing declared.
    """
    from . import attest

    path = _topo_path(workspace)
    pin = pin_path(workspace)
    if not path.exists():
        return "none", "no topology.yaml"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if not pin.exists():
        return "unpinned", f"sha256={digest[:12]}… has no signed pin"
    try:
        record = json.loads(pin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "drifted", f"{pin.name} is unreadable"
    if attest.verify(record) != attest.VERIFIED:
        return "drifted", f"{pin.name} failed attestation " \
                          f"({attest.verify(record)}); the pin itself is not trustworthy"
    if str(record.get("sha256") or "") != digest:
        return "drifted", (f"topology.yaml was edited after it was pinned "
                           f"(pinned {str(record.get('sha256'))[:12]}…, now {digest[:12]}…)")
    return "pinned", f"sha256={digest[:12]}…"


def load(workspace: str = "") -> dict | None:
    """Load and validate the topology. Returns None if no file exists."""
    path = _topo_path(workspace)
    if not path.exists():
        return None
    state, detail = pin_status(workspace)
    if state == "drifted":
        raise TopologyError(f"topology is not the policy that was approved: {detail}")
    from . import attest
    if state == "unpinned" and attest.installed():
        raise TopologyError(
            f"topology has no approved pin, so nothing here is policy: {detail}. "
            f"Deleting the pin is not an un-pin — have the operator approve the file "
            f"(`brain topology {workspace or ''} pin`) or write a grant for the run")
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise TopologyError(f"topology.yaml must be a YAML mapping, got {type(data).__name__}")
    _validate(data)
    return data


def _validate(data: dict):
    """Validate the topology structure and detect cycles."""
    seats = data.get("seats")
    if not isinstance(seats, dict) or not seats:
        raise TopologyError("topology.yaml must have a non-empty 'seats' mapping")

    known = set(seats.keys())
    for seat_id, seat in seats.items():
        if not isinstance(seat, dict):
            raise TopologyError(f"seat '{seat_id}' must be a mapping")
        for edge in seat.get("edges", []):
            kind = edge.get("kind", "")
            if kind not in EDGE_KINDS:
                raise TopologyError(
                    f"seat '{seat_id}': unknown edge kind '{kind}' "
                    f"(valid: {', '.join(sorted(EDGE_KINDS))})"
                )
            target = edge.get("to", "")
            if target not in known:
                raise TopologyError(
                    f"seat '{seat_id}': edge target '{target}' is not a declared seat "
                    f"(known: {', '.join(sorted(known))})"
                )

    # Detect cycles in delegates_to / spawned_by (the ordering edges)
    _detect_cycle(seats)


def _detect_cycle(seats: dict):
    """Detect cycles in the delegation graph (delegates_to + spawned_by)."""
    adj: dict[str, list[str]] = {s: [] for s in seats}
    for seat_id, seat in seats.items():
        for edge in seat.get("edges", []):
            if edge.get("kind") in ("delegates_to", "spawned_by"):
                adj[seat_id].append(edge["to"])

    WHITE, GRAY, BLACK = 0, 1, 2
    color = {s: WHITE for s in seats}
    path: list[str] = []

    def dfs(node: str):
        color[node] = GRAY
        path.append(node)
        for nb in adj[node]:
            if color[nb] == GRAY:
                cycle_start = path.index(nb)
                cycle = path[cycle_start:] + [nb]
                raise TopologyError(
                    f"delegation cycle detected: {' → '.join(cycle)}"
                )
            if color[nb] == WHITE:
                dfs(nb)
        path.pop()
        color[node] = BLACK

    for s in seats:
        if color[s] == WHITE:
            dfs(s)


def can_route(source: str, target: str, workspace: str = "") -> tuple[bool, str]:
    """May *source* route work to *target*? Denied unless a declared edge says yes.

    Inside a declared topology the graph is exhaustive: an undeclared name is not a
    seat, and a missing edge is a missing route. Self-routing is not exempt either —
    declaring it is one line of YAML, exempting it here is a hole.

    When the policy denies, the caller gets one more chance: a human-minted grant,
    which is *spent* on the attempt either way, so it buys one step over the line and
    nothing else.
    """
    slug = workspace or ws_mod.default_workspace()
    topo = load(slug)

    if topo is None:
        _note_ungoverned(slug, source, target)
        return True, "no topology declared for this workspace (routing is ungoverned here)"

    seats = topo.get("seats", {})
    if not source:
        return False, "no source agent given: routing needs a declared seat, not an anonymous caller"
    if source not in seats:
        return _escape(slug, source, target,
                       f"seat '{source}' is not declared in topology.yaml "
                       f"(declared: {', '.join(sorted(seats))})")
    if target not in seats:
        return _escape(slug, source, target,
                       f"target '{target}' is not a declared seat")

    for edge in seats[source].get("edges", []):
        if edge.get("to") == target and edge.get("kind") in ROUTING_EDGES:
            return True, f"edge: {source} --{edge['kind']}--> {target}"

    for edge in seats[target].get("edges", []):
        if edge.get("to") == source and edge.get("kind") == "collaborates_with":
            return True, f"edge: {target} --collaborates_with--> {source} (bidirectional)"

    return _escape(slug, source, target, _denial(seats, source, target))


def _denial(seats: dict, source: str, target: str) -> str:
    reachable = [e["to"] for e in seats[source].get("edges", [])
                 if e.get("kind") in ROUTING_EDGES]
    return (f"no routing edge from '{source}' to '{target}' "
            f"(valid targets for '{source}': {', '.join(reachable) or 'none'})")


def _escape(slug: str, source: str, target: str, why: str) -> tuple[bool, str]:
    """A denied route stays denied unless a grant pays for it. The grant is spent on
    the attempt, so it cannot be hoarded and replayed against the next gate."""
    if bypass_enabled(seat=source, action=f"route:{source}->{target}", workspace=slug):
        return True, f"granted override of: {why}"
    return False, why


def _note_ungoverned(slug: str, source: str, target: str) -> None:
    """Say it out loud, once per route per process, that no policy was consulted."""
    key = (slug, source, target)
    if key in _UNGOVERNED_SEEN:
        return
    _UNGOVERNED_SEEN.add(key)
    from . import events
    events.emit("ROUTING_UNGOVERNED", stage="AUTHORIZE", workspace=slug,
                actor=f"agent:{source or '?'}",
                payload={"target": target, "why": "no topology.yaml in this workspace"})


def render_ascii(workspace: str = "") -> str:
    """Render a simple ASCII representation of the topology."""
    topo = load(workspace)
    if topo is None:
        return "(no topology.yaml found)"

    lines = ["Agent Topology", "=" * 40]
    seats = topo.get("seats", {})
    for seat_id, seat in seats.items():
        role = seat.get("role", "?")
        lines.append(f"\n  [{seat_id}] ({role})")
        for edge in seat.get("edges", []):
            arrow = "──▶" if edge["kind"] in ROUTING_EDGES else "···"
            lines.append(f"    {arrow} {edge['kind']} → {edge['to']}")
    return "\n".join(lines)


def list_seats(workspace: str = "") -> list[dict]:
    """Return a list of seat dicts for the topology command."""
    topo = load(workspace)
    if topo is None:
        return []
    result = []
    for seat_id, seat in topo.get("seats", {}).items():
        result.append({
            "id": seat_id,
            "role": seat.get("role", ""),
            "edges": seat.get("edges", []),
        })
    return result
