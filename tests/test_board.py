# -*- coding: utf-8 -*-
"""The board, the review gate, the router, and who a transition is credited to."""

import os
import unittest
from unittest import mock

import tests.harness as h
from brain import board, coordination, daemon, events, store
from brain.errors import (BrainError, NotFound, ReviewGate, UnverifiedEvidenceError)
from brain.paths import stamp


class Tasks(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("board")

    def test_create_and_read_card(self):
        card = board.create_task(title="Fix the thing", workspace=self.slug,
                                 project="jarvis", agent="opencode", files="a.py,b.py")
        record = store.read_record("tasks", card["id"], self.slug)
        self.assertEqual(record["fm"]["status"], "backlog")
        self.assertEqual(record["fm"]["files"], ["a.py", "b.py"])
        self.assertEqual(record["fm"]["agent"], "opencode")

    def test_agent_aliases_are_canonicalised(self):
        card = board.create_task(title="x", workspace=self.slug, agent="antigravity")
        record = store.read_record("tasks", card["id"], self.slug)
        self.assertEqual(record["fm"]["agent"], "agy")
        self.assertEqual(board.role_of("claude-code"), "builder")
        self.assertEqual(board.role_of("antigravity"), "reviewer")

    def test_spec_link_must_exist(self):
        with self.assertRaises(NotFound):
            board.create_task(title="x", workspace=self.slug, spec_id="spec-nope")

    def test_spec_then_linked_card(self):
        spec = board.create_spec(title="Migration", spec="Do it in phases.",
                                workspace=self.slug, phases="a, b")
        record = store.read_record("specs", spec["id"], self.slug)
        self.assertEqual(record["fm"]["phases"], ["a", "b"])
        card = board.create_task(title="phase a", workspace=self.slug, spec_id=spec["id"])
        self.assertEqual(store.read_record("tasks", card["id"], self.slug)["fm"]["spec_id"],
                         spec["id"])

    def test_running_requires_an_owner(self):
        card = board.create_task(title="orphan", workspace=self.slug)
        with self.assertRaises(BrainError):
            board.move(card["id"], "running", workspace=self.slug)

    def test_running_with_owner_is_fine(self):
        card = board.create_task(title="owned", workspace=self.slug, agent="opencode")
        result = board.move(card["id"], "running", workspace=self.slug)
        self.assertEqual(result["from"], "backlog")
        self.assertEqual(result["status"], "running")

    def test_invalid_status_rejected(self):
        card = board.create_task(title="x", workspace=self.slug)
        with self.assertRaises(BrainError):
            board.move(card["id"], "shipped", workspace=self.slug)

    def test_activity_log_records_the_transition(self):
        card = board.create_task(title="x", workspace=self.slug, agent="opencode")
        board.move(card["id"], "running", workspace=self.slug, notes="starting")
        record = store.read_record("tasks", card["id"], self.slug)
        self.assertIn("backlog -> running", record["body"])
        self.assertIn("starting", record["body"])


class ReviewGateEnforcement(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("gate")
        self.card = board.create_task(title="Ship it", workspace=self.slug, agent="opencode")

    def test_done_is_refused_without_review_evidence(self):
        board.move(self.card["id"], "review", workspace=self.slug, agent="opencode")
        with self.assertRaises(ReviewGate) as ctx:
            board.move(self.card["id"], "done", workspace=self.slug)
        self.assertIn("cannot reach [done]", str(ctx.exception))
        self.assertEqual(store.read_record("tasks", self.card["id"], self.slug)["fm"]["status"],
                         "review")

    def test_force_is_break_glass_not_a_flag(self):
        """--force opens the evidence gate, so it costs the break-glass authority."""
        board.move(self.card["id"], "review", workspace=self.slug)
        with self.assertRaises(BrainError):
            board.move(self.card["id"], "done", workspace=self.slug, force=True,
                       agent="operator")
        with mock.patch.dict(os.environ, {"BRAIN_BYPASS": "1"}):
            board.move(self.card["id"], "done", workspace=self.slug, force=True,
                       agent="operator")
        self.assertEqual(store.read_record("tasks", self.card["id"], self.slug)["fm"]["status"],
                         "done")

    def test_review_evidence_opens_the_gate(self):
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=self.card["id"], files="a.py")
        coordination.end(session["id"], summary="implemented", target_agent="agy",
                         test_status="pytest: 7 passed", workspace=self.slug)
        ok, why = board.review_evidence(self.card["id"], workspace=self.slug)
        self.assertTrue(ok, why)
        from brain import evidence
        evidence.record_receipt(task_id=self.card["id"], command="pytest -q", exit_code=0,
                                stdout="7 passed", workspace=self.slug,
                                session_id=session["id"])
        board.move(self.card["id"], "done", workspace=self.slug)
        self.assertEqual(store.read_record("tasks", self.card["id"], self.slug)["fm"]["status"],
                         "done")

    def test_a_named_reviewer_alone_is_not_evidence(self):
        """Naming a reviewer and typing a test string must not clear the done gate."""
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=self.card["id"], files="a.py")
        coordination.end(session["id"], summary="trust me", target_agent="agy",
                         test_status="pytest: 999 passed", workspace=self.slug)
        board.move(self.card["id"], "review", workspace=self.slug)
        with self.assertRaises(UnverifiedEvidenceError) as ctx:
            board.move(self.card["id"], "done", workspace=self.slug)
        self.assertIn("without OS execution receipt", str(ctx.exception))

    def test_a_finished_session_without_tests_is_not_evidence(self):
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=self.card["id"])
        coordination.end(session["id"], summary="chatted", workspace=self.slug)
        ok, why = board.review_evidence(self.card["id"], workspace=self.slug)
        self.assertFalse(ok)
        self.assertIn("none recorded", why)


