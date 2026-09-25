# -*- coding: utf-8 -*-
"""INV-003: A task with unresolved dependencies cannot execute."""

import unittest

import tests.harness as h
from brain import board, coordination, evidence
from brain.errors import CycleDetectedError, DependencyBlockedError


class TestInv003Dependencies(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv003")

    def test_task_created_with_unmet_dependencies_is_blocked(self):
        """INV-003.1: A task with pending dependencies is initialized in [blocked]."""
        task_a = board.create_task("Task A: Auth Engine", workspace=self.slug)
        task_b = board.create_task("Task B: API Integration", workspace=self.slug,
                                   depends_on=task_a["id"])
        self.assertEqual(task_b["status"], "blocked")
        self.assertEqual(task_b["depends_on"], [task_a["id"]])

        found = board.get_task(task_b["id"], workspace=self.slug)
        self.assertEqual(found[1]["fm"]["status"], "blocked")
        self.assertIn(f"Depends on: {task_a['id']}", found[1]["body"])

    def test_task_cannot_move_to_running_while_dependencies_unmet(self):
        """INV-003.2: Moving a blocked task to running is rejected with DependencyBlockedError."""
        task_a = board.create_task("Task A: Auth Engine", workspace=self.slug)
        task_b = board.create_task("Task B: API Integration", workspace=self.slug,
                                   depends_on=task_a["id"])

        with self.assertRaises(DependencyBlockedError) as ctx:
            board.move(task_b["id"], "running", workspace=self.slug, agent="opencode")
        self.assertIn(task_a["id"], str(ctx.exception))

    def test_cycle_detection_rejects_circular_dependencies(self):
        """INV-003.3: Graph cycle detection prevents circular dependencies."""
        task_a = board.create_task("Task A", workspace=self.slug)
        task_b = board.create_task("Task B", workspace=self.slug, depends_on=task_a["id"])

        # Attempting to make Task A depend on Task B forms A -> B -> A
        with self.assertRaises(CycleDetectedError):
            board.create_task("Task C", workspace=self.slug, depends_on=[task_b["id"], task_a["id"]])
            # Or direct cycle:
            board.check_cycle(task_id=task_a["id"], depends_on=[task_b["id"]], workspace=self.slug)

    def test_cascade_unblocking_when_prerequisite_reaches_done(self):
        """INV-003.4: Completing prerequisite task automatically transitions dependent task BLOCKED -> READY."""
        task_a = board.create_task("Task A: Auth Engine", workspace=self.slug, agent="opencode")
        task_b = board.create_task("Task B: API Integration", workspace=self.slug,
                                   depends_on=task_a["id"])
        self.assertEqual(task_b["status"], "blocked")

        # Advance Task A: running -> review -> done (with required evidence)
        board.move(task_a["id"], "running", workspace=self.slug, agent="opencode")
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=task_a["id"], files="src/auth.py")
        coordination.end(session["id"], summary="auth finished", workspace=self.slug,
                         test_status="pytest: 10 passed")
        evidence.record_receipt(
            task_id=task_a["id"],
            command="pytest tests/test_auth.py",
            exit_code=0,
            stdout="10 passed in 0.3s",
            workspace=self.slug,
            session_id=session["id"],
        )
        board.move(task_a["id"], "done", workspace=self.slug)

        # Verify Task B was automatically unblocked to READY
        updated_b = board.get_task(task_b["id"], workspace=self.slug)
        self.assertEqual(updated_b[1]["fm"]["status"], "ready")
        self.assertIn(f"Unblocked: all dependencies satisfied", updated_b[1]["body"])

        # Now Task B is permitted to enter running
        moved_b = board.move(task_b["id"], "running", workspace=self.slug, agent="claude")
        self.assertEqual(moved_b["status"], "running")

    def test_actionable_skips_blocked_tasks(self):
        """INV-003.5: actionable() only returns runnable cards, ignoring blocked cards."""
        task_a = board.create_task("Task A", workspace=self.slug, status="ready")
        task_b = board.create_task("Task B", workspace=self.slug, depends_on=task_a["id"])
        self.assertEqual(task_b["status"], "blocked")

        # actionable must choose task_a, not task_b
        next_step = board.actionable(workspace=self.slug)
        self.assertEqual(next_step["task_id"], task_a["id"])


if __name__ == "__main__":
    unittest.main()
