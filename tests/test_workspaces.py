# -*- coding: utf-8 -*-
"""Workspaces are how JARVIS work stays out of TITAN work."""

import tempfile
import unittest
from pathlib import Path

import tests.harness as h
from brain import const, workspaces as ws_mod


class Slugs(unittest.TestCase):
    def test_slugify(self):
        self.assertEqual(ws_mod.slugify("Project TITAN"), "project-titan")
        self.assertEqual(ws_mod.slugify("JARVIS"), "jarvis")
        self.assertEqual(ws_mod.slugify("  weird///name  "), "weird-name")
        self.assertEqual(ws_mod.slugify(""), const.GLOBAL_WORKSPACE)

    def test_resolve_alias_by_name_and_alias(self):
        h.reset_vault()
        slug = ws_mod.register("JARVIS Voice", path=str(h.VAULT / "j"),
                              aliases=["jarvis", "voice-assistant"])
        self.assertEqual(ws_mod.resolve_alias("jarvis"), slug)
        self.assertEqual(ws_mod.resolve_alias("JARVIS Voice"), slug)
        self.assertEqual(ws_mod.resolve_alias("voice-assistant"), slug)
        self.assertEqual(ws_mod.resolve_alias("jarvis-voice"), slug)


class Detection(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("detect")

    def test_marker_file_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            nested = Path(tmp) / "a" / "b"
            nested.mkdir(parents=True)
            Path(tmp, const.WORKSPACE_MARKER).write_text(self.slug + "\n")
            self.assertEqual(ws_mod.detect(cwd=nested), self.slug)

    def test_registered_path_prefix(self):
        path = Path(ws_mod.entry(self.slug)["path"])
        nested = path / "src" / "deep"
        nested.mkdir(parents=True, exist_ok=True)
        self.assertEqual(ws_mod.detect(cwd=nested), self.slug)

    def test_unbound_directory_falls_back_to_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(ws_mod.detect(cwd=tmp), ws_mod.default_workspace())

    def test_explicit_beats_everything(self):
        self.assertEqual(ws_mod.detect(cwd="/tmp", explicit=self.slug), self.slug)

    def test_env_var(self):
        self.assertEqual(ws_mod.detect(cwd="/tmp", explicit=""), ws_mod.default_workspace())


class Scoping(unittest.TestCase):
    def test_read_scope_includes_global(self):
        self.assertEqual(ws_mod.read_scope("jarvis"), ["jarvis", const.GLOBAL_WORKSPACE])
        self.assertEqual(ws_mod.read_scope(const.GLOBAL_WORKSPACE), [const.GLOBAL_WORKSPACE])

    def test_write_scope_promotes_to_global(self):
        self.assertEqual(ws_mod.write_scope("jarvis", "global"), const.GLOBAL_WORKSPACE)
        self.assertEqual(ws_mod.write_scope("jarvis"), "jarvis")

    def test_bind_directory_writes_marker(self):
        h.reset_vault()
        slug = h.fresh_workspace("bind")
        with tempfile.TemporaryDirectory() as tmp:
            actions = ws_mod.bind_directory(slug, tmp)
            marker = Path(tmp) / const.WORKSPACE_MARKER
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.read_text().strip(), slug)
            self.assertTrue(any("marker" in a for a in actions))


if __name__ == "__main__":
    unittest.main()
