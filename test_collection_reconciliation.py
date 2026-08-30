"""Tests for Collection reconciliation grouping and explicit review rules."""
from __future__ import annotations

import re
import unittest

from collection_ingestion import (
    CollectionCandidate,
    IngestionSource,
    RomFileEvidence,
    UserPlaythroughEvidence,
)
from collection_reconciliation import (
    CandidateResolution,
    FirstClearDecision,
    IdentityMigrationKind,
    IdentityMigrationProposal,
    IgnoredRomDecision,
    MatchBasis,
    ReconciliationError,
    RememberedAssociationDecision,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    RomSelectionDecision,
    UserFieldProposal,
    UserFieldResolution,
    automatic_first_clear,
    build_reconciliation_groups,
    generate_local_collection_id,
    is_local_collection_key,
    resolved_target_key,
    validate_review_decision,
)


def _rom(path: str, sha: str, title: str = "Hack") -> RomFileEvidence:
    return RomFileEvidence(
        path=path,
        filename=path.rsplit("/", 1)[-1],
        sha256=sha,
        size_bytes=1024,
        title_hint=title,
    )


def _candidate(
    title: str = "Hack",
    *,
    roms=(),
    history=(),
    source=IngestionSource.ROM_SCAN,
) -> CollectionCandidate:
    return CollectionCandidate(
        source=source,
        title_hints=(title,),
        rom_files=tuple(roms),
        user_history=tuple(history),
        allow_local_only=True,
    )


def _resolution(
    candidate_id: str,
    candidate: CollectionCandidate,
    basis: MatchBasis,
    target: str = "",
    **kwargs,
) -> CandidateResolution:
    return CandidateResolution(
        candidate_id=candidate_id,
        candidate=candidate,
        match_basis=basis,
        target_key=target,
        **kwargs,
    )


def _history(record_id: str, *, play_kind="First Play", category="100%"):
    return UserPlaythroughEvidence(
        source=IngestionSource.GIGANTIC_BUCKET,
        source_record_id=record_id,
        category=category,
        play_kind=play_kind,
        elapsed_text="1:23:45",
        elapsed_seconds=5025,
        completed_date_iso="2020-01-02",
    )


