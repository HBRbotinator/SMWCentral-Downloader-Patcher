"""Tests for immutable deterministic Collection change plans."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from collection_change_plan import (
    PlanFinalizationError,
    RecordIntentKind,
    StorePrecondition,
    catalogue_snapshot_from_evidence,
    finalize_collection_change_plan,
)
from collection_ingestion import (
    CollectionCandidate,
    EvidenceStrength,
    IdentityEvidence,
    IdentityEvidenceKind,
    IngestionSource,
    RomFileEvidence,
    SharedMetadataEvidence,
    UserPlaythroughEvidence,
)
from collection_reconciliation import (
    CandidateResolution,
    FirstClearDecision,
    IdentityMigrationKind,
    IdentityMigrationProposal,
    IgnoredRomDecision,
    MatchBasis,
    RememberedAssociationDecision,
    ReviewAction,
    ReviewDecision,
    RomSelectionDecision,
    UserFieldProposal,
    UserFieldResolution,
    build_reconciliation_groups,
)


def _rom(path: str, sha: str, title="Hack", smwc_id: int | None = None):
    return RomFileEvidence(
        path=path,
        filename=path.rsplit("/", 1)[-1],
        sha256=sha,
        size_bytes=2048,
        title_hint=title,
        embedded_smwc_submission_id=smwc_id,
    )


def _metadata(title="Hack"):
    return SharedMetadataEvidence(
        source=IngestionSource.KAIZOFF,
        title=title,
        authors=("Author",),
        difficulty="Expert",
        hack_types=("Kaizo",),
        exits=12,
        release_timestamp=1700000000,
        rating=4.5,
        hall_of_fame=True,
        sa1_compatible=False,
        collaboration=False,
        demo=False,
        description="Rich description that should remain provider-cache data.",
        tags=("chocolate",),
        image_urls=("https://dl.smwcentral.net/image/1",),
        download_url="https://dl.smwcentral.net/123/Hack.zip",
        active=True,
        obsoleted_by_submission_id=999,
    )


def _history(record_id: str, *, play_kind="First Play", notes=""):
    return UserPlaythroughEvidence(
        source=IngestionSource.GIGANTIC_BUCKET,
        source_record_id=record_id,
        category="100%",
        play_kind=play_kind,
        icon="Playthrough",
        elapsed_text="4:12:05",
        elapsed_seconds=15125,
        completed_date_text="Jan 2, 2020",
        completed_date_iso="2020-01-02",
        notes=notes,
    )


def _candidate(
    title="Hack",
    *,
    source=IngestionSource.ROM_SCAN,
    roms=(),
    metadata=(),
    history=(),
    smwc_id: int | None = None,
):
    evidence = []
    if smwc_id is not None:
        evidence.append(
            IdentityEvidence(
                kind=IdentityEvidenceKind.SMWC_SUBMISSION_ID,
                value=str(smwc_id),
                source=source,
                strength=EvidenceStrength.STRONG,
            )
        )
    return CollectionCandidate(
        source=source,
        title_hints=(title,),
        author_hints=("Local Author",),
        identity_evidence=tuple(evidence),
        rom_files=tuple(roms),
        shared_metadata=tuple(metadata),
        user_history=tuple(history),
        allow_local_only=True,
    )


def _resolution(
    candidate_id,
    candidate,
    basis,
    target="",
    **kwargs,
):
    return CandidateResolution(
        candidate_id=candidate_id,
        candidate=candidate,
        match_basis=basis,
        target_key=target,
        **kwargs,
    )


def _group(*resolutions):
    groups = build_reconciliation_groups(resolutions)
    if len(groups) != 1:
        raise AssertionError(groups)
    return groups[0]


class CollectionChangePlanTest(unittest.TestCase):
    def test_known_smwc_target_uses_kaizoff_for_durable_catalogue_metadata_only(self):
        candidate = _candidate(
            "Hack",
            source=IngestionSource.KAIZOFF,
            metadata=(_metadata(),),
            smwc_id=123,
        )
        group = _group(_resolution("kaizoff", candidate, MatchBasis.DIRECT, "123"))
        plan = finalize_collection_change_plan(
            (group,),
            existing_collection_keys=("123",),
        )

        self.assertEqual(RecordIntentKind.UPDATE, plan.record_intents[0].kind)
        snapshot = plan.catalogue_updates[0].metadata
        self.assertEqual(123, snapshot.submission_id)
        self.assertEqual("Hack", snapshot.title)
        self.assertEqual(("Author",), snapshot.authors)
        self.assertEqual("Expert", snapshot.difficulty)
        self.assertEqual(("Kaizo",), snapshot.hack_types)
        self.assertFalse(hasattr(snapshot, "description"))
        self.assertFalse(hasattr(snapshot, "tags"))
        self.assertFalse(hasattr(snapshot, "download_url"))
        self.assertFalse(hasattr(snapshot, "obsoleted_by_submission_id"))

    def test_catalogue_snapshot_rejects_non_kaizoff_or_local_identity(self):
        metadata = _metadata()
        with self.assertRaises(PlanFinalizationError):
            catalogue_snapshot_from_evidence("usr_0123456789abcdef", metadata)
        foreign = SharedMetadataEvidence(
            source=IngestionSource.MANUAL,
            title="Manual",
        )
        with self.assertRaises(PlanFinalizationError):
            catalogue_snapshot_from_evidence("123", foreign)

    def test_new_numeric_rom_target_sets_primary_but_existing_target_preserves_it(self):
        candidate = _candidate(
            roms=(_rom("C:/ROMs/Hack.sfc", "a" * 64, smwc_id=123),),
            smwc_id=123,
        )
        group = _group(_resolution("rom", candidate, MatchBasis.DIRECT, "123"))

        new_plan = finalize_collection_change_plan((group,))
        existing_plan = finalize_collection_change_plan(
            (group,),
            existing_collection_keys=("123",),
        )

        self.assertEqual(RecordIntentKind.CREATE, new_plan.record_intents[0].kind)
        self.assertEqual("C:/ROMs/Hack.sfc", new_plan.rom_updates[0].primary_path)
        self.assertFalse(new_plan.rom_updates[0].preserve_existing_primary)
        self.assertEqual(123, new_plan.rom_updates[0].assets[0].smwc_submission_id)
        self.assertTrue(existing_plan.rom_updates[0].preserve_existing_primary)
        self.assertEqual("", existing_plan.rom_updates[0].primary_path)

    def test_unmatched_local_import_requires_preallocated_opaque_identity(self):
        group = _group(
            _resolution(
                "local",
                _candidate("Super Bui Bui World"),
                MatchBasis.UNMATCHED,
            )
        )
        decision = ReviewDecision(group_id=group.group_id, action=ReviewAction.IMPORT_LOCAL)

        with self.assertRaises(PlanFinalizationError):
            finalize_collection_change_plan((group,), {group.group_id: decision})

        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            local_identity_allocations={group.group_id: "usr_0123456789abcdef"},
        )
        self.assertEqual("usr_0123456789abcdef", plan.record_intents[0].target_key)
        self.assertEqual(RecordIntentKind.CREATE, plan.record_intents[0].kind)
        self.assertEqual("Super Bui Bui World", plan.local_record_seeds[0].title)
        self.assertEqual(("Local Author",), plan.local_record_seeds[0].authors)

    def test_giganticbucket_history_is_preserved_and_one_ordinary_run_becomes_first_clear(self):
        playthrough = _history("556:0", notes="Race version note stays on this run")
        proposals = (
            UserFieldProposal(
                field="completed",
                current_value=False,
                proposed_value=True,
                source=IngestionSource.GIGANTIC_BUCKET,
                reason="Imported completed playthrough",
            ),
            UserFieldProposal(
                field="completed_date",
                current_value="",
                proposed_value="2020-01-02",
                source=IngestionSource.GIGANTIC_BUCKET,
                reason="Imported first completion date",
            ),
        )
        candidate = _candidate(
            "Quickie World 2",
            source=IngestionSource.GIGANTIC_BUCKET,
            history=(playthrough,),
            smwc_id=19279,
        )
        group = _group(
            _resolution(
                "history",
                candidate,
                MatchBasis.DIRECT,
                "19279",
                user_field_proposals=proposals,
            )
        )
        plan = finalize_collection_change_plan(
            (group,),
            existing_collection_keys=("19279",),
        )

        history = plan.user_history_updates[0]
        self.assertEqual("556:0", history.first_clear_source_record_id)
        self.assertEqual("Race version note stays on this run", history.playthroughs[0].notes)
        self.assertEqual(
            {"completed", "completed_date"},
            {operation.field for operation in plan.user_state_updates},
        )
        self.assertNotIn("notes", {operation.field for operation in plan.user_state_updates})
        self.assertNotIn("time_to_beat", {operation.field for operation in plan.user_state_updates})

    def test_multiple_playthroughs_require_verified_first_clear_or_explicit_none(self):
        candidate = _candidate(
            source=IngestionSource.GIGANTIC_BUCKET,
            history=(_history("1:0"), _history("1:1", play_kind="Replay")),
            smwc_id=123,
        )
        group = _group(_resolution("history", candidate, MatchBasis.DIRECT, "123"))

        with self.assertRaises(PlanFinalizationError):
            finalize_collection_change_plan((group,), existing_collection_keys=("123",))

        choose = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ACCEPT,
            first_clear=FirstClearDecision(
                decided=True,
                source=IngestionSource.GIGANTIC_BUCKET,
                source_record_id="1:0",
            ),
        )
        chosen = finalize_collection_change_plan(
            (group,),
            {group.group_id: choose},
            existing_collection_keys=("123",),
        )
        self.assertEqual("1:0", chosen.user_history_updates[0].first_clear_source_record_id)

        none = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ACCEPT,
            first_clear=FirstClearDecision(decided=True, source_record_id=None),
        )
        no_first_clear = finalize_collection_change_plan(
            (group,),
            {group.group_id: none},
            existing_collection_keys=("123",),
        )
        self.assertIsNone(no_first_clear.user_history_updates[0].first_clear_source_record_id)
        self.assertTrue(no_first_clear.user_history_updates[0].first_clear_decided)

    def test_pb_only_history_never_becomes_first_clear_without_review(self):
        candidate = _candidate(
            source=IngestionSource.GIGANTIC_BUCKET,
            history=(_history("2:0", play_kind="Any% PB"),),
            smwc_id=123,
        )
        group = _group(_resolution("pb", candidate, MatchBasis.DIRECT, "123"))

        with self.assertRaises(PlanFinalizationError):
            finalize_collection_change_plan((group,), existing_collection_keys=("123",))

        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ACCEPT,
            first_clear=FirstClearDecision(decided=True, source_record_id=None),
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=("123",),
        )
        self.assertIsNone(plan.user_history_updates[0].first_clear_source_record_id)

    def test_conflicting_user_state_is_not_silently_overwritten(self):
        proposal = UserFieldProposal(
            field="completed_date",
            current_value="2021-04-10",
            proposed_value="2019-03-03",
            source=IngestionSource.GIGANTIC_BUCKET,
            reason="Imported first completion date",
            conflict=True,
        )
        group = _group(
            _resolution(
                "history",
                _candidate(source=IngestionSource.GIGANTIC_BUCKET, smwc_id=123),
                MatchBasis.DIRECT,
                "123",
                user_field_proposals=(proposal,),
            )
        )

        with self.assertRaises(PlanFinalizationError):
            finalize_collection_change_plan((group,), existing_collection_keys=("123",))

        keep_existing = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ACCEPT,
            user_field_resolutions=(
                UserFieldResolution(field="completed_date", use_proposed=False),
            ),
        )
        kept = finalize_collection_change_plan(
            (group,),
            {group.group_id: keep_existing},
            existing_collection_keys=("123",),
        )
        self.assertEqual((), kept.user_state_updates)

        use_imported = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ACCEPT,
            user_field_resolutions=(
                UserFieldResolution(field="completed_date", use_proposed=True),
            ),
        )
        changed = finalize_collection_change_plan(
            (group,),
            {group.group_id: use_imported},
            existing_collection_keys=("123",),
        )
        self.assertEqual("2019-03-03", changed.user_state_updates[0].value)

    def test_confirmed_local_promotion_emits_identity_and_reference_migration(self):
        migration = IdentityMigrationProposal(
            source_key="usr_0123456789abcdef",
            target_key="43123",
            kind=IdentityMigrationKind.LOCAL_PROMOTION,
        )
        group = _group(
            _resolution(
                "promote",
                _candidate("New Hack"),
                MatchBasis.USER_CONFIRMED,
                "43123",
                existing_collection_key="usr_0123456789abcdef",
                migration=migration,
            )
        )
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.CONFIRM_MIGRATION,
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=("usr_0123456789abcdef",),
        )

        self.assertEqual(RecordIntentKind.CREATE, plan.record_intents[0].kind)
        self.assertEqual("usr_0123456789abcdef", plan.identity_migrations[0].source_key)
        self.assertEqual("43123", plan.identity_migrations[0].target_key)
        self.assertEqual((), plan.identity_migrations[0].prior_submission_ids)
        self.assertEqual("43123", plan.reference_migrations[0].target_key)

    def test_numeric_replacement_retains_prior_submission_and_merges_existing_target(self):
        migration = IdentityMigrationProposal(
            source_key="41022",
            target_key="43123",
            kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
            prior_submission_ids=(39000,),
        )
        group = _group(
            _resolution(
                "replace",
                _candidate("Super Dram World 3"),
                MatchBasis.USER_CONFIRMED,
                "43123",
                existing_collection_key="41022",
                migration=migration,
            )
        )

        with self.assertRaises(PlanFinalizationError):
            finalize_collection_change_plan(
                (group,),
                existing_collection_keys=("41022",),
            )

        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.CONFIRM_MIGRATION,
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=("41022", "43123"),
        )
        operation = plan.identity_migrations[0]
        self.assertTrue(operation.merge_existing_target)
        self.assertEqual((41022, 39000), operation.prior_submission_ids)
        self.assertEqual(RecordIntentKind.UPDATE, plan.record_intents[0].kind)

    def test_keep_separate_does_not_emit_identity_migration(self):
        migration = IdentityMigrationProposal(
            source_key="41022",
            target_key="43123",
            kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
        )
        group = _group(
            _resolution(
                "replace",
                _candidate("Hack"),
                MatchBasis.USER_CONFIRMED,
                "43123",
                existing_collection_key="41022",
                migration=migration,
            )
        )
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.KEEP_SEPARATE,
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=("41022",),
        )

        self.assertEqual((), plan.identity_migrations)
        self.assertEqual((), plan.reference_migrations)
        self.assertEqual("43123", plan.record_intents[0].target_key)
        self.assertEqual(RecordIntentKind.CREATE, plan.record_intents[0].kind)

    def test_different_rom_hash_selection_and_ignore_are_fully_resolved_in_plan(self):
        group = _group(
            _resolution(
                "a",
                _candidate(roms=(_rom("C:/ROMs/Hack.sfc", "a" * 64),)),
                MatchBasis.AUTO_TITLE,
                "123",
            ),
            _resolution(
                "b",
                _candidate(roms=(_rom("C:/ROMs/Hack-v2.sfc", "b" * 64),)),
                MatchBasis.AUTO_TITLE,
                "123",
            ),
        )
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ACCEPT,
            rom_selection=RomSelectionDecision(
                kept_paths=("C:/ROMs/Hack-v2.sfc",),
                primary_path="C:/ROMs/Hack-v2.sfc",
                ignored=(
                    IgnoredRomDecision(
                        path="C:/ROMs/Hack.sfc",
                        sha256="a" * 64,
                    ),
                ),
            ),
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
        )

        self.assertEqual("C:/ROMs/Hack-v2.sfc", plan.rom_updates[0].primary_path)
        self.assertEqual(1, len(plan.rom_updates[0].assets))
        self.assertEqual("C:/ROMs/Hack.sfc", plan.ignored_roms[0].path)
        self.assertEqual("a" * 64, plan.ignored_roms[0].sha256)

    def test_existing_target_merges_rom_assets_from_separate_review_groups(self):
        direct_group = build_reconciliation_groups(
            (
                _resolution(
                    "akogare-exact",
                    _candidate(
                        "Akogare Mario World",
                        roms=(_rom("C:/ROMs/Akogare Mario World v1.0.sfc", "a" * 64),),
                    ),
                    MatchBasis.DIRECT,
                    "18612",
                    existing_collection_key="18612",
                ),
            )
        )[0]
        review_group = build_reconciliation_groups(
            (
                _resolution(
                    "akogare-short",
                    _candidate(
                        "Akogare",
                        roms=(_rom("C:/ROMs/Akogare v1.2.sfc", "b" * 64),),
                    ),
                    MatchBasis.SUGGESTED_TITLE,
                    "18612",
                    existing_collection_key="18612",
                ),
            )
        )[0]
        decision = ReviewDecision(
            group_id=review_group.group_id,
            action=ReviewAction.USE_TARGET,
            target_key="18612",
        )

        plan = finalize_collection_change_plan(
            (direct_group, review_group),
            {review_group.group_id: decision},
            existing_collection_keys=("18612",),
        )

        self.assertEqual(1, len(plan.rom_updates))
        operation = plan.rom_updates[0]
        self.assertEqual("18612", operation.target_key)
        self.assertTrue(operation.preserve_existing_primary)
        self.assertEqual("", operation.primary_path)
        self.assertEqual(
            {
                "C:/ROMs/Akogare Mario World v1.0.sfc",
                "C:/ROMs/Akogare v1.2.sfc",
            },
            {asset.path for asset in operation.assets},
        )

    def test_new_target_convergence_with_multiple_primary_choices_fails_actionably(self):
        first = build_reconciliation_groups(
            (
                _resolution(
                    "first",
                    _candidate(roms=(_rom("C:/ROMs/Hack.sfc", "a" * 64),)),
                    MatchBasis.AUTO_TITLE,
                    "123",
                ),
            )
        )[0]
        second = build_reconciliation_groups(
            (
                _resolution(
                    "second",
                    _candidate(roms=(_rom("C:/ROMs/Hack Alt.sfc", "b" * 64),)),
                    MatchBasis.SUGGESTED_TITLE,
                    "123",
                ),
            )
        )[0]
        decision = ReviewDecision(
            group_id=second.group_id,
            action=ReviewAction.USE_TARGET,
            target_key="123",
        )

        with self.assertRaisesRegex(PlanFinalizationError, "Combined ROM review is required"):
            finalize_collection_change_plan(
                (first, second),
                {second.group_id: decision},
            )

    def test_source_scoped_remembered_match_is_part_of_final_plan(self):
        group = _group(
            _resolution(
                "qworld",
                _candidate("QW2"),
                MatchBasis.SUGGESTED_TITLE,
                "19279",
            )
        )
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.USE_TARGET,
            target_key="19279",
            remembered_associations=(
                RememberedAssociationDecision(
                    source=IngestionSource.ROM_SCAN,
                    value="QW2",
                ),
            ),
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
        )
        remembered = plan.remembered_associations[0]
        self.assertEqual(IngestionSource.ROM_SCAN, remembered.source)
        self.assertEqual("QW2", remembered.value)
        self.assertEqual("19279", remembered.target_key)

    def test_skip_and_ignore_are_explicit_nonblocking_final_dispositions(self):
        skip_group = _group(
            _resolution("skip-me", _candidate("Unknown"), MatchBasis.UNMATCHED)
        )
        skip = ReviewDecision(group_id=skip_group.group_id, action=ReviewAction.SKIP)
        skipped = finalize_collection_change_plan(
            (skip_group,),
            {skip_group.group_id: skip},
        )
        self.assertEqual(("skip-me",), skipped.skipped_candidate_ids)
        self.assertEqual((), skipped.record_intents)

        ignore_group = _group(
            _resolution(
                "ignore-me",
                _candidate(roms=(_rom("D:/Old/Hack.sfc", "c" * 64),)),
                MatchBasis.UNMATCHED,
            )
        )
        ignore = ReviewDecision(group_id=ignore_group.group_id, action=ReviewAction.IGNORE)
        ignored = finalize_collection_change_plan(
            (ignore_group,),
            {ignore_group.group_id: ignore},
        )
        self.assertEqual(("ignore-me",), ignored.ignored_candidate_ids)
        self.assertEqual("D:/Old/Hack.sfc", ignored.ignored_roms[0].path)
        self.assertEqual("c" * 64, ignored.ignored_roms[0].sha256)

    def test_plan_preconditions_are_deterministic_and_plan_is_immutable(self):
        group = _group(_resolution("ready", _candidate(), MatchBasis.DIRECT, "123"))
        preconditions = (
            StorePrecondition("processed.json", "sha256:aaa"),
            StorePrecondition("identity_hints", "sha256:bbb"),
        )
        first = finalize_collection_change_plan((group,), preconditions=preconditions)
        second = finalize_collection_change_plan((group,), preconditions=preconditions)

        self.assertEqual(first, second)
        self.assertNotIn("CollectionCandidate", repr(first))
        with self.assertRaises(FrozenInstanceError):
            first.record_intents[0].target_key = "456"

    def test_unused_or_invalid_local_allocations_fail_closed(self):
        group = _group(_resolution("ready", _candidate(), MatchBasis.DIRECT, "123"))
        with self.assertRaises(PlanFinalizationError):
            finalize_collection_change_plan(
                (group,),
                local_identity_allocations={group.group_id: "usr_0123456789abcdef"},
            )
        with self.assertRaises(PlanFinalizationError):
            finalize_collection_change_plan(
                (group,),
                local_identity_allocations={group.group_id: "usr_title_based"},
            )

    def test_keep_separate_new_submission_selects_primary_instead_of_preserving_old_one(self):
        migration = IdentityMigrationProposal(
            source_key="41022",
            target_key="43123",
            kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
        )
        candidate = _candidate(
            "Hack",
            roms=(_rom("C:/ROMs/Hack-new.sfc", "d" * 64, smwc_id=43123),),
            smwc_id=43123,
        )
        group = _group(
            _resolution(
                "replacement-rom",
                candidate,
                MatchBasis.USER_CONFIRMED,
                "43123",
                existing_collection_key="41022",
                migration=migration,
            )
        )
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.KEEP_SEPARATE,
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=("41022",),
        )

        self.assertEqual((), plan.identity_migrations)
        self.assertEqual(RecordIntentKind.CREATE, plan.record_intents[0].kind)
        self.assertFalse(plan.rom_updates[0].preserve_existing_primary)
        self.assertEqual("C:/ROMs/Hack-new.sfc", plan.rom_updates[0].primary_path)

    def test_local_manual_metadata_seeds_user_owned_catalogue_like_fields(self):
        manual_metadata = SharedMetadataEvidence(
            source=IngestionSource.MANUAL,
            title="Grand Poo World 3",
            authors=("Barbarian",),
            difficulty="Kaizo: Expert",
            hack_types=("Kaizo",),
            exits=16,
        )
        candidate = _candidate(
            "GPW3",
            source=IngestionSource.MANUAL,
            metadata=(manual_metadata,),
        )
        group = _group(_resolution("manual", candidate, MatchBasis.UNMATCHED))
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.IMPORT_LOCAL,
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            local_identity_allocations={group.group_id: "usr_0123456789abcdef"},
        )

        seed = plan.local_record_seeds[0]
        self.assertEqual("Grand Poo World 3", seed.title)
        self.assertEqual(("Barbarian",), seed.authors)
        self.assertEqual("Kaizo: Expert", seed.difficulty)
        self.assertEqual(("Kaizo",), seed.hack_types)
        self.assertEqual(16, seed.exits)
        self.assertEqual(("manual",), seed.source_candidate_ids)
        self.assertEqual((), plan.catalogue_updates)

    def test_manual_metadata_never_overrides_known_smwc_catalogue_metadata(self):
        kaizoff_candidate = _candidate(
            source=IngestionSource.KAIZOFF,
            metadata=(_metadata("Canonical Title"),),
            smwc_id=123,
        )
        manual_candidate = _candidate(
            "Custom Title",
            source=IngestionSource.MANUAL,
            metadata=(
                SharedMetadataEvidence(
                    source=IngestionSource.MANUAL,
                    title="Custom Title",
                    authors=("Custom Author",),
                    difficulty="Custom",
                    exits=99,
                ),
            ),
            smwc_id=123,
        )
        group = _group(
            _resolution("kaizoff", kaizoff_candidate, MatchBasis.DIRECT, "123"),
            _resolution("manual", manual_candidate, MatchBasis.USER_CONFIRMED, "123"),
        )
        plan = finalize_collection_change_plan(
            (group,),
            existing_collection_keys=("123",),
        )

        self.assertEqual("Canonical Title", plan.catalogue_updates[0].metadata.title)
        self.assertEqual(IngestionSource.KAIZOFF, plan.catalogue_updates[0].source)
        self.assertEqual(("kaizoff",), plan.catalogue_updates[0].source_candidate_ids)
        self.assertEqual((), plan.local_record_seeds)

    def test_rom_plan_preserves_source_and_candidate_provenance(self):
        rom = _rom("C:/ROMs/Hack.sfc", "a" * 64, smwc_id=123)
        scan = _candidate(roms=(rom,), smwc_id=123)
        manual = _candidate(
            source=IngestionSource.MANUAL,
            roms=(rom,),
            smwc_id=123,
        )
        group = _group(
            _resolution("scan", scan, MatchBasis.DIRECT, "123"),
            _resolution("manual-rom", manual, MatchBasis.USER_CONFIRMED, "123"),
        )
        plan = finalize_collection_change_plan((group,))
        asset = plan.rom_updates[0].assets[0]

        self.assertEqual(
            (IngestionSource.MANUAL, IngestionSource.ROM_SCAN),
            asset.sources,
        )
        self.assertEqual(("manual-rom", "scan"), asset.source_candidate_ids)

    def test_first_clear_reference_keeps_source_provenance(self):
        candidate = _candidate(
            source=IngestionSource.GIGANTIC_BUCKET,
            history=(_history("1:0"), _history("1:1", play_kind="Replay")),
            smwc_id=123,
        )
        group = _group(_resolution("history", candidate, MatchBasis.DIRECT, "123"))
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ACCEPT,
            first_clear=FirstClearDecision(
                decided=True,
                source=IngestionSource.GIGANTIC_BUCKET,
                source_record_id="1:0",
            ),
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=("123",),
        )
        history = plan.user_history_updates[0]
        self.assertEqual(IngestionSource.GIGANTIC_BUCKET, history.first_clear_source)
        self.assertEqual("1:0", history.first_clear_source_record_id)

    def test_identity_migration_keeps_review_provenance(self):
        migration = IdentityMigrationProposal(
            source_key="41022",
            target_key="43123",
            kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
        )
        group = _group(
            _resolution(
                "replacement",
                _candidate("Hack"),
                MatchBasis.USER_CONFIRMED,
                "43123",
                existing_collection_key="41022",
                migration=migration,
                reason="User confirmed this KaizOFF result as the replacement submission.",
            )
        )
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.CONFIRM_MIGRATION,
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=("41022",),
        )
        self.assertEqual(
            ("User confirmed this KaizOFF result as the replacement submission.",),
            plan.identity_migrations[0].provenance,
        )

    def test_plan_rejects_migrated_source_that_is_also_kept_active(self):
        migration = IdentityMigrationProposal(
            source_key="41022",
            target_key="43123",
            kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
        )
        migration_group = _group(
            _resolution(
                "replacement",
                _candidate(),
                MatchBasis.USER_CONFIRMED,
                "43123",
                existing_collection_key="41022",
                migration=migration,
            )
        )
        source_group = _group(
            _resolution(
                "stale-source-update",
                _candidate(),
                MatchBasis.DIRECT,
                "41022",
                existing_collection_key="41022",
            )
        )
        decision = ReviewDecision(
            group_id=migration_group.group_id,
            action=ReviewAction.CONFIRM_MIGRATION,
        )
        with self.assertRaises(PlanFinalizationError):
            finalize_collection_change_plan(
                (migration_group, source_group),
                {migration_group.group_id: decision},
                existing_collection_keys=("41022",),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
