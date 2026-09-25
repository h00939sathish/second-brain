# Strategic Implementation Roadmap

**Document Version:** 1.0.0  
**Authority:** Local Agent Control Plane  
**Target:** Phased migration of `/mnt/shared/projects/second-brain`

---

## Phase 0: Constitutional Invariants & Baseline Harness
*Goal: Freeze the invariants, establish physical trust boundaries, and create an executable invariant test suite before refactoring runtime code.*

* **Deliverables:**
  * `docs/INVARIANTS.md`, `docs/TRUST_MODEL.md`, `docs/STATE_MACHINES.md`, `docs/EVENT_MODEL.md`.
  * Test suite in `tests/invariants/`:
    * `test_inv001_leases.py`
    * `test_inv002_completion.py`
    * `test_inv003_dependencies.py`
    * `test_inv004_claims.py`
    * `test_inv005_events.py`
    * `test_inv006_authority.py`
    * `test_inv007_state_machine.py`
  * CLI command: `brain verify-invariants`.
* **Acceptance Criteria:**
  * Tests run against mock and baseline engine; invariant failures produce clear, actionable diagnostic output.

---

## Phase 1: Git-Anchored Claim Provenance
*Goal: Eliminate passive knowledge decay by anchoring all claims to Git commit hashes and dependency files.*

* **Deliverables:**
  * Extend claim schema in `brain/const.py`:
    * Add `verified_commit`, `depends_on.files`, `depends_on.symbols`.
    * Add `needs_revalidation` to `STATUSES` and `WITHHELD_STATUSES`.
  * Update `brain/knowledge.py`:
    * Auto-populate `verified_commit` from current `git rev-parse HEAD`.
    * Add Git diff scanner in `sweep` / `verify` checking touched files since `verified_commit`.
    * Transition touched claims to `needs_revalidation`.
  * Update `brain recall` to withhold `needs_revalidation` by default.
* **Acceptance Criteria:**
  * Modifying a dependency file in Git immediately marks dependent claims as needing revalidation upon next sweep/query.

---

## Phase 2: Task DAG & Dependency Scheduler
*Goal: Transition from a flat Kanban board to a Directed Acyclic Graph scheduler capable of conflict-free parallel dispatch.*

* **Deliverables:**
  * Extend task schema in `brain/const.py`:
    * Add `depends_on` (list of prerequisite task IDs).
    * Add `blocked` and `ready` to `TASK_STATUSES`.
  * Update `brain/board.py`:
    * Graph cycle detection (Kahn’s algorithm / topological sort).
    * Automated transition: `BLOCKED` → `READY` when all prerequisites enter `DONE`.
    * Update `actionable()` to select only unblocked `READY` tasks.
  * Update `daemon.py` to support parallel dispatch of disjoint tasks.
* **Acceptance Criteria:**
  * A task cannot enter `RUNNING` while any prerequisite task is not `DONE`.
  * Two tasks with disjoint file leases and cleared dependencies can be dispatched concurrently.

---

## Phase 3: Trusted Append-Only Event Stream
*Goal: Establish the event log as the canonical historical source of truth.*

* **Deliverables:**
  * Create `brain/events.py`:
    * `EventWriter` with advisory lock and atomic sequence incrementation.
    * Output: `workspaces/<ws>/events/YYYY-MM-DD.jsonl`.
  * Hook `EventWriter` into all state transitions:
    * Tasks, Leases, Claims, Dispatches.
  * Add event query endpoints in `http.py` and `cli.py` (`brain events`).
* **Acceptance Criteria:**
  * Every authorization and state change writes a valid schema v1 JSON record.

---

## Phase 4: Machine Evidence & Verification Model
*Goal: Guarantee that tasks can only be completed by verified physical execution records rather than agent assertions.*

* **Deliverables:**
  * Create `brain/evidence.py`:
    * Validate execution records against test harness exit codes and working tree diffs.
  * Update `brain/dispatch.py`:
    * Write cryptographically hashed process receipts (PID, command, exit code, execution duration).
  * Update `brain/board.py`:
    * `move(task_id, "done")` checks physical execution receipt.
* **Acceptance Criteria:**
  * Fabricated `--test-status` strings without corresponding OS execution records are rejected with `UnverifiedEvidenceError`.

---

## Phase 5: Empirical Capability Telemetry
*Goal: Track observed worker performance in your actual repositories to provide evidence-based task routing.*

* **Deliverables:**
  * Create `brain/telemetry.py`:
    * Project empirical metrics from the event stream: first-pass test rate, rework count, review rejections, duration.
    * Domain-specific aggregation (`#python`, `#refactor`, `#shell`).
  * Add advisory ranking to `brain route`:
    * Output candidate agents ranked by empirical evidence with minimum sample size thresholds.
* **Acceptance Criteria:**
  * Routing outputs observed pass-rates from repository history rather than static heuristics.

---

## Phase 6: JARVIS Control Plane Substrate
*Goal: Interface JARVIS directly with the Control Plane as an untrusted high-level planner.*

* **Deliverables:**
  * High-level Goal Decomposition API endpoint (`POST /api/goals`).
  * Map JARVIS intent graphs directly to Task DAGs.
  * Enforce all execution boundaries across all dispatched sub-workers.
* **Acceptance Criteria:**
  * JARVIS operates multiple workers safely without direct shell access or uncoordinated writes.
