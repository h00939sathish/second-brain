# Event Model & Append-Only Log Specification

**Document Version:** 1.0.0  
**Authority:** Local Agent Control Plane  
**Governing Invariant:** INV-005 (Canonical Append-Only Event Logging)

---

## 1. Architectural Role

The event stream is the **canonical timeline and source of truth** for the Local Agent Control Plane. 

* **The Event Log is History:** It records immutable facts about what was proposed, authorized, observed, and recorded.
* **Markdown Files are Projections:** Files in `tasks/`, `claims/`, and `sessions/` are convenient, human-readable materialized views projected from the event stream. If a markdown file is corrupted or desynchronized, it can be recomputed deterministically from the event stream.

---

## 2. Event Schema (v1)

Every event is serialized as a single-line JSON object within `workspaces/<workspace>/events/YYYY-MM-DD.jsonl`:

```json
{
  "event_id": "evt_20260922_000184",
  "sequence": 184,
  "timestamp": "2026-09-22T14:02:15.102Z",
  "workspace": "jarvis",
  "schema_version": 1,
  "stage": "AUTHORIZE",
  "actor": "control-plane",
  "event_type": "LEASE_GRANTED",
  "execution_id": "exec_9821_codex",
  "task_id": "task-104",
  "payload": {
    "agent": "codex",
    "files": ["src/auth/token.py"],
    "duration_minutes": 30,
    "expires_at": "2026-09-22T14:32:15Z"
  }
}
```

### Field Definitions

| Field | Type | Description |
|---|---|---|
| `event_id` | `str` | Unique, monotonically ascending identifier (`evt_<date>_<seq>`). |
| `sequence` | `int` | Monotonically increasing sequence integer per workspace. |
| `timestamp` | `str` | ISO 8601 UTC timestamp with millisecond precision. |
| `workspace` | `str` | Target workspace slug (`jarvis`, `titan`, `global`, etc.). |
| `schema_version`| `int` | Schema specification version (currently `1`). |
| `stage` | `enum` | Pipeline stage: `PROPOSE`, `AUTHORIZE`, `OBSERVE`, `RECORD`. |
| `actor` | `str` | Identity of initiator: `agent:<name>`, `control-plane`, `os`, `human`. |
| `event_type` | `str` | Formal typed event name (see Catalog below). |
| `execution_id` | `str` | Correlation ID tying proposals, authorizations, and observed runs. |
| `task_id` | `str` | Optional task correlation ID. |
| `payload` | `dict`| Event-specific payload schema. |

---

## 3. Standard Event Types Catalog

### A. Lifecycle & Task Events
* `TASK_PROPOSED`: Worker/JARVIS submits desired task creation.
* `TASK_CREATED`: Control plane validates parameters and creates task in `BACKLOG` or `READY`.
* `TASK_BLOCKED`: Dependency graph evaluation marks task blocked on antecedent edges.
* `TASK_UNBLOCKED`: Antecedents completed; task moved to `READY`.
* `TASK_DISPATCHED`: Worker process spawned with prompt and leases.
* `TASK_COMPLETION_PROPOSED`: Worker claims task complete and supplies evidence handle.
* `TASK_COMPLETED`: Evidence validated by ReviewGate; state moved to `DONE`.

### B. Concurrency & Lease Events
* `LEASE_REQUESTED`: Agent requests reservation of file paths.
* `LEASE_GRANTED`: Files verified uncontested; exclusive lease token issued.
* `LEASE_DENIED`: Target file conflict detected (`LeaseConflict`).
* `LEASE_RELEASED`: Orderly release of file leases at session close.
* `LEASE_EXPIRED`: Stale lease reclaimed by heartbeat or sweep.

### C. OS Observation Events
* `PROCESS_SPAWNED`: Subprocess started with PID, command line, and working directory.
* `PROCESS_TERMINATED`: Subprocess exited with measured exit code, duration, and output size.
* `TEST_OBSERVED`: Test harness run parsed; records passed/failed test counts and command exit code.
* `GIT_DIFF_OBSERVED`: Working tree diff scanned; records modified/added/deleted paths.

### D. Knowledge & Claims Events
* `CLAIM_PROPOSED`: Fact submitted with source file and initial evidence.
* `CLAIM_RECORDED`: Fact anchored to current Git commit hash and dependency list.
* `CLAIM_STALE_DETECTED`: Git changes touch claim dependencies; moved to `NEEDS_REVALIDATION`.
* `CLAIM_VERIFIED`: Fact re-tested against current HEAD; returned to `ACTIVE`.
* `CLAIM_SUPERSEDED`: Fact contradicted and linked to replacement claim ID.
* `CLAIM_DISPUTED`: Counter-evidence registered against claim.

---

## 4. Immutability & Event Writer Guarantees

1. **Strict Append-Only:** Events are opened with `O_APPEND`. Existing lines are never updated or rewritten.
2. **Synchronous Sequence Ordering:** The `EventWriter` serializes events under the vault's advisory lock (`.lock`), ensuring sequences are strictly gapless and monotonic.
3. **Write Precedence:** The event must be flushed and fsynced to disk **before** any materialized projection (e.g. updating `tasks/task-104.md`) is written.
4. **Crash Recovery:** If a crash occurs between the event append and the projection update, replaying the event log reconciles the materialized view.
