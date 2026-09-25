# -*- coding: utf-8 -*-
"""Tests for Mission Control HTTP API."""

import json
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

import tests.harness as h
from brain import board, http


class TestHttpApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), http.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("httpws")

    def _url(self, path):
        return f"http://127.0.0.1:{self.port}{path}"

    def _get(self, path):
        req = urllib.request.Request(self._url(path), method="GET")
        with urllib.request.urlopen(req) as resp:
            data = resp.read().decode("utf-8")
            return resp.status, json.loads(data) if "application/json" in resp.headers.get("Content-Type", "") else data

    def _post(self, path, payload):
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self._url(path), data=body, method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def test_squad_endpoints(self):
        status, data = self._get(f"/api/squad?workspace={self.slug}")
        self.assertEqual(200, status)
        self.assertEqual(self.slug, data["workspace"])
        self.assertIn("roles", data)

        # Set role
        status, post_res = self._post("/api/squad/role", {
            "role": "builder",
            "agent": "claude",
            "workspace": self.slug,
        })
        self.assertEqual(200, status)
        self.assertTrue(post_res["success"])
        self.assertEqual("claude", post_res["roles"]["builder"])

        # Re-fetch squad
        status, data = self._get(f"/api/squad?workspace={self.slug}")
        self.assertEqual(200, status)
        self.assertEqual("claude", data["roles"]["builder"])

    def test_notes_chatroom_endpoints(self):
        # Post note with topic
        status, res = self._post("/api/notes", {
            "text": "Meeting notes for architecture sync",
            "agent": "agy",
            "topic": "architecture",
            "workspace": self.slug,
        })
        self.assertEqual(200, status)
        self.assertTrue(res["success"])

        # Read notes filtered by topic
        status, notes = self._get(f"/api/notes?workspace={self.slug}&topic=architecture")
        self.assertEqual(200, status)
        self.assertEqual(1, len(notes))
        self.assertEqual("architecture", notes[0]["topic"])
        self.assertEqual("Meeting notes for architecture sync", notes[0]["text"])

    def test_deliberation_flow_endpoints(self):
        # Create a task first
        t = board.create_task("Deliberation test task", workspace=self.slug, agent="claude")
        task_id = t["id"]

        # Open deliberation room
        status, res = self._post("/api/deliberation/open", {
            "task_id": task_id,
            "workspace": self.slug,
            "risk": "normal",
        })
        self.assertEqual(200, status)
        self.assertTrue(res["success"])

        # Get room
        status, room = self._get(f"/api/deliberation?task={task_id}&workspace={self.slug}")
        self.assertEqual(200, status)
        self.assertEqual(task_id, room["context"]["task_id"])
        self.assertEqual("OPEN", room["context"]["status"])

        # Post message to room
        status, post_msg = self._post("/api/deliberation/post", {
            "task_id": task_id,
            "sender": "agy",
            "type": "QUESTION",
            "body": "Ready to coordinate on this task.",
            "workspace": self.slug,
        })
        self.assertEqual(200, status)
        self.assertTrue(post_msg["success"])

        # Adjudicate (blocked because no proposals submitted yet)
        status, adj = self._post("/api/deliberation/adjudicate", {
            "task_id": task_id,
            "workspace": self.slug,
        })
        self.assertEqual(409, status)
        self.assertFalse(adj["ok"])
        self.assertEqual("BLOCKED", adj["status"])
