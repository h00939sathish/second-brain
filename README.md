# Second Brain — Multi-Agent Coordination & Execution Hub (v4.2)

A unified platform combining **shared memory truth store**, **Traycer-style upstream specs**, and **agtx-style Kanban orchestration** with an autonomous division of labor across all coding agents.

## Autonomous Superpower Roles

- **Lead Architect & Arbiter:** **GPT 5.6 (Codex)** — High-density logic, constraints, invariant specification, final sign-off.
- **Context Analyst & Final Reviewer:** **Gemini 3.7 Flash (Antigravity)** — Ingests full 1M+ token repo context to critique specs during planning; audits complete git diffs and runs test suites during review.
- **Core Builders (Heavy Lifters):** **opencode & Claude Code** — Executes mechanical file edits, refactoring, package installs, and local test runs.
- **Invariant:** Neither Codex nor AGY performs repetitive heavy lifting; heavy code generation is offloaded to Builders.

## Core Architecture

1. **Autonomous Cycle Routing (`brain_cycle_route`, `brain_cycle_next`)**:
   - Trivial tasks execute directly (0 overhead).
   - Complex features activate the 4-stage pipeline: GPT 5.6 $\leftrightarrow$ Gemini 3.7 Planning Debate $\rightarrow$ Builders Heavy Lifting $\rightarrow$ Gemini 3.7 Final Review $\rightarrow$ GPT 5.6 Sign-off.

2. **Upstream Specs & Phases (`specs/*.md`)** *(Traycer pattern)*:
   - Spec-first development: architectural intent, constraints, and phased milestones.

3. **Git-Backed Kanban Tasks (`tasks/*.md`)** *(agtx pattern)*:
   - Pipeline: `backlog` $\rightarrow$ `planning` $\rightarrow$ `running` $\rightarrow$ `review` $\rightarrow$ `done`.

4. **Coordination & Concurrency (`sessions/*.md`)**:
   - Agent presence, file leases/locks, git branch/worktree tracking, and structured handoffs.

5. **Knowledge & Claims (`claims/*.md`)**:
   - Long-term facts, rules, and architecture decisions with truth lifecycle (`active` $\rightarrow$ `superseded` / `expired` / `disputed`).
   - Fast Search: Indexed via **SQLite FTS5** with BM25 relevance ranking.

6. **L0 Auto-Injection (`meta/l0_pointers.md`)**:
   - Auto-injected context pointers (budget-enforced $\le 2.2$KB).

Vault: D:\projects\second-brain
