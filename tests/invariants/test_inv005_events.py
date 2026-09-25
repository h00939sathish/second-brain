# -*- coding: utf-8 -*-
"""INV-005: Every externally observable state transition and authorization produces an append-only event."""

import os
import unittest
from unittest import mock

import tests.harness as h
from brain import board, const, coordination, errors, events, knowledge


class TestInv005Events(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv005")

    def test_session_lifecycle_records_execution_audit(self):
        """INV-005.1: Session lifecycle actions leave an auditable record of events."""
        session = coordination.start(agent="codex", workspace=self.slug,
                                     task="Audit event trail", files="src/api.py")
        coordination.end(session["id"], summary="Audit completed", workspace=self.slug)

        # Verify that ended session records timestamps in markdown view
        ended = coordination.get(session["id"], self.slug)
        self.assertEqual(ended[1]["fm"]["status"], "ended")
        self.assertTrue(ended[1]["fm"]["ended"])

        # Verify immutable event stream records
        evs = events.read_events(workspace=self.slug)
        types = [e["event_type"] for e in evs]
        self.assertIn("LEASE_GRANTED", types)
        self.assertIn("LEASE_RELEASED", types)

        grant_ev = next(e for e in evs if e["event_type"] == "LEASE_GRANTED")
        self.assertEqual(grant_ev["stage"], "AUTHORIZE")
        self.assertEqual(grant_ev["actor"], "agent:codex")
        self.assertEqual(grant_ev["payload"]["session_id"], session["id"])
        self.assertEqual(grant_ev["payload"]["files"], ["src/api.py"])
        self.assertEqual(grant_ev["schema_version"], 1)

    def test_lease_conflict_emits_lease_denied(self):
        """INV-005.2: Authorization refusals (e.g. lease conflicts) are recorded as events."""
        s1 = coordination.start(agent="codex", workspace=self.slug, files="shared.py")
        self.assertTrue(s1["id"])

        with self.assertRaises(errors.LeaseConflict):
            coordination.start(agent="claude", workspace=self.slug, files="shared.py")

        evs = events.read_events(workspace=self.slug, event_type="LEASE_DENIED")
        self.assertEqual(len(evs), 1)
        denied = evs[0]
        self.assertEqual(denied["stage"], "AUTHORIZE")
        self.assertEqual(denied["actor"], "agent:claude")
        self.assertEqual(denied["payload"]["holder"], "codex")
        self.assertEqual(denied["payload"]["conflicts"], ["shared.py"])

    def test_task_lifecycle_and_cascade_events(self):
        """INV-005.3: Task creation, state transitions, unblocking, and completion emit events."""
        t1 = board.create_task("Backend schema", workspace=self.slug)
        t2 = board.create_task("Frontend UI", workspace=self.slug, depends_on=[t1["id"]])

        # Move t1 through pipeline
        board.move(t1["id"], "planning", workspace=self.slug, agent="codex")
        board.move(t1["id"], "running", workspace=self.slug, agent="codex")
        board.move(t1["id"], "review", workspace=self.slug, agent="codex")
        with mock.patch.dict(os.environ, {"BRAIN_BYPASS": "1"}):
            board.move(t1["id"], "done", workspace=self.slug, agent="agy",
                       tests="tests pass", force=True)

        # Check events for t1 and t2
        all_evs = events.read_events(workspace=self.slug, oldest=True)
        created_evs = [e for e in all_evs if e["event_type"] == "TASK_CREATED"]
        self.assertEqual(len(created_evs), 2)

        # t2 was unblocked when t1 reached done
        unblocked_evs = [e for e in all_evs if e["event_type"] == "TASK_UNBLOCKED"]
        self.assertEqual(len(unblocked_evs), 1)
        self.assertEqual(unblocked_evs[0]["task_id"], t2["id"])
        self.assertEqual(unblocked_evs[0]["payload"]["prerequisite"], t1["id"])

        # t1 completed event
        completed_evs = [e for e in all_evs if e["event_type"] == "TASK_COMPLETED"]
        self.assertEqual(len(completed_evs), 1)
        self.assertEqual(completed_evs[0]["task_id"], t1["id"])

    def test_claim_lifecycle_events(self):
        """INV-005.4: Claim creation, disputes, revalidations emit events."""
        c = knowledge.add("SQLite FTS5 requires BM25 scoring", workspace=self.slug,
                          confidence=0.95, verified_commit="abc12345", depends_on=["brain/index.py"])
        cid = c["id"]

        knowledge.dispute(cid, reason="BM25 is default, no config needed", by="claude")
        knowledge.revalidate(cid, note="Re-verified on latest commit", workspace=self.slug,
                             verified_commit="def67890")

        evs = events.read_events(workspace=self.slug, oldest=True)
        ev_types = [e["event_type"] for e in evs]
        self.assertIn("CLAIM_CREATED", ev_types)
        self.assertIn("CLAIM_DISPUTED", ev_types)
        self.assertIn("CLAIM_REVALIDATED", ev_types)

        reval_ev = next(e for e in evs if e["event_type"] == "CLAIM_REVALIDATED")
        self.assertEqual(reval_ev["payload"]["verified_commit"], "def67890")

    def test_schema_v1_invariants_and_monotonic_sequence(self):
        """INV-005.5: All events conform to Schema v1 and maintain monotonic sequence numbering."""
        for i in range(5):
            board.create_task(f"Task {i}", workspace=self.slug)

        evs = events.read_events(workspace=self.slug, oldest=True)
        self.assertGreaterEqual(len(evs), 5)

        prev_seq = 0
        for ev in evs:
            # Check required fields
            self.assertIn("event_id", ev)
            self.assertIn("sequence", ev)
            self.assertIn("timestamp", ev)
            self.assertIn("workspace", ev)
            self.assertIn("schema_version", ev)
            self.assertIn("stage", ev)
            self.assertIn("actor", ev)
            self.assertIn("event_type", ev)
            self.assertIn("payload", ev)

            # Check schema version
            self.assertEqual(ev["schema_version"], const.EVENT_SCHEMA_VERSION)
            self.assertIn(ev["stage"], const.EVENT_STAGES)

            # Monotonic sequence
            seq = ev["sequence"]
            self.assertGreater(seq, prev_seq)
            prev_seq = seq


if __name__ == "__main__":
    unittest.main()
