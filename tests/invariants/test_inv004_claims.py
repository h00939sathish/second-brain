# -*- coding: utf-8 -*-
"""INV-004: Stale or unverified claims cannot be injected as verified ground truth."""

import unittest
from pathlib import Path

import tests.harness as h
from brain import const, knowledge, paths, vcs


class TestInv004Claims(unittest.TestCase):
    def setUp(self):
        h.reset_vault()
        self.slug = h.fresh_workspace("inv004")

    def test_withheld_statuses_include_needs_revalidation(self):
        """INV-004.1: WITHHELD_STATUSES and STATUSES must include needs_revalidation."""
        self.assertIn("needs_revalidation", const.STATUSES)
        self.assertIn("needs_revalidation", const.WITHHELD_STATUSES)
        self.assertIn("superseded", const.WITHHELD_STATUSES)
        self.assertIn("disputed", const.WITHHELD_STATUSES)

    def test_withheld_statuses_are_excluded_from_default_recall(self):
        """INV-004.2: Claims in withheld statuses are withheld from active recall."""
        active = knowledge.add("Active ground truth fact", workspace=self.slug, status="active")
        stale = knowledge.add("Stale truth fact", workspace=self.slug, status="needs_revalidation")
        superseded = knowledge.add("Old obsolete truth fact", workspace=self.slug, status="active")
        replacement = knowledge.add("Replacement truth fact", workspace=self.slug, status="active")
        knowledge.supersede(superseded["id"], replacement["id"])

        shown, withheld = knowledge.recall("truth fact", workspace=self.slug)
        shown_ids = [r["id"] for r in shown]
        withheld_ids = [r["id"] for r in withheld]

        self.assertIn(active["id"], shown_ids)
        self.assertNotIn(stale["id"], shown_ids, "needs_revalidation must be excluded from default recall")
        self.assertNotIn(superseded["id"], shown_ids, "superseded must be excluded from default recall")
        self.assertIn(stale["id"], withheld_ids)
        self.assertIn(superseded["id"], withheld_ids)

    def test_claim_records_verified_commit_and_depends_on(self):
        """INV-004.3: Claims store git commit hash and dependency files list."""
        claim = knowledge.add(
            "Gross exposure is capped at $10M",
            workspace=self.slug,
            source="src/risk.py",
            depends_on="src/risk.py,src/engine.py",
            verified_commit="a81f92c3",
        )
        found = knowledge.get(claim["id"], workspace=self.slug)
        fm = found[1]["fm"]
        self.assertEqual(fm["verified_commit"], "a81f92c3")
        self.assertEqual(fm["depends_on"], ["src/risk.py", "src/engine.py"])
        self.assertIn("**Depends on:** src/risk.py, src/engine.py", found[1]["body"])

    def test_git_modification_triggers_needs_revalidation(self):
        """INV-004.4: Git modifications to dependent files transition ACTIVE -> NEEDS_REVALIDATION."""
        # 1. Commit initial version of dependency file in vault repo
        dep_file = paths.VAULT / "src" / "risk.py"
        dep_file.parent.mkdir(parents=True, exist_ok=True)
        dep_file.write_text("# initial risk implementation\n")
        vcs.commit("initial risk commit", paths=[dep_file], no_verify=True)
        base_commit = vcs.head_commit()
        self.assertTrue(base_commit, "Base commit must exist")

        # 2. Record claim anchored to base_commit
        claim = knowledge.add(
            "Gross exposure cap is active",
            workspace=self.slug,
            depends_on=["src/risk.py"],
            verified_commit=base_commit,
        )

        # 3. Modify the dependency file
        dep_file.write_text("# modified risk implementation with new exposure rules\n")

        # 4. Trigger invalidation scan
        invalidated = knowledge.invalidate_stale_claims(workspace=self.slug)
        self.assertTrue(any(item[0] == claim["id"] for item in invalidated))

        # 5. Verify claim transitioned to needs_revalidation
        updated = knowledge.get(claim["id"], workspace=self.slug)
        self.assertEqual(updated[1]["fm"]["status"], "needs_revalidation")
        self.assertIn("Flagged NEEDS_REVALIDATION", updated[1]["body"])

        # 6. Verify default recall now withholds this claim
        shown, withheld = knowledge.recall("exposure cap", workspace=self.slug)
        self.assertNotIn(claim["id"], [r["id"] for r in shown])
        self.assertIn(claim["id"], [r["id"] for r in withheld])

    def test_revalidate_restores_active_status(self):
        """INV-004.5: Revalidation restores ACTIVE status and updates commit SHA."""
        # Create claim in needs_revalidation state
        claim = knowledge.add(
            "Authentication token lifetime is 3600s",
            workspace=self.slug,
            status="needs_revalidation",
            verified_commit="old00000",
        )
        # Revalidate with note
        res = knowledge.revalidate(claim["id"], note="confirmed valid with security team",
                                   workspace=self.slug, verified_commit="new11111")
        self.assertEqual(res["status"], "active")
        self.assertEqual(res["verified_commit"], "new11111")

        updated = knowledge.get(claim["id"], workspace=self.slug)
        self.assertEqual(updated[1]["fm"]["status"], "active")
        self.assertEqual(updated[1]["fm"]["verified_commit"], "new11111")
        self.assertIn("confirmed valid with security team", updated[1]["body"])

        # Default recall now presents the claim
        shown, _ = knowledge.recall("token lifetime", workspace=self.slug)
        self.assertIn(claim["id"], [r["id"] for r in shown])


if __name__ == "__main__":
    unittest.main()
