# -*- coding: utf-8 -*-
"""Reclassification and brief ranking: keeping the right knowledge in front of the
right agent."""

import unittest

import tests.harness as h
from brain import const, knowledge, l0, store, workspaces as ws_mod


class Reclassify(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.widget = ws_mod.register("widget", path=str(h.VAULT / "projects" / "widget"),
                                      display_name="Widget Project",
                                      aliases=["widget-voice"],
                                      keywords="gadget,sprocket")
        ws_mod.ensure_workspace_dirs(self.widget)

    def test_record_naming_the_project_moves(self):
        claim = knowledge.add("The sprocket validates every gadget before sealing",
                              workspace=const.GLOBAL_WORKSPACE)
        moved, kept = knowledge.reclassify(const.GLOBAL_WORKSPACE)
        self.assertEqual([m["id"] for m in moved], [claim["id"]])
        self.assertEqual(moved[0]["to"], self.widget)
        record = store.read_record("claims", claim["id"], self.widget)
        self.assertIsNotNone(record)
        self.assertIsNone(store.read_record("claims", claim["id"], const.GLOBAL_WORKSPACE))
        self.assertEqual(record["fm"]["scope"], "workspace")

    def test_unrelated_record_stays_shared(self):
        claim = knowledge.add("Postgres listens on 5433 with a pool of 10",
                              workspace=const.GLOBAL_WORKSPACE)
        moved, kept = knowledge.reclassify(const.GLOBAL_WORKSPACE)
        self.assertEqual(moved, [])
        self.assertEqual(kept, 1)
        self.assertIsNotNone(store.read_record("claims", claim["id"],
                                              const.GLOBAL_WORKSPACE))

    def test_a_single_generic_keyword_is_not_enough(self):
        claim = knowledge.add("we should order a sprocket at some point",
                              workspace=const.GLOBAL_WORKSPACE)
        moved, _ = knowledge.reclassify(const.GLOBAL_WORKSPACE)
        self.assertEqual(moved, [], "one keyword hit is too weak a signal to relocate")
        self.assertIsNotNone(store.read_record("claims", claim["id"],
                                               const.GLOBAL_WORKSPACE))

    def test_body_text_alone_does_not_relocate_a_record(self):
        """Long environment notes mention every project; that must not decide scope."""
        claim = knowledge.add("Machine inventory", workspace=const.GLOBAL_WORKSPACE,
                              evidence="widget project gadget sprocket " * 40)
        moved, _ = knowledge.reclassify(const.GLOBAL_WORKSPACE)
        self.assertEqual(moved, [])
        self.assertIsNotNone(store.read_record("claims", claim["id"],
                                              const.GLOBAL_WORKSPACE))

    def test_dry_run_changes_nothing(self):
        claim = knowledge.add("The sprocket validates every gadget",
                              workspace=const.GLOBAL_WORKSPACE)
        moved, _ = knowledge.reclassify(const.GLOBAL_WORKSPACE, dry_run=True)
        self.assertEqual(len(moved), 1)
        self.assertIsNotNone(store.read_record("claims", claim["id"],
                                              const.GLOBAL_WORKSPACE))


class BriefRanking(unittest.TestCase):
    def test_own_workspace_outranks_shared_truth(self):
        h.reset_vault()
        slug = h.fresh_workspace("rank")
        knowledge.add("shared fact about the build pipeline",
                      workspace=const.GLOBAL_WORKSPACE)
        knowledge.add("project fact about the build pipeline", workspace=slug)
        text = l0.render(slug)
        own = text.index("project fact about the build pipeline")
        shared = text.index("shared fact about the build pipeline")
        self.assertLess(own, shared,
                        "a workspace brief must lead with its own work, not shared noise")

    def test_brief_truncates_on_a_word_boundary_and_counts_correctly(self):
        h.reset_vault()
        slug = h.fresh_workspace("clip")
        for i in range(40):
            knowledge.add(f"claim number {i} " + ("padding words " * 20), workspace=slug)
        text = l0.render(slug)
        self.assertIn("more — run `brain recall", text)
        for line in text.splitlines():
            self.assertNotIn("…w", line.replace("… ", ""), "truncation split a word")

    def test_brief_stays_within_budget(self):
        h.reset_vault()
        slug = h.fresh_workspace("budget")
        for i in range(60):
            knowledge.add(f"a fairly long claim about topic {i} " + ("word " * 30),
                          workspace=slug)
        size = len(l0.render(slug).encode("utf-8"))
        self.assertLessEqual(size, const.L0_BUDGET, f"brief is {size}B")


class Identity(unittest.TestCase):
    def test_replace_narrows_keywords(self):
        h.reset_vault()
        slug = ws_mod.register("narrow", path=str(h.VAULT / "narrow"))
        ws_mod.set_identity(slug, keywords="alpha,beta")
        ws_mod.set_identity(slug, keywords="gamma", replace=True)
        self.assertEqual(ws_mod.entry(slug)["keywords"], ["gamma"])

    def test_merge_is_additive_by_default(self):
        h.reset_vault()
        slug = ws_mod.register("widen", path=str(h.VAULT / "widen"))
        ws_mod.set_identity(slug, keywords="alpha")
        ws_mod.set_identity(slug, keywords="beta")
        self.assertEqual(ws_mod.entry(slug)["keywords"], ["alpha", "beta"])

    def test_score_requires_presence_not_frequency(self):
        h.reset_vault()
        slug = ws_mod.register("freq", path=str(h.VAULT / "freq"), display_name="Frequency")
        once = ws_mod.score_text("Frequency appears once", slug)
        many = ws_mod.score_text("Frequency " * 20, slug)
        self.assertEqual(once, many)


if __name__ == "__main__":
    unittest.main()
