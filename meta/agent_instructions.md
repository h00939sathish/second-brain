# Agent Integration Instructions (v4.2)

> Multi-agent division of labor & execution protocol for Second Brain.

## The Autonomous Multi-Agent Cycle

```
[User Prompts Any Agent]
          │
          ▼
   [brain_cycle_route]
   ├── Trivial Task    ──► Direct execution (zero pipeline overhead)
   └── Complex Feature ──► 4-Stage Autonomous Pipeline:
```

### Role Division & Invariants:

1. **Stage 1: The Planning Debate (GPT 5.6 & Gemini 3.7 Flash)**
   - **Codex (GPT 5.6):** Formulates concise, dense architectural invariants & constraints (conserving tokens).
   - **Antigravity CLI (Gemini 3.7 Flash):** Ingests whole-codebase context (1M context window), critiques the spec for edge cases, and refines execution phases.
   - **Result:** Codex approves and creates the upstream spec (`brain_spec_create`) and generates Kanban tasks (`brain_task_create`).
   - ⚠️ **INVARIANT:** Neither Codex nor AGY writes boilerplate code or does repetitive line edits.

2. **Stage 2: Heavy Lifting (opencode / Claude Code)**
   - **Builders:** Claim tasks in `running`, reserve file leases (`brain_reserve`), do all mechanical file edits, refactoring, package installs, and local test runs.
   - On phase completion, end session with handoff to Antigravity (`brain_task_move -> review`).

3. **Stage 3: Final Review & Verification (Gemini 3.7 Flash / Antigravity CLI)**
   - **Antigravity:** Ingests full git diffs and full repo context (1M tokens).
   - Audits for architectural drift against the debated spec.
   - Executes comprehensive test suites (`pytest`, `cargo`, `npm`).
   - Posts structured verification report (`brain_post`) and advances task to `done`.

4. **Stage 4: Sign-off (Codex / GPT 5.6)**
   - Codex validates the review report and commits any permanent architectural claims into `claims/*.md`.

---

## Tool Quick Reference (26 Tools)

| Category | Tools |
|---|---|
| **Autonomous Cycle** | `brain_cycle_route`, `brain_cycle_next` |
| **Upstream Specs (Traycer)** | `brain_spec_create`, `brain_specs` |
| **Kanban Tasks (agtx)** | `brain_task_create`, `brain_task_move`, `brain_tasks` |
| **Presence & Sessions** | `brain_dashboard`, `brain_session_start`, `brain_session_update`, `brain_session_end`, `brain_sessions` |
| **Concurrency & Locks** | `brain_reserve`, `brain_check_files` |
| **Context & Scratchpad** | `brain_post`, `brain_read`, `brain_promote` |
| **Knowledge & Claims** | `brain_recall` *(BM25)*, `brain_claim`, `brain_supersede`, `brain_dispute`, `brain_verify`, `brain_related`, `brain_status`, `brain_sweep` |
