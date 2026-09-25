# -*- coding: utf-8 -*-
"""The CLI surface itself: that every handler is reachable, that every flag it offers
does something, and that the deliberation room believes the seat rather than the name it
was handed.

Three bugs of one shape lived here. `cmd_deliberate` and `cmd_who_working` were the only
two of sixty handlers never registered, so `task-create --coordination-required` imposed
INV-008 on a card that no CLI command could clear — any agent could strand any card with
one flag, and the only exits were `--force` (rightly refused to agents) or importing the
library, which is the side door this milestone exists to shut.

Registering the verb is not enough on its own: the room recorded whatever sender it was
handed, so one process could fill a four-seat quorum by posting four names, and a
`--severity` list that offered `critical` but refused `blocking` let an objection look
terminal while `adjudicate` walked straight past it. An authorization that looks earned
and is not is the failure this file is here to catch, so it checks the flags against the
choices the gate actually honours, not against whatever the parser happens to advertise.
"""

import ast
import os
import pathlib
import re
import unittest

import tests.harness as h
from brain import cli, const, deliberation, events


def _surface():
    """(handlers defined, handlers registered, verbs the parser offers)."""
    src = pathlib.Path(cli.__file__).read_text(encoding="utf-8")
    defined = {node.name for node in ast.parse(src).body
               if isinstance(node, ast.FunctionDef) and node.name.startswith("cmd_")}
    block = src.split("HANDLERS = {")[1].split("\n}")[0]
    registered = set(re.findall(r":\s*(cmd_[a-z0-9_]+)", block))
    verbs = set(_parser_choices())
    return defined, registered, verbs


def _parser_choices():
    return cli.build_parser()._subparsers._group_actions[0].choices  # noqa: SLF001


def _deliberate_parser():
    return _parser_choices()["deliberate"]


class TestCliSurface(unittest.TestCase):
    def test_no_handler_is_defined_but_unreachable(self):
        defined, registered, _ = _surface()
        self.assertEqual(set(), defined - registered,
                         "a handler the CLI never dispatches to: whoever imposes what it "
                         "clears can impose it and nobody can satisfy it")

    def test_every_verb_dispatches_to_a_handler(self):
        _, registered, verbs = _surface()
        self.assertEqual(set(), {v for v in verbs if ("cmd_" + v.replace("-", "_")) not in registered},
                         "verbs in the parser with no entry in HANDLERS")

    def test_adjudication_has_no_force_flag_to_pick_up(self):
        """`adjudicate(force=True)` ignores objections and participants, so nothing on the
        command line may reach it."""
        options = _deliberate_parser()._option_string_actions  # noqa: SLF001
        self.assertEqual([], [o for o in options if "force" in o])

    def test_every_adjudication_choice_blocks_or_does_not(self):
        """A severity the room calls blocking must be one `adjudicate` honours — otherwise
        the parser advertises a gate that is not there."""
        blocking = {"high", "blocking"}
        self.assertTrue(blocking <= set(const.DELIBERATION_SEVERITIES))
        offered = set(_deliberate_parser()._option_string_actions["--severity"].choices)  # noqa: SLF001
        self.assertEqual(set(const.DELIBERATION_SEVERITIES), offered,
                         "--severity does not match the vocabulary the room stores")
        self.assertEqual([], sorted(offered - blocking - {"low", "medium"}),
                         "--severity offers a level that stops nothing")

    def test_no_flag_is_offered_that_the_handler_ignores(self):
        """Flags nobody reads are a UI that lies: the caller believes they said something."""
        options = {o.lstrip("-").replace("-", "_")
                   for o in _deliberate_parser()._option_string_actions}  # noqa: SLF001
        src = pathlib.Path(cli.__file__).read_text(encoding="utf-8")
        handler = src.split("def cmd_deliberate(")[1].split("\ndef cmd_")[0]
        unread = {name for name in options | {"action"}
                  if name not in {"workspace", "json", "all_workspaces"} and f'"{name}"' not in handler}
        self.assertEqual(set(), unread, "deliberate accepts flags cmd_deliberate never reads")


