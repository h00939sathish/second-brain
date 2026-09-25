# -*- coding: utf-8 -*-
"""Tests for Declarative Squads (squad.yaml and brain squad CLI)."""

import unittest

import tests.harness as h
from brain import const, squad
from brain.errors import BrainError


class TestSquad(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("squad")

    def test_default_squad_loadout_when_unconfigured(self):
        sq = squad.load_squad(self.slug)
        self.assertFalse(sq["configured"])
        self.assertEqual("claude", sq["roles"]["lead"])
        self.assertEqual("codex", sq["roles"]["builder"])
        self.assertEqual("agy", sq["roles"]["reviewer"])
        self.assertEqual("opencode", sq["roles"]["qa"])

    def test_save_and_load_squad(self):
        data = {
            "name": "titan-core",
            "roles": {
                "lead": "opencode",
                "builder": "codex",
                "reviewer": "agy",
                "qa": "claude",
            },
        }
        res = squad.save_squad(data, self.slug)
        self.assertTrue(res["configured"])

        loaded = squad.load_squad(self.slug)
        self.assertTrue(loaded["configured"])
        self.assertEqual("titan-core", loaded["name"])
        self.assertEqual("opencode", loaded["roles"]["lead"])
        self.assertEqual("claude", loaded["roles"]["qa"])

    def test_set_role_updates_configuration(self):
        squad.save_squad({"name": "test-team", "roles": {}}, self.slug)
        squad.set_role("reviewer", "claude", self.slug)
        agent = squad.get_agent("reviewer", self.slug)
        self.assertEqual("claude", agent)

    def test_invalid_role_rejected(self):
        with self.assertRaises(BrainError):
            squad.set_role("cheerleader", "claude", self.slug)

    def test_route_stage_maps_kanban_to_squad_roles(self):
        squad.save_squad({
            "name": "routing-team",
            "roles": {
                "lead": "claude",
                "builder": "codex",
                "reviewer": "agy",
                "qa": "opencode",
            }
        }, self.slug)

        self.assertEqual("claude", squad.route_stage("planning", self.slug))
        self.assertEqual("claude", squad.route_stage("backlog", self.slug))
        self.assertEqual("codex", squad.route_stage("running", self.slug))
        self.assertEqual("codex", squad.route_stage("ready", self.slug))
        self.assertEqual("agy", squad.route_stage("review", self.slug))
        self.assertEqual("opencode", squad.route_stage("done", self.slug))

    def test_cli_squad_commands(self):
        # 1. show default
        code, out, err = h.run("squad", "-w", self.slug, expect=0)
        self.assertIn("default (unconfigured)", out)
        self.assertIn("lead", out)
        self.assertIn("claude", out)

        # 2. init
        code, out, err = h.run("squad", "init", "--name", "alpha-pod", "-w", self.slug, expect=0)
        self.assertIn("initialized squad 'alpha-pod'", out)

        # 3. set
        code, out, err = h.run("squad", "set", "builder", "agy", "-w", self.slug, expect=0)
        self.assertIn("role 'builder' set to 'agy'", out)

        # 4. show configured
        code, out, err = h.run("squad", "-w", self.slug, expect=0)
        self.assertIn("declared", out)
        self.assertIn("alpha-pod", out)
        self.assertIn("agy", out)


if __name__ == "__main__":
    unittest.main()
