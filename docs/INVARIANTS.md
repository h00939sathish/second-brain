# Constitutional Invariants

**Document Version:** 1.0.0  
**Authority:** Local Agent Control Plane  
**Scope:** Universal across all agents, workspaces, and execution modes.

---

## The Core Axiom

> **"No LLM should be trusted with authority that deterministic infrastructure can enforce."**  
> *The agent proposes; the runtime authorizes. The operating environment decides what actually happened.*

Every feature, state transition, and CLI command in the Local Agent Control Plane must satisfy and enforce the following seven constitutional invariants. Any proposal or write operation violating an invariant is rejected unconditionally.

---

## Invariant Catalog

### INV-001: Active Uncontested File Lease
> **An agent cannot modify a file without an active, uncontested lease.**

* **Statement:** Any file modification, write proposal, or code alteration must be covered by an unexpired lease held specifically by the executing agent.
* **Enforcement Point:**
  * `brain guard` write interceptor hook.
  * `brain start --files <paths>` / `brain reserve --files <paths>`.
  * POSIX filesystem permissions / advisory locks.
* **Failure Mode:** `LeaseConflict` (HTTP 409 / Non-zero exit).
* **Required Test Coverage (`tests/invariants/test_inv001_leases.py`):**
  1. Write without an active session → rejected.
  2. Write to a file not declared in session leases → rejected.
  3. Attempt to lease a file already leased by another live agent → `LeaseConflict`.
  4. Write with an expired lease → rejected.
  5. Write with an active, uncontested lease held by calling agent → permitted.

---

### INV-002: Machine-Verified Evidence for Completion
> **A task cannot transition to `DONE` without machine-verified evidence.**

* **Statement:** A task card cannot reach the terminal `DONE` state based on an agent's assertion or text declaration. The transition requires a machine-generated execution record containing verified process exit codes, test outputs, and Git diff verification.
* **Enforcement Point:**
  * `ReviewGate` in `board.move(task_id, "done")`.
  * `brain/evidence.py` verifier engine.
* **Failure Mode:** `UnverifiedEvidenceError` / `ReviewGate` rejection.
* **Required Test Coverage (`tests/invariants/test_inv002_completion.py`):**
  1. Agent claims completion without running tests → rejected.
  2. Agent provides fabricated test string without OS process receipt → rejected.
  3. Execution record shows test exit code != 0 → rejected.
  4. Working tree contains unstaged/untracked changes outside lease → rejected.
  5. Machine-verified execution record with exit code 0 + review receipt → transition permitted.

---

### INV-003: Dependency-Satisfied Execution (Task DAG)
> **A task with unresolved dependencies cannot execute.**

* **Statement:** A task card with antecedent dependency edges (`depends_on`) cannot enter `READY` or `RUNNING` until all prerequisite tasks have reached `DONE` with verified evidence.
* **Enforcement Point:**
  * `DAGScheduler` in `board.py`.
  * `dispatch.py` and `daemon.py` auto-cycle loops.
* **Failure Mode:** `DependencyBlockedError`.
* **Required Test Coverage (`tests/invariants/test_inv003_dependencies.py`):**
  1. Dispatching a task with uncompleted dependencies → rejected as `BLOCKED`.
  2. Cyclic dependencies in task graph → rejected upon creation/scheduling.
  3. Prerequisite task completes → dependent task automatically transitions `BLOCKED` → `READY`.
  4. Independent tasks with disjoint file leases → parallel dispatch permitted.

---

### INV-004: Temporal Knowledge Validity (Git Anchoring)
> **`NEEDS_REVALIDATION` claims cannot be injected as verified ground truth.**

* **Statement:** Claims are valid relative to a specific Git commit (`verified_commit`). When Git changes touch a claim's dependency files (`depends_on.files`), the claim automatically transitions to `NEEDS_REVALIDATION`. While in this state, it is withheld from default knowledge retrieval.
* **Enforcement Point:**
  * Git diff scanner in `knowledge.py` and `maintenance.py` (`brain sweep`).
  * `brain recall` query filter.
