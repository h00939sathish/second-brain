# -*- coding: utf-8 -*-
"""Tests for transcript retrieval and evidence receipt integration."""

import unittest
from pathlib import Path

import tests.harness as h
from brain import dispatch, evidence, store


class TestTranscript(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("tr")
        self.log_dir = dispatch.run_dir(self.slug)
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def test_get_transcript_and_filtering(self):
        log_file = self.log_dir / "tsk-test1.log"
        content = (
            "Line 1: starting task\n"
            "Line 2: \x1b[32mPASS\x1b[0m test_foo\n"
            "Line 3: \x1b[31mFAIL\x1b[0m test_bar\n"
            "Line 4: finished\n"
        )
        log_file.write_text(content, encoding="utf-8")

        # Basic get
        tr = dispatch.get_transcript("tsk-test1", workspace=self.slug)
        self.assertEqual(tr["total_lines"], 4)
        self.assertIn("PASS test_foo", tr["content"])
        self.assertNotIn("\x1b[32m", tr["content"])  # ANSI stripped

        # Tail
        tr_tail = dispatch.get_transcript("tsk-test1", workspace=self.slug, tail=2)
        self.assertEqual(len(tr_tail["lines"]), 2)
        self.assertEqual(tr_tail["lines"][-1], "Line 4: finished")

        # Grep
        tr_grep = dispatch.get_transcript("tsk-test1", workspace=self.slug, grep="FAIL")
        self.assertEqual(len(tr_grep["lines"]), 1)
        self.assertIn("FAIL test_bar", tr_grep["lines"][0])

    def test_record_receipt_with_transcript_log(self):
        log_file = self.log_dir / "tsk-rcpt.log"
        log_file.write_text("Execution step 1\nStep 2 OK\n", encoding="utf-8")

        rcpt = evidence.record_receipt(
            task_id="tsk-rcpt",
            command="pytest",
            exit_code=0,
            stdout="2 passed",
            workspace=self.slug,
            transcript_log=str(log_file),
        )
        self.assertTrue(rcpt["transcript_sha256"])
        self.assertIn("Step 2 OK", rcpt["transcript_excerpt"])

    def test_cli_transcript(self):
        log_file = self.log_dir / "tsk-cli.log"
        log_file.write_text("Hello from CLI transcript\n", encoding="utf-8")

        code, out, _ = h.run("-w", self.slug, "transcript", "tsk-cli")
        self.assertEqual(code, 0)
        self.assertIn("Hello from CLI transcript", out)
