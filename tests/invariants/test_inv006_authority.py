# -*- coding: utf-8 -*-
"""INV-006: Agent output cannot directly mutate authoritative control-plane state."""

import unittest

import tests.harness as h
from brain import board, store
from brain.errors import BrainError, SchemaError


class TestInv006Authority(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv006")

    def test_invalid_task_status_rejected_by_authorizer(self):
        """INV-006.1: Untrusted agent proposing non-existent status is rejected."""
        with self.assertRaises(BrainError):
            board.create_task("Hack state", workspace=self.slug, status="COMPLETED_TRUST_ME")

    def test_task_cannot_enter_running_without_agent(self):
        """INV-006.2: Agent proposing running state without assigned worker is rejected."""
        task = board.create_task("Unowned task", workspace=self.slug)
        with self.assertRaises(BrainError) as ctx:
            board.move(task["id"], "running", workspace=self.slug, agent="")
        self.assertIn("cannot enter [running] without an assigned agent", str(ctx.exception))

    def test_malformed_frontmatter_is_rejected_by_store(self):
        """INV-006.3: Corrupted or unauthorized schema keys are rejected upon record validation."""
        bad_fm = {"id": "bad-task", "status": "backlog"}  # Missing title and created
        with self.assertRaises(SchemaError):
            store.write_record("tasks", bad_fm, "body", workspace=self.slug)


if __name__ == "__main__":
    unittest.main()
