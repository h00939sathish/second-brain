# -*- coding: utf-8 -*-
"""Tests for Phase 6: JARVIS Control Plane Substrate (Goal Proposals & Task DAG compilation)."""

import json
import unittest
from pathlib import Path

import tests.harness as h
from brain import board, events, goals, store, workspaces as ws_mod
from brain.errors import BrainError, CycleDetectedError, LeaseConflict
from brain.http import Handler


class MockWFile:
    def __init__(self):
        self.data = bytearray()

    def write(self, b):
        self.data.extend(b)


class MockRFile:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read(self, n):
        chunk = self.data[self.offset:self.offset + n]
        self.offset += len(chunk)
        return chunk


class TestGoals(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("goals")

    def test_validate_dag_acyclic(self):
        tasks = [
            {"key": "t1", "title": "Setup database"},
            {"key": "t2", "title": "Run migrations", "depends_on": ["t1"]},
            {"key": "t3", "title": "Deploy API", "depends_on": ["t2"]},
        ]
        # Should not raise
        goals.validate_goal_dag(tasks)

    def test_validate_dag_cycle_direct(self):
        tasks = [
            {"key": "t1", "title": "Task 1", "depends_on": ["t2"]},
            {"key": "t2", "title": "Task 2", "depends_on": ["t1"]},
        ]
        with self.assertRaises(CycleDetectedError) as ctx:
            goals.validate_goal_dag(tasks)
        self.assertIn("cycle detected", str(ctx.exception))

    def test_validate_dag_cycle_indirect(self):
        tasks = [
            {"key": "a", "title": "A", "depends_on": ["c"]},
            {"key": "b", "title": "B", "depends_on": ["a"]},
            {"key": "c", "title": "C", "depends_on": ["b"]},
        ]
        with self.assertRaises(CycleDetectedError) as ctx:
            goals.validate_goal_dag(tasks)
        self.assertIn("cycle detected", str(ctx.exception))

    def test_validate_dag_concurrent_lease_conflict(self):
        tasks = [
            {"key": "t1", "title": "Refactor auth", "files": ["src/auth.py"]},
            {"key": "t2", "title": "Add 2FA", "files": ["src/auth.py"]},
        ]
        # t1 and t2 do not depend on each other, but touch the same file -> conflict!
        with self.assertRaises(LeaseConflict) as ctx:
            goals.validate_goal_dag(tasks)
        self.assertIn("src/auth.py", str(ctx.exception))

    def test_validate_dag_sequenced_lease_overlap_allowed(self):
        tasks = [
            {"key": "t1", "title": "Refactor auth", "files": ["src/auth.py"]},
            {"key": "t2", "title": "Add 2FA", "files": ["src/auth.py"], "depends_on": ["t1"]},
        ]
        # t2 depends on t1, so they are not concurrent -> allowed
        goals.validate_goal_dag(tasks)

    def test_propose_goal_compiles_dag_and_emits_events(self):
        proposal = {
            "goal": "Build payment system",
            "spec": {
                "title": "Payment System Architecture",
                "description": "Stripe integration and webhooks",
            },
            "tasks": [
                {"key": "db", "title": "Create payment tables", "files": ["models/payment.py"]},
                {"key": "api", "title": "Create payment routes", "files": ["routes/payment.py"], "depends_on": ["db"]},
                {"key": "webhook", "title": "Handle webhooks", "depends_on": ["api"]},
            ],
            "workspace": self.slug,
            "actor": "agent:jarvis",
        }

        res = goals.propose_goal(
            goal=proposal["goal"],
            tasks=proposal["tasks"],
            spec=proposal["spec"],
            workspace=proposal["workspace"],
            actor=proposal["actor"],
        )

        self.assertTrue(res["ok"])
        self.assertTrue(res["spec_id"].startswith("spec-"))
        self.assertEqual(len(res["tasks"]), 3)

        db_task = next(t for t in res["tasks"] if t["key"] == "db")
        api_task = next(t for t in res["tasks"] if t["key"] == "api")
        wh_task = next(t for t in res["tasks"] if t["key"] == "webhook")

        # Initial statuses: root is ready, children are blocked
        self.assertEqual(db_task["status"], "ready")
        self.assertEqual(api_task["status"], "blocked")
        self.assertEqual(wh_task["status"], "blocked")

        # Dependency resolution: api_task must depend on db_task's real ID
        self.assertEqual(api_task["depends_on"], [db_task["id"]])
        self.assertEqual(wh_task["depends_on"], [api_task["id"]])

        # Verify emitted events
        all_events = events.read_events(workspace=self.slug)
        event_types = [e["event_type"] for e in all_events]
        self.assertIn("GOAL_PROPOSED", event_types)
        self.assertIn("GOAL_ACCEPTED", event_types)

        # Check event payload details
        acc_evt = next(e for e in all_events if e["event_type"] == "GOAL_ACCEPTED")
        self.assertEqual(acc_evt["actor"], "agent:jarvis")
        self.assertEqual(acc_evt["stage"], "AUTHORIZE")
        self.assertEqual(acc_evt["payload"]["spec_id"], res["spec_id"])
        self.assertEqual(len(acc_evt["payload"]["tasks"]), 3)

    def test_cli_goal_propose(self):
        tasks_json = json.dumps([
            {"key": "s1", "title": "Step 1"},
            {"key": "s2", "title": "Step 2", "depends_on": ["s1"]},
        ])
        code, out, _ = h.run(
            "goal-propose",
            "-w", self.slug,
            "--goal", "Implement CLI goal",
            "--tasks-json", tasks_json,
            "--json",
        )
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["tasks"]), 2)

    def test_http_api_goals_post_and_get(self):
        # 1. POST /api/goals with valid payload
        valid_payload = json.dumps({
            "goal": "Refactor user authentication",
            "workspace": self.slug,
            "tasks": [
                {"key": "step1", "title": "Step 1"},
                {"key": "step2", "title": "Step 2", "depends_on": ["step1"]},
            ],
        }).encode("utf-8")

        handler = Handler.__new__(Handler)
        handler.headers = {"Content-Length": str(len(valid_payload))}
        handler.rfile = MockRFile(valid_payload)
        handler.wfile = MockWFile()
        handler.path = "/api/goals"
        handler.headers_buffer = []

        status_code = []
        def mock_send_response(code, message=None):
            status_code.append(code)
        handler.send_response = mock_send_response
        handler.send_header = lambda k, v: None
        handler.end_headers = lambda: None

        handler.do_POST()
        self.assertEqual(status_code[-1], 200)
        resp_data = json.loads(handler.wfile.data.decode("utf-8"))
        self.assertTrue(resp_data["ok"])
        self.assertEqual(len(resp_data["tasks"]), 2)

        # 2. POST /api/goals with cyclic payload -> should return 409
        cyclic_payload = json.dumps({
            "goal": "Impossible Cycle",
            "workspace": self.slug,
            "tasks": [
                {"key": "a", "title": "A", "depends_on": ["b"]},
                {"key": "b", "title": "B", "depends_on": ["a"]},
            ],
        }).encode("utf-8")

        handler.headers = {"Content-Length": str(len(cyclic_payload))}
        handler.rfile = MockRFile(cyclic_payload)
        handler.wfile = MockWFile()
        handler.do_POST()
        self.assertEqual(status_code[-1], 409)

        # 3. GET /api/goals
        handler.path = f"/api/goals?workspace={self.slug}"
        handler.wfile = MockWFile()
        handler.do_GET()
        self.assertEqual(status_code[-1], 200)
        get_resp = json.loads(handler.wfile.data.decode("utf-8"))
        self.assertIn("goals", get_resp)


if __name__ == "__main__":
    unittest.main()
