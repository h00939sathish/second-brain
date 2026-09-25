# -*- coding: utf-8 -*-
"""Agent self-configuration is the riskiest code in the project: it edits files the
user did not ask us to own. These tests point it at a throwaway HOME."""

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import tests.harness as h
from brain import agents


class ConfigWriters(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="brain-home-"))
        self._original = agents.HOME
        agents.HOME = self.home
        self.addCleanup(lambda: setattr(agents, "HOME", self._original))

    def write(self, rel, text):
        path = self.home / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_claude_mcp_is_registered_once_and_is_idempotent(self):
        config = self.write(".claude.json", json.dumps({"numStartups": 7, "mcpServers": {}}))
        actions = []
        agents.configure_claude(actions)
        first = json.loads(config.read_text())
        self.assertEqual(first["numStartups"], 7)          # unrelated keys preserved
        self.assertIn("second-brain", first["mcpServers"])
        self.assertTrue(any("updated" in a for a in actions), actions)

        actions = []
        agents.configure_claude(actions)
        self.assertEqual(json.loads(config.read_text()), first)
        self.assertTrue(any("already configured" in a for a in actions), actions)

    def test_claude_hook_is_installed_and_preserves_env(self):
        self.write(".claude.json", "{}")
        settings = self.write(".claude/settings.json",
                              json.dumps({"env": {"ANTHROPIC_BASE_URL": "http://x"},
                                          "theme": "dark"}))
        agents.configure_claude([])
        data = json.loads(settings.read_text())
        self.assertEqual(data["env"]["ANTHROPIC_BASE_URL"], "http://x")
        self.assertEqual(data["theme"], "dark")
        command = data["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertIn("guard --agent claude", command)
        # A missing shim must not block every tool call.
        self.assertTrue(command.startswith("if [ -x "))

    def test_codex_section_replacement_leaves_no_duplicate_table(self):
        self.write(".codex/config.toml", 'model = "gpt"\n'
                                        "\n[mcp_servers.other]\ncommand = \"x\"\n"
                                        "\n[mcp_servers.second-brain]\n"
                                        'command = "/old/python"\n'
                                        "\n[mcp_servers.second-brain.env]\n"
                                        'SECOND_BRAIN_VAULT = "/old/path"\n')
        with unittest.mock.patch.object(agents, "find_cli", return_value="/bin/codex"):
            agents.configure_codex([])
        config = (self.home / ".codex" / "config.toml").read_text()
        self.assertIn("[mcp_servers.other]", config)                 # untouched neighbour
        self.assertEqual(config.count("[mcp_servers.second-brain]"), 1)
        self.assertEqual(config.count("[mcp_servers.second-brain.env]"), 1)
        self.assertNotIn("/old/path", config)
        self.assertIn(str(h.VAULT), config)

        import tomllib
        parsed = tomllib.loads(config)
        self.assertEqual(list(parsed["mcp_servers"]), ["other", "second-brain"])

    def test_opencode_rewrites_stale_instruction_paths(self):
        config = self.write(".config/opencode/opencode.json", json.dumps({
            "instructions": ["/home/someone/Work/second-brain/meta/l0_pointers.md",
                            "instructions/plan-debate.md"],
        }))
        agents.configure_opencode([])
        data = json.loads(config.read_text())
        self.assertIn("instructions/plan-debate.md", data["instructions"])
        self.assertIn(str(h.VAULT / "AGENTS.md"), data["instructions"])
        stale = [p for p in data["instructions"] if "/home/someone/" in p]
        self.assertEqual(stale, [])
        self.assertEqual(len(data["instructions"]), len(set(data["instructions"])))
        self.assertIn("second-brain", data["mcp"])

    def test_guard_plugin_is_generated_and_refreshable(self):
        self.write(".config/opencode/opencode.json", "{}")
        agents.configure_opencode([])
        plugin = self.home / ".config" / "opencode" / "plugin" / "brain-guard.js"
        self.assertTrue(plugin.is_file())
        body = plugin.read_text()
        self.assertIn("brain", body)
        self.assertIn("guard", body)
        # Session lifecycle commands must be able to run, or the guard deadlocks.
        self.assertIn("CLEARANCE", body)

    def test_broken_json_is_reported_not_clobbered(self):
        """A config we cannot parse must be left exactly as it is and reported."""
        config = self.write(".claude.json", "{ this is not json")
        actions = agents.configure(["claude"])
        self.assertTrue(any("FAILED" in a for a in actions), actions)
        self.assertEqual(config.read_text(), "{ this is not json")

    def test_shim_body_points_at_this_vault(self):
        body = agents.shim_body()
        self.assertIn(str(h.VAULT), body)
        self.assertIn("engine.py", body)

    def test_bootstrap_brief_mentions_the_enforced_rules(self):
        text = agents.bootstrap_brief(agent="opencode", workspace="jarvis")
        for needle in ("brain start", "refused", "brain claim", "brain recall",
                       "--global", "jarvis"):
            self.assertIn(needle, text)


class Skill(unittest.TestCase):
    """The skill is the only integration that needs no config file, so it has to be
    valid for clients that validate frontmatter strictly."""

    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="brain-home-"))
        self._original = agents.HOME
        agents.HOME = self.home
        self.addCleanup(lambda: setattr(agents, "HOME", self._original))

    def test_frontmatter_is_strictly_valid(self):
        body = agents.skill_body()
        self.assertTrue(body.startswith("---\n"))
        front, _, rest = body[4:].partition("\n---\n")
        fields = dict(line.split(":", 1) for line in front.splitlines()
                      if ":" in line and not line.startswith(" "))
        self.assertEqual(fields["name"].strip(), "second-brain")
        # Clients cap name at 64 chars and require lowercase-with-hyphens.
        self.assertRegex(fields["name"].strip(), r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(fields["name"].strip()), 64)
        self.assertLessEqual(len(fields["description"]), 1024)
        self.assertTrue(rest.strip(), "the skill must actually contain instructions")

    def test_installs_into_both_conventions_and_is_idempotent(self):
        actions = []
        agents.install_skill(actions)
        for rel in ((".agents",), (".claude",)):
            target = self.home / rel[0] / "skills" / "second-brain" / "SKILL.md"
            self.assertTrue(target.is_file(), target)
            self.assertEqual(target.read_text(), agents.skill_body())
        self.assertTrue(agents.skill_installed())

        actions = []
        agents.install_skill(actions)
        self.assertTrue(all("up to date" in a for a in actions), actions)

    def test_project_copy_shadows_the_global_one(self):
        project = self.home / "JARVIS"
        project.mkdir(parents=True)
        actions = []
        agents.install_skill(actions, project_root=str(project))
        self.assertTrue((project / ".agents" / "skills" / "second-brain" / "SKILL.md")
                        .is_file())
        first = next(a for a in actions if a.startswith("project skill"))
        self.assertIn("JARVIS", first)

    def test_an_unrelated_skill_file_is_not_touched(self):
        target = self.home / ".agents" / "skills" / "other" / "SKILL.md"
        target.parent.mkdir(parents=True)
        target.write_text("---\nname: other\n---\nkeep me\n", encoding="utf-8")
        agents.install_skill([])
        self.assertEqual(target.read_text(), "---\nname: other\n---\nkeep me\n")

    def test_every_registered_project_is_wired_by_one_setup(self):
        """The point of the skill layer is that adding a project is not a per-agent chore:
        one `brain setup` reaches every directory already in the registry."""
        h.reset_vault()
        from brain import workspaces as ws_mod
        actions = []
        agents.configure_projects(actions, dry_run=True)
        self.assertEqual([a for a in actions if a.startswith("project '")], [],
                         "the fresh vault registers no project paths")

        first, second = h.fresh_workspace("alpha"), h.fresh_workspace("beta")
        actions = []
        agents.configure_projects(actions)
        projects = [a for a in actions if a.startswith("project '")]
        self.assertEqual(len(projects), 2, actions)
        for slug in (first, second):
            root = Path(ws_mod.entry(slug)["path"])
            self.assertTrue((root / ".agents" / "skills" / "second-brain" / "SKILL.md")
                            .is_file(), root)

    def test_the_vault_does_not_get_a_pointer_to_itself(self):
        """The vault's AGENTS.md is the generated brief; a pointer block in it would
        duplicate the whole document into itself."""
        h.reset_vault()
        from brain import workspaces as ws_mod
        ws_mod.register("self", path=str(h.VAULT))
        actions = []
        agents.configure_projects(actions, dry_run=True)
        self.assertEqual([a for a in actions if a.startswith("project '")], [])
        self.assertFalse((h.VAULT / ".agents").exists())

    def test_project_wiring_dry_run_writes_nothing(self):
        h.reset_vault()
        from brain import workspaces as ws_mod
        slug = h.fresh_workspace("dry")
        root = Path(ws_mod.entry(slug)["path"])
        actions = []
        agents.configure_projects(actions, dry_run=True)
        self.assertTrue(any("would write" in a for a in actions), actions)
        self.assertFalse((root / ".agents").exists())

    def test_setup_installs_the_skill_and_the_shim(self):
        h.reset_vault()
        actions = agents.configure([])   # no CLIs in the patched HOME
        self.assertTrue(any(a.startswith("skill:") for a in actions), actions)
        shim_actions = agents.install_shim()
        shim = self.home / ".local" / "bin" / "brain"
        self.assertTrue(shim.is_file())
        self.assertTrue(os.access(shim, os.X_OK))
        self.assertTrue(any("installed" in a for a in shim_actions), shim_actions)


if __name__ == "__main__":
    unittest.main()
