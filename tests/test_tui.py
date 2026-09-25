# -*- coding: utf-8 -*-
"""Tests for Terminal User Interface (brain tui)."""

import unittest

import tests.harness as h
from brain import coordination, tui


class TestTui(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("tui")

    def test_collect_state_structure(self):
        state = tui.collect_state(self.slug)
        self.assertEqual(self.slug, state["workspace"])
        self.assertIn("squad", state)
        self.assertIn("sessions", state)
        self.assertIn("tasks", state)
        self.assertIn("notes", state)
        self.assertIn("claims", state)

    def test_render_snapshot_contains_key_sections(self):
        coordination.post("Test note for TUI", workspace=self.slug, topic="tui-test", agent="agy")
        state = tui.collect_state(self.slug)
        rendered = tui.render_snapshot(state)
        self.assertIn("SECOND BRAIN TERMINAL DASHBOARD", rendered)
        self.assertIn("[SQUAD MEMBERS]", rendered)
        self.assertIn("[ACTIVE SESSIONS & FILE LEASES]", rendered)
        self.assertIn("[KANBAN BOARD]", rendered)
        self.assertIn("[AGENT CHATROOM & RECENT NOTES]", rendered)
        self.assertIn("Test note for TUI", rendered)
        self.assertIn("#tui-test", rendered)

    def test_cli_tui_once_command(self):
        code, out, err = h.run("tui", "--once", "-w", self.slug, expect=0)
        self.assertIn("SECOND BRAIN TERMINAL DASHBOARD", out)
        self.assertIn(f"[{self.slug}]", out)


if __name__ == "__main__":
    unittest.main()