* **Failure Mode:** Withheld from prompt brief / flagged with `[STALE - RECHECK REQUIRED]`.
* **Required Test Coverage (`tests/invariants/test_inv004_claims.py`):**
  1. Claim created with current Git commit hash and dependency files.
  2. Git commit modifies dependent file → claim transitions `ACTIVE` → `NEEDS_REVALIDATION`.
  3. Default `brain recall` does not return `NEEDS_REVALIDATION` claims.
  4. `brain verify <claim-id>` against new `HEAD` → resets status to `ACTIVE`.
  5. Contradictory evidence provided → transitions to `SUPERSEDED`.

---

### INV-005: Canonical Append-Only Event Logging
> **Every externally observable state transition and authorization decision produces an append-only event.**

* **Statement:** The control plane records all proposals, authorization decisions, and observed OS facts into an immutable, append-only JSONL event stream (`events/YYYY-MM-DD.jsonl`). Agents cannot directly append or forge events; only the trusted runtime writes events.
* **Enforcement Point:**
  * `brain/events.py` `EventWriter`.
* **Failure Mode:** System write aborts if event serialization fails.
* **Required Test Coverage (`tests/invariants/test_inv005_events.py`):**
  1. State transition writes structured event with sequence number and timestamp.
  2. Lease acquisition writes `LEASE_GRANTED` event.
  3. Lease conflict writes `LEASE_DENIED` event.
  4. Direct agent attempt to forge an event in `events.jsonl` is blocked by permission boundary.
  5. Materialized state (markdown files) can be reconstructed from event history.

---

### INV-006: Untrusted Proposal Boundary
> **Agent output cannot directly mutate authoritative control-plane state.**

* **Statement:** Untrusted worker agents emit proposals (desired state). The control plane validates proposals against invariants, checks locks, and performs the authorized mutation on behalf of the agent.
* **Enforcement Point:**
  * API/CLI schema validation and parameter sanitization.
  * Prohibition of direct file writes into `.lock`, `meta/`, or task metadata by worker processes.
* **Failure Mode:** `SchemaError` / `UnauthorizedMutationError`.
* **Required Test Coverage (`tests/invariants/test_inv006_authority.py`):**
  1. Direct edits to task frontmatter by agent subshell bypass the control plane → flagged as invalid or rejected.
  2. Malformed parameters in agent proposals → rejected with structured validation errors.
  3. Authorization check precedes all mutations.

---

### INV-007: Validated State Machine Transitions
> **All state transitions are strictly validated against formal Finite State Machines.**

* **Statement:** No entity (Task, Claim, Lease) may skip states or execute illegal transitions. All state changes are deterministic and monotonic.
* **Enforcement Point:**
  * Task FSM, Claim FSM, Lease FSM in `board.py`, `knowledge.py`, `coordination.py`.
* **Failure Mode:** `InvalidStateTransitionError`.
* **Required Test Coverage (`tests/invariants/test_inv007_state_machine.py`):**
  1. Illegal Task transition (`backlog` → `done` without `review`) → rejected.
  2. Illegal Claim transition (`superseded` → `active`) → rejected.
  3. Illegal Lease transition (`released` → `active` without new request) → rejected.
  4. Valid linear and cyclic transitions adhere strictly to state graphs.

---

## Verification Tooling

The CLI command:
```bash
brain verify-invariants
```
executes the full `tests/invariants/` test suite and prints the constitutional compliance matrix:

```
INV-001 (File Leases)            [PASS]
INV-002 (Verified Evidence)       [PASS]
INV-003 (DAG Dependencies)        [PASS]
INV-004 (Temporal Knowledge)      [PASS]
INV-005 (Event Stream Logging)    [PASS]
INV-006 (Authority Boundary)      [PASS]
INV-007 (FSM Transitions)         [PASS]
----------------------------------------
7 / 7 Constitutional Invariants Verified
```
