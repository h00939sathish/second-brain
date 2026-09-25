# -*- coding: utf-8 -*-
"""Tests for empirical capability telemetry and evidence-based task routing (Phase 5)."""

import unittest

import tests.harness as h
from brain import board, coordination, evidence, telemetry


class TestTelemetry(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("telemetry")

    def test_empty_telemetry_returns_defaults(self):
        """Telemetry projection handles zero-state gracefully."""
        stats = telemetry.compute_telemetry(workspace=self.slug)
        self.assertIsInstance(stats, dict)

    def test_observed_runs_and_pass_rates_project_accurately(self):
        """Empirical runs, completions, and pass rates are calculated from receipts."""
        # Create Task 1 for opencode (python refactor)
        t1 = board.create_task("Refactor auth module", workspace=self.slug, agent="opencode")
        s1 = coordination.start(agent="opencode", workspace=self.slug, task_id=t1["id"], files="auth.py")

        # Opencode runs 2 tests: first fails, second passes (rework!)
        evidence.record_receipt(task_id=t1["id"], command="pytest tests/", exit_code=1,
                                duration_ms=500, workspace=self.slug)
        evidence.record_receipt(task_id=t1["id"], command="pytest tests/", exit_code=0,
                                duration_ms=400, workspace=self.slug)
        coordination.end(s1["id"], summary="fixed auth", test_status="pytest passed",
                         workspace=self.slug)
        board.move(t1["id"], "done", workspace=self.slug)

        # Create Task 2 for opencode (python test) - passes first try
        t2 = board.create_task("Write unit tests", workspace=self.slug, agent="opencode")
        s2 = coordination.start(agent="opencode", workspace=self.slug, task_id=t2["id"], files="test_auth.py")
        evidence.record_receipt(task_id=t2["id"], command="pytest tests/", exit_code=0,
                                duration_ms=300, workspace=self.slug)
        coordination.end(s2["id"], summary="added tests", test_status="pytest passed",
                         workspace=self.slug)
        board.move(t2["id"], "done", workspace=self.slug)

        # Create Task 3 for claude (fails tests, not done)
        t3 = board.create_task("Refactor database query", workspace=self.slug, agent="claude")
        s3 = coordination.start(agent="claude", workspace=self.slug, task_id=t3["id"], files="db.py")
        evidence.record_receipt(task_id=t3["id"], command="pytest tests/test_db.py", exit_code=1,
                                duration_ms=600, workspace=self.slug)

        # Compute telemetry
        stats = telemetry.compute_telemetry(workspace=self.slug)
        self.assertIn("opencode", stats)
        self.assertIn("claude", stats)

        oc = stats["opencode"]
        self.assertEqual(oc["tasks_assigned"], 2)
        self.assertEqual(oc["tasks_completed"], 2)
        self.assertEqual(oc["runs_total"], 3)
        self.assertEqual(oc["runs_passed"], 2)
        self.assertEqual(oc["runs_failed"], 1)
        self.assertEqual(oc["rework_count"], 1)
        self.assertAlmostEqual(oc["first_pass_rate"], 0.67, places=2)
        self.assertEqual(oc["avg_duration_ms"], 400)
        self.assertIn("python", oc["domains"])

        cl = stats["claude"]
        self.assertEqual(cl["tasks_assigned"], 1)
        self.assertEqual(cl["tasks_completed"], 0)
        self.assertEqual(cl["runs_total"], 1)
        self.assertEqual(cl["runs_passed"], 0)
        self.assertEqual(cl["runs_failed"], 1)
        self.assertEqual(cl["first_pass_rate"], 0.0)

    def test_rank_agents_prioritizes_empirical_evidence(self):
        """Agent ranking elevates high pass-rate workers in relevant technical domains."""
        # Setup history: opencode has high success in python
        t1 = board.create_task("Python optimization", workspace=self.slug, agent="opencode")
        s1 = coordination.start(agent="opencode", workspace=self.slug, task_id=t1["id"])
        evidence.record_receipt(task_id=t1["id"], command="pytest", exit_code=0, workspace=self.slug)
        coordination.end(s1["id"], summary="done", test_status="pass", workspace=self.slug)
        board.move(t1["id"], "done", workspace=self.slug)

        # Setup history: claude has failing runs
        t2 = board.create_task("Python refactoring", workspace=self.slug, agent="claude")
        s2 = coordination.start(agent="claude", workspace=self.slug, task_id=t2["id"])
        evidence.record_receipt(task_id=t2["id"], command="pytest", exit_code=1, workspace=self.slug)

        rankings = telemetry.rank_agents(prompt="Refactor python script", files=["main.py"],
                                         workspace=self.slug)
        self.assertTrue(len(rankings) >= 2)
        self.assertEqual(rankings[0]["agent"], "opencode")
        self.assertTrue(rankings[0]["has_data"])
        self.assertEqual(rankings[0]["first_pass_rate"], 1.0)
        self.assertIn("python", rankings[0]["domains"])

    def test_board_route_incorporates_empirical_recommendations(self):
        """board.route includes evidence-backed recommendations in pipeline plan."""
        # Add empirical data
        t1 = board.create_task("Implement database schema", workspace=self.slug, agent="opencode")
        s1 = coordination.start(agent="opencode", workspace=self.slug, task_id=t1["id"])
        evidence.record_receipt(task_id=t1["id"], command="pytest", exit_code=0, workspace=self.slug)
        coordination.end(s1["id"], summary="done", test_status="pass", workspace=self.slug)
        board.move(t1["id"], "done", workspace=self.slug)

        result = board.route("codex", "Implement complex migration database schema pipeline",
                             workspace=self.slug)
        self.assertEqual(result["action"], "pipeline")
        self.assertIn("recommendations", result)
        self.assertTrue(len(result["recommendations"]) > 0)
        self.assertIn("Empirical Worker Recommendations", result["brief"])
        self.assertIn("opencode", result["brief"])


if __name__ == "__main__":
    unittest.main()
