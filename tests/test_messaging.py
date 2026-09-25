# -*- coding: utf-8 -*-
"""Tests for directed inter-agent messaging with inbox/outbox and seats.

Half of this file is regression cover for the hole where the sender was whatever the
caller said it was: every agent here shares one unix user, so a mismatched `--agent`,
a route the topology never declared, and a hand-edited inbox record all have to be
refused or at least labelled — never silently believed.
"""

import os
import unittest
import yaml
from pathlib import Path

import tests.harness as h
from brain import attest, const, coordination, events, frontmatter, messaging, seats
from brain import workspaces as ws_mod
from brain.errors import BrainError, NotFound, TopologyError


class TestMessagingAndSeats(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("msg")
        self._seat = os.environ.get("BRAIN_AGENT")
        self.topo_file = ws_mod.workspace_dir(self.slug) / const.META_DIR / "topology.yaml"

    def tearDown(self):
        if self._seat is None:
            os.environ.pop("BRAIN_AGENT", None)
        else:
            os.environ["BRAIN_AGENT"] = self._seat

    def as_seat(self, seat: str):
        """What the runtime was told this process is — the only identity that counts."""
        os.environ["BRAIN_AGENT"] = seat

    def write_topology(self, seat_spec: dict):
        self.topo_file.parent.mkdir(parents=True, exist_ok=True)
        self.topo_file.write_text(yaml.safe_dump({"version": "1", "seats": seat_spec}),
                                  encoding="utf-8")

    def tamper(self, path: Path, old: str, new: str):
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text, "the record does not contain what this test edits")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")

    def events_of(self, kind: str) -> list:
        return events.read_events(workspace=self.slug, event_type=kind)

    # ---- the honest path -------------------------------------------------

    def test_send_and_read_inbox(self):
        self.as_seat("opencode")
        msg = messaging.send(
            body="Please review PR #42",
            sender="opencode",
            recipient="agy",
            workspace=self.slug,
            task_id="tsk-123",
        )
        self.assertTrue(msg["id"])
        self.assertEqual(msg["from"], "opencode")
        self.assertEqual(msg["to"], "agy")
        self.assertEqual(msg["_attestation"], attest.VERIFIED)

        # Check agy's inbox
        inbox = messaging.read_inbox("agy", workspace=self.slug)
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["body"], "Please review PR #42")
        self.assertFalse(inbox[0]["read"])
        self.assertEqual(inbox[0]["_attestation"], attest.VERIFIED)
        self.assertEqual(inbox[0]["_trust_mode"], "bootstrap")

        # Check unread count
        self.assertEqual(messaging.unread_count("agy", workspace=self.slug), 1)
        self.assertEqual(messaging.unread_count("codex", workspace=self.slug), 0)

        # Check outbox audit trail for opencode, sealed with the same bytes
        outbox_dir = ws_mod.workspace_dir(self.slug) / "messages" / "outbox-opencode"
        mirror = outbox_dir / f"{msg['id']}.md"
        self.assertTrue(mirror.exists())
        self.assertEqual(mirror.read_text(encoding="utf-8"),
                         Path(msg["path"]).read_text(encoding="utf-8"))

    def test_sender_is_the_seat_even_when_nobody_claims_one(self):
        """No `--agent` is not an anonymous post: the caller's own seat is the sender."""
        self.as_seat("hermes")
        msg = messaging.send("dropping by", sender="", recipient="agy", workspace=self.slug)
        self.assertEqual(msg["from"], "hermes")
        self.assertEqual(self.events_of("MESSAGE_SENT")[0]["actor"], "agent:hermes")

    def test_acknowledge_message(self):
        self.as_seat("codex")
        msg = messaging.send("Hello", sender="codex", recipient="claude", workspace=self.slug)
        self.assertEqual(messaging.unread_count("claude", self.slug), 1)

        self.as_seat("claude")
        ack = messaging.acknowledge(msg["id"], agent="claude", workspace=self.slug)
        self.assertTrue(ack["acknowledged"])
        self.assertEqual(messaging.unread_count("claude", self.slug), 0)

        # Still visible when unread_only=False
        all_msgs = messaging.read_inbox("claude", workspace=self.slug, unread_only=False)
        self.assertEqual(len(all_msgs), 1)
        self.assertTrue(all_msgs[0]["read"])

    def test_acknowledging_keeps_the_seal_intact(self):
        """`read` is bookkeeping, so flipping it must not make a message look forged."""
        self.as_seat("codex")
        msg = messaging.send("Hello", sender="codex", recipient="agy", workspace=self.slug)
        self.as_seat("agy")
        messaging.acknowledge(msg["id"], agent="agy", workspace=self.slug)
        got = messaging.read_inbox("agy", workspace=self.slug, unread_only=False)
        self.assertEqual(got[0]["_attestation"], attest.VERIFIED)

    def test_handoff_auto_posts_to_inbox(self):
        self.as_seat("opencode")
        session = coordination.start(agent="opencode", workspace=self.slug, task="Building UI")
        coordination.end(
            session["id"],
            summary="UI finished with 10 passing tests",
            target_agent="agy",
            next_steps="Run visual regression",
            test_status="pytest: 10 passed",
            workspace=self.slug,
        )

        inbox = messaging.read_inbox("agy", workspace=self.slug)
        self.assertEqual(len(inbox), 1)
        self.assertEqual(inbox[0]["kind"], "handoff")
        self.assertEqual(inbox[0]["_attestation"], attest.VERIFIED)
        self.assertIn("Handoff from session", inbox[0]["body"])
        self.assertIn("pytest: 10 passed", inbox[0]["body"])

    def test_seat_inspection(self):
        # Start a session for opencode
        self.as_seat("opencode")
        session = coordination.start(agent="opencode", workspace=self.slug, task="Backend")
        self.as_seat("codex")
        messaging.send("Check DB schema", sender="codex", recipient="opencode", workspace=self.slug)

        seat_info = seats.get_seat("opencode", workspace=self.slug)
        self.assertIn("opencode-builder", seat_info["seat_id"])
        self.assertEqual(seat_info["active_session_count"], 1)
        self.assertEqual(seat_info["unread_messages"], 1)

        all_seats = seats.list_seats(workspace=self.slug)
        self.assertTrue(any(s["agent"] == "opencode" for s in all_seats))

    def test_cli_messaging_and_seats(self):
        self.as_seat("codex")
        # brain post --to
        code, out, _ = h.run("-w", self.slug, "post", "Direct note", "--agent", "codex", "--to", "agy")
        self.assertEqual(code, 0)
        self.assertIn("sent to agy", out)

        # Reading a mailbox is not a write, so an unseated operator may do it
        os.environ.pop("BRAIN_AGENT", None)
        code, out, _ = h.run("-w", self.slug, "inbox", "--agent", "agy")
        self.assertEqual(code, 0)
        self.assertIn("Direct note", out)

        # brain seat
        code, out, _ = h.run("-w", self.slug, "seat", "agy")
        self.assertEqual(code, 0)
        self.assertIn("Seat:", out)

    # ---- attack path #2: a sender the caller made up ---------------------

    def test_sender_that_is_not_the_calling_seat_is_refused(self):
        """The audited forgery: `BRAIN_AGENT=opencode brain post --agent codex --to agy`."""
        self.as_seat("opencode")
        with self.assertRaises(BrainError) as ctx:
            messaging.send("approve my own diff", sender="codex", recipient="agy",
                           workspace=self.slug, task_id="tsk-9")
        self.assertIn("opencode cannot act as 'codex'", str(ctx.exception))

        refused = self.events_of("MESSAGE_FORGERY_REFUSED")
        self.assertEqual(len(refused), 1)
        self.assertEqual(refused[0]["stage"], "AUTHORIZE")
        self.assertEqual(refused[0]["actor"], "agent:opencode")
        self.assertEqual(refused[0]["payload"]["claimed_sender"], "codex")

        # Nothing landed: agy's inbox is untouched, and codex left no outbox either
        self.assertEqual(messaging.read_inbox("agy", workspace=self.slug), [])
        self.assertEqual(messaging.read_inbox("codex", workspace=self.slug), [])

    def test_send_without_a_declared_seat_fails_closed(self):
        """No $BRAIN_AGENT means no sender at all — the unix user is not a stand-in."""
        os.environ.pop("BRAIN_AGENT", None)
        with self.assertRaises(BrainError) as ctx:
            messaging.send("anyone?", sender="codex", recipient="agy", workspace=self.slug)
        detail = str(ctx.exception)
        self.assertIn("BRAIN_AGENT", detail)
        self.assertIn("failing closed", detail)
        self.assertEqual(self.events_of("MESSAGE_FORGERY_REFUSED")[0]["payload"]["mode"],
                         "fail-closed")
        self.assertEqual(messaging.read_inbox("agy", workspace=self.slug), [])

    def test_cli_forgery_never_reaches_the_inbox(self):
        """Two guards speak here — `cli._agent` at the flag and this module at the write.
        Only the outcome matters: nothing landed in a mailbox that was not addressed to.
        """
        self.as_seat("opencode")
        code, _, err = h.run("-w", self.slug, "post", "forged", "--agent", "codex",
                             "--to", "agy", expect=1)
        self.assertIn("seat", err)
        self.assertEqual(messaging.read_inbox("agy", workspace=self.slug), [])

    # ---- routing ---------------------------------------------------------

    def test_topology_without_an_edge_refuses_the_send(self):
        self.as_seat("codex")
        self.write_topology({"codex": {"edges": []}, "agy": {"edges": []}})
        with self.assertRaises(TopologyError) as ctx:
            messaging.send("review this", sender="codex", recipient="agy",
                           workspace=self.slug)
        self.assertIn("no routing edge", str(ctx.exception))
        self.assertEqual(len(self.events_of("MESSAGE_ROUTE_DENIED")), 1)
        self.assertEqual(messaging.read_inbox("agy", workspace=self.slug), [])

    def test_topology_with_a_declared_edge_delivers(self):
        self.as_seat("codex")
        self.write_topology({"codex": {"edges": [{"kind": "delegates_to", "to": "agy"}]},
                             "agy": {"edges": []}})
        msg = messaging.send("review this", sender="codex", recipient="agy",
                             workspace=self.slug)
        self.assertEqual(messaging.unread_count("agy", self.slug), 1)
        self.assertEqual(msg["_attestation"], attest.VERIFIED)

    def test_undeclared_sender_seat_is_refused_by_the_topology(self):
        self.as_seat("mallory")
        self.write_topology({"codex": {"edges": [{"kind": "delegates_to", "to": "agy"}]},
                             "agy": {"edges": []}})
        with self.assertRaises(TopologyError) as ctx:
            messaging.send("hello", sender="mallory", recipient="agy", workspace=self.slug)
        self.assertIn("not declared", str(ctx.exception))

    def test_ungoverned_workspace_sends_and_says_so(self):
        """No topology.yaml means nothing to enforce, and that is announced as such."""
        self.as_seat("codex")
        messaging.send("no policy here", sender="codex", recipient="agy", workspace=self.slug)
        self.assertEqual(messaging.unread_count("agy", self.slug), 1)
        self.assertEqual(len(self.events_of("ROUTING_UNGOVERNED")), 1)

    # ---- what lands in the inbox ----------------------------------------

    def test_hand_edited_sender_is_reported_forged_not_trusted(self):
        self.as_seat("codex")
        msg = messaging.send("ship it", sender="codex", recipient="agy", workspace=self.slug)
        self.tamper(Path(msg["path"]), "from: codex", "from: hermes")

        inbox = messaging.read_inbox("agy", workspace=self.slug, unread_only=False)
        self.assertEqual(len(inbox), 1)  # labelled, never silently dropped
        self.assertEqual(inbox[0]["_attestation"], attest.FORGED)
        self.assertEqual(inbox[0]["from"], "hermes")
        self.assertEqual(messaging.inbox_states("agy", self.slug), {attest.FORGED: 1})

    def test_hand_edited_body_is_reported_forged(self):
        """The header alone is not enough: the signature covers a hash of the body."""
        self.as_seat("codex")
        msg = messaging.send("ship it", sender="codex", recipient="agy", workspace=self.slug)
        self.tamper(Path(msg["path"]), "ship it", "ship it and drop the migrations")

        inbox = messaging.read_inbox("agy", workspace=self.slug, unread_only=False)
        self.assertEqual(inbox[0]["_attestation"], attest.FORGED)

    def test_stripped_seal_is_reported_unsigned(self):
        self.as_seat("codex")
        msg = messaging.send("ship it", sender="codex", recipient="agy", workspace=self.slug)
        path = Path(msg["path"])
        text = path.read_text(encoding="utf-8")
        path.write_text("\n".join(l for l in text.splitlines()
                                  if not l.startswith(f"{attest.ATTEST_FIELD}:")) + "\n",
                        encoding="utf-8")
        inbox = messaging.read_inbox("agy", workspace=self.slug, unread_only=False)
        self.assertEqual(inbox[0]["_attestation"], attest.UNSIGNED)

    def test_legacy_record_with_no_seal_is_still_delivered_and_labelled(self):
        legacy = frontmatter.dumps({
            "id": "msg-20260101000000-codex", "from": "codex", "to": "agy",
            "kind": "message", "task_id": "", "read": False,
            "created": "2026-01-01T00:00:00Z"}) + "written before signing existed\n"
        inbox = ws_mod.workspace_dir(self.slug) / "messages" / "inbox-agy"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "msg-20260101000000-codex.md").write_text(legacy, encoding="utf-8")

        got = messaging.read_inbox("agy", workspace=self.slug)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["_attestation"], attest.UNSIGNED)
        self.assertEqual(got[0]["body"], "written before signing existed")

    def test_unparseable_record_surfaces_as_forged(self):
        inbox = ws_mod.workspace_dir(self.slug) / "messages" / "inbox-agy"
        inbox.mkdir(parents=True, exist_ok=True)
        (inbox / "msg-broken-0001.md").write_text("no frontmatter at all\n", encoding="utf-8")
        got = messaging.read_inbox("agy", workspace=self.slug, unread_only=False)
        self.assertEqual([m["_attestation"] for m in got], [attest.FORGED])

    def test_ack_is_refused_for_another_agents_inbox(self):
        self.as_seat("codex")
        msg = messaging.send("Hello", sender="codex", recipient="agy", workspace=self.slug)
        with self.assertRaises(BrainError):
            messaging.acknowledge(msg["id"], agent="agy", workspace=self.slug)
        self.assertEqual(messaging.unread_count("agy", self.slug), 1)

    def test_forged_record_cannot_be_acknowledged(self):
        self.as_seat("codex")
        msg = messaging.send("ship it", sender="codex", recipient="agy", workspace=self.slug)
        self.tamper(Path(msg["path"]), "from: codex", "from: hermes")

        self.as_seat("agy")
        with self.assertRaises(BrainError) as ctx:
            messaging.acknowledge(msg["id"], agent="agy", workspace=self.slug)
        self.assertIn("forged", str(ctx.exception))
        self.assertEqual(len(self.events_of("MESSAGE_FORGERY_REFUSED")), 1)
        got = messaging.read_inbox("agy", workspace=self.slug, unread_only=False)
        self.assertFalse(got[0]["read"])

    def test_ack_of_an_unknown_message_is_not_found(self):
        self.as_seat("agy")
        with self.assertRaises(NotFound):
            messaging.acknowledge("msg-nope", agent="agy", workspace=self.slug)