class CardOwnership(unittest.TestCase):
    """`move` knows who is asking: the author is the session, not the caller."""

    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("owner")

    def _refusals(self):
        return events.read_events(workspace=self.slug,
                                  event_type="OWNERSHIP_CONFLICT_REFUSED")

    def test_the_operator_seat_is_the_documented_escalation_path(self):
        card = board.create_task("stuck card", workspace=self.slug, agent="opencode",
                                 files="a.py")
        coordination.start(agent="opencode", workspace=self.slug, files="a.py")
        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "operator"}):
            result = board.move(card["id"], "review", workspace=self.slug)
        self.assertEqual(result["status"], "review")
        self.assertEqual(store.read_record("tasks", card["id"], self.slug)["fm"]["agent"],
                         "opencode")
        self.assertEqual(self._refusals(), [])

    def test_force_breaks_the_gate_but_not_the_author(self):
        """--force is the human's break-glass on the evidence, not a way to sign the work."""
        card = board.create_task("unreviewed", workspace=self.slug, agent="opencode")
        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "claude", "BRAIN_BYPASS": "1"}):
            board.move(card["id"], "done", workspace=self.slug, agent="claude", force=True)
        self.assertEqual(store.read_record("tasks", card["id"], self.slug)["fm"]["agent"],
                         "opencode")

    def test_an_expired_lease_does_not_hold_the_card(self):
        """Liveness is `store.build_locks`'s, so a crashed agent cannot freeze the board."""
        card = board.create_task("abandoned", workspace=self.slug, agent="opencode",
                                 files="a.py")
        session = coordination.start(agent="opencode", workspace=self.slug, files="a.py")
        record = store.read_record("sessions", session["id"], self.slug)
        record["fm"]["lease_expires"] = stamp(minutes=-5)
        store.update_record("sessions", record, workspace=self.slug)

        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "claude"}):
            board.move(card["id"], "running", workspace=self.slug, agent="claude")
        self.assertEqual(store.read_record("tasks", card["id"], self.slug)["fm"]["agent"],
                         "claude")
        self.assertEqual(self._refusals(), [])


class Routing(unittest.TestCase):
    def test_lightweight_request_executes_directly(self):
        result = board.route("opencode", "rename this variable", project="x")
        self.assertEqual(result["action"], "direct")

    def test_cross_cutting_request_activates_the_pipeline(self):
        prompt = ("Implement the migration so every agent can refactor the database "
                  "schema and redesign the endpoint.").center(200, " ")
        result = board.route("opencode", prompt, project="titan")
        self.assertEqual(result["action"], "pipeline")
        self.assertTrue(result["signals"])
        self.assertIn("brain spec-create", result["brief"])

    def test_a_bare_comma_is_not_a_complexity_signal(self):
        """The old heuristic scored any prompt containing a comma into the pipeline."""
        result = board.route("opencode", "fix the typo, thanks")
        self.assertEqual(result["action"], "direct")

    def test_role_specific_next_action(self):
        h.reset_vault()
        slug = h.fresh_workspace("next")
        card = board.create_task(title="Review me", workspace=slug, agent="opencode")
        board.move(card["id"], "review", workspace=slug)
        step = board.next_action("agy", workspace=slug)
        self.assertEqual(step["task_id"], card["id"])
        self.assertEqual(step["agent"], "agy")
        self.assertIn("Audit", step["brief"])


class Watchdog(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("watch")
        self.card = board.create_task(title="in flight", workspace=self.slug, agent="opencode")
        board.move(self.card["id"], "running", workspace=self.slug)

    def test_live_session_blocks_a_second_dispatch(self):
        coordination.start(agent="opencode", workspace=self.slug, task_id=self.card["id"],
                           files="a.py")
        ok, detail = daemon.should_dispatch(self.card["id"], "running", self.slug)
        self.assertFalse(ok)
        self.assertIn("already in flight", detail)

    def test_circuit_breaker_trips_after_repeated_attempts(self):
        daemon.clear_attempts(self.card["id"], self.slug)
        results = [daemon.should_dispatch(self.card["id"], "running", self.slug) for _ in range(5)]
        self.assertTrue(results[0][0])
        self.assertFalse(results[-1][0])
        self.assertIn("circuit breaker", results[-1][1])

    def test_attempts_reset_when_the_card_moves(self):
        daemon.clear_attempts(self.card["id"], self.slug)
        daemon.should_dispatch(self.card["id"], "running", self.slug)
        ok, detail = daemon.should_dispatch(self.card["id"], "review", self.slug)
        self.assertTrue(ok)
        self.assertIn("attempt 1/", detail)

    def test_daemon_status_is_false_without_a_heartbeat(self):
        self.assertFalse(daemon.daemon_status()["active"])

    def test_daemon_status_is_true_with_a_fresh_heartbeat(self):
        daemon.write_heartbeat({"pid": __import__("os").getpid(), "ticks": 1,
                                "interval": 5, "last_tick_epoch": __import__("time").time()})
        self.assertTrue(daemon.daemon_status()["active"])


if __name__ == "__main__":
    unittest.main()
