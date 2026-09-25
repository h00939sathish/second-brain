# -*- coding: utf-8 -*-
"""The knowledge base: scoping, lifecycle and search."""

import unittest

import tests.harness as h
from brain import const, knowledge, maintenance, store


class Scoping(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.jarvis = h.fresh_workspace("jarvis")
        self.titan = h.fresh_workspace("titan")

    def test_claims_are_isolated_between_workspaces(self):
        knowledge.add("JARVIS runs on Arch", workspace=self.jarvis, tags="jarvis")
        knowledge.add("TITAN uses a gross exposure gate", workspace=self.titan, tags="titan")

        leaked, _ = knowledge.recall(query="exposure", workspace=self.jarvis)
        self.assertEqual(leaked, [], "JARVIS must not see TITAN's claims")

        mine, _ = knowledge.recall(query="Arch", workspace=self.jarvis)
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["workspace"], self.jarvis)

        theirs, _ = knowledge.recall(query="exposure", workspace=self.titan)
        self.assertEqual(len(theirs), 1)
        self.assertEqual(theirs[0]["workspace"], self.titan)

    def test_global_claims_are_visible_everywhere(self):
        knowledge.add("The box has an RTX 3050", workspace=self.jarvis, tags="system",
                      scope="global")
        for slug in (self.jarvis, self.titan):
            found, _ = knowledge.recall(query="RTX", workspace=slug)
            self.assertEqual(len(found), 1, f"{slug} should see shared truth")
            self.assertEqual(found[0]["workspace"], const.GLOBAL_WORKSPACE)

    def test_records_land_in_their_workspace_directory(self):
        result = knowledge.add("scoped fact", workspace=self.titan)
        self.assertIn(f"workspaces/{self.titan}/claims", result["path"])
        self.assertTrue(store.record_path("claims", result["id"], self.titan).exists())


