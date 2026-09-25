# Control Plane Architecture & Codebase Audit

**Target Architecture:** Local Agent Control Plane  
**Target Repository:** `/mnt/shared/projects/second-brain`  
**Audit Date:** 2026-09-22  
**Baseline Test Suite Status:** 141 tests passing (100% pass rate)

---

## Executive Summary

The existing `/mnt/shared/projects/second-brain` codebase is not a generic "AI memory/RAG" wrapper; it is already a functioning prototype of a local coordination system for autonomous coding workers. It possesses strong physical foundations—including atomic file writes, advisory locking, file leasing (`check_files`), a review gate, multi-workspace directory routing, and multi-CLI process dispatch.

However, its enforcement currently relies on a hybrid of **deterministic runtime checks** and **agent-reported assertions** (e.g., self-reported test strings). To elevate this codebase into a hardened **Local Agent Control Plane**, the system must transition from a Kanban-and-notes vault into an invariant-governed execution runtime centered on:
1. **Propose-Authorize-Observe-Record** control loops
2. **Git-anchored temporal knowledge validation**
3. **DAG-based task scheduling**
4. **Machine-observed execution evidence**
5. **An append-only event stream as the historical backbone**

---

## 1. Existing Architecture Mapping

The repository comprises ~250KB of clean, dependency-free Python (stdlib only) structured into modular components:

| Module | Lines | Current Responsibility | Classification |
|---|---|---|---|
| `brain/paths.py` | 249 | Vault resolution, atomic writes (`atomic_write` temp+rename), advisory lock (`.lock`). | **KEEP** |
| `brain/frontmatter.py` | 196 | Escaped YAML-like frontmatter serialization with round-trip proof (`dumps(parse(t)) == t`). | **KEEP** |
| `brain/const.py` | 156 | Global constants, static CLI tables, agent roles, regex keywords, and record schema schemas. | **MODIFY** |
| `brain/errors.py` | 41 | Typed exceptions (`BrainError`, `SchemaError`, `NotFound`, `LeaseConflict`, `ReviewGate`, `AgentUnavailable`). | **MODIFY** |
| `brain/store.py` | 387 | Low-level file CRUD, ID generation (`new_id`), schema validation, and active lease scanning. | **KEEP / WRAP** |
| `brain/workspaces.py` | 488 | Directory-to-workspace auto-resolver, `.brain-workspace` markers, read scoping, aliases. | **KEEP** |
| `brain/coordination.py` | 376 | Sessions (`start`, `update`, `reserve`, `end`), file leasing, write guarding (`guard`), context scratchpad. | **MODIFY** |
| `brain/board.py` | 347 | Kanban task cards, specs with phases, linear `move` transitions, `ReviewGate`, keyword routing. | **MODIFY** |
| `brain/knowledge.py` | 415 | Claims CRUD (`add`, `review`, `supersede`, `dispute`), FTS5 recall (`recall`), deduplication. | **MODIFY** |
| `brain/index.py` | 280 | SQLite FTS5 full-text search index, BM25 ranking, incremental stat-walk synchronizer. | **KEEP** |
| `brain/vcs.py` | 83 | Scoped Git operations (explicit path staging, commits, branch checking). | **KEEP / EXTEND** |
| `brain/agents.py` | 748 | CLI discovery (`shutil.which`), environment sanitization, agent config installer (MCP & skills). | **KEEP** |
| `brain/dispatch.py` | 273 | Process spawning, stdin prompt streaming, logging (`.run.json`, `.prompt.txt`, `.log`). | **MODIFY** |
| `brain/daemon.py` | 215 | Background scheduling loop, auto-cycle, circuit breaker (3-strike failure cutoff). | **MODIFY** |
| `brain/l0.py` | 245 | Compact prompt brief generator (<= 2,200 bytes budget). | **KEEP** |
| `brain/maintenance.py`| 104 | `brain sweep`: stale session closer, note archiver, index sync. | **MODIFY** |
| `brain/http.py` | 556 | Mission Control REST API on `:8000`. | **WRAP** |
| `brain/cli.py` | 1184 | Argparse CLI entry point exposing all engine commands. | **MODIFY** |
| `mcp/brain_mcp.py` | 540 | 30 MCP tool definitions directly delegating to `brain.cli`. | **WRAP** |

---

## 2. Existing Enforcement Mechanisms

### A. Concurrency & File Isolation (`LeaseConflict`)
* **How it works:** When an agent runs `brain start --files a.py` or `brain reserve <sess> --files b.py`, `store.check_files()` scans all active sessions in the target workspace. If any active session's frontmatter lists those files, a `LeaseConflict` exception is raised with the holder's agent name.
* **Write Interception:** `brain guard` acts as a pre-tool hook for agent harnesses (e.g. Claude Code PreToolUse). It verifies if the calling agent holds an active session clearing the touched paths.
* **Gaps:** 
  1. Guard rails can be bypassed via `force=True` or `BRAIN_BYPASS=1`.
  2. Leases are implicitly tied to sessions rather than being distinct, first-class tokens with discrete lease IDs and cryptographic or session bounds.

