# Second Brain — Multi-Agent Coordination & Execution Hub (v5.0)

A unified platform combining a **shared memory truth store**, **Traycer-style upstream specs**, **agtx-style Kanban orchestration**, and a **Real-Time Mission Control Web Dashboard** with an autonomous division of labor across all coding agents.

---

## 🚀 Mission Control Web Dashboard

The web dashboard provides real-time observability over all active agents, running tasks, token consumption, and knowledge graphs:

```bash
# Option 1: Run Full-Stack (Backend API + Frontend UI)
python server.py
# Open: http://localhost:8000

# Option 2: Run Vite Frontend Dev Server with API Proxy
npm install
npm run dev
# Open: http://localhost:3000
```

### Dashboard Features:
1. **Interactive Kanban Board:** Live 5-column board (`backlog` $\rightarrow$ `planning` $\rightarrow$ `running` $\rightarrow$ `review` $\rightarrow$ `done`) synced with `tasks/*.md`.
2. **Token & Telemetry Analytics:** Real-time token consumption breakdown, cost calculator, and model latency charts.
3. **Live Terminal & Log Stream:** Real-time stdout/stderr streaming from active agent processes.
4. **Knowledge Graph & Specs Navigator:** Visual map linking upstream architecture specs, Kanban tasks, and persistent claims.
5. **Concurrency & File Locks Monitor:** Live view of active agent sessions, file reservations, and handoffs.

---

## 🤖 Autonomous Superpower Roles

- **Lead Architect & Arbiter:** **GPT 5.6 (Codex)** — High-density logic, constraints, invariant specification, final sign-off.
- **Context Analyst & Final Reviewer:** **Gemini 3.7 Flash (Antigravity)** — Ingests full 1M+ token repo context to critique specs during planning; audits complete git diffs and runs test suites during review.
- **Core Builders (Heavy Lifters):** **opencode & Claude Code** — Executes mechanical file edits, refactoring, package installs, and local test runs.
- **Invariant:** Neither Codex nor AGY performs repetitive heavy lifting; heavy code generation is offloaded to Builders.

---

## ⚙️ Core Architecture & CLI

1. **Autonomous Daemon (`engine.py daemon`)**:
   - Continuously watches the board and auto-chains tasks hands-free:
     $$\text{Task in } [\text{planning}] \xrightarrow{\text{auto}} \textbf{Codex} \xrightarrow{\text{moves to } [\text{running}]} \textbf{opencode} \xrightarrow{\text{moves to } [\text{review}]} \textbf{Antigravity} \xrightarrow{} [\text{done}]$$

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

---

## 📡 REST API Endpoints (`server.py`)

- `GET /api/status`: Vault health, active task count, L0 byte budget.
- `GET /api/tasks`: List all Kanban tasks with agent assignments.
- `POST /api/tasks`: Create a new task.
- `POST /api/tasks/:id/move`: Advance task status.
- `GET /api/specs`: List all upstream architecture specs.
- `GET /api/claims`: List all permanent knowledge claims.
- `GET /api/graph`: Graph nodes & edge connections for visual rendering.
- `GET /api/leases`: Live file reservation leases.
- `GET /api/handoffs`: Audit trail of cross-agent task handoffs.
- `GET /api/context`: Shared ephemeral bulletin notes.
- `GET /api/logs`: Real-time agent execution log entries.
- `POST /api/dispatch`: Directly trigger an agent for a specific task.
- `POST /api/auto-cycle`: Auto-dispatch the highest-priority actionable task.
