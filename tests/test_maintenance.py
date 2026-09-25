# -*- coding: utf-8 -*-
"""Recovery and housekeeping: repairing corruption, clearing dangling links, sweep."""

import unittest

import tests.harness as h
from brain import frontmatter, index, knowledge, maintenance, store, workspaces as ws_mod


class Repair(unittest.TestCase):
    """The old writer emitted unquoted values, so any newline in a value split the
    frontmatter and made the record unreadable. That is how two claims in the real
    vault were lost."""

    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("repair")

    def corrupt(self, name="20260101-aaaaaa"):
        path = store.record_path("claims", name, self.slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "---\n"
            f"id: {name}\n"
            "claim: the headline\n"
            "status: active\n"
            "confidence: 0.9\n"
            "created: 2026-01-01T00:00:00Z\n"
            "reviewed_at: ''\n"
            "source: legacy\n"
            "tags: a,b\n"
            "TITAN FX: prose that leaked into the block\n"
            "another stray: line\n"
            "---\n\nbody text\n",
            encoding="utf-8",
        )
        return path

    def test_corrupt_file_does_not_parse(self):
        path = self.corrupt()
        with self.assertRaises(Exception):
            frontmatter.parse_file(path)

    def test_repair_keeps_schema_keys_and_moves_prose_to_the_body(self):
        path = self.corrupt()
        ok, detail = store.repair_malformed(path, kind="claims")
        self.assertTrue(ok, detail)
        record = frontmatter.parse_file(path)
        self.assertEqual(record["fm"]["id"], "20260101-aaaaaa")
        self.assertEqual(record["fm"]["status"], "active")
        self.assertNotIn("TITAN FX", record["fm"])
        self.assertIn("TITAN FX: prose that leaked into the block", record["body"])
        self.assertIn("another stray: line", record["body"])
        self.assertIn("body text", record["body"])          # nothing discarded

    def test_original_is_quarantined(self):
        path = self.corrupt()
        store.repair_malformed(path, kind="claims")
        quarantine = store.VAULT / "meta" / "quarantine"
        self.assertTrue(list(quarantine.glob("*20260101-aaaaaa*")))

    def test_repair_refuses_a_file_it_does_not_understand(self):
        path = store.record_path("claims", "20260101-bbbbbb", self.slug)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\njust a sentence with no keys at all\n---\nbody\n", encoding="utf-8")
        ok, detail = store.repair_malformed(path, kind="claims")
        self.assertFalse(ok)
        self.assertIn("no recognised schema keys", detail)

    def test_dry_run_changes_nothing(self):
        path = self.corrupt()
        before = path.read_text(encoding="utf-8")
        ok, detail = store.repair_malformed(path, kind="claims", dry_run=True)
        self.assertTrue(ok)
        self.assertIn("would", detail)
        self.assertEqual(path.read_text(encoding="utf-8"), before)


class DanglingLinks(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("dangle")

    def test_verify_finds_and_fix_clears_a_dangling_link(self):
        claim = knowledge.add("points at a ghost", workspace=self.slug)
        record = store.read_record("claims", claim["id"], self.slug)
        record["fm"]["promoted_from"] = "ctx-20200101-ghost"
        store.update_record("claims", record, workspace=self.slug)

        self.assertTrue(knowledge.chain_issues(claim["id"]))

        cleared = knowledge.clear_dangling(claim["id"])
        self.assertEqual(cleared, ["promoted_from -> ctx-20200101-ghost"])
        self.assertEqual(knowledge.chain_issues(claim["id"]), [])
        record = store.read_record("claims", claim["id"], self.slug)
        self.assertEqual(record["fm"]["promoted_from"], "")
        self.assertIn("dangling reference(s) cleared", record["body"])


class Sweep(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("sweep")

    def test_sweep_reports_never_reviewed_claims(self):
        knowledge.add("unchecked", workspace=self.slug)
        changed = maintenance.sweep(quiet=True)
        self.assertTrue(any("never reviewed" in why for _, why in changed), changed)

    def test_sweep_flags_a_claim_whose_review_is_old(self):
        claim = knowledge.add("old news", workspace=self.slug)
        knowledge.review(claim["id"])
        record = store.read_record("claims", claim["id"], self.slug)
        record["fm"]["reviewed_at"] = "2020-01-01T00:00:00Z"
        store.update_record("claims", record, workspace=self.slug)
        changed = maintenance.sweep(quiet=True)
        self.assertTrue(any(claim["id"] == cid and "stale" in why for cid, why in changed),
                        changed)

    def test_sweep_regenerates_the_brief(self):
        maintenance.sweep(quiet=True)
        self.assertTrue((ws_mod.workspace_dir(self.slug) / "l0_pointers.md").is_file())


class IndexRebuild(unittest.TestCase):
    def test_schema_change_is_detected_and_rebuilt(self):
        """A vault indexed by an older build must not keep an incompatible table."""
        h.reset_vault()
        slug = h.fresh_workspace("index")
        claim = knowledge.add("searchable fact about widgets", workspace=slug)
        index.init()
        index.reindex_doc("claims", slug, store.record_path("claims", claim["id"], slug),
                          {"id": claim["id"], "claim": "searchable fact about widgets"},
                          "body")
        rows = index.search("claims", query="widgets", workspace=[slug])
        self.assertTrue(rows)
        self.assertEqual(rows[0]["id"], claim["id"])

        # Simulate an old-format database.
        import sqlite3
        conn = sqlite3.connect(str(index.db_path()))
        conn.execute("UPDATE index_meta SET value = '1' WHERE key = 'schema_version'")
        conn.commit()
        conn.close()
        index.init()
        rows = index.search("claims", query="widgets", workspace=[slug])
        self.assertEqual(rows, [])
        index.reindex_all()
        rows = index.search("claims", query="widgets", workspace=[slug])
        self.assertTrue(rows)


class MigrateInference(unittest.TestCase):
    def test_project_field_wins(self):
        from brain.cli import infer_workspace
        h.reset_vault()
        ws_mod.register("titan", path="/tmp/titan", display_name="Project TITAN",
                        aliases=["project-titan"])
        self.assertEqual(infer_workspace({"project": "Project TITAN"}), "titan")
        self.assertEqual(infer_workspace({"project": "project-titan"}), "titan")

    def test_text_inference_falls_back_to_global(self):
        from brain.cli import infer_workspace
        h.reset_vault()
        ws_mod.register("jarvis", path="/tmp/jarvis", display_name="JARVIS",
                        aliases=["jarvis-voice"])
        self.assertEqual(infer_workspace({"tags": "jarvis,audio"}, ""), "jarvis")
        self.assertEqual(infer_workspace({"tags": "misc", "claim": "nothing relevant"}), "global")


class Merge(unittest.TestCase):
    def test_merge_moves_records_and_drops_the_source(self):
        h.reset_vault()
        source = h.fresh_workspace("src")
        target = h.fresh_workspace("dst")
        knowledge.add("moves over", workspace=source)
        h.run("ws", "merge", source, target)
        self.assertNotIn(source, ws_mod.all_slugs())
        found, _ = knowledge.recall(query="moves", workspace=target)
        self.assertTrue(found)


if __name__ == "__main__":
    unittest.main()
