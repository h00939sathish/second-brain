# -*- coding: utf-8 -*-
"""INV-008: Execution requires a valid Deliberation Record for tasks requiring coordination."""

import unittest

import tests.harness as h
from brain import board, deliberation, events
from brain.errors import DeliberationGate


class TestInv008Deliberation(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv008")

    def test_unauthorized_execution_denied_without_deliberation_record(self):
        """INV-008.1: A task requiring coordination cannot move to ready/running without an authorized Deliberation Record."""
        task = board.create_task(
            title="Refactor core auth middleware",
            workspace=self.slug,
            agent="codex",
            files="src/auth.py",
            coordination_required=True,
        )
        task_id = task["id"]
        self.assertEqual(task["status"], "coordinating")

        # Moving to running or ready must be refused by DeliberationGate
        with self.assertRaises(DeliberationGate) as ctx:
            board.move(task_id, "ready", workspace=self.slug)
        self.assertIn("deliberation required", str(ctx.exception))

        with self.assertRaises(DeliberationGate) as ctx:
            board.move(task_id, "running", workspace=self.slug, agent="codex")
        self.assertIn("deliberation required", str(ctx.exception))

    def test_room_lifecycle_and_proposals(self):
        """INV-008.2: Deliberation room opens, collects structured proposals, and emits audit events."""
        task = board.create_task(
            title="Update token validation",
            workspace=self.slug,
            agent="codex",
            files="src/token.py",
        )
        task_id = task["id"]

        # Open deliberation room
        room = deliberation.open_room(
            task_id=task_id,
            workspace=self.slug,
            risk="high",
            participants=["codex", "claude", "opencode"],
            actor="agent:jarvis",
        )
        self.assertEqual(room["status"], "OPEN")
        self.assertEqual(room["risk"], "high")

        # Submit technical proposal from codex
        prop = deliberation.submit_proposal(
            task_id=task_id,
            agent="codex",
            plan=["inspect middleware", "update expiry checks", "run test suite"],
            files_expected=["src/token.py", "tests/test_token.py"],
            risks=["backward compatibility with legacy clients"],
            workspace=self.slug,
        )
        self.assertEqual(prop["proposal_id"], "prop_01")
        self.assertEqual(prop["status"], "PROPOSED")

        # Verify event stream
        evs = events.read_events(workspace=self.slug)
        types = [e["event_type"] for e in evs]
        self.assertIn("DELIBERATION_OPENED", types)
        self.assertIn("PROPOSAL_SUBMITTED", types)

    def test_unresolved_objection_blocks_adjudication(self):
        """INV-008.3: An active high/blocking objection blocks authorization."""
        task = board.create_task(
            title="Refactor database layer",
            workspace=self.slug,
            coordination_required=True,
        )
        task_id = task["id"]
        deliberation.open_room(task_id, workspace=self.slug, participants=["codex", "claude"])

        # Codex proposes
        deliberation.submit_proposal(
            task_id=task_id,
            agent="codex",
            plan=["switch to async engine"],
            files_expected=["src/db.py"],
            workspace=self.slug,
        )

        # Claude objects
        obj = deliberation.raise_objection(
            task_id=task_id,
            sender="claude",
            body="Async engine breaks legacy synchronous callers in worker pool",
            severity="blocking",
            proposal_id="prop_01",
            workspace=self.slug,
        )
        self.assertEqual(obj["type"], "OBJECTION")

        # Adjudication must fail due to unresolved objection
        result = deliberation.adjudicate(task_id, workspace=self.slug)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("unresolved blocking objection", result["reason"])

        # Task remains blocked from running
        with self.assertRaises(DeliberationGate):
            board.move(task_id, "ready", workspace=self.slug)

    def test_resolved_objection_authorizes_and_advances_task(self):
        """INV-008.4: Resolving objections enables consensus, writes Decision Record, and unblocks task."""
        task = board.create_task(
            title="Migrate session store",
            workspace=self.slug,
            coordination_required=True,
        )
        task_id = task["id"]
        deliberation.open_room(task_id, workspace=self.slug, participants=["codex", "claude"])

        deliberation.submit_proposal(
            task_id=task_id,
            agent="codex",
            plan=["introduce Redis sessions"],
            files_expected=["src/sessions.py"],
            workspace=self.slug,
        )

        obj = deliberation.raise_objection(
            task_id=task_id,
            sender="claude",
            body="Redis dependency must support fallback in dev environments",
            severity="high",
            workspace=self.slug,
        )

        # Codex resolves objection with evidence/acknowledgement
        deliberation.resolve_objection(
            task_id=task_id,
            resolver="codex",
            message_id_or_ref=obj["message_id"],
            resolution_notes="Added in-memory fallback driver for development mode",
            workspace=self.slug,
        )

        # Adjudication succeeds
        res = deliberation.adjudicate(task_id, workspace=self.slug)
        self.assertTrue(res["ok"])
        self.assertEqual(res["status"], "AUTHORIZED")
        self.assertIn("src/sessions.py", res["decision"]["authorized_files"])

        # Task has automatically transitioned to ready
        slug, updated_task = board.get_task(task_id, self.slug)
        self.assertEqual(updated_task["fm"]["status"], "ready")

        # Now moving to running is permitted
        board.move(task_id, "running", workspace=self.slug, agent="codex")
        _, running_task = board.get_task(task_id, self.slug)
        self.assertEqual(running_task["fm"]["status"], "running")

    def test_agent_presence_tracking(self):
        """INV-008.5: Agent presence tracks live focus, state, and files."""
        task = board.create_task(title="Presence test", workspace=self.slug, coordination_required=True)
        task_id = task["id"]
        deliberation.open_room(task_id, workspace=self.slug)

        deliberation.update_presence(
            task_id=task_id,
            agent="claude",
            state="REVIEWING",
            focus="backward compatibility audit",
            files=["src/auth.py"],
            workspace=self.slug,
        )

        room = deliberation.get_room(task_id, workspace=self.slug)
        self.assertIn("claude", room["presence"])
        self.assertEqual(room["presence"]["claude"]["state"], "REVIEWING")
        self.assertEqual(room["presence"]["claude"]["focus"], "backward compatibility audit")
        self.assertEqual(room["presence"]["claude"]["files"], ["src/auth.py"])


if __name__ == "__main__":
    unittest.main()