### B. Verification Gate (`ReviewGate`)
* **How it works:** In `board.move(task_id, "done")`, the engine executes `review_evidence(task_id)`. It scans finished sessions associated with `task_id` for:
  1. A `test_status` field (e.g., `"pytest: 12 passed"`), OR
  2. A handoff to a designated reviewer agent role (e.g., `agy`, `antigravity`, `gemini`).
  If neither exists, the move to `done` is blocked with HTTP 409 / exit code 1.
* **Gaps:**
  1. **Self-Reported Evidence:** The `test_status` string is currently supplied by the agent itself (`brain end --test-status "..."`). An untrusted agent can report `"pytest: 100% pass"` without running any test command.
  2. No verification that modified files match the repository working tree diff.

### C. Advisory Locking & Atomic Writes
* **How it works:** Mutating commands acquire an advisory lock via `paths.lock()` (`.lock` file in the vault). Writes execute via `atomic_write()` (writing to a temporary file on the same filesystem and executing an atomic POSIX rename).
* **Assessment:** **Solid.** Prevents corrupt or partial state during concurrent CLI invocations.

---

## 3. Existing State Machines

### A. Task FSM
* **Defined States (`const.TASK_STATUSES`):** `("backlog", "planning", "running", "review", "done")`.
* **Current Transition Logic:** Linear and permissive. An agent can jump from `backlog` directly to `done` (provided `ReviewGate` passes).
* **Deficiency:** No `blocked` or `ready` states. No modeling of prerequisite dependencies.

### B. Claim FSM
* **Defined States (`const.STATUSES`):** `("active", "superseded", "expired", "disputed")`.
* **Current Transition Logic:** Transitions are manual via CLI commands (`supersede`, `dispute`) or time-based via `sweep` (claims older than 90 days are flagged stale).
* **Deficiency:** Completely disconnected from Git. A claim verified at commit `A` remains `active` even after commit `B` completely deletes or rewrites the underlying implementation files.

### C. Session FSM
* **Defined States:** `active` -> `ended` (or auto-closed as `stale` by `sweep` after 24h).
* **Deficiency:** Does not represent the four discrete lease states: `REQUESTED`, `ACTIVE`, `RELEASED`, `EXPIRED`.

---

## 4. Invariant Coverage Audit

Evaluating the current implementation against the target constitutional invariants:

| Invariant | Description | Current Status | Current Enforcement | Gaps to Close |
|---|---|---|---|---|
| **INV-001** | File modification requires active, uncontested lease. | **Strong** | `store.check_files()`, `brain guard` | Enforce lease tokens; eliminate unmonitored bypass paths. |
| **INV-002** | Task cannot become `DONE` without machine-verified evidence. | **Weak** | `board.review_evidence()` | Replace self-reported test strings with OS process execution receipts. |
| **INV-003** | Task with unresolved dependencies cannot execute. | **Zero** | None | Add `depends_on` task edges; build DAG validation in scheduler. |
| **INV-004** | Stale/unverified claims cannot be injected as ground truth. | **Weak** | `const.WITHHELD_STATUSES` in recall | Add `NEEDS_REVALIDATION` status triggered by Git diff changes against source files. |
| **INV-005** | Every state transition & authorization produces an append-only event. | **Zero** | None (fragmented `.run.json` and body text) | Build trusted `EventWriter` producing `events/YYYY-MM-DD.jsonl`. |
| **INV-006** | Agent output cannot directly mutate authoritative state. | **Partial** | Frontmatter parser schema validation | Enforce strict Propose-Authorize separation on all write endpoints. |
| **INV-007** | State transitions are validated by runtime FSMs. | **Partial** | `status in TASK_STATUSES` check | Implement explicit transition matrices rejecting illegal state jumps. |

---

## 5. Existing Tests & Verification Baseline

* **Test Framework:** Standard library `unittest`.
* **Execution:** `python3 -m unittest discover -s tests -t .`
* **Test Suites:**
  * `tests/test_agents.py` (CLI detection, env sanitization, setup)
  * `tests/test_board.py` (Tasks, specs, review gate, actionable routing)
  * `tests/test_coordination.py` (Sessions, lease conflicts, guard, notes)
  * `tests/test_dispatch.py` (Background process spawning, run records)
  * `tests/test_frontmatter.py` (Round-trip escaping, parser fuzzing)
  * `tests/test_knowledge.py` (Claims, supersede, dispute, FTS recall)
  * `tests/test_maintenance.py` (Sweep, stale session reaping, note archival)
  * `tests/test_scoping.py` (Workspace boundary isolation, global visibility)
  * `tests/test_workspaces.py` (Workspace registration, aliases, binding)
* **Results:** **141 passed in 2.48 seconds.**
* **Test Isolation Harness:** `tests/harness.py` creates a temporary, throwaway directory tree with full vault structure for every test case. This harness is exceptionally well-built and will be reused to build invariant test suites.

---

## 6. Gaps Against Target Architecture

