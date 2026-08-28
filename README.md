# Second Brain — Multi-Agent Coordination & Execution Hub (v4)

A unified platform combining **shared memory truth store** with **Traycer-style upstream specs** and **agtx-style Kanban orchestration & worktree tracking** across all coding agents (Hermes, opencode, Claude Code, Codex, Antigravity, etc.).

## Core Architecture

1. **Upstream Specs & Phases (`specs/*.md`)** *(Traycer pattern)*:
   - Spec-first development: architectural intent, constraints, and phased milestones.
   - Prevents unguided "vibe coding".

2. **Git-Backed Kanban Tasks (`tasks/*.md`)** *(agtx pattern)*:
   - Kanban board pipeline: `backlog` $\rightarrow$ `planning` $\rightarrow$ `running` $\rightarrow$ `review` $\rightarrow$ `done`.
   - Task assignment, target files, and phase tracking.

3. **Coordination & Concurrency (`sessions/*.md`)**:
   - Real-time agent presence and progress milestones.
   - **File Leases / Locks**: Prevents concurrent editing collisions across agents.
   - **Git Branch & Worktree Tracking**: Records active branch/worktree.
   - **Structured Handoffs**: Target agent, modified files, test status, and next steps.

4. **Shared Context Scratchpad (`context/*.md`)**:
   - Ephemeral discoveries, decisions, and blockers (7-day TTL).
   - **Promotion**: Promote any context note to a permanent claim (`brain_promote`).

5. **Knowledge & Claims (`claims/*.md`)**:
   - Long-term facts, rules, and architecture decisions with truth lifecycle (`active` $\rightarrow$ `superseded` / `expired` / `disputed`).
   - **Fast Search**: Indexed via **SQLite FTS5** with BM25 relevance ranking.

6. **L0 Auto-Injection (`meta/l0_pointers.md`)**:
   - Injected into agent system instructions:
     - Active agent sessions & locked files
     - Active Kanban tasks in progress
     - Recent context notes
     - Active claims (budget-enforced ≤ 2.2KB)

## MCP Integration (24 Tools)

Exposed via `mcp/brain_mcp.py` (FastMCP stdio):

- **Specs**: `brain_spec_create`, `brain_specs`
- **Kanban**: `brain_task_create`, `brain_task_move`, `brain_tasks`
- **Coordination**: `brain_dashboard`, `brain_session_start`, `brain_session_update`, `brain_session_end`, `brain_sessions`
- **Concurrency**: `brain_reserve`, `brain_check_files`
- **Context**: `brain_post`, `brain_read`, `brain_promote`
- **Knowledge**: `brain_recall`, `brain_claim`, `brain_supersede`, `brain_dispute`, `brain_verify`, `brain_related`, `brain_status`, `brain_sweep`

Vault: D:\projects\second-brain
