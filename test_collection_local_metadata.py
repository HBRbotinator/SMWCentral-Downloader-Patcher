"""Tests for explicit local/manual Collection metadata."""
from __future__ import annotations

import unittest

from collection_change_plan import finalize_collection_change_plan
from collection_ingestion import CollectionCandidate, IngestionSource, RomFileEvidence
from collection_reconciliation import (
    CandidateResolution,
    LocalRecordMetadataDecision,
    MatchBasis,
    ReviewAction,
    ReviewDecision,
    ReconciliationError,
    validate_review_decision,
    build_reconciliation_groups,
)
from local_collection_metadata import validate_local_collection_metadata
import save_sync


LOCAL_ID = "usr_0123456789abcdef"


def _local_rom_group(title="Grand Poo World 3"):
    rom = RomFileEvidence(
        path=f"C:/ROMs/{title.replace(' ', '_')}.sfc",
        filename=f"{title.replace(' ', '_')}.sfc",
        sha256="a" * 64,
        size_bytes=4194304,
        title_hint=title,
        difficulty_hint="Master",
    )
    candidate = CollectionCandidate(
        source=IngestionSource.ROM_SCAN,
        title_hints=(title,),
        rom_files=(rom,),
        allow_local_only=True,
    )
    resolution = CandidateResolution(
        candidate_id="rom:local-metadata",
        candidate=candidate,
        match_basis=MatchBasis.UNMATCHED,
        reason="No catalogue identity established.",
    )
    groups = build_reconciliation_groups((resolution,))
    return groups[0]


class LocalCollectionMetadataValidationTest(unittest.TestCase):
    def test_normalizes_user_owned_type_difficulty_and_exits(self):
        metadata = validate_local_collection_metadata(
            "  Grand   Poo World 3  ",
            "master",
            "Kaizo, Tool-Assisted, kaizo",
            "41",
        )
        self.assertEqual("Grand Poo World 3", metadata.title)
        self.assertEqual("Master", metadata.difficulty)
        self.assertEqual(("kaizo", "tool_assisted"), metadata.hack_types)
        self.assertEqual(41, metadata.exits)

    def test_unknown_type_is_not_silently_standard(self):
        metadata = validate_local_collection_metadata(
            "Local Hack", "Unknown", "Unknown", 0
        )
        self.assertEqual((), metadata.hack_types)
        self.assertEqual("Unknown", metadata.difficulty)



    def test_local_metadata_cannot_hide_on_non_local_action(self):
        group = _local_rom_group()
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.SKIP,
            local_metadata=LocalRecordMetadataDecision(title="Local Hack"),
        )
        with self.assertRaisesRegex(ReconciliationError, "Local metadata"):
            validate_review_decision(group, decision)


class SaveSyncLocalMetadataTest(unittest.TestCase):
    def test_new_local_save_defaults_to_unknown_not_standard(self):
        _hack_id, entry = save_sync.build_local_entry("Local.srm", "Local Hack", 0)
        self.assertEqual("Unknown", entry["current_difficulty"])
        self.assertEqual("unknown", entry["hack_type"])
        self.assertEqual([], entry["hack_types"])

    def test_new_local_save_accepts_explicit_metadata(self):
        _hack_id, entry = save_sync.build_local_entry(
            "GPW3.srm",
            "Grand Poo World 3",
            41,
            difficulty="Master",
            hack_types="Kaizo",
        )
        self.assertEqual("Master", entry["current_difficulty"])
        self.assertEqual("kaizo", entry["hack_type"])
        self.assertEqual(["kaizo"], entry["hack_types"])
        self.assertEqual(41, entry["exits"])

    def test_usr_records_are_not_automatic_save_title_matches(self):
        index = save_sync.build_hack_index(
            [
                {
                    "id": LOCAL_ID,
                    "title": "Grand Poo World 3",
                    "hack_types": ["kaizo"],
                }
            ]
        )
        self.assertEqual({}, index)


class RomImportLocalMetadataTest(unittest.TestCase):
    def test_explicit_review_metadata_seeds_new_local_record(self):
        group = _local_rom_group()
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.IMPORT_LOCAL,
            local_metadata=LocalRecordMetadataDecision(
                title="Grand Poo World 3",
                difficulty="Master",
                hack_types=("kaizo",),
                exits=41,
            ),
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            local_identity_allocations={group.group_id: LOCAL_ID},
        )
        seed = plan.local_record_seeds[0]
        self.assertEqual("Grand Poo World 3", seed.title)
        self.assertEqual("Master", seed.difficulty)
        self.assertEqual(("kaizo",), seed.hack_types)
        self.assertEqual(41, seed.exits)

    def test_attach_existing_local_keeps_existing_metadata_out_of_plan(self):
        group = _local_rom_group()
        decision = ReviewDecision(
            group_id=group.group_id,
            action=ReviewAction.ATTACH_LOCAL,
            target_key=LOCAL_ID,
        )
        plan = finalize_collection_change_plan(
            (group,),
            {group.group_id: decision},
            existing_collection_keys=(LOCAL_ID,),
        )
        self.assertEqual((), plan.local_record_seeds)


if __name__ == "__main__":
    unittest.main()
