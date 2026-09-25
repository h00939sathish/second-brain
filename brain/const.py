# -*- coding: utf-8 -*-
"""Tunables and static tables. No I/O and no imports from other brain modules."""

# ---- claim lifecycle ----
STATUSES = ("active", "needs_revalidation", "superseded", "expired", "disputed")
WITHHELD_STATUSES = ("needs_revalidation", "expired", "superseded", "disputed")
CLAIM_MATURITIES = ("provisional", "established", "canonical")
DEFAULT_CLAIM_MATURITY = "provisional"

# ---- kanban / task lifecycle ----
TASK_STATUSES = ("backlog", "blocked", "planning", "coordinating", "ready", "running", "review", "done")

# ---- budgets / defaults ----
L0_BUDGET = 2200
L0_MAX_LINE = 140
SESSION_STALE_HOURS = 24
DEFAULT_LEASE_MINS = 30
CONTEXT_TTL_DAYS = 7
GLOBAL_WORKSPACE = "global"
DAEMON_HEARTBEAT_SECONDS = 30
MAX_DISPATCH_LOG_LINES = 20

# ---- file/dir names ----
META_DIR = "meta"
WORKSPACES_DIR = "workspaces"
CONFIG_NAME = "config.json"
WORKSPACES_NAME = "workspaces.json"
L0_NAME = "l0_pointers.md"
DB_NAME = "search_index.db"
HEARTBEAT_NAME = "daemon_heartbeat.json"
WORKSPACE_MARKER = ".brain-workspace"

# ---- squads (OpenRig RigSpec pods) ----
SQUAD_FILE = "squad.yaml"
SQUAD_ROLES = ("lead", "builder", "reviewer", "qa")
DEFAULT_SQUAD_ROLES = {"lead": "claude", "builder": "codex", "reviewer": "agy", "qa": "opencode"}

WS_SUBDIRS = ("claims", "specs", "tasks", "sessions", "context", "context/archive", "logs", "events", "receipts", "deliberation", "messages")
EVENT_SCHEMA_VERSION = 1
EVENT_STAGES = ("PROPOSE", "AUTHORIZE", "OBSERVE", "RECORD")

# ---- topology & routing (INV-003 & OpenRig topology) ----
TOPOLOGY_FILE = "topology.yaml"
EDGE_KINDS = ("delegates_to", "can_observe", "collaborates_with", "escalates_to", "spawned_by")

# ---- hot-potato closure contract ----
CLOSURE_REASONS = (
    "handed_off",
    "completed",
    "blocked",
    "denied",
    "canceled",
    "no-follow-on",
    "escalation",
)
MESSAGES_DIR = "messages"
GRANTS_DIR = "grants"

# ---- deliberation layer (INV-008) ----
DELIBERATION_DIR = "deliberation"
DELIBERATION_MESSAGE_TYPES = (
    "QUESTION",
    "PROPOSAL",
    "ANSWER",
    "OBJECTION",
    "SUGGESTION",
    "DEPENDENCY",
    "WARNING",
    "HANDOFF",
    "EVIDENCE",
    "ACKNOWLEDGEMENT",
)
DELIBERATION_SEVERITIES = ("low", "medium", "high", "blocking")
DELIBERATION_PRESENCE_STATES = ("ANALYZING", "PROPOSING", "REVIEWING", "OBJECTING", "IDLE")

# ---- roles: which stage of the pipeline an agent owns ----
AGENT_ROLES = {
    "codex": "planner",
    "opencode": "builder",
    "claude": "builder",
    "claude-code": "builder",
    "crush": "builder",
    "antigravity": "reviewer",
    "agy": "reviewer",
    "gemini": "reviewer",
    "hermes": "orchestrator",
    "freebuff": "builder",
    "operator": "operator",
}

# Every known agent CLI. `bins` is tried in order through shutil.which(), so the
# same table serves Windows, macOS and Linux without any platform branching.
AGENT_CLIS = {
    "codex": {
        "bins": ("codex", "codex.cmd", "codex.exe"),
        "args": ("exec", "-"),
        "stdin": True,
        "label": "Codex",
    },
    "opencode": {
        "bins": ("opencode", "opencode.cmd", "opencode.exe"),
        "args": ("run",),
        "stdin": True,
        "label": "opencode",
    },
    "claude": {
        "bins": ("claude", "claude.cmd", "claude.exe"),
        "args": ("-p",),
        "stdin": True,
        "label": "Claude Code",
    },
    "agy": {
        "bins": ("agy", "antigravity", "agy.exe", "agy.cmd"),
        "args": ("exec",),
        "stdin": True,
        "label": "Antigravity",
    },
    "gemini": {
        "bins": ("gemini", "gemini.cmd", "gemini.exe"),
        "args": (),
        "stdin": True,
        "label": "Gemini CLI",
    },
    "crush": {
        "bins": ("crush", "crush.exe"),
        "args": ("run",),
        "stdin": True,
        "label": "Crush",
    },
}

# Aliases accepted on the command line / in task frontmatter.
AGENT_ALIASES = {
    "claude-code": "claude",
    "antigravity": "agy",
    "antigravity-cli": "agy",
    "antigravity-ide": "agy",
    "open-code": "opencode",
}

