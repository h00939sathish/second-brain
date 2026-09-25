# -*- coding: utf-8 -*-
"""Typed failures.

Every one of these is raised where a rule is *enforced* rather than printed, so a
protocol violation stops the work instead of scrolling past in a warning line.
`--force` (or BRAIN_BYPASS=1) is the documented break-glass path.
"""


class BrainError(Exception):
    """Base class for all brain failures."""


class SchemaError(BrainError):
    """A record does not satisfy its required schema."""


class NotFound(BrainError):
    """A referenced record does not exist."""


class LeaseConflict(BrainError):
    """Files are reserved by another live session."""

    def __init__(self, conflicts, holder=""):
        self.conflicts = list(conflicts)
        self.holder = holder
        detail = ", ".join(self.conflicts)
        super().__init__(
            f"{len(self.conflicts)} file(s) reserved by another live session: {detail}"
            + (f" (holder: {holder})" if holder else "")
        )


class ReviewGate(BrainError):
    """A task cannot reach `done` without verifiable review evidence."""


class UnverifiedEvidenceError(ReviewGate):
    """A task cannot reach `done` without machine-verified execution evidence (INV-002)."""


class AgentUnavailable(BrainError):
    """An agent CLI is not installed on this machine."""


class DependencyBlockedError(BrainError):
    """A task cannot execute because antecedent dependencies are not DONE."""

    def __init__(self, task_id, unmet):
        self.task_id = task_id
        self.unmet = list(unmet)
        detail = ", ".join(self.unmet)
        super().__init__(
            f"task {task_id} cannot execute: unresolved dependencies: {detail}"
        )


class CycleDetectedError(BrainError):
    """A cyclic dependency was detected in the task DAG."""


class DeliberationGate(BrainError):
    """A task requiring coordination cannot execute without a valid Deliberation Record (INV-008)."""

    def __init__(self, task_id: str, reason: str):
        self.task_id = task_id
        self.reason = reason
        super().__init__(f"deliberation required for task {task_id}: {reason}")


class TopologyError(BrainError):
    """Raised when an operation violates the declared agent topology graph."""

