"""Tests for combined ROM review after separate groups converge on one new target."""
from __future__ import annotations

import unittest

from collection_change_plan import finalize_collection_change_plan
from collection_ingestion import CollectionCandidate, IngestionSource, RomFileEvidence
from collection_ingestion_convergence_review import (
    CollectionIngestionConvergenceReviewError,
    ConvergedRomDecision,
    build_converged_rom_reviews,
    decision_map_by_target,
)
from collection_reconciliation import (
    CandidateResolution,
    IgnoredRomDecision,
    MatchBasis,
    ReviewAction,
    ReviewDecision,
    RomSelectionDecision,
    build_reconciliation_groups,
)


def _rom(path: str, sha: str):
    return RomFileEvidence(
        path=path,
        filename=path.rsplit("/", 1)[-1],
        sha256=sha,
        size_bytes=2048,
        title_hint=path.rsplit("/", 1)[-1].rsplit(".", 1)[0],
    )


def _group(candidate_id: str, path: str, sha: str, basis: MatchBasis, target: str):
    resolution = CandidateResolution(
        candidate_id=candidate_id,
        candidate=CollectionCandidate(
            source=IngestionSource.ROM_SCAN,
            title_hints=(candidate_id,),
            rom_files=(_rom(path, sha),),
        ),
        match_basis=basis,
        target_key=target,
        reason="test",
    )
    return build_reconciliation_groups((resolution,))[0]


class CollectionIngestionConvergenceReviewTest(unittest.TestCase):
    def test_new_target_convergence_requires_combined_rom_review(self):
        first = _group("first", "C:/ROMs/Hack.sfc", "a" * 64, MatchBasis.AUTO_TITLE, "123")
        second = _group(
            "second",
            "C:/ROMs/Hack Alt.sfc",
            "b" * 64,
            MatchBasis.SUGGESTED_TITLE,
            "123",
        )
        group_decisions = {
            second.group_id: ReviewDecision(
                group_id=second.group_id,
                action=ReviewAction.USE_TARGET,
                target_key="123",
            )
        }

        reviews = build_converged_rom_reviews((first, second), group_decisions)

        self.assertEqual(1, len(reviews))
        self.assertEqual("123", reviews[0].target_key)
        self.assertEqual(
            {"C:/ROMs/Hack.sfc", "C:/ROMs/Hack Alt.sfc"},
            {rom.path for rom in reviews[0].rom_files},
        )

    def test_existing_target_does_not_require_combined_primary_review(self):
        first = _group("first", "C:/ROMs/A.sfc", "a" * 64, MatchBasis.DIRECT, "18612")
        second = _group("second", "C:/ROMs/B.sfc", "b" * 64, MatchBasis.DIRECT, "18612")

        reviews = build_converged_rom_reviews(
            (first, second),
            {},
            existing_collection_keys=("18612",),
        )

        self.assertEqual((), reviews)

    def test_combined_review_can_keep_both_choose_primary_and_ignore_one(self):
        first = _group("first", "C:/ROMs/A.sfc", "a" * 64, MatchBasis.AUTO_TITLE, "123")
        second = _group(
            "second",
            "C:/ROMs/B.sfc",
            "b" * 64,
            MatchBasis.SUGGESTED_TITLE,
            "123",
        )
        group_decisions = {
            second.group_id: ReviewDecision(
                group_id=second.group_id,
                action=ReviewAction.USE_TARGET,
                target_key="123",
            )
        }
        reviews = build_converged_rom_reviews((first, second), group_decisions)
        review = reviews[0]
        decision = ConvergedRomDecision(
            target_key="123",
            selection=RomSelectionDecision(
                kept_paths=("C:/ROMs/B.sfc",),
                primary_path="C:/ROMs/B.sfc",
                ignored=(IgnoredRomDecision("C:/ROMs/A.sfc", "a" * 64),),
            ),
        )

        normalized = decision_map_by_target(reviews, {"123": decision})
        plan = finalize_collection_change_plan(
            (first, second),
            group_decisions,
            converged_rom_decisions=normalized,
        )

        self.assertEqual("C:/ROMs/B.sfc", plan.rom_updates[0].primary_path)
        self.assertEqual(
            ("C:/ROMs/B.sfc",),
            tuple(asset.path for asset in plan.rom_updates[0].assets),
        )
        self.assertEqual("C:/ROMs/A.sfc", plan.ignored_roms[0].path)

    def test_missing_combined_decision_fails_before_hidden_primary_choice(self):
        first = _group("first", "C:/ROMs/A.sfc", "a" * 64, MatchBasis.DIRECT, "123")
        second = _group("second", "C:/ROMs/B.sfc", "b" * 64, MatchBasis.DIRECT, "123")

        with self.assertRaisesRegex(
            CollectionIngestionConvergenceReviewError,
            "Combined ROM review is required",
        ):
            decision_map_by_target(
                build_converged_rom_reviews((first, second), {}),
                {},
            )

    def test_combined_decision_rejects_stale_path_hash_ignore(self):
        first = _group("first", "C:/ROMs/A.sfc", "a" * 64, MatchBasis.DIRECT, "123")
        second = _group("second", "C:/ROMs/B.sfc", "b" * 64, MatchBasis.DIRECT, "123")
        reviews = build_converged_rom_reviews((first, second), {})
        decision = ConvergedRomDecision(
            target_key="123",
            selection=RomSelectionDecision(
                kept_paths=("C:/ROMs/B.sfc",),
                primary_path="C:/ROMs/B.sfc",
                ignored=(IgnoredRomDecision("C:/ROMs/A.sfc", "f" * 64),),
            ),
        )

        with self.assertRaisesRegex(
            CollectionIngestionConvergenceReviewError,
            r"path \+ SHA-256",
        ):
            decision_map_by_target(reviews, {"123": decision})


if __name__ == "__main__":
    unittest.main(verbosity=2)