# ---- routing: keyword sets that mark a request as needing the full pipeline ----
COMPLEX_KEYWORDS = (
    "refactor", "migrate", "architecture", "implement", "build", "feature",
    "pipeline", "database", "redesign", "endpoint", "oauth", "jwt", "schema",
    "concurrency", "migration", "breaking change",
)
ROUTING_THRESHOLD = 3

# ---- agent display metadata (shared by the dashboard) ----
AGENT_META = {
    "codex": {"code": "CX", "name": "Codex (Planner)", "color": "#a855f7"},
    "claude": {"code": "CL", "name": "Claude Code (Builder)", "color": "#f97316"},
    "opencode": {"code": "OC", "name": "opencode (Builder)", "color": "#10b981"},
    "agy": {"code": "AG", "name": "Antigravity (Reviewer)", "color": "#06b6d4"},
    "gemini": {"code": "GM", "name": "Gemini (Reviewer)", "color": "#06b6d4"},
    "crush": {"code": "CR", "name": "Crush (Builder)", "color": "#eab308"},
    "hermes": {"code": "HE", "name": "Hermes (Orchestrator)", "color": "#3b82f6"},
    "freebuff": {"code": "FB", "name": "Freebuff (Builder)", "color": "#ec4899"},
}
DEFAULT_AGENT_META = {"code": "AG", "name": "Agent", "color": "#64748b"}

# ---- claim schema ----
CLAIM_FM_ORDER = (
    "id", "claim", "status", "confidence", "workspace", "scope", "created",
    "reviewed_at", "source", "tags", "supersedes", "superseded_by",
    "disputed_by", "dispute_reason", "promoted_from",
    "verified_commit", "depends_on",
)
CLAIM_REQUIRED = ("id", "claim", "status", "confidence", "created")

SPEC_FM_ORDER = ("id", "title", "project", "workspace", "phases", "created", "updated")
SPEC_REQUIRED = ("id", "title", "created")

TASK_FM_ORDER = ("id", "title", "project", "workspace", "spec_id", "phase", "agent",
                 "status", "files", "depends_on", "closure_reason", "closure_target",
                 "closure_notes", "created", "updated")
TASK_REQUIRED = ("id", "title", "status", "created")

SESSION_FM_ORDER = ("id", "agent", "project", "workspace", "task", "task_id", "branch",
                    "worktree", "status", "files", "lease_expires", "started", "updated",
                    "ended", "target_agent", "test_status")
SESSION_REQUIRED = ("id", "agent", "status", "started")

CONTEXT_FM_ORDER = ("id", "agent", "project", "workspace", "tags", "created",
                    "promoted_to")
CONTEXT_REQUIRED = ("id", "agent", "created")

# ---- trust zones ---------------------------------------------------------
# The workspace is not one trust blob. What each zone permits, and who may change it,
# differs — which is the distinction the control plane was missing when every path under
# workspaces/ was excluded from integrity checking.
ZONE_CODE = "code"            # source an agent may edit while holding a lease
ZONE_STATE = "state"          # cards, sessions, notes: brain writes, agent may not hand-edit
ZONE_EVIDENCE = "evidence"    # receipts, transcripts: only the witness may write
ZONE_POLICY = "policy"        # topology, grants: only a human pin may change
ZONE_TRANSIENT = "transient"  # editor and lock files nobody is asked to justify

WITNESS_BINARY = "/usr/local/bin/brain-witness"


def zone_for_path(path: str) -> str:
    """Classify a vault-relative path into its trust zone."""
    p = str(path or "").replace("\\", "/").lstrip("./")
    parts = [seg for seg in p.split("/") if seg]
    if parts[-1] == "topology.yaml" or parts[-1] == "topology.pin.json" \
            or "grants" in parts or "meta" in parts:
        return ZONE_POLICY
    if "receipts" in parts or "logs" in parts:
        return ZONE_EVIDENCE
    if "messages" in parts:
        return ZONE_EVIDENCE
    if p.startswith(".obsidian/") or p in (".lock", ".gitignore") or p.endswith(".tmp"):
        return ZONE_TRANSIENT
    if parts[:1] == ["workspaces"]:
        return ZONE_STATE
    if parts[:1] in (["brain"], ["tests"], ["src"], ["tools"], ["mcp"]) or p.endswith(".py"):
        return ZONE_CODE
    return ZONE_STATE


DEFAULT_CONFIG = {
    "vault_version": 5,
    "sweep": {"expire_unreviewed_after_days": 120, "stale_after_days": 90},
    "recall": {"withhold": list(WITHHELD_STATUSES)},
    "session": {"stale_after_hours": SESSION_STALE_HOURS,
                "default_lease_mins": DEFAULT_LEASE_MINS},
    "context": {"default_limit": 20, "ttl_days": CONTEXT_TTL_DAYS},
    "pipeline": {"roles": AGENT_ROLES, "complex_keywords": list(COMPLEX_KEYWORDS),
                 "complexity_threshold": ROUTING_THRESHOLD},
    "search": {"engine": "sqlite_fts5", "algorithm": "bm25"},
    "vcs": {"auto_commit": True},
    "enforce": {"lease_conflicts": True, "review_gate": True},
}