class CollectionReconciliationTest(unittest.TestCase):
    def test_local_identity_is_opaque_random_and_not_evidence_derived(self):
        first = generate_local_collection_id()
        second = generate_local_collection_id()

        self.assertRegex(first, r"^usr_[0-9a-f]{16}$")
        self.assertTrue(is_local_collection_key(first))
        self.assertNotEqual(first, second)
        self.assertNotIn("Hack", first)
        self.assertNotIn("ROM", first)

    def test_same_hash_direct_candidates_group_without_rom_selection_block(self):
        sha = "a" * 64
        groups = build_reconciliation_groups(
            (
                _resolution(
                    "rom-a",
                    _candidate(roms=(_rom("C:/ROMs/Hack.sfc", sha),)),
                    MatchBasis.DIRECT,
                    "123",
                ),
                _resolution(
                    "rom-b",
                    _candidate(roms=(_rom("D:/Backup/Hack.sfc", sha),)),
                    MatchBasis.DIRECT,
                    "123",
                ),
            )
        )

        self.assertEqual(1, len(groups))
        group = groups[0]
        self.assertEqual((sha,), group.rom_hashes)
        self.assertFalse(group.blocking)
        self.assertEqual((ReviewState.READY,), group.review_states)
        self.assertEqual(2, len(group.rom_files))

    def test_different_hashes_same_title_proposal_requires_rom_confirmation(self):
        groups = build_reconciliation_groups(
            (
                _resolution(
                    "rom-a",
                    _candidate(roms=(_rom("C:/ROMs/Hack.sfc", "a" * 64),)),
                    MatchBasis.AUTO_TITLE,
                    "123",
                ),
                _resolution(
                    "rom-b",
                    _candidate(roms=(_rom("C:/ROMs/Hack-v2.sfc", "b" * 64),)),
                    MatchBasis.AUTO_TITLE,
                    "123",
                ),
            )
        )

        self.assertEqual(1, len(groups))
        self.assertIn(ReviewState.ROM_SELECTION_REQUIRED, groups[0].review_states)
        self.assertTrue(groups[0].blocking)

    def test_established_collection_target_anchors_matching_source_evidence(self):
        sha_a = "a" * 64
        sha_b = "b" * 64
        groups = build_reconciliation_groups(
            (
                _resolution(
                    "history",
                    _candidate(source=IngestionSource.GIGANTIC_BUCKET),
                    MatchBasis.DIRECT,
                    "19279",
                    existing_collection_key="19279",
                ),
                _resolution(
                    "rom",
                    _candidate(roms=(_rom("C:/ROMs/QW2.sfc", sha_a),)),
                    MatchBasis.AUTO_TITLE,
                    "19279",
                ),
                _resolution(
                    "rom-copy",
                    _candidate(roms=(_rom("D:/ROMs/QW2.sfc", sha_b),)),
                    MatchBasis.AUTO_TITLE,
                    "19279",
                ),
            )
        )

        self.assertEqual(1, len(groups))
        self.assertEqual("target:19279", groups[0].group_id)
        self.assertIn(ReviewState.ROM_SELECTION_REQUIRED, groups[0].review_states)

    def test_matching_review_states_keep_safe_and_guarded_matches_distinct(self):
        auto = build_reconciliation_groups(
            (_resolution("auto", _candidate(), MatchBasis.AUTO_TITLE, "123"),)
        )[0]
        suggested = build_reconciliation_groups(
            (_resolution("suggested", _candidate(), MatchBasis.SUGGESTED_TITLE, "123"),)
        )[0]
        ambiguous = build_reconciliation_groups(
            (
                _resolution(
                    "ambiguous",
                    _candidate(),
                    MatchBasis.AMBIGUOUS,
                    alternative_target_keys=("123", "456"),
                ),
            )
        )[0]
        conflict = build_reconciliation_groups(
            (
                _resolution(
                    "conflict",
                    _candidate(),
                    MatchBasis.CONFLICT,
                    alternative_target_keys=("123", "456"),
                ),
            )
        )[0]

        self.assertEqual((ReviewState.AUTO_MATCHED,), auto.review_states)
        self.assertFalse(auto.blocking)
        self.assertEqual((ReviewState.NEEDS_CONFIRMATION,), suggested.review_states)
        self.assertEqual((ReviewState.AMBIGUOUS,), ambiguous.review_states)
        self.assertEqual((ReviewState.IDENTITY_CONFLICT,), conflict.review_states)

    def test_guarded_suggestion_does_not_share_identity_bucket_with_safe_match(self):
        groups = build_reconciliation_groups(
            (
                _resolution(
                    "bunbun",
                    _candidate(
                        "Bunbun World",
                        roms=(_rom("C:/ROMs/bunbunworld1.0.sfc", "a" * 64),),
                    ),
                    MatchBasis.AUTO_TITLE,
                    "20177",
                ),
                _resolution(
                    "bui-bui",
                    _candidate(
                        "Bui Bui World",
                        roms=(_rom("C:/ROMs/Bui Bui World.sfc", "b" * 64),),
                    ),
                    MatchBasis.SUGGESTED_TITLE,
                    "20177",
                ),
            )
        )

        self.assertEqual(2, len(groups))
        by_member = {group.members[0].candidate_id: group for group in groups}
        self.assertEqual("proposal:20177", by_member["bunbun"].group_id)
        self.assertTrue(by_member["bui-bui"].group_id.startswith("review-sha256:"))
        self.assertEqual(
            (ReviewState.NEEDS_CONFIRMATION,),
            by_member["bui-bui"].review_states,
        )

    def test_unmatched_item_may_resolve_to_explicit_local_allocation(self):
        group = build_reconciliation_groups(
            (_resolution("local", _candidate("Super Bui Bui World"), MatchBasis.UNMATCHED),)
        )[0]
        decision = ReviewDecision(group_id=group.group_id, action=ReviewAction.IMPORT_LOCAL)

        with self.assertRaises(ReconciliationError):
            resolved_target_key(group, decision)

        self.assertEqual(
            "usr_0123456789abcdef",
            resolved_target_key(group, decision, "usr_0123456789abcdef"),
        )

    def test_numeric_submission_replacement_is_explicit_and_title_inference_cannot_create_it(self):
        migration = IdentityMigrationProposal(
            source_key="41022",
            target_key="43123",
            kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
        )
        candidate = _candidate("Super Dram World 3")

        with self.assertRaises(ReconciliationError):
            _resolution(
                "auto-update",
                candidate,
                MatchBasis.AUTO_TITLE,
                "43123",
                existing_collection_key="41022",
                migration=migration,
            )

        group = build_reconciliation_groups(
            (
                _resolution(
                    "confirmed-update",
                    candidate,
                    MatchBasis.USER_CONFIRMED,
                    "43123",
                    existing_collection_key="41022",
                    migration=migration,
                ),
            )
        )[0]
        self.assertIn(ReviewState.IDENTITY_MIGRATION, group.review_states)
        self.assertEqual((41022,), migration.retained_submission_ids)

    def test_local_promotion_rejects_wrong_identity_shapes(self):
        promotion = IdentityMigrationProposal(
            source_key="usr_0123456789abcdef",
            target_key="43123",
            kind=IdentityMigrationKind.LOCAL_PROMOTION,
        )
        self.assertEqual((), promotion.retained_submission_ids)

        with self.assertRaises(ReconciliationError):
            IdentityMigrationProposal(
                source_key="41022",
                target_key="43123",
                kind=IdentityMigrationKind.LOCAL_PROMOTION,
            )
        with self.assertRaises(ReconciliationError):
            IdentityMigrationProposal(
                source_key="usr_0123456789abcdef",
                target_key="usr_fedcba9876543210",
                kind=IdentityMigrationKind.LOCAL_PROMOTION,
            )

    def test_multiple_or_speedrun_history_requires_first_clear_verification(self):
        multiple = build_reconciliation_groups(
            (
                _resolution(
                    "history",
                    _candidate(
                        history=(
                            _history("1:0"),
                            _history("1:1", play_kind="Replay"),
                        ),
                        source=IngestionSource.GIGANTIC_BUCKET,
                    ),
                    MatchBasis.DIRECT,
                    "123",
                ),
            )
        )[0]
        pb = build_reconciliation_groups(
            (
                _resolution(
                    "pb",
                    _candidate(
                        history=(_history("2:0", play_kind="Any% PB"),),
                        source=IngestionSource.GIGANTIC_BUCKET,
                    ),
                    MatchBasis.DIRECT,
                    "123",
                ),
            )
        )[0]
        ordinary = _history("3:0")

        self.assertIn(ReviewState.FIRST_CLEAR_VERIFICATION, multiple.review_states)
        self.assertIn(ReviewState.FIRST_CLEAR_VERIFICATION, pb.review_states)
        self.assertEqual(ordinary, automatic_first_clear((ordinary,)))
        self.assertIsNone(automatic_first_clear((_history("4:0", play_kind="Race PB"),)))

    def test_remote_provider_cannot_propose_user_state_and_giganticbucket_notes_stay_history(self):
        with self.assertRaises(ReconciliationError):
            UserFieldProposal(
                field="completed",
                current_value=False,
                proposed_value=True,
                source=IngestionSource.KAIZOFF,
                reason="provider",
            )
        with self.assertRaises(ReconciliationError):
            UserFieldProposal(
                field="notes",
                current_value="",
                proposed_value="Imported note",
                source=IngestionSource.GIGANTIC_BUCKET,
                reason="playthrough note",
            )

    def test_user_conflict_rom_selection_and_first_clear_require_complete_decision(self):
        proposals = (
            UserFieldProposal(
                field="completed_date",
                current_value="2021-01-01",
                proposed_value="2020-01-01",
                source=IngestionSource.GIGANTIC_BUCKET,
                reason="Imported completion date",
                conflict=True,
            ),
        )
        group = build_reconciliation_groups(
            (
                _resolution(
                    "complex",
                    _candidate(
                        roms=(
                            _rom("C:/ROMs/Hack.sfc", "a" * 64),
                            _rom("C:/ROMs/Hack-v2.sfc", "b" * 64),
                        ),
                        history=(_history("5:0"), _history("5:1", play_kind="Replay")),
                    ),
                    MatchBasis.DIRECT,
                    "123",
                    user_field_proposals=proposals,
                ),
            )
        )[0]

        with self.assertRaises(ReconciliationError):
            validate_review_decision(
                group,
                ReviewDecision(group_id=group.group_id, action=ReviewAction.ACCEPT),
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
            user_field_resolutions=(
                UserFieldResolution(field="completed_date", use_proposed=False),
            ),
            first_clear=FirstClearDecision(decided=True, source_record_id=None),
            remembered_associations=(
                RememberedAssociationDecision(
                    source=IngestionSource.ROM_SCAN,
                    value="Hack-v2",
                ),
            ),
        )
        validate_review_decision(group, decision)

    def test_migration_review_accepts_only_confirm_or_keep_separate(self):
        migration = IdentityMigrationProposal(
            source_key="41022",
            target_key="43123",
            kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
        )
        group = build_reconciliation_groups(
            (
                _resolution(
                    "update",
                    _candidate(),
                    MatchBasis.USER_CONFIRMED,
                    "43123",
                    existing_collection_key="41022",
                    migration=migration,
                ),
            )
        )[0]

        with self.assertRaises(ReconciliationError):
            validate_review_decision(
                group,
                ReviewDecision(group_id=group.group_id, action=ReviewAction.ACCEPT),
            )
        validate_review_decision(
            group,
            ReviewDecision(
                group_id=group.group_id,
                action=ReviewAction.CONFIRM_MIGRATION,
            ),
        )
        validate_review_decision(
            group,
            ReviewDecision(group_id=group.group_id, action=ReviewAction.KEEP_SEPARATE),
        )

    def test_ignore_requires_rom_evidence(self):
        group = build_reconciliation_groups(
            (_resolution("unmatched", _candidate(), MatchBasis.UNMATCHED),)
        )[0]
        with self.assertRaises(ReconciliationError):
            validate_review_decision(
                group,
                ReviewDecision(group_id=group.group_id, action=ReviewAction.IGNORE),
            )

    def test_only_authorized_sources_can_propose_user_owned_scalar_state(self):
        for source in (
            IngestionSource.KAIZOFF,
            IngestionSource.ROM_SCAN,
            IngestionSource.TOOL_PATCH,
        ):
            with self.subTest(source=source):
                with self.assertRaises(ReconciliationError):
                    UserFieldProposal(
                        field="completed",
                        current_value=False,
                        proposed_value=True,
                        source=source,
                        reason="not authorized",
                    )

        UserFieldProposal(
            field="completed",
            current_value=False,
            proposed_value=True,
            source=IngestionSource.SAVE_SCAN,
            reason="save completion evidence",
        )
        UserFieldProposal(
            field="notes",
            current_value="",
            proposed_value="Explicit user note",
            source=IngestionSource.MANUAL,
            reason="explicit manual edit",
        )

    def test_first_clear_selection_is_source_scoped_not_record_id_only(self):
        gigantic = _history("same-id")
        manual = UserPlaythroughEvidence(
            source=IngestionSource.MANUAL,
            source_record_id="same-id",
            category="100%",
            play_kind="Replay",
            elapsed_text="2:00:00",
            elapsed_seconds=7200,
        )
        candidate = _candidate(
            history=(gigantic, manual),
            source=IngestionSource.GIGANTIC_BUCKET,
        )
        group = build_reconciliation_groups(
            (_resolution("history", candidate, MatchBasis.DIRECT, "123"),)
        )[0]

        with self.assertRaises(ReconciliationError):
            validate_review_decision(
                group,
                ReviewDecision(
                    group_id=group.group_id,
                    action=ReviewAction.ACCEPT,
                    first_clear=FirstClearDecision(
                        decided=True,
                        source=IngestionSource.SAVE_SCAN,
                        source_record_id="same-id",
                    ),
                ),
            )

        validate_review_decision(
            group,
            ReviewDecision(
                group_id=group.group_id,
                action=ReviewAction.ACCEPT,
                first_clear=FirstClearDecision(
                    decided=True,
                    source=IngestionSource.GIGANTIC_BUCKET,
                    source_record_id="same-id",
                ),
            ),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
