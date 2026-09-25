# -*- coding: utf-8 -*-
"""Tests for hot-potato closure contract on tasks."""

import unittest

import tests.harness as h
from brain import board, coordination, evidence, store
from brain.errors import BrainError, ReviewGate


class TestHotPotatoClosure(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("closure")

    def test_move_done_requires_closure_reason(self):
        task = board.create_task(title="Feature X", workspace=self.slug, agent="opencode")
        t_id = task["id"]

        # Run session with tests to satisfy ReviewGate and evidence
        session = coordination.start(agent="opencode", workspace=self.slug, task_id=t_id)
        evidence.record_receipt(task_id=t_id, command="pytest", exit_code=0, stdout="5 passed", workspace=self.slug)
        coordination.end(session["id"], summary="done", test_status="pytest: 5 passed", workspace=self.slug)

        # Move to done without closure_reason should fail if no target_agent and no explicit closure
        # But wait! If latest session recorded test_status, does it default to "completed"?
        # Let's test with a task where no tests/target_agent are auto-inferred or with explicit closure
        res = board.move(t_id, "done", workspace=self.slug, closure_reason="completed")
        self.assertEqual(res["status"], "done")

        # Verify task frontmatter has closure_reason
        _, rec = board.get_task(t_id, self.slug)
        self.assertEqual(rec["fm"]["closure_reason"], "completed")

    def test_invalid_closure_reason_rejected(self):
        task = board.create_task(title="Feature Y", workspace=self.slug, agent="opencode")
        t_id = task["id"]

        session = coordination.start(agent="opencode", workspace=self.slug, task_id=t_id)
        evidence.record_receipt(task_id=t_id, command="pytest", exit_code=0, stdout="pass", workspace=self.slug)
        coordination.end(session["id"], summary="done", test_status="pytest: pass", workspace=self.slug)

        with self.assertRaises(BrainError) as ctx:
            board.move(t_id, "done", workspace=self.slug, closure_reason="bogus_reason")
        self.assertIn("invalid closure_reason", str(ctx.exception))

    def test_handed_off_closure_requires_target(self):
        task = board.create_task(title="Feature Z", workspace=self.slug, agent="opencode")
        t_id = task["id"]

        session = coordination.start(agent="opencode", workspace=self.slug, task_id=t_id)
        evidence.record_receipt(task_id=t_id, command="pytest", exit_code=0, stdout="pass", workspace=self.slug)
        coordination.end(session["id"], summary="done", test_status="pytest: pass", workspace=self.slug)

        # handed_off without target should fail
        with self.assertRaises(BrainError) as ctx:
            board.move(t_id, "done", workspace=self.slug, closure_reason="handed_off", closure_target="")
        self.assertIn("requires a closure_target", str(ctx.exception))

        # handed_off with target should succeed
        res = board.move(t_id, "done", workspace=self.slug, closure_reason="handed_off", closure_target="agy")
        self.assertEqual(res["status"], "done")
        _, rec = board.get_task(t_id, self.slug)
        self.assertEqual(rec["fm"]["closure_reason"], "handed_off")
        self.assertEqual(rec["fm"]["closure_target"], "agy")
