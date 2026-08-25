"""Tests for explicit finalized SMWC replacement Apply/runtime recovery composition."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collection_change_plan import (
    CollectionChangePlan,
    IdentityMigrationOperation,
    ReferenceMigrationOperation,
    RomSubmissionProvenanceOperation,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion_entrypoint import collection_identity_reference_participants
from collection_plan_apply import (
    COLLECTION_APPLY_JOURNAL_FILENAME,
    COLLECTION_APPLY_JOURNAL_SCHEMA,
    CollectionPlanStaleStateError,
    collect_store_preconditions,
)
from collection_reconciliation import IdentityMigrationKind
from collection_update_apply import (
    CollectionUpdateApplyError,
    apply_finalized_collection_update,
    collection_update_apply_recovery_pending,
    recover_collection_update_apply,
)
from collection_update_discovery import CollectionUpdateSelection
from collection_update_plan import FinalizedCollectionUpdatePlan
from hack_data_manager import HackDataManager
from rom_title_matching import CatalogueEntry


SOURCE_KEY = "41022"
TARGET_KEY = "43123"
ROM_PATH = "C:/Roms/Super Dram World 3.sfc"


class CollectionUpdateApplyTest(unittest.TestCase):
    def _fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        processed = root / "processed.json"
        processed.write_text(
            json.dumps(
                {
                    SOURCE_KEY: {
                        "title": "Super Dram World 3",
                        "completed": True,
                        "completed_date": "2026-01-02",
                        "personal_rating": 5,
                        "notes": "preserve user state",
                        "files": [
                            {
                                "path": ROM_PATH,
                                "filename": "Super Dram World 3.sfc",
                                "sha256": "a" * 64,
                                "size": 1024,
                                "primary": True,
                            }
                        ],
                        "file_path": ROM_PATH,
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "config.json").write_text(
            json.dumps(
                {
                    "save_sync_associations": {"Super Dram World 3.srm": SOURCE_KEY},
                    "unrelated_setting": {"preserve": True},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        (root / "planner_state.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "entries": {
                        SOURCE_KEY: {
                            "lifecycle_status": "Planned",
                            "planning_horizon": "Next",
                            "list_ids": [],
                            "planned_at": "",
                            "started_at": "",
                            "beaten_at": "",
                            "completed_at": "",
                            "last_played_at": "",
                        }
                    },
                    "lists": [],
                    "next_queue": [SOURCE_KEY],
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        manager = HackDataManager(str(processed))
        hints = CollectionIdentityHintsStore.beside_processed_json(processed)
        participants = collection_identity_reference_participants(processed)
        return root, processed, manager, hints, participants

    @staticmethod
    def _selection():
        return CollectionUpdateSelection(
            source_collection_key=SOURCE_KEY,
            source_entry=CatalogueEntry(int(SOURCE_KEY), "Super Dram World 3"),
            target_entry=CatalogueEntry(int(TARGET_KEY), "Super Dram World 3 Remastered"),
            target_already_in_collection=False,
            catalogue_fetched_at=1.0,
            catalogue_source="test",
            catalogue_stale=False,
        )

    def _finalized(self, preconditions):
        plan = CollectionChangePlan(
            preconditions=tuple(preconditions),
            record_intents=(),
            catalogue_updates=(),
            local_record_seeds=(),
            rom_updates=(),
            user_history_updates=(),
            user_state_updates=(),
            identity_migrations=(
                IdentityMigrationOperation(
                    source_key=SOURCE_KEY,
                    target_key=TARGET_KEY,
                    kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
                    merge_existing_target=False,
                    prior_submission_ids=(int(SOURCE_KEY),),
                    provenance=("explicit reviewed replacement",),
                ),
            ),
            reference_migrations=(
                ReferenceMigrationOperation(source_key=SOURCE_KEY, target_key=TARGET_KEY),
            ),
            ignored_roms=(),
            remembered_associations=(),
            skipped_candidate_ids=(),
            ignored_candidate_ids=(),
            rom_submission_provenance_updates=(
                RomSubmissionProvenanceOperation(
                    target_key=TARGET_KEY,
                    path=ROM_PATH,
                    smwc_submission_id=int(SOURCE_KEY),
                    reason="preserve old ROM provenance",
                ),
            ),
        )
        return FinalizedCollectionUpdatePlan(
            selection=self._selection(),
            plan=plan,
            detail_fetched_at=2.0,
            detail_source="test",
            detail_stale=False,
        )

    def test_apply_migrates_collection_references_and_preserves_old_rom_provenance(self):
        root, processed, manager, hints, participants = self._fixture()
        finalized = self._finalized(collect_store_preconditions(manager, hints, participants))

        result = apply_finalized_collection_update(
            processed,
            finalized,
            manager=manager,
            identity_hints=hints,
            participants=participants,
        )

        collection = json.loads(processed.read_text(encoding="utf-8"))
        self.assertNotIn(SOURCE_KEY, collection)
        self.assertIn(TARGET_KEY, collection)
        self.assertTrue(collection[TARGET_KEY]["completed"])
        self.assertEqual(collection[TARGET_KEY]["notes"], "preserve user state")
        self.assertEqual(
            collection[TARGET_KEY]["files"][0]["smwc_submission_id"],
            int(SOURCE_KEY),
        )
        self.assertIn(int(SOURCE_KEY), collection[TARGET_KEY]["prior_smwc_submission_ids"])

        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["save_sync_associations"]["Super Dram World 3.srm"], TARGET_KEY)
        self.assertEqual(config["unrelated_setting"], {"preserve": True})

        planner = json.loads((root / "planner_state.json").read_text(encoding="utf-8"))
        self.assertNotIn(SOURCE_KEY, planner["entries"])
        self.assertIn(TARGET_KEY, planner["entries"])
        self.assertEqual(planner["next_queue"], [TARGET_KEY])
        self.assertEqual(result.identity_migration_count, 1)
        self.assertEqual(result.reference_participant_count, 2)
        self.assertFalse(collection_update_apply_recovery_pending(processed))

    def test_changed_dependent_store_rejects_finalized_replacement(self):
        root, processed, manager, hints, participants = self._fixture()
        finalized = self._finalized(collect_store_preconditions(manager, hints, participants))
        config_path = root / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["unrelated_setting"] = {"changed": True}
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        with self.assertRaises(CollectionPlanStaleStateError):
            apply_finalized_collection_update(
                processed,
                finalized,
                manager=manager,
                identity_hints=hints,
                participants=participants,
            )

        collection = json.loads(processed.read_text(encoding="utf-8"))
        self.assertIn(SOURCE_KEY, collection)
        self.assertNotIn(TARGET_KEY, collection)

    def test_wrapper_rejects_non_replacement_plan(self):
        _root, processed, manager, hints, participants = self._fixture()
        finalized = self._finalized(collect_store_preconditions(manager, hints, participants))
        bad_plan = CollectionChangePlan(
            preconditions=finalized.plan.preconditions,
            record_intents=(),
            catalogue_updates=(),
            local_record_seeds=(),
            rom_updates=(),
            user_history_updates=(),
            user_state_updates=(),
            identity_migrations=(),
            reference_migrations=(),
            ignored_roms=(),
            remembered_associations=(),
            skipped_candidate_ids=(),
            ignored_candidate_ids=(),
        )
        bad = FinalizedCollectionUpdatePlan(
            selection=finalized.selection,
            plan=bad_plan,
            detail_fetched_at=2.0,
            detail_source="test",
            detail_stale=False,
        )
        with self.assertRaises(CollectionUpdateApplyError):
            apply_finalized_collection_update(
                processed,
                bad,
                manager=manager,
                identity_hints=hints,
                participants=participants,
            )

    def test_recovery_helpers_share_the_coordinated_collection_journal(self):
        root, processed, _manager, _hints, _participants = self._fixture()
        self.assertFalse(collection_update_apply_recovery_pending(processed))
        self.assertFalse(recover_collection_update_apply(processed))
        journal = {
            "schema_version": COLLECTION_APPLY_JOURNAL_SCHEMA,
            "transaction_id": "replacement-test-committed",
            "state": "committed",
            "entries": [
                {
                    "target": "processed.json",
                    "staged": "",
                    "rollback": None,
                    "original_exists": True,
                }
            ],
        }
        journal_path = root / COLLECTION_APPLY_JOURNAL_FILENAME
        journal_path.write_text(json.dumps(journal) + "\n", encoding="utf-8")
        self.assertTrue(collection_update_apply_recovery_pending(processed))
        self.assertTrue(recover_collection_update_apply(processed))
        self.assertFalse(journal_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
