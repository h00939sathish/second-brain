# -*- coding: utf-8 -*-
"""Sessions, leases and the scratchpad — the concurrency guarantees."""

import unittest

import tests.harness as h
from brain import board, coordination, store
from brain.paths import stamp
from brain.errors import BrainError, LeaseConflict, NotFound


class Leases(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("coord")

    def test_start_leases_files(self):
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task="work", files="src/a.py,src/b.py")
        locks = store.build_locks([self.slug])
        self.assertEqual(sorted(locks), ["src/a.py", "src/b.py"])
        self.assertEqual(locks["src/a.py"]["agent"], "opencode")
        self.assertEqual(locks["src/a.py"]["session_id"], session["id"])

    def test_second_session_on_the_same_file_is_refused(self):
        coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        with self.assertRaises(LeaseConflict) as ctx:
            coordination.start(agent="claude", workspace=self.slug, files="src/a.py")
        self.assertIn("src/a.py", str(ctx.exception))
        self.assertIn("opencode", str(ctx.exception))

    def test_a_different_file_is_fine(self):
        coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        coordination.start(agent="claude", workspace=self.slug, files="src/c.py")
        self.assertEqual(len(coordination.list_sessions(workspace=self.slug, active_only=True)), 2)

    def test_force_overrides_a_lease_conflict(self):
        coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        session = coordination.start(agent="claude", workspace=self.slug, files="src/a.py",
                                     force=True)
        self.assertTrue(session["id"])

    def test_reserve_refuses_another_sessions_file(self):
        first = coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        second = coordination.start(agent="claude", workspace=self.slug)
        with self.assertRaises(LeaseConflict):
            coordination.reserve(second["id"], "src/a.py", workspace=self.slug)
        coordination.reserve(first["id"], "src/d.py", workspace=self.slug)
        self.assertIn("src/d.py", store.build_locks([self.slug]))

    def test_end_releases_the_lease(self):
        session = coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        coordination.end(session["id"], summary="done", workspace=self.slug)
        self.assertEqual(store.build_locks([self.slug]), {})
        record = store.read_record("sessions", session["id"], self.slug)
        self.assertEqual(record["fm"]["status"], "ended")
        self.assertEqual(record["fm"]["lease_expires"], "")

    def test_expired_lease_is_not_a_lock(self):
        session = coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        record = store.read_record("sessions", session["id"], self.slug)
        record["fm"]["lease_expires"] = stamp(minutes=-5)
        store.update_record("sessions", record, workspace=self.slug)
        self.assertEqual(store.build_locks([self.slug]), {})

    def test_inactive_session_holds_nothing(self):
        session = coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        record = store.read_record("sessions", session["id"], self.slug)
        record["fm"]["status"] = "stale"
        store.update_record("sessions", record, workspace=self.slug)
        self.assertEqual(store.build_locks([self.slug]), {})

    def test_check_files_reports_conflicts(self):
        coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        conflicts = coordination.check_files("src/a.py,src/z.py", workspace=self.slug)
        self.assertEqual([f for f, _ in conflicts], ["src/a.py"])

    def test_update_records_progress_and_extends_lease(self):
        session = coordination.start(agent="opencode", workspace=self.slug, files="src/a.py",
                                     lease_mins=5)
        coordination.update(session["id"], progress="halfway", extend_lease=120,
                            workspace=self.slug)
        record = store.read_record("sessions", session["id"], self.slug)
        self.assertIn("halfway", record["body"])
        self.assertGreater(store.build_locks([self.slug])["src/a.py"]["remaining_mins"], 100)

    def test_ending_an_unknown_session_fails(self):
        with self.assertRaises(NotFound):
            coordination.end("s-20200101-nope", workspace=self.slug)

    def test_session_cannot_be_updated_after_it_ends(self):
        session = coordination.start(agent="opencode", workspace=self.slug)
        coordination.end(session["id"], workspace=self.slug)
        with self.assertRaises(BrainError):
            coordination.update(session["id"], progress="late", workspace=self.slug)

    def test_expire_stale_closes_abandoned_sessions(self):
        session = coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        record = store.read_record("sessions", session["id"], self.slug)
        record["fm"]["updated"] = "2020-01-01T00:00:00Z"
        store.update_record("sessions", record, workspace=self.slug)
        changed = coordination.expire_stale(workspace=self.slug, hours=1)
        self.assertEqual([c[0] for c in changed], [session["id"]])
        self.assertEqual(store.build_locks([self.slug]), {})

    def test_handoff_is_routed_to_review(self):
        card = board.create_task(title="card", workspace=self.slug, agent="opencode")
        session = coordination.start(agent="opencode", workspace=self.slug,
                                     task_id=card["id"], files="a.py")
        coordination.end(session["id"], summary="built it", target_agent="antigravity",
                         test_status="pytest: 3 passed", workspace=self.slug)
        record = store.read_record("tasks", card["id"], self.slug)
        self.assertEqual(record["fm"]["status"], "review")
        self.assertEqual(record["fm"]["agent"], "opencode")


