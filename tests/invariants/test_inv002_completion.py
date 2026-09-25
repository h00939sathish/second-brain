# -*- coding: utf-8 -*-
"""INV-002: A task cannot transition to DONE without machine-verified evidence."""

import os
import unittest
from pathlib import Path

import tests.harness as h
from brain import board, coordination, events, evidence, vcs, workspaces as ws_mod
from brain.errors import ReviewGate, UnverifiedEvidenceError
from brain.paths import VAULT


class TestInv002Completion(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv002")
        self.task = board.create_task("Refactor authentication", workspace=self.slug,
                                      agent="opencode", status="running")

    def test_completion_without_evidence_is_rejected(self):
        """INV-002.1: Transitioning to DONE without any evidence is blocked by ReviewGate."""
        with self.assertRaises(ReviewGate):
            board.move(self.task["id"], "done", workspace=self.slug)

    def test_fabricated_test_string_without_os_receipt_is_rejected(self):
        """INV-002.2: An agent asserting test results without OS process receipts is rejected."""
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=self.task["id"], files="src/auth.py")
        coordination.end(session["id"], summary="I think I finished the code",
                         workspace=self.slug, test_status="pytest: 42 passed in 0.1s")

        with self.assertRaises(UnverifiedEvidenceError) as ctx:
            board.move(self.task["id"], "done", workspace=self.slug)
        self.assertIn("without OS execution receipt", str(ctx.exception))

    def test_execution_record_with_nonzero_exit_code_is_rejected(self):
        """INV-002.3: Execution receipt showing non-zero test exit code is rejected."""
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=self.task["id"], files="src/auth.py")
        coordination.end(session["id"], summary="ran tests but failed",
                         workspace=self.slug, test_status="pytest: 1 failed")

        evidence.record_receipt(
            task_id=self.task["id"],
            command="pytest tests/test_auth.py",
            exit_code=1,
            stderr="AssertionError: 401 != 200",
            workspace=self.slug,
            session_id=session["id"],
        )

        with self.assertRaises(UnverifiedEvidenceError) as ctx:
            board.move(self.task["id"], "done", workspace=self.slug)
        self.assertIn("failed with exit code 1", str(ctx.exception))

    def test_working_tree_outside_lease_is_rejected(self):
        """INV-002.4: Uncommitted modifications outside declared session leases block completion."""
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=self.task["id"], files="src/auth.py")
        coordination.end(session["id"], summary="finished",
                         workspace=self.slug, test_status="pytest: 14 passed")

        evidence.record_receipt(
            task_id=self.task["id"],
            command="pytest tests/test_auth.py",
            exit_code=0,
            stdout="14 passed",
            workspace=self.slug,
            session_id=session["id"],
        )

        # Create uncommitted dirty file outside leased files in git repository
        repo_dir = Path(ws_mod.entry(self.slug).get("path") or str(VAULT))
        if not vcs.is_repo(repo_dir):
            vcs._git(["init"], cwd=repo_dir)
            vcs._git(["config", "user.name", "test"], cwd=repo_dir)
            vcs._git(["config", "user.email", "test@example.com"], cwd=repo_dir)
            vcs._git(["commit", "--allow-empty", "-m", "init", "--no-verify"], cwd=repo_dir)

        unleased_file = repo_dir / "unleased_rogue_file.py"
        unleased_file.write_text("print('unauthorized write')", encoding="utf-8")

        try:
            with self.assertRaises(UnverifiedEvidenceError) as ctx:
                board.move(self.task["id"], "done", workspace=self.slug)
            self.assertIn("working tree contains changes outside session lease", str(ctx.exception))
        finally:
            if unleased_file.exists():
                unleased_file.unlink()

    def test_machine_verified_execution_record_permits_done(self):
        """INV-002.5: Machine-verified execution record with exit code 0 permits DONE transition."""
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=self.task["id"], files="src/auth.py")
        coordination.end(session["id"], summary="tests passed cleanly",
                         workspace=self.slug, test_status="pytest: 14 passed")

        receipt = evidence.record_receipt(
            task_id=self.task["id"],
            command="pytest tests/test_auth.py",
            exit_code=0,
            stdout="14 passed in 0.42s",
            duration_ms=420,
            workspace=self.slug,
            session_id=session["id"],
        )
        self.assertEqual(receipt["exit_code"], 0)

        result = board.move(self.task["id"], "done", workspace=self.slug)
        self.assertEqual(result["status"], "done")
        self.assertTrue(result["changed"])

        # Check that event was emitted
        completed_events = events.read_events(workspace=self.slug, event_type="TASK_COMPLETED",
                                              task_id=self.task["id"])
        self.assertEqual(len(completed_events), 1)


if __name__ == "__main__":
    unittest.main()
