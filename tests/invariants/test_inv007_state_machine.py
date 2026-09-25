# -*- coding: utf-8 -*-
"""INV-007: All state transitions are strictly validated against formal Finite State Machines."""

import os
import unittest
from unittest import mock

import tests.harness as h
from brain import board, const, coordination, evidence, events, knowledge, store
from brain.errors import BrainError


class TestInv007StateMachine(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv007")

    def test_invalid_task_transition_rejected(self):
        """INV-007.1: Illegal task status string is rejected."""
        task = board.create_task("Test task", workspace=self.slug)
        with self.assertRaises(BrainError):
            board.move(task["id"], "invalid_state", workspace=self.slug)

    def test_claim_status_restricted_to_formal_fsm(self):
        """INV-007.2: Claim status must belong to defined STATUSES."""
        with self.assertRaises(BrainError):
            knowledge.add("Random fact", workspace=self.slug, status="hallucinated")

    def test_task_statuses_set_matches_specification(self):
        """INV-007.3: The task lifecycle matches the documented FSM states."""
        self.assertIn("backlog", const.TASK_STATUSES)
        self.assertIn("planning", const.TASK_STATUSES)
        self.assertIn("running", const.TASK_STATUSES)
        self.assertIn("review", const.TASK_STATUSES)
        self.assertIn("done", const.TASK_STATUSES)


class TestInv007TransitionOwnership(unittest.TestCase):
    """INV-007.4+: *which* seat may drive a transition, and whose name it leaves behind.

    A transition used to be validated only against the caller's own assertion, so
    `move --agent <whoever>` decided who was recorded as the author of the work.
    """

    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv007")

    def _card_with_finished_work(self, target="agy"):
        """opencode does the work and hands off to `target` — the honest pipeline."""
        card = board.create_task("Harden the leases", workspace=self.slug, agent="opencode",
                                 files="src/leases.py")
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=card["id"], files="src/leases.py")
        evidence.record_receipt(task_id=card["id"], command="pytest -q", exit_code=0,
                                stdout="9 passed", workspace=self.slug,
                                session_id=session["id"])
        coordination.end(session["id"], summary="implemented", test_status="pytest: 9 passed",
                         target_agent=target, workspace=self.slug)
        return card

    def _refusals(self):
        return events.read_events(workspace=self.slug,
                                  event_type="OWNERSHIP_CONFLICT_REFUSED")

    def test_a_foreign_seat_cannot_move_the_card_and_become_its_author(self):
        """INV-007.4: claude, handed nothing, may not close opencode's card as itself."""
        card = self._card_with_finished_work()
        self.assertEqual(store.read_record("tasks", card["id"], self.slug)["fm"]["status"],
                         "review")

        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "claude"}):
            with self.assertRaises(BrainError) as ctx:
                board.move(card["id"], "done", workspace=self.slug, agent="claude")
        self.assertIn("ownership refused", str(ctx.exception))

        after = store.read_record("tasks", card["id"], self.slug)["fm"]
        self.assertEqual(after["status"], "review", "a refused transition must not land")
        self.assertEqual(after["agent"], "opencode", "the caller is not the recorded author")
        self.assertEqual(len(self._refusals()), 1, "every refusal is audited")
        refusal = self._refusals()[0]
        self.assertEqual(refusal["stage"], "AUTHORIZE")
        self.assertEqual(refusal["actor"], "agent:claude")
        self.assertEqual(refusal["task_id"], card["id"])

    def test_a_declared_handoff_lets_the_recipient_drive_the_transition(self):
        """INV-007.5: the handoff agy was named in still closes the card — as opencode's work."""
        card = self._card_with_finished_work(target="agy")
        self.assertEqual(self._refusals(), [], "a handoff must not be refused")

        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "agy"}):
            result = board.move(card["id"], "done", workspace=self.slug)

        self.assertEqual(result["status"], "done")
        self.assertEqual(self._refusals(), [])
        after = store.read_record("tasks", card["id"], self.slug)["fm"]
        self.assertEqual(after["agent"], "opencode", "authorship follows the finished session")
        self.assertEqual(after["closure_target"], "agy")

    def test_an_unseated_caller_cannot_write_itself_in_as_author_either(self):
        """INV-007.6: without a seat the claim is still not the author — and it says so."""
        card = self._card_with_finished_work()
        board.move(card["id"], "done", workspace=self.slug, agent="claude")

        record = store.read_record("tasks", card["id"], self.slug)
        self.assertEqual(record["fm"]["agent"], "opencode")
        self.assertIn("author recorded as opencode, not claude", record["body"])


if __name__ == "__main__":
    unittest.main()
