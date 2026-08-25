"""Tests for the immutable-plan-only final preview model."""
from __future__ import annotations

import unittest

from collection_change_plan import (
    CatalogueMetadataOperation,
    CatalogueMetadataSnapshot,
    CollectionChangePlan,
    IdentityMigrationOperation,
    IgnoredRomOperation,
    LocalRecordSeedOperation,
    PlannedRomAsset,
    RecordIntent,
    RecordIntentKind,
    ReferenceMigrationOperation,
    RememberedAssociationOperation,
    RomAssetsOperation,
    RomSubmissionProvenanceOperation,
    StorePrecondition,
    UserHistoryOperation,
    UserStateOperation,
)
from collection_ingestion import IngestionSource, UserPlaythroughEvidence
from collection_ingestion_plan_preview import CollectionIngestionPlanPreviewModel
from collection_reconciliation import IdentityMigrationKind


LOCAL_ID = "usr_1111111111111111"
TARGET_ID = "41022"
SHA = "a" * 64


def _plan():
    history = UserPlaythroughEvidence(
        source=IngestionSource.GIGANTIC_BUCKET,
        source_record_id="gb:1",
        play_kind="First Play",
        elapsed_text="1:23:45",
    )
    return CollectionChangePlan(
        preconditions=(
            StorePrecondition("collection", "sha256:collection"),
            StorePrecondition("collection_identity_hints", "missing"),
            StorePrecondition("planner_state", "sha256:planner"),
            StorePrecondition("save_sync_config", "sha256:config"),
        ),
        record_intents=(
            RecordIntent(TARGET_ID, RecordIntentKind.CREATE),
            RecordIntent(LOCAL_ID, RecordIntentKind.UPDATE),
        ),
        catalogue_updates=(
            CatalogueMetadataOperation(
                target_key=TARGET_ID,
                metadata=CatalogueMetadataSnapshot(
                    submission_id=41022,
                    title="Super Dram World 3",
                    authors=("PangaeaPanga",),
                    difficulty="Grandmaster",
                    hack_types=("Kaizo",),
                    exits=28,
                    release_timestamp=1700000000,
                    rating=4.625,
                    hall_of_fame=True,
                    sa1_compatible=False,
                    collaboration=False,
                    demo=False,
                ),
                source=IngestionSource.KAIZOFF,
                source_candidate_ids=("rom:1",),
            ),
        ),
        local_record_seeds=(
            LocalRecordSeedOperation(
                target_key=LOCAL_ID,
                title="Local Hack",
                authors=("Me",),
                source_candidate_ids=("local:1",),
            ),
        ),
        rom_updates=(
            RomAssetsOperation(
                target_key=TARGET_ID,
                assets=(
                    PlannedRomAsset(
                        path="C:/ROMs/Super Dram World 3.sfc",
                        filename="Super Dram World 3.sfc",
                        sha256=SHA,
                        size_bytes=1024,
                        sources=(IngestionSource.ROM_SCAN,),
                        source_candidate_ids=("rom:1",),
                        smwc_submission_id=41022,
                    ),
                ),
                primary_path="C:/ROMs/Super Dram World 3.sfc",
            ),
        ),
        rom_submission_provenance_updates=(
            RomSubmissionProvenanceOperation(
                target_key=TARGET_ID,
                path="C:/ROMs/Super Dram World 3.sfc",
                smwc_submission_id=41022,
                reason="preserve reviewed numeric submission provenance",
            ),
        ),
        user_history_updates=(
            UserHistoryOperation(
                target_key=TARGET_ID,
                playthroughs=(history,),
                first_clear_decided=True,
                first_clear_source=IngestionSource.GIGANTIC_BUCKET,
                first_clear_source_record_id="gb:1",
            ),
        ),
        user_state_updates=(
            UserStateOperation(
                target_key=TARGET_ID,
                field="completed",
                value=True,
                source=IngestionSource.GIGANTIC_BUCKET,
                reason="imported completed playthrough",
            ),
        ),
        identity_migrations=(
            IdentityMigrationOperation(
                source_key=LOCAL_ID,
                target_key=TARGET_ID,
                kind=IdentityMigrationKind.LOCAL_PROMOTION,
                merge_existing_target=False,
                prior_submission_ids=(),
                provenance=("user confirmed identity",),
            ),
        ),
        reference_migrations=(
            ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),
        ),
        ignored_roms=(IgnoredRomOperation("D:/Duplicate.sfc", SHA),),
        remembered_associations=(
            RememberedAssociationOperation(
                IngestionSource.ROM_SCAN,
                "SDW3",
                TARGET_ID,
            ),
        ),
        skipped_candidate_ids=("candidate:skip",),
        ignored_candidate_ids=("candidate:ignore",),
    )


class CollectionIngestionPlanPreviewModelTest(unittest.TestCase):
    def test_summary_counts_plan_operations_and_optional_dependent_stores(self):
        model = CollectionIngestionPlanPreviewModel(_plan())

        summary = model.summary()

        self.assertEqual(1, summary.creates)
        self.assertEqual(1, summary.updates)
        self.assertEqual(1, summary.identity_migrations)
        self.assertEqual(1, summary.rom_assets)
        self.assertEqual(1, summary.rom_provenance_updates)
        self.assertEqual(1, summary.imported_playthroughs)
        self.assertEqual(1, summary.user_state_changes)
        self.assertEqual(1, summary.ignored_roms)
        self.assertEqual(1, summary.remembered_associations)
        self.assertEqual(1, summary.skipped_items)
        self.assertEqual(1, summary.ignored_items)
        self.assertEqual(1, summary.dependent_reference_migrations)
        self.assertEqual(("planner_state", "save_sync_config"), summary.dependent_stores)

    def test_rows_are_derived_from_plan_and_surface_reference_migrations(self):
        model = CollectionIngestionPlanPreviewModel(_plan())

        rows = model.rows()
        joined = "\n".join(
            f"{row.category}|{row.target}|{row.change}|{row.details}"
            for row in rows
        )

        self.assertIn("Super Dram World 3", joined)
        self.assertIn("PangaeaPanga", joined)
        self.assertIn("Hall of Fame: yes", joined)
        self.assertIn("SA-1: no", joined)
        self.assertIn("Local Hack", joined)
        self.assertIn("C:/ROMs/Super Dram World 3.sfc", joined)
        self.assertIn("Preserve SMWC submission provenance", joined)
        self.assertIn("SMWC 41022", joined)
        self.assertIn("usr_1111111111111111 → 41022", joined)
        self.assertIn("planner_state, save_sync_config", joined)
        self.assertIn("Selected first clear: giganticbucket:gb:1", joined)
        self.assertIn("giganticbucket:gb:1", joined)
        self.assertIn("Remember reviewed source association", joined)
        self.assertIn("candidate:skip", joined)
        self.assertIn("candidate:ignore", joined)

    def test_model_rejects_non_plan_input(self):
        with self.assertRaises(TypeError):
            CollectionIngestionPlanPreviewModel(object())


if __name__ == "__main__":
    unittest.main(verbosity=2)
