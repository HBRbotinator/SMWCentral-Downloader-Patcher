"""Tests for Commit 011 finalized-plan Apply/runtime recovery composition."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collection_change_plan import (
    CollectionChangePlan,
    IdentityMigrationOperation,
    ReferenceMigrationOperation,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion_entrypoint import (
    apply_collection_ingestion_plan,
    collection_identity_reference_participants,
    collection_ingestion_apply_recovery_pending,
    recover_collection_ingestion_apply,
)
from collection_plan_apply import (
    COLLECTION_APPLY_JOURNAL_FILENAME,
    COLLECTION_APPLY_JOURNAL_SCHEMA,
    CollectionPlanStaleStateError,
    collect_store_preconditions,
)
from collection_reconciliation import IdentityMigrationKind
from hack_data_manager import HackDataManager


LOCAL_KEY = "usr_1111111111111111"
TARGET_KEY = "41022"


class CollectionIngestionApplyEntrypointTest(unittest.TestCase):
    def _fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        processed = root / "processed.json"
        processed.write_text(
            json.dumps(
                {
                    LOCAL_KEY: {
                        "title": "Local Dram",
                        "completed": True,
                        "completed_date": "2026-01-02",
                        "personal_rating": 4,
                        "notes": "keep me",
                        "time_to_beat": 123,
                        "files": [],
                        "file_path": "",
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
                    "save_sync_associations": {"Local Dram.srm": LOCAL_KEY},
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
                        LOCAL_KEY: {
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
                    "next_queue": [LOCAL_KEY],
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
    def _migration_plan(preconditions):
        return CollectionChangePlan(
            preconditions=tuple(preconditions),
            record_intents=(),
            catalogue_updates=(),
            local_record_seeds=(),
            rom_updates=(),
            user_history_updates=(),
            user_state_updates=(),
            identity_migrations=(
                IdentityMigrationOperation(
                    source_key=LOCAL_KEY,
                    target_key=TARGET_KEY,
                    kind=IdentityMigrationKind.LOCAL_PROMOTION,
                    merge_existing_target=False,
                    prior_submission_ids=(),
                    provenance=("reviewed local promotion",),
                ),
            ),
            reference_migrations=(
                ReferenceMigrationOperation(
                    source_key=LOCAL_KEY,
                    target_key=TARGET_KEY,
                ),
            ),
            ignored_roms=(),
            remembered_associations=(),
            skipped_candidate_ids=(),
            ignored_candidate_ids=(),
        )

    def test_apply_uses_final_plan_and_updates_collection_save_sync_and_planner(self):
        root, processed, manager, hints, participants = self._fixture()
        plan = self._migration_plan(
            collect_store_preconditions(manager, hints, participants)
        )

        result = apply_collection_ingestion_plan(
            processed,
            plan,
            manager=manager,
            identity_hints=hints,
            participants=participants,
        )

        collection = json.loads(processed.read_text(encoding="utf-8"))
        self.assertNotIn(LOCAL_KEY, collection)
        self.assertEqual(collection[TARGET_KEY]["notes"], "keep me")
        self.assertEqual(manager.data, collection)

        config = json.loads((root / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(
            config["save_sync_associations"]["Local Dram.srm"],
            TARGET_KEY,
        )
        self.assertEqual(config["unrelated_setting"], {"preserve": True})

        planner = json.loads(
            (root / "planner_state.json").read_text(encoding="utf-8")
        )
        self.assertNotIn(LOCAL_KEY, planner["entries"])
        self.assertIn(TARGET_KEY, planner["entries"])
        self.assertEqual(planner["next_queue"], [TARGET_KEY])
        self.assertEqual(result.identity_migration_count, 1)
        self.assertEqual(result.reference_participant_count, 2)
        self.assertFalse(collection_ingestion_apply_recovery_pending(processed))


    def test_apply_performs_no_provider_or_matching_work(self):
        _root, processed, manager, hints, participants = self._fixture()
        plan = self._migration_plan(
            collect_store_preconditions(manager, hints, participants)
        )

        with patch(
            "collection_ingestion_entrypoint.KaizOffCatalogueProvider"
        ) as provider_class:
            apply_collection_ingestion_plan(
                processed,
                plan,
                manager=manager,
                identity_hints=hints,
                participants=participants,
            )

        provider_class.assert_not_called()

    def test_changed_dependent_store_rejects_plan_before_collection_migration(self):
        root, processed, manager, hints, participants = self._fixture()
        plan = self._migration_plan(
            collect_store_preconditions(manager, hints, participants)
        )
        config_path = root / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["unrelated_setting"] = {"changed": True}
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        with self.assertRaises(CollectionPlanStaleStateError):
            apply_collection_ingestion_plan(
                processed,
                plan,
                manager=manager,
                identity_hints=hints,
                participants=participants,
            )

        collection = json.loads(processed.read_text(encoding="utf-8"))
        self.assertIn(LOCAL_KEY, collection)
        self.assertNotIn(TARGET_KEY, collection)

    def test_recovery_helpers_only_operate_on_existing_transaction_journal(self):
        root, processed, _manager, _hints, _participants = self._fixture()
        self.assertFalse(collection_ingestion_apply_recovery_pending(processed))
        self.assertFalse(recover_collection_ingestion_apply(processed))

        journal = {
            "schema_version": COLLECTION_APPLY_JOURNAL_SCHEMA,
            "transaction_id": "test-committed",
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

        self.assertTrue(collection_ingestion_apply_recovery_pending(processed))
        self.assertTrue(recover_collection_ingestion_apply(processed))
        self.assertFalse(journal_path.exists())
        self.assertFalse(collection_ingestion_apply_recovery_pending(processed))


if __name__ == "__main__":
    unittest.main(verbosity=2)
