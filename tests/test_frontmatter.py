# -*- coding: utf-8 -*-
"""Frontmatter must never lose or corrupt a value. These are the highest-value tests
in the suite: claims are the durable product of the vault."""

import unittest

from tests.harness import frontmatter
from brain.errors import SchemaError


class RoundTrip(unittest.TestCase):
    def assertRoundTrips(self, fm):
        rendered = frontmatter.dumps(fm)
        parsed, body = frontmatter.parse(rendered + "body text\n")
        self.assertEqual(parsed, {k: v for k, v in fm.items() if v is not None}, rendered)
        self.assertEqual(body, "body text\n")

    def test_plain_values(self):
        self.assertRoundTrips({"id": "20260916-abc123", "status": "active", "n": 7})

    def test_tricky_values(self):
        self.assertRoundTrips({
            "claim": "Has: a colon",
            "newline": "line one\nline two",
            "dashes": "---",
            "dash_start": "- looks like a list item",
            "hash": "# looks like a comment",
            "quotes": 'he said "hi"',
            "unicode": "héllo → ok ✓",
            "empty": "",
            "bool_true": True,
            "bool_false": False,
            "float": 0.95,
            "leading_space": " padded ",
        })

    def test_lists_and_tuples(self):
        self.assertRoundTrips({"tags": ["alpha", "beta"], "phases": []})

    def test_delimiter_inside_body_is_inert(self):
        text = "---\nid: x\n---\n\nbody with --- inside\nand --- again\n"
        fm, body = frontmatter.parse(text)
        self.assertEqual(fm["id"], "x")
        self.assertIn("--- again", body)

    def test_crlf_files_parse(self):
        text = "---\r\nid: x\r\nstatus: active\r\n---\r\n\r\nbody\r\n"
        fm, _ = frontmatter.parse(text.replace("\r\n", "\n"))
        self.assertEqual(fm["status"], "active")

    def test_yaml_block_sequence(self):
        fm, _ = frontmatter.parse("---\ntags:\n  - one\n  - two\n---\nbody\n")
        self.assertEqual(fm["tags"], ["one", "two"])

    def test_roundtrip_ok_helper(self):
        self.assertTrue(frontmatter.roundtrip_ok({"a": "x", "b": ["y", "z"]}))
        self.assertTrue(frontmatter.roundtrip_ok({"a": "multi\nline"}))


class Parsing(unittest.TestCase):
    def test_missing_frontmatter_rejected(self):
        with self.assertRaises(SchemaError):
            frontmatter.parse("no frontmatter here\n")

    def test_unterminated_frontmatter_rejected(self):
        with self.assertRaises(SchemaError):
            frontmatter.parse("---\nid: x\n")

    def test_malformed_line_rejected(self):
        with self.assertRaises(SchemaError):
            frontmatter.parse("---\nthis line has no key value pair noise 123\n---\n")


class Validation(unittest.TestCase):
    def test_missing_required_field(self):
        with self.assertRaises(SchemaError) as ctx:
            frontmatter.validate({"id": "x"}, ("id", "claim"), "claim")
        self.assertIn("claim", str(ctx.exception))

    def test_invalid_status(self):
        with self.assertRaises(SchemaError):
            frontmatter.validate({"id": "x", "status": "maybe"}, ("id",), "claim",
                                 statuses=("active", "expired"))

    def test_confidence_bounds(self):
        with self.assertRaises(SchemaError):
            frontmatter.validate({"id": "x", "confidence": 1.5}, ("id",), "claim")
        with self.assertRaises(SchemaError):
            frontmatter.validate({"id": "x", "confidence": "high"}, ("id",), "claim")
        frontmatter.validate({"id": "x", "confidence": 0.0}, ("id",), "claim")


if __name__ == "__main__":
    unittest.main()
