"""Tests for Save Data Sync Collection-ID reference migration."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collection_change_plan import (
    CollectionChangePlan,
    IdentityMigrationOperation,
    RecordIntent,
    RecordIntentKind,
    ReferenceMigrationOperation,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion_session import build_collection_ingestion_session
from collection_plan_apply import (
    CollectionPlanApplyError,
    CollectionPlanStaleStateError,
    apply_collection_change_plan,
    collect_store_preconditions,
)
from collection_reconciliation import IdentityMigrationKind
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffIndexSnapshot
from rom_ingestion import RomLibraryScan
from save_sync_reference_participant import (
    SAVE_SYNC_ASSOCIATION_CONFIG_KEY,
    SAVE_SYNC_REFERENCE_STORE_NAME,
    SaveSyncAssociationReferenceParticipant,
    SaveSyncReferenceError,
)


LOCAL_ID = "usr_1111111111111111"
TARGET_ID = "43123"


def _json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


class SaveSyncAssociationReferenceParticipantTest(unittest.TestCase):
    def _fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="save_sync_reference_")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config = root / "config.json"
        config.write_bytes(
            _json_bytes(
                {
                    "base_rom_path": "C:/ROMs/base.smc",
                    "save_sync_dirs": ["C:/Saves"],
                    SAVE_SYNC_ASSOCIATION_CONFIG_KEY: {
                        "localhack": LOCAL_ID,
                        "alternate": LOCAL_ID,
                        "other": "100",
                    },
                    "future_unknown_setting": {"preserve": True},
                }
            )
        )
        participant = SaveSyncAssociationReferenceParticipant(config)
        return root, config, participant

    def test_factory_uses_config_beside_processed_json(self):
        participant = SaveSyncAssociationReferenceParticipant.beside_processed_json(
            "C:/AppData/processed.json"
        )

        self.assertEqual(Path("C:/AppData/config.json"), participant.path)
        self.assertEqual(SAVE_SYNC_REFERENCE_STORE_NAME, participant.store_name)

    def test_revision_token_hashes_entire_config_and_missing_is_explicit(self):
        root, config, participant = self._fixture()
        before = participant.revision_token()

        document = json.loads(config.read_text(encoding="utf-8"))
        document["base_rom_path"] = "D:/ROMs/base.smc"
        config.write_bytes(_json_bytes(document))
        after = participant.revision_token()

        self.assertTrue(before.startswith("sha256:"))
        self.assertNotEqual(before, after)
        self.assertEqual(
            "missing",
            SaveSyncAssociationReferenceParticipant(root / "absent.json").revision_token(),
        )

    def test_prepare_migrates_every_targeting_alias_and_preserves_other_config(self):
        _, config, participant = self._fixture()
        expected = participant.revision_token()

        prepared = participant.prepare_reference_migrations(
            (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
        )

        self.assertEqual(expected, prepared.expected_revision_token)
        self.assertEqual(SAVE_SYNC_REFERENCE_STORE_NAME, prepared.store_name)
        self.assertEqual(1, len(prepared.writes))
        self.assertEqual(config, prepared.writes[0].path)
        self.assertEqual(expected, participant.revision_token())
        document = json.loads(prepared.writes[0].content_bytes.decode("utf-8"))
        self.assertEqual(
            {
                "localhack": TARGET_ID,
                "alternate": TARGET_ID,
                "other": "100",
            },
            document[SAVE_SYNC_ASSOCIATION_CONFIG_KEY],
        )
        self.assertEqual(["C:/Saves"], document["save_sync_dirs"])
        self.assertEqual({"preserve": True}, document["future_unknown_setting"])

    def test_no_matching_reference_prepares_no_write(self):
        _, _, participant = self._fixture()

        prepared = participant.prepare_reference_migrations(
            (ReferenceMigrationOperation("999", TARGET_ID),)
        )

        self.assertEqual((), prepared.writes)

    def test_numeric_replacement_uses_same_reference_migration_contract(self):
        _, config, participant = self._fixture()
        document = json.loads(config.read_text(encoding="utf-8"))
        document[SAVE_SYNC_ASSOCIATION_CONFIG_KEY]["dram3"] = "41022"
        config.write_bytes(_json_bytes(document))

        prepared = participant.prepare_reference_migrations(
            (ReferenceMigrationOperation("41022", "43123"),)
        )
        updated = json.loads(prepared.writes[0].content_bytes.decode("utf-8"))

        self.assertEqual("43123", updated[SAVE_SYNC_ASSOCIATION_CONFIG_KEY]["dram3"])
        self.assertEqual(LOCAL_ID, updated[SAVE_SYNC_ASSOCIATION_CONFIG_KEY]["localhack"])

    def test_malformed_config_or_association_shape_fails_closed(self):
        root, config, participant = self._fixture()
        config.write_text('{"save_sync_associations":{},"save_sync_associations":{}}', encoding="utf-8")
        with self.assertRaises(SaveSyncReferenceError):
            participant.prepare_reference_migrations(
                (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
            )

        config.write_bytes(_json_bytes({SAVE_SYNC_ASSOCIATION_CONFIG_KEY: []}))
        with self.assertRaises(SaveSyncReferenceError):
            participant.prepare_reference_migrations(
                (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
            )

        missing = SaveSyncAssociationReferenceParticipant(root / "missing.json")
        prepared = missing.prepare_reference_migrations(
            (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
        )
        self.assertEqual((), prepared.writes)

    def test_non_string_association_targets_fail_closed(self):
        _, config, participant = self._fixture()
        config.write_bytes(
            _json_bytes({SAVE_SYNC_ASSOCIATION_CONFIG_KEY: {"broken": 43123}})
        )

        with self.assertRaises(SaveSyncReferenceError):
            participant.prepare_reference_migrations(
                (ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),)
            )


class SaveSyncReferenceTransactionalIntegrationTest(unittest.TestCase):
    def _fixture(self):
        temporary = tempfile.TemporaryDirectory(prefix="save_sync_reference_apply_")
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        processed = root / "processed.json"
        processed.write_bytes(
            _json_bytes(
                {
                    LOCAL_ID: {
                        "title": "Local Hack",
                        "authors": [],
                        "current_difficulty": "No Difficulty",
                        "hack_type": "standard",
                        "hack_types": ["standard"],
                        "exits": 10,
                        "completed": True,
                        "completed_date": "2025-01-02",
                        "personal_rating": 4,
                        "notes": "keep me",
                        "time_to_beat": 123,
                        "file_path": "",
                        "files": [],
                        "local_save_entry": True,
                    }
                }
            )
        )
        manager = HackDataManager(str(processed))
        manager._schedule_delayed_save = lambda: None
        manager._save_timer = None
        hints = CollectionIdentityHintsStore.beside_processed_json(processed)
        config = root / "config.json"
        config.write_bytes(
            _json_bytes(
                {
                    "save_sync_dirs": ["C:/Saves"],
                    SAVE_SYNC_ASSOCIATION_CONFIG_KEY: {
                        "localhack": LOCAL_ID,
                        "other": "100",
                    },
                }
            )
        )
        participant = SaveSyncAssociationReferenceParticipant(config)
        return root, processed, manager, hints, config, participant

    @staticmethod
    def _plan(preconditions):
        migration = IdentityMigrationOperation(
            source_key=LOCAL_ID,
            target_key=TARGET_ID,
            kind=IdentityMigrationKind.LOCAL_PROMOTION,
            merge_existing_target=False,
            prior_submission_ids=(),
            provenance=("user confirmed KaizOFF identity",),
        )
        return CollectionChangePlan(
            preconditions=tuple(preconditions),
            record_intents=(RecordIntent(TARGET_ID, RecordIntentKind.CREATE),),
            catalogue_updates=(),
            local_record_seeds=(),
            rom_updates=(),
            user_history_updates=(),
            user_state_updates=(),
            identity_migrations=(migration,),
            reference_migrations=(ReferenceMigrationOperation(LOCAL_ID, TARGET_ID),),
            ignored_roms=(),
            remembered_associations=(),
            skipped_candidate_ids=(),
            ignored_candidate_ids=(),
        )

    def test_local_promotion_moves_collection_and_save_alias_in_one_apply(self):
        _, processed, manager, hints, config, participant = self._fixture()
        preconditions = collect_store_preconditions(manager, hints, (participant,))
        plan = self._plan(preconditions)

        result = apply_collection_change_plan(
            plan,
            manager,
            hints,
            reference_participants=(participant,),
        )

        collection = json.loads(processed.read_text(encoding="utf-8"))
        config_doc = json.loads(config.read_text(encoding="utf-8"))
        self.assertNotIn(LOCAL_ID, collection)
        self.assertIn(TARGET_ID, collection)
        self.assertEqual(
            TARGET_ID,
            config_doc[SAVE_SYNC_ASSOCIATION_CONFIG_KEY]["localhack"],
        )
        self.assertEqual("100", config_doc[SAVE_SYNC_ASSOCIATION_CONFIG_KEY]["other"])
        self.assertEqual(1, result.reference_participant_count)

    def test_injected_transaction_failure_restores_collection_and_config(self):
        _, processed, manager, hints, config, participant = self._fixture()
        original_collection = processed.read_bytes()
        original_config = config.read_bytes()
        preconditions = collect_store_preconditions(manager, hints, (participant,))
        plan = self._plan(preconditions)

        with self.assertRaises(CollectionPlanApplyError):
            apply_collection_change_plan(
                plan,
                manager,
                hints,
                reference_participants=(participant,),
                fail_after_replace=1,
            )

        self.assertEqual(original_collection, processed.read_bytes())
        self.assertEqual(original_config, config.read_bytes())
        self.assertIn(LOCAL_ID, manager.data)

    def test_ingestion_session_captures_save_sync_config_precondition(self):
        _, _, manager, hints, _, participant = self._fixture()
        catalogue = KaizOffIndexSnapshot(
            entries=(),
            fetched_at=1.0,
            source="test",
            stale=False,
        )
        session = build_collection_ingestion_session(
            manager,
            hints,
            catalogue,
            rom_scan=RomLibraryScan(root="C:/ROMs", roms=(), duplicate_groups=()),
            participants=(participant,),
        )

        tokens = {item.store_name: item.revision_token for item in session.preconditions}
        self.assertEqual(participant.revision_token(), tokens[SAVE_SYNC_REFERENCE_STORE_NAME])

    def test_config_change_after_review_makes_plan_stale(self):
        _, processed, manager, hints, config, participant = self._fixture()
        preconditions = collect_store_preconditions(manager, hints, (participant,))
        plan = self._plan(preconditions)

        document = json.loads(config.read_text(encoding="utf-8"))
        document["save_sync_dirs"].append("D:/Other Saves")
        config.write_bytes(_json_bytes(document))

        with self.assertRaises(CollectionPlanStaleStateError):
            apply_collection_change_plan(
                plan,
                manager,
                hints,
                reference_participants=(participant,),
            )

        self.assertIn(LOCAL_ID, json.loads(processed.read_text(encoding="utf-8")))

    def test_config_outside_collection_root_is_rejected_by_transaction_boundary(self):
        root, _, manager, hints, _, _ = self._fixture()
        outside_dir = Path(tempfile.mkdtemp(prefix="save_sync_reference_outside_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(outside_dir, ignore_errors=True))
        outside_config = outside_dir / "config.json"
        outside_config.write_bytes(
            _json_bytes({SAVE_SYNC_ASSOCIATION_CONFIG_KEY: {"localhack": LOCAL_ID}})
        )
        participant = SaveSyncAssociationReferenceParticipant(outside_config)
        preconditions = collect_store_preconditions(manager, hints, (participant,))
        plan = self._plan(preconditions)

        with self.assertRaises(CollectionPlanApplyError):
            apply_collection_change_plan(
                plan,
                manager,
                hints,
                reference_participants=(participant,),
            )

        self.assertTrue(root.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
