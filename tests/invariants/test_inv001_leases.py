# -*- coding: utf-8 -*-
"""INV-001: An agent cannot modify a file without an active, uncontested lease.

The lease is also the only answer to "who is working on this", so it is bound to the
seat that opened it: a lease somebody else typed for you is not a claim on the file, and
a card cannot be reassigned out from under a lease that is still live.
"""

import os
import unittest
from unittest import mock

import tests.harness as h
from brain import board, coordination, events, store
from brain.errors import BrainError, LeaseConflict


class TestInv001Leases(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv001")

    def test_write_without_session_is_rejected_by_guard(self):
        """INV-001.1: Guard must reject agent write attempts if no session exists."""
        decision = coordination.admit(agent="codex", files=["src/auth.py"], workspace=self.slug)
        self.assertFalse(decision["ok"], "Guard must deny writes when no session is active")
        self.assertIn("no active session", decision["reason"])

    def test_competing_lease_is_rejected(self):
        """INV-001.2: A file leased by agent A cannot be leased by agent B."""
        coordination.start(agent="opencode", workspace=self.slug, files="src/auth.py")
        with self.assertRaises(LeaseConflict):
            coordination.start(agent="claude", workspace=self.slug, files="src/auth.py")

    def test_valid_lease_is_authorized_by_guard(self):
        """INV-001.3: An agent holding an active lease on a file is authorized to write."""
        coordination.start(agent="codex", workspace=self.slug, files="src/auth.py")
        decision = coordination.admit(agent="codex", files=["src/auth.py"], workspace=self.slug)
        self.assertTrue(decision["ok"], "Guard must permit writes for files held in agent's lease")

    def test_unleased_file_access_is_rejected_when_workspace_held(self):
        """INV-001.4: Another agent cannot write to unleased files if another session holds the workspace."""
        coordination.start(agent="opencode", workspace=self.slug, files="src/auth.py")
        decision = coordination.admit(agent="claude", files=["src/auth.py"], workspace=self.slug)
        self.assertFalse(decision["ok"], "Guard must block foreign agent from touching leased file")
        self.assertTrue(decision["conflict"])

    def test_lease_release_restores_file_availability(self):
        """INV-001.5: Ending a session cleanly releases the lease for other workers."""
        session = coordination.start(agent="opencode", workspace=self.slug, files="src/auth.py")
        coordination.end(session["id"], summary="finished auth refactor", workspace=self.slug)
        self.assertEqual(store.build_locks([self.slug]), {})
        # Now another agent can acquire the lease
        next_session = coordination.start(agent="claude", workspace=self.slug, files="src/auth.py")
        self.assertTrue(next_session["id"])


class TestInv001LeaseOwnership(unittest.TestCase):
    """INV-001.6+: who a lease belongs to, and what may not be moved under one."""

    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv001")

    def _refusals(self):
        return events.read_events(workspace=self.slug,
                                  event_type="OWNERSHIP_CONFLICT_REFUSED")

    def test_a_lease_is_bound_to_a_seat_not_to_a_name(self):
        """INV-001.6: opening a session as somebody else is a forged claim, not a lease."""
        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "claude"}):
            with self.assertRaises(BrainError) as ctx:
                coordination.start(agent="opencode", workspace=self.slug, files="src/auth.py")
        self.assertIn("ownership refused", str(ctx.exception))
        self.assertEqual(store.build_locks([self.slug]), {}, "no lease may be taken")
        self.assertEqual(len(self._refusals()), 1)
        self.assertEqual(self._refusals()[0]["actor"], "agent:claude")

    def test_a_card_under_a_live_lease_cannot_be_reassigned(self):
        """INV-001.7: a move that changes the assigned agent under another seat's lease
        is refused, so `who owns this` cannot be edited away mid-flight."""
        card = board.create_task("Leased card", workspace=self.slug, agent="opencode",
                                 files="src/auth.py")
        coordination.start(agent="opencode", workspace=self.slug, files="src/auth.py")

        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "claude"}):
            with self.assertRaises(BrainError):
                board.move(card["id"], "running", workspace=self.slug, agent="claude")

        self.assertEqual(store.read_record("tasks", card["id"], self.slug)["fm"]["agent"],
                         "opencode")
        self.assertEqual(self._refusals()[0]["payload"]["leased_by"][0]["holder"], "opencode")

    def test_the_lease_holder_may_still_move_its_own_card(self):
        """The rule refuses foreign seats, not the work itself."""
        card = board.create_task("Owned card", workspace=self.slug, agent="opencode",
                                 files="src/auth.py")
        coordination.start(agent="opencode", workspace=self.slug, files="src/auth.py")
        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "opencode"}):
            self.assertEqual(board.move(card["id"], "running", workspace=self.slug,
                                        agent="opencode")["status"], "running")
        self.assertEqual(self._refusals(), [])

    def test_one_rule_governs_the_card_and_the_lease(self):
        """INV-001.8: cards and leases answer the same question, so they cannot disagree
        about who is working — which is what let B take credit for A's card."""
        card = board.create_task("Shared rule", workspace=self.slug, agent="opencode")
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=card["id"], files="src/auth.py")
        with mock.patch.dict(os.environ, {"BRAIN_AGENT": "claude"}):
            with self.assertRaises(BrainError):
                coordination.end(session["id"], summary="not mine to end", workspace=self.slug)
            with self.assertRaises(BrainError):
                board.move(card["id"], "review", workspace=self.slug)

        self.assertEqual(store.read_record("sessions", session["id"], self.slug)["fm"]["status"],
                         "active", "a foreign seat must not release another's lease")
        record = store.read_record("tasks", card["id"], self.slug)["fm"]
        self.assertEqual(record["agent"], "opencode")
        self.assertEqual(record["status"], "running", "the card is where opencode left it")
        self.assertEqual(len(self._refusals()), 2)

    def test_a_directory_lease_covers_what_is_inside_it(self):
        """INV-001.9: one path rule for leases and evidence — equality or a directory
        prefix with the separator, never `endswith` and never a bare prefix."""
        self.assertTrue(board.lease_covers("src", "src/auth.py"))
        self.assertTrue(board.lease_covers("src/", "src/nested/auth.py"))
        self.assertTrue(board.lease_covers("src/auth.py", "src/auth.py"))
        self.assertFalse(board.lease_covers("x/auth.py", "src/auth.py"),
                         "a suffix must never answer for a different path")
        self.assertFalse(board.lease_covers("src/a", "src/anything.py"),
                         "a prefix without the separator is not a directory")

        coordination.start(agent="opencode", workspace=self.slug, files="src")
        conflicts = coordination.check_files("src/auth.py", workspace=self.slug)
        self.assertEqual([path for path, _ in conflicts], ["src/auth.py"],
                         "the lease taken on the directory has to cover the file inside it")
        self.assertEqual(conflicts[0][1]["agent"], "opencode")


if __name__ == "__main__":
    unittest.main()