class TestDeliberationRoom(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("delib")
        self._seat = os.environ.get("BRAIN_AGENT")
        code, out, err = h.run("task-create", "--title", "needs a quorum", "--agent", "claude",
                              "--files", "wc.py", "--coordination-required", "-w", self.slug,
                              expect=None)
        self.assertEqual(0, code, out + err)
        self.task = re.search(r"(t-\d{8}-[0-9a-f]{6})", out).group(1)

    def tearDown(self):
        if self._seat is None:
            os.environ.pop("BRAIN_AGENT", None)
        else:
            os.environ["BRAIN_AGENT"] = self._seat

    def seat(self, name):
        """What the runtime was told this process is — the only identity the room accepts."""
        os.environ["BRAIN_AGENT"] = name

    def delib(self, *argv, seat="", expect=0):
        if seat:
            self.seat(seat)
        code, out, err = h.run("deliberate", *argv, "--task", self.task, "-w", self.slug,
                               expect=None)
        self.assertEqual(expect, code,
                         f"brain deliberate {' '.join(argv)} -> {code}\n{out}{err}")
        return out + err

    def move_to_running(self, seat="claude"):
        self.seat(seat)
        return h.run("move", self.task, "--status", "running", "--agent", "claude",
                     "-w", self.slug, expect=None)

    def test_a_stranded_card_is_unstranded_through_the_cli(self):
        """The point of the wiring: the gate fires, and the honest path clears it."""
        code, out, err = self.move_to_running()
        self.assertNotEqual(0, code, "coordination_required did not gate the card")
        self.assertIn("no Deliberation Record", out + err)

        self.delib("open", "--risk", "high", seat="operator")
        self.delib("propose", "--plan", "write it; test it", "--files", "wc.py", seat="claude")
        self.delib("object", "--body", "no rollback plan", "--severity", "blocking",
                   "--prop-id", "prop_01", seat="codex")
        self.assertIn("BLOCKED", self.delib("adjudicate", seat="operator"),
                      "a standing blocking objection did not stop consensus")

        obj_id = [m["message_id"] for m in deliberation.get_room(self.task, self.slug)["messages"]
                  if m["type"] == "OBJECTION"][0]
        self.delib("resolve", "--ref", obj_id, "--notes", "rollback staged", seat="codex")
        for name in ("opencode", "antigravity"):
            self.delib("post", "--body", "no objection", "--type", "ANSWER", seat=name)
        self.assertIn("AUTHORIZED", self.delib("adjudicate", seat="operator"),
                      "a full quorum could not close its own room")
        decision = deliberation.get_room(self.task, self.slug)["decision"]
        self.assertEqual("operator", decision["adjudicator"],
                         "the record does not say who adjudicated")

        code, out, err = self.move_to_running()
        self.assertEqual(0, code, out + err)

    def test_the_room_asks_only_for_names_a_seat_can_answer_with(self):
        """`antigravity` is an alias and messages record `agy`; asking for the alias left a
        high-risk room unreachable however honestly everyone behaved."""
        self.delib("open", "--risk", "high", "--participants", "antigravity,claude",
                   seat="operator")
        room = deliberation.get_room(self.task, self.slug)["context"]
        self.assertEqual(["agy", "claude"], room["required_participants"])

    def test_a_seat_cannot_fill_a_quorum_by_naming_the_others(self):
        self.delib("open", "--participants", "codex,claude", seat="operator")
        self.delib("propose", "--plan", "one step", seat="claude")
        text = self.delib("post", "--agent", "codex", "--body", "fine by me",
                          "--type", "ACKNOWLEDGEMENT", seat="claude", expect=1)
        self.assertIn("cannot act as", text)
        self.assertEqual(1, len(events.read_events(workspace=self.slug,
                                                   event_type="MESSAGE_FORGERY_REFUSED")),
                         "the forgery was refused but never audited")
        self.assertIn("did not contribute", self.delib("adjudicate", seat="operator"),
                      "claude spoke for codex after all")

    def test_presence_records_the_state_the_caller_asked_for(self):
        self.delib("open", seat="operator")
        self.delib("presence", "--state", "REVIEWING", "--focus", "the plan",
                   "--files", "wc.py", seat="claude")
        presence = deliberation.get_room(self.task, self.slug)["presence"]
        self.assertEqual("REVIEWING", presence["claude"]["state"])
        self.assertEqual(["wc.py"], presence["claude"]["files"])

    def test_resolution_notes_reach_the_record(self):
        self.delib("open", "--participants", "claude", seat="operator")
        self.delib("propose", "--plan", "one step", seat="claude")
        self.delib("object", "--body", "no test plan", "--severity", "high", seat="operator")
        obj_id = [m["message_id"] for m in deliberation.get_room(self.task, self.slug)["messages"]
                  if m["type"] == "OBJECTION"][0]
        self.delib("resolve", "--ref", obj_id, "--notes", "added the missing test",
                   seat="operator")
        last = deliberation.get_room(self.task, self.slug)["messages"][-1]
        self.assertIn("added the missing test", last["body"], "the resolution was thrown away")

    def test_no_seat_at_all_fails_closed_rather_than_guessing(self):
        os.environ.pop("BRAIN_AGENT", None)
        text = self.delib("propose", "--plan", "x", expect=1)
        self.assertIn("no $BRAIN_AGENT", text)

    def test_reading_a_room_needs_no_seat(self):
        self.delib("open", seat="operator")
        os.environ.pop("BRAIN_AGENT", None)
        text = self.delib()
        self.assertIn("OPEN", text)
        self.assertIn(self.task, text)

    def test_who_working_names_the_seat_behind_the_work(self):
        self.delib("open", seat="operator")
        self.delib("presence", "--focus", "the plan", "--files", "wc.py", seat="claude")
        code, out, err = h.run("who-working", "--task", self.task, "-w", self.slug, expect=None)
        self.assertEqual(0, code, out + err)
        self.assertIn("claude", out)
        self.assertIn("the plan", out)


if __name__ == "__main__":
    unittest.main()
