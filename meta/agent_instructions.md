# Agent Integration Instructions (v4)

> Paste or inject this block into each agent's system prompt / instructions
> so they follow the shared coordination & execution protocol.

## Second Brain (Multi-Agent Coordination & Execution Hub)

You have access to the shared brain (MCP server: `second-brain`). All coding agents
(opencode, Hermes, Claude, Codex, Antigravity) use this central hub.

### Workflow & Protocol:

1. **Before Writing Code (Spec & Kanban)**:
   - Check `brain_dashboard()` and `brain_tasks()` for active work and pending tasks.
   - For major features, verify an upstream architecture spec exists (`brain_specs()`) or create one (`brain_spec_create()`).
   - Pick or create a task on the Kanban board: `brain_task_create(...)` and advance it to `running`: `brain_task_move(task_id, status="running")`.

2. **At Session Start**:
   - If modifying files, check for active locks: `brain_check_files(files="path1,path2")`.
   - Register your session and reserve target files:
     `brain_session_start(agent="<name>", project="<proj>", task="<task>", task_id="<task_id>", files="path1,path2", lease_mins=30)`

3. **During Work**:
   - `brain_recall(query="...")` — BM25 search for permanent rules, architecture facts, and user preferences.
   - `brain_read(query="...")` — read shared context notes & blockers posted by other agents.
   - `brain_post(text="...", project="...", tags="...", agent="<name>")` — share discoveries or blockers.
   - `brain_promote(context_id="...")` — promote valuable discoveries into permanent claims.
   - `brain_session_update(session_id="...", progress="...")` — log phase progress.

4. **At Session End & Handoff**:
   - Move the task to `review` or `done`: `brain_task_move(task_id, status="review"|"done")`.
   - End your session: `brain_session_end(session_id, summary="...", target_agent="...", next_steps="...", modified_files="...", test_status="...")`
   - This records structured handoff metadata and **immediately releases all file locks**.

### Tool Quick Reference (24 Tools)

| Category | Tools |
|---|---|
| **Upstream Specs (Traycer)** | `brain_spec_create`, `brain_specs` |
| **Kanban Tasks (agtx)** | `brain_task_create`, `brain_task_move`, `brain_tasks` |
| **Coordination & Presence** | `brain_dashboard`, `brain_session_start`, `brain_session_update`, `brain_session_end`, `brain_sessions` |
| **Concurrency & Locks** | `brain_reserve`, `brain_check_files` |
| **Context & Scratchpad** | `brain_post`, `brain_read`, `brain_promote` |
| **Knowledge & Claims** | `brain_recall`, `brain_claim`, `brain_supersede`, `brain_dispute`, `brain_verify`, `brain_related`, `brain_status`, `brain_sweep` |