class Lifecycle(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("life")

    def add(self, text, **kwargs):
        return knowledge.add(text, workspace=self.slug, **kwargs)

    def test_new_claim_is_not_marked_reviewed(self):
        """The old writer stamped reviewed_at at creation, which hid the review gate."""
        claim = self.add("some fact")
        record = store.read_record("claims", claim["id"], self.slug)
        self.assertEqual(record["fm"].get("reviewed_at"), "")
        ids = [row["id"] for row in knowledge.unreviewed()]
        self.assertIn(claim["id"], ids)

    def test_review_stamps_and_clears_the_signal(self):
        claim = self.add("some fact")
        knowledge.review(claim["id"], note="checked the source")
        record = store.read_record("claims", claim["id"], self.slug)
        self.assertTrue(record["fm"]["reviewed_at"])
        self.assertNotIn(claim["id"], [row["id"] for row in knowledge.unreviewed()])

    def test_review_note_is_recorded(self):
        claim = self.add("some fact")
        knowledge.review(claim["id"], note="verified against src/x.py")
        record = store.read_record("claims", claim["id"], self.slug)
        self.assertIn("verified against src/x.py", record["body"])

    def test_supersede_links_both_directions(self):
        old = self.add("old truth")
        new = self.add("new truth")
        knowledge.supersede(old["id"], new["id"])
        old_record = store.read_record("claims", old["id"], self.slug)
        new_record = store.read_record("claims", new["id"], self.slug)
        self.assertEqual(old_record["fm"]["status"], "superseded")
        self.assertEqual(old_record["fm"]["superseded_by"], new["id"])
        self.assertEqual(new_record["fm"]["supersedes"], old["id"])
        self.assertEqual(knowledge.chain_issues(old["id"]), [])

    def test_superseded_claims_are_withheld_from_recall(self):
        old = self.add("the old way to do it")
        new = self.add("the new way to do it")
        knowledge.supersede(old["id"], new["id"])
        shown, withheld = knowledge.recall(query="way", workspace=self.slug)
        self.assertIn(old["id"], [c["id"] for c in withheld])
        self.assertNotIn(old["id"], [c["id"] for c in shown])
        shown_all, _ = knowledge.recall(query="way", workspace=self.slug, include_withheld=True)
        self.assertIn(old["id"], [c["id"] for c in shown_all])

    def test_dispute_keeps_evidence_and_withholds(self):
        claim = self.add("dubious fact")
        knowledge.dispute(claim["id"], reason="source was wrong", by="opencode")
        record = store.read_record("claims", claim["id"], self.slug)
        self.assertEqual(record["fm"]["status"], "disputed")
        self.assertIn("dubious fact", record["body"])  # evidence retained
        self.assertIn("source was wrong", record["body"])
        shown, withheld = knowledge.recall(query="dubious", workspace=self.slug)
        self.assertEqual(shown, [])
        self.assertEqual(len(withheld), 1)

    def test_dangling_chain_is_reported(self):
        claim = self.add("points at nothing")
        record = store.read_record("claims", claim["id"], self.slug)
        record["fm"]["superseded_by"] = "20200101-deadbe"
        store.update_record("claims", record, workspace=self.slug)
        issues = knowledge.chain_issues(claim["id"])
        self.assertTrue(any("dangling" in i for i in issues), issues)

    def test_full_text_survives_a_multiline_claim(self):
        text = "First line: with a colon\nsecond line\n---\nfourth line"
        claim = self.add(text)
        record = store.read_record("claims", claim["id"], self.slug)
        self.assertEqual(record["fm"]["claim"], text)

    def test_confidence_is_validated(self):
        with self.assertRaises(Exception):
            knowledge.add("bad confidence", workspace=self.slug, confidence=2.0)
        with self.assertRaises(Exception):
            knowledge.add("bad confidence", workspace=self.slug, confidence="high")

    def test_review_of_unknown_claim_fails(self):
        with self.assertRaises(Exception):
            knowledge.review("20200101-nope")

    def test_verify_is_clean_for_a_healthy_vault(self):
        self.add("healthy fact")
        self.assertEqual(knowledge.verify(), [])

    def test_sweep_flags_never_reviewed_claims(self):
        self.add("unchecked fact")
        flagged = maintenance.sweep(quiet=True)
        self.assertTrue(any("never reviewed" in why for _, why in flagged), flagged)


class Promote(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("promo")

    def test_promote_keeps_the_full_note_as_evidence(self):
        from brain import coordination
        note = coordination.post(
            "A long finding\nwith a second paragraph\nand a third detail",
            workspace=self.slug, agent="opencode", tags="finding")
        claim = knowledge.promote(note["id"], workspace=self.slug)
        record = store.read_record("claims", claim["id"], self.slug)
        self.assertEqual(record["fm"]["claim"], "A long finding")
        self.assertIn("third detail", knowledge.evidence_text(record))
        self.assertEqual(record["fm"]["promoted_from"], note["id"])
        note_record = store.read_record("context", note["id"], self.slug)
        self.assertEqual(note_record["fm"]["promoted_to"], claim["id"])


class Maturity(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("mat")

    def test_default_maturity_derivation(self):
        # Low confidence or no verified commit -> provisional
        c1 = knowledge.add("observation A", workspace=self.slug, confidence=0.7, verified_commit="")
        r1 = store.read_record("claims", c1["id"], self.slug)
        self.assertEqual("provisional", r1["fm"]["maturity"])

        # High confidence with commit -> established
        c2 = knowledge.add("proven fact", workspace=self.slug, confidence=0.9, verified_commit="abc1234")
        r2 = store.read_record("claims", c2["id"], self.slug)
        self.assertEqual("established", r2["fm"]["maturity"])

        # Global scope -> canonical
        c3 = knowledge.add("global law", workspace=self.slug, scope="global")
        r3 = store.read_record("claims", c3["id"], const.GLOBAL_WORKSPACE)
        self.assertEqual("canonical", r3["fm"]["maturity"])

        # Explicit maturity override
        c4 = knowledge.add("draft rule", workspace=self.slug, maturity="provisional")
        r4 = store.read_record("claims", c4["id"], self.slug)
        self.assertEqual("provisional", r4["fm"]["maturity"])

    def test_revalidate_elevates_provisional_to_established(self):
        c = knowledge.add("hypothesis", workspace=self.slug, confidence=0.6, verified_commit="")
        r = store.read_record("claims", c["id"], self.slug)
        self.assertEqual("provisional", r["fm"]["maturity"])

        res = knowledge.revalidate(c["id"], workspace=self.slug, note="confirmed in testing")
        self.assertEqual("established", res["maturity"])
        updated = store.read_record("claims", c["id"], self.slug)
        self.assertEqual("established", updated["fm"]["maturity"])
        self.assertIn("maturity elevated: provisional -> established", updated["body"])

    def test_elevate_claim_to_canonical(self):
        c = knowledge.add("local rule", workspace=self.slug)
        res = knowledge.elevate(c["id"], maturity="canonical", workspace=self.slug, note="promoted to squad standard")
        self.assertEqual("canonical", res["maturity"])
        updated = store.read_record("claims", c["id"], self.slug)
        self.assertEqual("canonical", updated["fm"]["maturity"])
        self.assertIn("Maturity elevated", updated["body"])

    def test_recall_filters_by_maturity(self):
        knowledge.add("draft idea", workspace=self.slug, maturity="provisional")
        knowledge.add("solid fact", workspace=self.slug, maturity="established")
        knowledge.add("core truth", workspace=self.slug, maturity="canonical")

        prov, _ = knowledge.recall(workspace=self.slug, maturity="provisional")
        self.assertEqual(1, len(prov))
        self.assertEqual("draft idea", prov[0]["claim"])
        self.assertEqual("provisional", prov[0]["maturity"])

        estab, _ = knowledge.recall(workspace=self.slug, maturity="established")
        self.assertEqual(1, len(estab))
        self.assertEqual("solid fact", estab[0]["claim"])
        self.assertEqual("established", estab[0]["maturity"])

        canon, _ = knowledge.recall(workspace=self.slug, maturity="canonical")
        self.assertEqual(1, len(canon))
        self.assertEqual("core truth", canon[0]["claim"])
        self.assertEqual("canonical", canon[0]["maturity"])

    def test_invalid_maturity_rejected(self):
        with self.assertRaises(Exception):
            knowledge.add("bogus", workspace=self.slug, maturity="infinite")
        c = knowledge.add("ok fact", workspace=self.slug)
        with self.assertRaises(Exception):
            knowledge.elevate(c["id"], maturity="legendary", workspace=self.slug)


if __name__ == "__main__":
    unittest.main()