```
[Target Control Plane Architecture]       [Current Implementation Baseline]
┌─────────────────────────────────┐       ┌─────────────────────────────────┐
│ Trusted Event Stream (Backbone) │ ◄──── │ MISSING: Fragmented run.json    │
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ Git-Aware Claim Lifecycle (FSM) │ ◄──── │ PARTIAL: Time-based only        │
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ Task DAG Scheduler              │ ◄──── │ MISSING: Flat Kanban board      │
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ Machine-Verified Evidence Engine│ ◄──── │ WEAK: Self-reported test strings│
├─────────────────────────────────┤       ├─────────────────────────────────┤
│ Empirical Capability Telemetry  │ ◄──── │ MISSING: Keyword regex routing  │
└─────────────────────────────────┘       └─────────────────────────────────┘
```

---

## 7. Component Classification

### A. KEEP (Preserve Intact)
* `brain/paths.py`: Atomic write semantics and advisory locking are battle-tested.
* `brain/frontmatter.py`: Guaranteed round-trip escaping must not be touched.
* `brain/workspaces.py`: CWD resolution and multi-project scoping work seamlessly.
* `brain/index.py`: Incremental FTS5 SQLite indexer is fast, deterministic, and dependency-free.
* `tests/harness.py`: Isolated throwaway vault test harness.

### B. MODIFY (Refactor & Extend)
* `brain/const.py`:
  * Add `NEEDS_REVALIDATION` to `STATUSES` and `WITHHELD_STATUSES`.
  * Add `blocked` and `ready` to `TASK_STATUSES`.
  * Add `verified_commit` and `depends_on` to `CLAIM_FM_ORDER`.
  * Add `depends_on` and `blocked_by` to `TASK_FM_ORDER`.
  * Define canonical event schemas and schema versions.
* `brain/errors.py`:
  * Add `DependencyBlockedError`, `InvalidStateTransition`, `UnverifiedEvidenceError`, `StaleKnowledgeError`.
* `brain/knowledge.py`:
  * Support `verified_commit` and file dependencies upon creation.
  * Integrate Git diff scanner to transition `active` -> `needs_revalidation`.
* `brain/board.py`:
  * Add dependency resolution logic to `actionable()`.
  * Formalize Task FSM state validation in `move()`.
* `brain/coordination.py`:
  * Formalize lease issuance into structured lease records.
* `brain/dispatch.py`:
  * Capture actual OS process execution records (PID, exit code, execution duration, command hash) for use by Evidence Engine.

### C. NEW MODULES TO CREATE
* `brain/events.py`: Trusted Event Writer managing append-only `events/YYYY-MM-DD.jsonl` with schema versioning.
* `brain/evidence.py`: Verifier for execution receipts, test runs, and Git working tree clean status.
* `tests/invariants/`: Executable invariant validation test suite (`test_inv001_leases.py` through `test_inv007_state_machine.py`).

---

## 8. Proposed Migration Sequence

```
Phase 0: Constitutional Invariants & Baseline Harness
  ├── Create docs/INVARIANTS.md
  ├── Build tests/invariants/ testing harness
  └── Implement `brain verify-invariants` CLI command

Phase 1: Git-Anchored Claim Provenance
  ├── Extend claim schema (verified_commit, depends_on.files)
  ├── Implement git diff scanner in brain/knowledge.py & maintenance.py
  └── Implement 3-state Claim FSM (ACTIVE -> NEEDS_REVALIDATION -> SUPERSEDED)

Phase 2: Task DAG & Dependency Scheduler
  ├── Extend task schema with `depends_on` list
  ├── Add topological DAG cycle detection and dependency resolution in brain/board.py
  └── Update `brain actionable` / `auto-cycle` to discover runnable DAG nodes

Phase 3: Trusted Append-Only Event Stream
  ├── Create brain/events.py (EventWriter, sequence counter, schema v1)
  ├── Hook EventWriter into state transitions across board, leases, and claims
  └── Keep Markdown files as materialized projections of event history

Phase 4: Machine Evidence & Verification Model
  ├── Create brain/evidence.py
  ├── Upgrade dispatch.py to write cryptographically hashed execution receipts
  └── Restrict `board.move(..., "done")` strictly to verified execution receipts

Phase 5: Advisory Capability Telemetry
  ├── Project empirical performance metrics from event stream
  └── Provide sample-bounded worker ranking for JARVIS task routing
```

---

## 9. Risk & Regression Analysis

| Risk | Impact | Mitigation Strategy |
|---|---|---|
| **Breaking Existing CLI/MCP Tool Surface** | High | Keep existing tool signatures and parameter defaults; treat new arguments (`depends_on`, `verified_commit`) as optional with sensible defaults. |
| **Git Diff Performance Overhead** | Medium | Cache `HEAD` commit ID in memory during operations; only scan Git diffs during explicit `sweep` or `verify` operations, never on read paths. |
| **Breaking Existing 141 Unit Tests** | High | Run full `python3 -m unittest` suite after every incremental module modification. No phase merges without 100% green tests. |
| **Unsynchronized Materialized Views** | Medium | Event stream writes precede Markdown file updates; in the event of partial failure, Markdown files can be re-projected from the event log. |
