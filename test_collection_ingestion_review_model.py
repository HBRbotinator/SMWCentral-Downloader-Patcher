"""Tests for the presentation-only Collection ingestion review model."""
from __future__ import annotations

import unittest

from collection_ingestion import CollectionCandidate, IngestionSource, RomFileEvidence
from collection_ingestion_review_model import (
    CollectionIngestionReviewError,
    CollectionIngestionReviewModel,
)
from collection_ingestion_session import (
    CandidateReviewEntry,
    CatalogueSuggestion,
    CollectionIngestionSession,
    search_session_catalogue,
)
from collection_reconciliation import (
    CandidateResolution,
    MatchBasis,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    build_reconciliation_groups,
)
from rom_title_matching import CatalogueEntry


def _entry(identifier: int, title: str, difficulty="Expert") -> CatalogueEntry:
    return CatalogueEntry(
        smwc_submission_id=identifier,
        title=title,
        difficulty=difficulty,
        hack_type="Kaizo",
        exits=20,
        authors=("Author",),
    )


def _rom(path: str, sha: str, title: str) -> RomFileEvidence:
    return RomFileEvidence(
        path=path,
        filename=path.rsplit("/", 1)[-1],
        sha256=sha,
        size_bytes=1024,
        title_hint=title,
    )


def _candidate(title: str, *, rom=None) -> CollectionCandidate:
    return CollectionCandidate(
        source=IngestionSource.ROM_SCAN,
        title_hints=(title,),
        rom_files=(rom,) if rom is not None else (),
        allow_local_only=True,
    )


def _session() -> CollectionIngestionSession:
    auto_candidate = _candidate(
        "Quickie World 2",
        rom=_rom("C:/ROMs/QW2.sfc", "a" * 64, "Quickie World 2"),
    )
    unmatched_candidate = _candidate(
        "Super Bui Bui World",
        rom=_rom("C:/ROMs/Super Bui Bui World.sfc", "b" * 64, "Super Bui Bui World"),
    )
    auto = CandidateResolution(
        candidate_id="rom:auto",
        candidate=auto_candidate,
        match_basis=MatchBasis.AUTO_TITLE,
        target_key="19279",
        reason="Strong title match.",
    )
    unmatched = CandidateResolution(
        candidate_id="rom:unmatched",
        candidate=unmatched_candidate,
        match_basis=MatchBasis.UNMATCHED,
        reason="No safe catalogue identity.",
    )
    groups = build_reconciliation_groups((auto, unmatched))
    suggestion = CatalogueSuggestion(
        target_key="19279",
        title="Quickie World 2",
        difficulty="Expert",
        hack_type="Kaizo",
        exits=20,
        confidence=0.99,
        authors=("Author",),
    )
    reviews = (
        CandidateReviewEntry(
            candidate_id="rom:auto",
            source=IngestionSource.ROM_SCAN,
            classification="Strong",
            confidence=0.99,
            suggestions=(suggestion,),
            reason="Strong title match.",
        ),
        CandidateReviewEntry(
            candidate_id="rom:unmatched",
            source=IngestionSource.ROM_SCAN,
            classification="Review",
            confidence=0.20,
            suggestions=(),
            reason="No safe catalogue identity.",
        ),
    )
    return CollectionIngestionSession(
        catalogue_fetched_at=12345.0,
        catalogue_source="cache",
        catalogue_stale=False,
        catalogue_entries=(
            _entry(19279, "Quickie World 2"),
            _entry(41022, "Super Dram World 3", "Grandmaster"),
            _entry(30000, "Sayonara Mario World"),
            _entry(30001, "Sayonara Mario World 2"),
        ),
        existing_collection_keys=(),
        preconditions=(),
        resolutions=(auto, unmatched),
        groups=groups,
        review_entries=reviews,
        suppressed_roms=(),
    )


