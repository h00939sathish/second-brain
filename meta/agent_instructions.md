# Agent Integration Instructions (v3)

> Paste or inject this block into each agent's system prompt / instructions
> so they follow the shared coordination protocol.

## Second Brain (Multi-Agent Coordination & Shared Memory)

You have access to the shared brain (MCP server: `second-brain`). All coding agents
(opencode, Hermes, Claude, Codex, Antigravity) use this central hub to coordinate.

### Protocol:

1. **At Session Start**:
   - Call `brain_dashboard()` for full situational awareness (active sessions, file locks, recent handoffs).
   - If planning to edit files, check availability: `brain_check_files(files="src/app.py,tests/test_app.py")`.
   - Register your session and reserve files:
     `brain_session_start(agent="<name>", project="<proj>", task="<task>", files="path1,path2", lease_mins=30)`

2. **During Work**:
   - `brain_recall(query="...")` — BM25 search for permanent facts, rules, and architecture notes.
   - `brain_read(query="...")` — read shared context notes & blockers posted by other agents.
   - `brain_post(text="...", project="...", tags="...", agent="<name>")` — share discoveries or blockers (auto-expires in 7 days).
   - `brain_promote(context_id="...")` — promote a valuable discovery note into a permanent claim.
   - `brain_reserve(session_id="...", files="...", lease_mins=30)` — reserve additional files.
   - `brain_session_update(session_id="...", progress="...")` — log key checkpoints.

3. **At Session End**:
   - Call `brain_session_end(session_id, summary="...", target_agent="...", next_steps="...", modified_files="...", test_status="...")`
   - This records structured handoff metadata and **immediately releases all file locks**.

### Tool Quick Reference (19 Tools)

| Category | Tools |
|---|---|
| **Coordination** | `brain_dashboard`, `brain_session_start`, `brain_session_update`, `brain_session_end`, `brain_sessions` |
| **Concurrency & Locks** | `brain_reserve`, `brain_check_files` |
| **Context & Scratchpad** | `brain_post`, `brain_read`, `brain_promote` |
| **Knowledge & Claims** | `brain_recall`, `brain_claim`, `brain_supersede`, `brain_dispute`, `brain_verify`, `brain_related`, `brain_status`, `brain_sweep` |
