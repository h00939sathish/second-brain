# -*- coding: utf-8 -*-
"""Dispatch must be platform-neutral, and must never spawn a real agent in tests."""

import unittest
from unittest import mock

import tests.harness as h
from brain import agents, board, const, coordination, daemon, dispatch, store


class Portability(unittest.TestCase):
    def test_every_cli_spec_has_bins_and_args(self):
        for name, spec in const.AGENT_CLIS.items():
            self.assertTrue(spec["bins"], name)
            self.assertIsInstance(spec["args"], tuple, name)

    def test_unknown_agent_has_no_argv(self):
        self.assertIsNone(dispatch.cli_argv("definitely-not-an-agent"))

    def test_known_agent_resolves_to_an_absolute_path_when_installed(self):
        argv = dispatch.cli_argv("opencode")
        if argv is None:
            self.skipTest("opencode not installed on this machine")
        self.assertTrue(argv[0].startswith("/") or ":" in argv[0])
        self.assertIn("run", argv)

    def test_no_shell_or_powershell_is_used(self):
        """The old dispatcher required pwsh.exe and .cmd shims, which do not exist here.

        The module docstring explains that history, so only the code is inspected.
        """
        with open(dispatch.__file__, encoding="utf-8") as handle:
            source = handle.read()
        code = source.split('"""', 2)[-1]
        self.assertNotIn("pwsh", code)
        self.assertNotIn("Get-Content", code)
        self.assertNotIn("codex.cmd", code)

    def test_child_env_pins_vault_and_workspace(self):
        env = agents.child_env("some-workspace")
        self.assertEqual(env["SECOND_BRAIN_VAULT"], str(h.VAULT))
        self.assertEqual(env["SECOND_BRAIN_WORKSPACE"], "some-workspace")
        self.assertIn(str(agents.shim_path().parent), env["PATH"])


class Prompt(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("prompt")
        spec = board.create_spec(title="Spec", spec="Constraints here.", workspace=self.slug)
        self.card = board.create_task(title="Implement the widget", workspace=self.slug,
                                     project="jarvis", agent="opencode",
                                     spec_id=spec["id"], files="a.py,b.py")
        self.task = store.read_record("tasks", self.card["id"], self.slug)

    def test_prompt_carries_task_spec_and_protocol(self):
        text = dispatch.build_prompt(self.task, workspace=self.slug, agent="opencode")
        self.assertIn(self.card["id"], text)
        self.assertIn("Implement the widget", text)
        self.assertIn("Constraints here.", text)      # linked spec is inlined
        self.assertIn("brain start", text)
        self.assertIn("a.py,b.py", text)
        self.assertIn("Workspace: " + self.slug, text)

    def test_reviewer_prompt_tells_it_to_close_the_card(self):
        text = dispatch.build_prompt(self.task, workspace=self.slug, agent="agy")
        self.assertIn("brain move", text)
        self.assertIn("done", text)

    def test_planner_prompt_forbids_bulk_edits(self):
        text = dispatch.build_prompt(self.task, workspace=self.slug, agent="codex")
        self.assertIn("spec-create", text)
        self.assertIn("Do not edit", text.replace("\n", " "))


class DispatchFlow(unittest.TestCase):
    """`cat` stands in for an agent CLI: it consumes the prompt and exits."""

    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("flow")
        self.card = board.create_task(title="Do work", workspace=self.slug, agent="opencode",
                                     files="a.py")
        self.patcher = mock.patch.object(dispatch, "cli_argv", return_value=["/bin/cat"])
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_dispatch_opens_a_session_and_writes_a_run_record(self):
        result = dispatch.dispatch(self.card["id"], workspace=self.slug, wait=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["agent"], "opencode")
        session = store.read_record("sessions", result["session_id"], self.slug)
        self.assertEqual(session["fm"]["task_id"], self.card["id"])
        self.assertEqual(store.read_record("tasks", self.card["id"], self.slug)["fm"]["status"],
                         "running")

        run = dispatch.read_run_record(self.slug, self.card["id"])
        self.assertEqual(run["agent"], "opencode")
        self.assertEqual(run["returncode"], 0)

        from pathlib import Path
        self.assertIn("brain start", Path(run["prompt"]).read_text(encoding="utf-8"))

    def test_missing_cli_reports_instead_of_raising(self):
        self.patcher.stop()
        with mock.patch.object(dispatch, "cli_argv", return_value=None):
            result = dispatch.dispatch(self.card["id"], workspace=self.slug)
        self.assertFalse(result["ok"])
        self.assertIn("not found on PATH", result["detail"])

    def test_redispatched_card_reuses_its_session(self):
        first = dispatch.dispatch(self.card["id"], workspace=self.slug, wait=True)
        second = dispatch.dispatch(self.card["id"], workspace=self.slug, wait=True)
        self.assertEqual(first["session_id"], second["session_id"])
        sessions = [s for s in coordination.list_sessions(workspace=self.slug)
                    if str(s["fm"].get("task_id")) == self.card["id"]]
        self.assertEqual(len(sessions), 1)

    def test_auto_cycle_is_idle_on_an_empty_board(self):
        store.delete_record("tasks", self.card["id"], workspace=self.slug)
        result = daemon.auto_cycle(workspace=self.slug)
        self.assertEqual(result["action"], "idle")

    def test_auto_cycle_does_not_dispatch_a_card_that_is_already_in_flight(self):
        dispatch.dispatch(self.card["id"], workspace=self.slug, wait=True)  # leaves a session
        result = daemon.auto_cycle(workspace=self.slug)
        self.assertEqual(result["action"], "skip")
        self.assertIn("already in flight", result["detail"])

    def test_auto_cycle_dispatches_once_then_reports(self):
        coordination.end(dispatch.dispatch(self.card["id"], workspace=self.slug,
                                          wait=True)["session_id"], workspace=self.slug)
        daemon.clear_attempts(self.card["id"], self.slug)
        first = daemon.auto_cycle(workspace=self.slug)
        second = daemon.auto_cycle(workspace=self.slug)
        self.assertEqual(first["action"], "dispatch")
        self.assertEqual(second["action"], "skip")


class Heartbeat(unittest.TestCase):
    def test_first_run_stops_and_leaves_a_heartbeat(self):
        h.reset_vault()
        import contextlib
        import io
        with contextlib.redirect_stdout(io.StringIO()):
            code = daemon.run(interval=5, workspace=h.fresh_workspace("hb"), once=True)
        self.assertEqual(code, 0)
        self.assertTrue(daemon.read_heartbeat().get("stopped"))


if __name__ == "__main__":
    unittest.main()