class Scratchpad(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("pad")

    def test_post_and_read(self):
        coordination.post("the build takes 90s", workspace=self.slug, agent="opencode",
                          tags="ci,perf")
        notes = coordination.read_notes(workspace=self.slug)
        self.assertEqual(len(notes), 1)
        self.assertIn("90s", notes[0]["body"])
        self.assertEqual(notes[0]["agent"], "opencode")

    def test_notes_are_workspace_scoped(self):
        other = h.fresh_workspace("pad-other")
        coordination.post("jarvis note", workspace=self.slug)
        coordination.post("titan note", workspace=other)
        self.assertEqual(len(coordination.read_notes(workspace=self.slug)), 1)
        self.assertEqual(len(coordination.read_notes(workspace=self.slug,
                                                     all_workspaces=True)), 2)

    def test_empty_note_rejected(self):
        with self.assertRaises(BrainError):
            coordination.post("   ", workspace=self.slug)

    def test_archiving_respects_promotion(self):
        old = coordination.post("old note", workspace=self.slug)
        record = store.read_record("context", old["id"], self.slug)
        record["fm"]["created"] = "2020-01-01T00:00:00Z"
        store.update_record("context", record, workspace=self.slug)
        changed = coordination.archive_old_notes(days=7)
        self.assertEqual([c[0] for c in changed], [old["id"]])


class GuardHook(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("guard")

    def test_guard_refuses_without_a_session(self):
        code, _, err = h.run("guard", "--agent", "opencode", "-w", self.slug, expect=None)
        self.assertEqual(code, 1)
        self.assertIn("BLOCKED", err)

    def test_guard_allows_when_a_session_is_open(self):
        coordination.start(agent="opencode", workspace=self.slug)
        code, _, _ = h.run("guard", "--agent", "opencode", "-w", self.slug, expect=None)
        self.assertEqual(code, 0)

    def test_another_agents_session_does_not_authorise_your_write(self):
        """The old rule was "any active session in this workspace", which meant a second
        agent could write freely under the first agent's session and leases meant nothing."""
        coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        code, _, _ = h.run("guard", "--agent", "claude", "-w", self.slug, expect=None)
        self.assertEqual(code, 1)

    def test_a_lease_on_a_different_file_does_not_block(self):
        coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        code, _, _ = h.run("guard", "--agent", "claude", "-w", self.slug,
                           "--files", "src/b.py", expect=None)
        self.assertEqual(code, 0)

    def test_guard_refuses_the_leased_file_specifically(self):
        coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        code, _, err = h.run("guard", "--agent", "claude", "-w", self.slug,
                             "--files", "src/a.py,src/q.py", expect=None)
        self.assertEqual(code, 1)
        self.assertIn("src/a.py", err)
        self.assertIn("opencode", err)
        reason = err.split("\n")[0]
        self.assertNotIn("src/q.py", reason)   # only the actual conflict is named

    def test_operator_session_clears_the_guard_for_everyone(self):
        coordination.start(agent="operator", workspace=self.slug)
        code, _, _ = h.run("guard", "--agent", "claude", "-w", self.slug, expect=None)
        self.assertEqual(code, 0)

    def test_admit_explains_itself(self):
        decision = coordination.admit("claude", workspace=self.slug)
        self.assertFalse(decision["ok"])
        self.assertIn("no active session", decision["reason"])
        coordination.start(agent="claude", workspace=self.slug, files="a.py")
        decision = coordination.admit("claude", files="a.py", workspace=self.slug)
        self.assertTrue(decision["ok"])
        self.assertTrue(decision["session"])

    def test_guard_reads_files_from_a_hook_json_payload(self):
        """Claude Code pipes `{tool_input:{file_path}}` on stdin; the guard has to use it
        or every edit in a workspace someone else is using gets blocked."""
        import io
        import json as _json
        import sys
        coordination.start(agent="opencode", workspace=self.slug, files="src/a.py")
        payload = _json.dumps({"tool_name": "Edit",
                               "tool_input": {"file_path": "src/b.py"}})
        stdin, sys.stdin = sys.stdin, io.StringIO(payload)
        try:
            code, _, _ = h.run("guard", "--agent", "claude", "-w", self.slug,
                               "--stdin-json", expect=None)
        finally:
            sys.stdin = stdin
        self.assertEqual(code, 0)

    def test_topic_filtering(self):
        coordination.post("General note", workspace=self.slug)
        coordination.post("Auth note 1", workspace=self.slug, topic="auth-v2")
        coordination.post("Auth note 2", workspace=self.slug, topic="auth-v2")
        coordination.post("Billing note", workspace=self.slug, topic="billing")

        all_notes = coordination.read_notes(workspace=self.slug)
        self.assertEqual(len(all_notes), 4)

        auth_notes = coordination.read_notes(workspace=self.slug, topic="auth-v2")
        self.assertEqual(len(auth_notes), 2)
        for n in auth_notes:
            self.assertEqual(n["topic"], "auth-v2")

        billing_notes = coordination.read_notes(workspace=self.slug, topic="billing")
        self.assertEqual(len(billing_notes), 1)
        self.assertEqual(billing_notes[0]["topic"], "billing")

    def test_wait_for_notes_returns_matching(self):
        before = coordination.post("Initial note", workspace=self.slug, topic="chat")
        new_note = coordination.post("Reply note", workspace=self.slug, topic="chat")

        found = coordination.wait_for_notes(workspace=self.slug, topic="chat",
                                            after=before["id"], timeout=2)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["id"], new_note["id"])

    def test_wait_for_notes_times_out_when_no_match(self):
        found = coordination.wait_for_notes(workspace=self.slug, topic="nonexistent", timeout=1)
        self.assertEqual(found, [])

    def test_cli_wait_command_timeout(self):
        code, _, err = h.run("wait", "--topic", "nonexistent", "--timeout", "1",
                             "-w", self.slug, expect=None)
        self.assertEqual(code, 1)
        self.assertIn("Timed out", err)


if __name__ == "__main__":
    unittest.main()