class CollectionIngestionReviewModelTest(unittest.TestCase):
    def test_summary_separates_nonblocking_and_unresolved_review(self):
        model = CollectionIngestionReviewModel(_session())
        summary = model.summary()

        self.assertEqual(2, summary.total_groups)
        self.assertEqual(1, summary.ready_groups)
        self.assertEqual(1, summary.blocking_groups)
        self.assertEqual(1, summary.unresolved_blocking_groups)
        self.assertFalse(summary.can_complete)

    def test_explicit_local_or_skip_decision_resolves_unmatched_group(self):
        model = CollectionIngestionReviewModel(_session())
        unmatched = next(group for group in model.session.groups if group.blocking)

        model.set_decision(
            unmatched.group_id,
            ReviewDecision(group_id=unmatched.group_id, action=ReviewAction.IMPORT_LOCAL),
        )
        self.assertTrue(model.is_group_resolved(unmatched.group_id))
        self.assertTrue(model.can_complete)
        self.assertEqual(0, model.summary().unresolved_blocking_groups)

        model.set_decision(
            unmatched.group_id,
            ReviewDecision(group_id=unmatched.group_id, action=ReviewAction.SKIP),
        )
        self.assertEqual(1, model.summary().skipped_groups)

    def test_invalid_decision_is_rejected_before_ui_can_continue(self):
        model = CollectionIngestionReviewModel(_session())
        unmatched = next(group for group in model.session.groups if group.blocking)

        with self.assertRaises(CollectionIngestionReviewError):
            model.set_decision(
                unmatched.group_id,
                ReviewDecision(group_id=unmatched.group_id, action=ReviewAction.ACCEPT),
            )
        self.assertFalse(model.can_complete)

    def test_decision_snapshot_is_detached(self):
        model = CollectionIngestionReviewModel(_session())
        unmatched = next(group for group in model.session.groups if group.blocking)
        decision = ReviewDecision(group_id=unmatched.group_id, action=ReviewAction.SKIP)
        model.set_decision(unmatched.group_id, decision)

        snapshot = model.decisions
        snapshot.clear()
        self.assertEqual(decision, model.decision_for(unmatched.group_id))

    def test_rows_put_unresolved_blocker_first_and_keep_auto_match_visible(self):
        model = CollectionIngestionReviewModel(_session())
        rows = model.rows()

        self.assertTrue(rows[0].blocking)
        self.assertFalse(rows[0].resolved)
        self.assertEqual("Unmatched", rows[0].status)
        auto = next(row for row in rows if not row.blocking)
        self.assertEqual("Auto-matched", auto.status)
        self.assertEqual("19279", auto.target_key)
        self.assertEqual("Quickie World 2", auto.target_title)

    def test_context_retains_source_scoped_rom_alias_and_ranked_suggestions(self):
        model = CollectionIngestionReviewModel(_session())
        auto = next(group for group in model.session.groups if not group.blocking)
        context = model.context(auto.group_id)

        self.assertEqual("19279", context.suggestions[0].target_key)
        self.assertIn(
            (IngestionSource.ROM_SCAN, "Quickie World 2"),
            context.rememberable_aliases,
        )
        self.assertIn("Strong title match.", context.candidate_reasons)

    def test_frozen_catalogue_search_supports_name_and_exact_id(self):
        session = _session()
        name_results = search_session_catalogue(session, "Sayonara", limit=10)
        id_results = search_session_catalogue(session, "SMWC-ID-41022")

        self.assertGreaterEqual(len(name_results), 2)
        self.assertEqual("30000", name_results[0].target_key)
        self.assertEqual(("Author",), name_results[0].authors)
        self.assertEqual(1, len(id_results))
        self.assertEqual("41022", id_results[0].target_key)
        self.assertEqual("Super Dram World 3", id_results[0].title)

    def test_frozen_catalogue_search_rejects_unbounded_limit(self):
        with self.assertRaises(Exception):
            search_session_catalogue(_session(), "Hack", limit=1000)

    def test_attention_rows_include_blockers_without_hiding_resolved_review(self):
        model = CollectionIngestionReviewModel(_session())
        unmatched = next(group for group in model.session.groups if group.blocking)
        model.set_decision(
            unmatched.group_id,
            ReviewDecision(group_id=unmatched.group_id, action=ReviewAction.SKIP),
        )

        rows = model.rows(attention_only=True)
        self.assertEqual(1, len(rows))
        self.assertEqual("Skipped", rows[0].status)
        self.assertTrue(rows[0].resolved)

    def test_review_states_remain_domain_states_not_ui_guesses(self):
        model = CollectionIngestionReviewModel(_session())
        blocking = next(group for group in model.session.groups if group.blocking)
        self.assertEqual((ReviewState.UNMATCHED,), blocking.review_states)
        self.assertEqual(("Unmatched",), model.context(blocking.group_id).row.issue_labels)


if __name__ == "__main__":
    unittest.main(verbosity=2)
