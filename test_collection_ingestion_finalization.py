"""Tests for review-to-plan Collection ingestion finalization."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion import CollectionCandidate, IngestionSource, RomFileEvidence
from collection_ingestion_convergence_review import ConvergedRomDecision
from collection_ingestion_finalization import (
    CollectionIngestionFinalizationError,
    CollectionIngestionFinalizationStaleStateError,
    allocate_local_identity_allocations,
    finalize_reviewed_ingestion_session,
)
from collection_ingestion_session import CollectionIngestionSession
from collection_plan_apply import collect_store_preconditions
from collection_reconciliation import (
    CandidateResolution,
    IdentityMigrationKind,
    IdentityMigrationProposal,
    MatchBasis,
    ReconciliationGroup,
    ReviewAction,
    ReviewDecision,
    ReviewIssue,
    ReviewState,
    RomSelectionDecision,
    build_reconciliation_groups,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffDetailSnapshot, KaizOffHackMetadata
from planner_reference_participant import PlannerCollectionReferenceParticipant
from save_sync_reference_participant import SaveSyncAssociationReferenceParticipant


LOCAL_ID = "usr_0123456789abcdef"


def _detail(identifier: int, title: str) -> KaizOffDetailSnapshot:
    return KaizOffDetailSnapshot(
        metadata=KaizOffHackMetadata(
            smwc_submission_id=identifier,
            title=title,
            authors=("Author",),
            tags=("tag",),
            image_urls=(),
            rating=4.5,
            size_bytes=123,
            downloads=5,
            download_url=f"https://dl.smwcentral.net/{identifier}/hack.zip",
            release_timestamp=1700000000,
            difficulty="Expert",
            hack_types=("Kaizo",),
            exits=20,
            demo=False,
            hall_of_fame=False,
            sa1_compatible=True,
            collaboration=False,
            description="Rich description",
            active=True,
            last_fetched="2026-08-24T00:00:00Z",
            obsoleted_by_submission_id=None,
        ),
        fetched_at=1.0,
        source="test",
        stale=False,
    )


class _Fixture:
    def __init__(self, initial=None):
        self.temporary = tempfile.TemporaryDirectory(prefix="ingestion_finalization_")
        self.root = Path(self.temporary.name)
        self.processed = self.root / "processed.json"
        self.processed.write_text(json.dumps(initial or {}, indent=2), encoding="utf-8")
        self.manager = HackDataManager(str(self.processed))
        self.hints = CollectionIdentityHintsStore.beside_processed_json(self.processed)
        self.participants = (
            SaveSyncAssociationReferenceParticipant.beside_processed_json(self.processed),
            PlannerCollectionReferenceParticipant.beside_processed_json(self.processed),
        )

    def close(self):
        self.temporary.cleanup()

    def session(self, group: ReconciliationGroup) -> CollectionIngestionSession:
        return CollectionIngestionSession(
            catalogue_fetched_at=1.0,
            catalogue_source="test",
            catalogue_stale=False,
            catalogue_entries=(),
            existing_collection_keys=tuple(sorted(self.manager.data)),
            preconditions=collect_store_preconditions(
                self.manager,
                self.hints,
                self.participants,
            ),
            resolutions=group.members,
            groups=(group,),
            review_entries=(),
            suppressed_roms=(),
        )


def _group(*, target="", blocking_state=None, title="Unknown Hack"):
    resolution = CandidateResolution(
        candidate_id="candidate-1",
        candidate=CollectionCandidate(
            source=IngestionSource.ROM_SCAN,
            title_hints=(title,),
        ),
        match_basis=MatchBasis.DIRECT if target else MatchBasis.UNMATCHED,
        target_key=target,
        reason="test",
    )
    issues = (
        ReviewIssue(blocking_state, "review required")
        if blocking_state is not None
        else ReviewIssue(ReviewState.READY, "ready")
    ,)
    return ReconciliationGroup(
        group_id="group-1",
        members=(resolution,),
        proposed_target_key=target,
        issues=issues,
        rom_hashes=(),
    )


class CollectionIngestionFinalizationTest(unittest.TestCase):
    def test_allocates_only_explicit_local_imports(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        group = _group(blocking_state=ReviewState.UNMATCHED)
        session = fixture.session(group)
        decision = ReviewDecision(group.group_id, ReviewAction.IMPORT_LOCAL)

        allocations = allocate_local_identity_allocations(
            session,
            {group.group_id: decision},
            id_factory=lambda: LOCAL_ID,
        )

        self.assertEqual({group.group_id: LOCAL_ID}, allocations)

    def test_invalid_or_colliding_local_allocator_fails_closed(self):
        fixture = _Fixture({LOCAL_ID: {"title": "Existing"}})
        self.addCleanup(fixture.close)
        group = _group(blocking_state=ReviewState.UNMATCHED)
        session = fixture.session(group)
        decision = ReviewDecision(group.group_id, ReviewAction.IMPORT_LOCAL)

        with self.assertRaises(CollectionIngestionFinalizationError):
            allocate_local_identity_allocations(
                session,
                {group.group_id: decision},
                id_factory=lambda: "title-derived-id",
            )

        with self.assertRaisesRegex(CollectionIngestionFinalizationError, "unique"):
            allocate_local_identity_allocations(
                session,
                {group.group_id: decision},
                id_factory=lambda: LOCAL_ID,
            )

    def test_local_review_finalizes_without_catalogue_detail_fetch(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        group = _group(blocking_state=ReviewState.UNMATCHED, title="My Local Hack")
        session = fixture.session(group)
        decision = ReviewDecision(group.group_id, ReviewAction.IMPORT_LOCAL)
        provider = Mock()

        plan = finalize_reviewed_ingestion_session(
            session,
            {group.group_id: decision},
            fixture.manager,
            fixture.hints,
            provider,
            participants=fixture.participants,
            id_factory=lambda: LOCAL_ID,
        )

        provider.get_hack.assert_not_called()
        self.assertEqual((LOCAL_ID,), tuple(item.target_key for item in plan.creates))
        self.assertEqual("My Local Hack", plan.local_record_seeds[0].title)
        self.assertEqual(
            {"collection", "collection_identity_hints", "save_sync_config", "planner_state"},
            {item.store_name for item in plan.preconditions},
        )

    def test_new_numeric_target_fetches_only_required_rich_detail(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        group = _group(target="41022", title="Super Dram World 3")
        session = fixture.session(group)
        provider = Mock()
        provider.get_hack.return_value = _detail(41022, "Super Dram World 3")

        plan = finalize_reviewed_ingestion_session(
            session,
            {},
            fixture.manager,
            fixture.hints,
            provider,
            participants=fixture.participants,
        )

        provider.get_hack.assert_called_once_with(41022, force_refresh=False)
        self.assertEqual("41022", plan.creates[0].target_key)
        self.assertEqual("Super Dram World 3", plan.catalogue_updates[0].metadata.title)

    def test_existing_numeric_target_does_not_require_detail_fetch(self):
        fixture = _Fixture({"41022": {"title": "Super Dram World 3"}})
        self.addCleanup(fixture.close)
        group = _group(target="41022", title="Super Dram World 3")
        session = fixture.session(group)
        provider = Mock()

        plan = finalize_reviewed_ingestion_session(
            session,
            {},
            fixture.manager,
            fixture.hints,
            provider,
            participants=fixture.participants,
        )

        provider.get_hack.assert_not_called()
        self.assertEqual("41022", plan.updates[0].target_key)


    def test_new_target_convergence_uses_explicit_combined_rom_decision(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)

        first_resolution = CandidateResolution(
            candidate_id="first",
            candidate=CollectionCandidate(
                source=IngestionSource.ROM_SCAN,
                title_hints=("Hack",),
                rom_files=(
                    RomFileEvidence(
                        path="C:/ROMs/Hack.sfc",
                        filename="Hack.sfc",
                        sha256="a" * 64,
                        size_bytes=2048,
                        title_hint="Hack",
                    ),
                ),
            ),
            match_basis=MatchBasis.AUTO_TITLE,
            target_key="41022",
            reason="auto",
        )
        second_resolution = CandidateResolution(
            candidate_id="second",
            candidate=CollectionCandidate(
                source=IngestionSource.ROM_SCAN,
                title_hints=("Hack Alt",),
                rom_files=(
                    RomFileEvidence(
                        path="C:/ROMs/Hack Alt.sfc",
                        filename="Hack Alt.sfc",
                        sha256="b" * 64,
                        size_bytes=2048,
                        title_hint="Hack Alt",
                    ),
                ),
            ),
            match_basis=MatchBasis.SUGGESTED_TITLE,
            target_key="41022",
            reason="suggested",
        )
        groups = build_reconciliation_groups((first_resolution, second_resolution))
        self.assertEqual(2, len(groups))
        suggested = next(
            group
            for group in groups
            if MatchBasis.SUGGESTED_TITLE in {member.match_basis for member in group.members}
        )
        decisions = {
            suggested.group_id: ReviewDecision(
                suggested.group_id,
                ReviewAction.USE_TARGET,
                target_key="41022",
            )
        }
        session = CollectionIngestionSession(
            catalogue_fetched_at=1.0,
            catalogue_source="test",
            catalogue_stale=False,
            catalogue_entries=(),
            existing_collection_keys=(),
            preconditions=collect_store_preconditions(
                fixture.manager, fixture.hints, fixture.participants
            ),
            resolutions=(first_resolution, second_resolution),
            groups=groups,
            review_entries=(),
            suppressed_roms=(),
        )
        provider = Mock()
        provider.get_hack.return_value = _detail(41022, "Hack")
        combined = {
            "41022": ConvergedRomDecision(
                target_key="41022",
                selection=RomSelectionDecision(
                    kept_paths=("C:/ROMs/Hack.sfc", "C:/ROMs/Hack Alt.sfc"),
                    primary_path="C:/ROMs/Hack.sfc",
                ),
            )
        }

        plan = finalize_reviewed_ingestion_session(
            session,
            decisions,
            fixture.manager,
            fixture.hints,
            provider,
            participants=fixture.participants,
            converged_rom_decisions=combined,
        )

        self.assertEqual(1, len(plan.rom_updates))
        self.assertEqual("C:/ROMs/Hack.sfc", plan.rom_updates[0].primary_path)
        self.assertEqual(2, len(plan.rom_updates[0].assets))

    def test_planner_state_conflict_is_detected_during_read_only_preflight(self):
        fixture = _Fixture({LOCAL_ID: {"title": "Local Hack"}})
        self.addCleanup(fixture.close)
        planner_path = fixture.root / "planner_state.json"
        planner_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "entries": {
                        LOCAL_ID: {"lifecycle_status": "Playing"},
                        "41022": {"lifecycle_status": "Completed"},
                    },
                    "lists": [],
                    "next_queue": [LOCAL_ID],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        proposal = IdentityMigrationProposal(
            source_key=LOCAL_ID,
            target_key="41022",
            kind=IdentityMigrationKind.LOCAL_PROMOTION,
        )
        resolution = CandidateResolution(
            candidate_id="candidate-migration",
            candidate=CollectionCandidate(
                source=IngestionSource.ROM_SCAN,
                title_hints=("Super Dram World 3",),
            ),
            match_basis=MatchBasis.DIRECT,
            target_key="41022",
            existing_collection_key=LOCAL_ID,
            migration=proposal,
            reason="user-reviewable local promotion",
        )
        group = ReconciliationGroup(
            group_id="migration-group",
            members=(resolution,),
            proposed_target_key="41022",
            issues=(ReviewIssue(ReviewState.IDENTITY_MIGRATION, "confirm migration"),),
            rom_hashes=(),
            migration=proposal,
        )
        session = fixture.session(group)
        decision = ReviewDecision(group.group_id, ReviewAction.CONFIRM_MIGRATION)
        provider = Mock()
        provider.get_hack.return_value = _detail(41022, "Super Dram World 3")

        with self.assertRaisesRegex(
            CollectionIngestionFinalizationError,
            "planner_state.*different planning state",
        ):
            finalize_reviewed_ingestion_session(
                session,
                {group.group_id: decision},
                fixture.manager,
                fixture.hints,
                provider,
                participants=fixture.participants,
            )

    def test_state_changed_after_review_fails_before_hydration(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        group = _group(target="41022", title="Super Dram World 3")
        session = fixture.session(group)
        fixture.processed.write_text('{"999":{"title":"Changed"}}\n', encoding="utf-8")
        provider = Mock()

        with self.assertRaises(CollectionIngestionFinalizationStaleStateError):
            finalize_reviewed_ingestion_session(
                session,
                {},
                fixture.manager,
                fixture.hints,
                provider,
                participants=fixture.participants,
            )

        provider.get_hack.assert_not_called()

    def test_state_changed_during_detail_fetch_fails_before_final_plan(self):
        fixture = _Fixture()
        self.addCleanup(fixture.close)
        group = _group(target="41022", title="Super Dram World 3")
        session = fixture.session(group)
        provider = Mock()

        def fetch(_identifier, *, force_refresh=False):
            self.assertFalse(force_refresh)
            fixture.processed.write_text('{"999":{"title":"Changed"}}\n', encoding="utf-8")
            return _detail(41022, "Super Dram World 3")

        provider.get_hack.side_effect = fetch
        with self.assertRaises(CollectionIngestionFinalizationStaleStateError):
            finalize_reviewed_ingestion_session(
                session,
                {},
                fixture.manager,
                fixture.hints,
                provider,
                participants=fixture.participants,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
