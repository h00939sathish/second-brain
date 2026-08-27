# Second Brain — Multi-Agent Coordination & Shared Memory (v3)

Shared truth store, concurrency control, and coordination hub across all coding agents
(Hermes, opencode, Claude Code, Codex, Antigravity, etc.).

## Core Architecture

1. **Knowledge & Claims (`claims/*.md`)**:
   - Long-term facts, rules, and architecture notes.
   - Status lifecycle: `active` → `superseded` / `expired` / `disputed`.
   - **Fast Search**: Indexed via **SQLite FTS5** with BM25 relevance ranking.

2. **Coordination & Concurrency (`sessions/*.md`)**:
   - Real-time agent presence and progress milestones.
   - **File Reservations / Leases**: Prevents concurrent editing conflicts across agents.
   - **Git Branch & Worktree Awareness**: Tracks which branch/worktree each agent is on.
   - **Structured Handoffs**: Target agent, modified files, test status, and next steps.

3. **Shared Context Scratchpad (`context/*.md`)**:
   - Ephemeral discoveries, decisions, and blockers.
   - **TTL Archival**: Auto-archives notes older than 7 days during `sweep`.
   - **Promotion**: Promote any context note to a permanent claim (`brain_promote`).

4. **L0 Auto-Injection (`meta/l0_pointers.md`)**:
   - High-priority summary injected into agent system instructions:
     - Active agent sessions & locked files
     - Recent context notes
     - Active claims (budget-enforced ≤ 2.2KB)

## MCP Integration (19 Tools)

Exposed via `mcp/brain_mcp.py` (FastMCP stdio):

- **Coordination**: `brain_dashboard`, `brain_session_start`, `brain_session_update`, `brain_session_end`, `brain_sessions`
- **Concurrency**: `brain_reserve`, `brain_check_files`
- **Context**: `brain_post`, `brain_read`, `brain_promote`
- **Knowledge**: `brain_recall`, `brain_claim`, `brain_supersede`, `brain_dispute`, `brain_verify`, `brain_related`, `brain_status`, `brain_sweep`

Vault: D:\projects\second-brain
