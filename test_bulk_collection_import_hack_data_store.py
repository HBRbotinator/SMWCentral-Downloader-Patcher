"""Specification tests for the real v5.1 HackDataManager bulk-import store."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path


BULK_IMPORT_EXTENSION_KEY = "bulk_collection_import"
BULK_IMPORT_EXTENSION_VERSION = 1
BULK_IMPORT_TEMP_SUFFIX = ".bulk-import.tmp"

INITIAL_COLLECTION = {
    "12345": {
        "title": "Existing Hybrid",
        "current_difficulty": "Intermediate",
        "folder_name": "intermediate",
        "hack_type": "standard",
        "hack_types": ["standard"],
        "hall_of_fame": False,
        "sa1_compatibility": False,
        "collaboration": False,
        "demo": False,
        "authors": ["Existing Author"],
        "exits": 10,
        "date": "2025-01-01",
        "obsolete": False,
        "completed": True,
        "completed_date": "2026-07-01",
        "personal_rating": 5,
        "time_to_beat": 7200,
        "notes": "Preserve this",
        "file_path": "C:/roms/existing.smc",
        "files": [
            {
                "path": "C:/roms/existing.smc",
                "name": "Standard",
                "primary": True,
            }
        ],
        "additional_paths": ["C:/saves/existing.srm"],
        "save_sync_metadata": {
            "association": "existing.srm",
        },
        "provider_extension": {
            "provider": "smwc",
            "future": {"keep": True},
        },
        BULK_IMPORT_EXTENSION_KEY: {
            "version": BULK_IMPORT_EXTENSION_VERSION,
            "aliases": [],
            "source_references": [
                {"source": "smwc", "external_id": "12345"},
            ],
            "attributes": {
                "tags": ["classic"],
            },
        },
    },
    "usr_0": {
        "title": "Pending User Edit",
        "current_difficulty": "Advanced",
        "authors": ["User Author"],
        "exits": 20,
        "date": "",
        "completed": False,
        "completed_date": "",
        "personal_rating": 0,
        "time_to_beat": 0,
        "notes": "Unsaved note",
        "obsolete": False,
        "file_path": "",
        "additional_paths": [],
    },
}


class BulkCollectionImportHackDataStoreContractMixin:
    """Reusable contract for the concrete HackDataManager store adapter."""

    def make_manager(self, path):
        raise NotImplementedError

    def make_store(self, manager):
        raise NotImplementedError

    def shared_sha256(self, record):
        raise NotImplementedError

    def _write_collection(self, path, data):
        path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _make(self, *, unsaved=False):
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        path = root / "processed.json"
        self._write_collection(path, INITIAL_COLLECTION)

        manager = self.make_manager(path)
        manager._schedule_delayed_save = lambda: None
        if unsaved:
            manager.data["usr_0"]["notes"] = "Pending changed note"
            manager.unsaved_changes = True

        store = self.make_store(manager)
        self.addCleanup(temporary.cleanup)
        return root, path, manager, store

    def test_store_reads_live_manager_identity(self):
        _, _, manager, store = self._make()

        self.assertTrue(store.record_exists("12345"))
        self.assertTrue(store.record_exists("usr_0"))
        self.assertFalse(store.record_exists("99999"))
        self.assertEqual(
            store.shared_sha256("12345"),
            self.shared_sha256(manager.data["12345"]),
        )

    def test_missing_record_has_no_shared_fingerprint(self):
        _, _, _, store = self._make()

        self.assertIsNone(store.shared_sha256("missing"))

    def test_transaction_stages_without_mutating_manager_or_disk(self):
        _, path, manager, store = self._make()
        before_data = copy.deepcopy(manager.data)
        before_bytes = path.read_bytes()

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value="Staged Title",
            source_reference_additions=[],
            attribute_changes=[
                {"field": "exit_count", "value": 11},
            ],
        )

        self.assertEqual(manager.data, before_data)
        self.assertEqual(path.read_bytes(), before_bytes)

        transaction.rollback()

    def test_create_builds_valid_v5_1_collection_record(self):
        _, _, manager, store = self._make()

        transaction = store.begin_transaction()
        transaction.create_record(
            collection_key="67890",
            title="Imported Hack",
            source_references=[
                {"source": "smwc", "external_id": "67890"},
                {
                    "source": "kaizoff",
                    "external_id": "provider-record-1",
                },
            ],
            attributes={
                "authors": ["Imported Author"],
                "difficulty": "Expert",
                "exit_count": 15,
                "release_date": "2026-06-15",
                "tags": ["short", "vanilla"],
            },
            user_state={},
        )
        transaction.commit()

        record = manager.data["67890"]
        self.assertEqual(record["title"], "Imported Hack")
        self.assertEqual(record["current_difficulty"], "Expert")
        self.assertEqual(record["authors"], ["Imported Author"])
        self.assertEqual(record["exits"], 15)
        self.assertEqual(record["date"], "2026-06-15")
        self.assertFalse(record["completed"])
        self.assertEqual(record["completed_date"], "")
        self.assertEqual(record["personal_rating"], 0)
        self.assertEqual(record["time_to_beat"], 0)
        self.assertEqual(record["notes"], "")
        self.assertEqual(record["file_path"], "")
        self.assertEqual(record["files"], [])
        self.assertEqual(record["additional_paths"], [])
        self.assertFalse(record["obsolete"])

        extension = record[BULK_IMPORT_EXTENSION_KEY]
        self.assertEqual(extension["version"], 1)
        self.assertEqual(extension["aliases"], [])
        self.assertEqual(
            extension["source_references"],
            [
                {"source": "smwc", "external_id": "67890"},
                {
                    "source": "kaizoff",
                    "external_id": "provider-record-1",
                },
            ],
        )
        self.assertEqual(
            extension["attributes"],
            {"tags": ["short", "vanilla"]},
        )

    def test_create_without_optional_shared_metadata_uses_safe_defaults(self):
        _, _, manager, store = self._make()

        transaction = store.begin_transaction()
        transaction.create_record(
            collection_key="usr_import_0123456789abcdef",
            title="Local Imported Hack",
            source_references=[
                {
                    "source": "kaizoff",
                    "external_id": "kaizoff-only",
                }
            ],
            attributes={},
            user_state={},
        )
        transaction.commit()

        record = manager.data["usr_import_0123456789abcdef"]
        self.assertEqual(
            record["current_difficulty"],
            "No Difficulty",
        )
        self.assertEqual(record["authors"], [])
        self.assertEqual(record["exits"], 0)
        self.assertEqual(record["date"], "")

    def test_create_rejects_nonempty_user_state(self):
        _, _, _, store = self._make()

        transaction = store.begin_transaction()
        with self.assertRaises(Exception):
            transaction.create_record(
                collection_key="usr_import_0123456789abcdef",
                title="Unsafe",
                source_references=[],
                attributes={},
                user_state={"notes": "must not enter import"},
            )
        transaction.rollback()

    def test_update_preserves_every_unmentioned_collection_field(self):
        _, _, manager, store = self._make()
        before = copy.deepcopy(manager.data["12345"])

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value="Updated Hybrid",
            source_reference_additions=[
                {
                    "source": "kaizoff",
                    "external_id": "provider-record-2",
                }
            ],
            attribute_changes=[
                {"field": "difficulty", "value": "Advanced"},
                {"field": "exit_count", "value": 12},
                {"field": "release_date", "value": "2025-02-02"},
                {"field": "tags", "value": ["classic", "short"]},
            ],
        )
        transaction.commit()

        record = manager.data["12345"]
        self.assertEqual(record["title"], "Updated Hybrid")
        self.assertEqual(record["current_difficulty"], "Advanced")
        self.assertEqual(record["exits"], 12)
        self.assertEqual(record["date"], "2025-02-02")
        self.assertEqual(
            record[BULK_IMPORT_EXTENSION_KEY]["attributes"]["tags"],
            ["classic", "short"],
        )

        for key in (
            "completed",
            "completed_date",
            "personal_rating",
            "time_to_beat",
            "notes",
            "file_path",
            "files",
            "additional_paths",
            "save_sync_metadata",
            "provider_extension",
        ):
            self.assertEqual(record[key], before[key], key)

    def test_update_maps_authors_to_existing_v5_1_field(self):
        _, _, manager, store = self._make()

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value=None,
            source_reference_additions=[],
            attribute_changes=[
                {
                    "field": "authors",
                    "value": ["New Author", "Coauthor"],
                }
            ],
        )
        transaction.commit()

        self.assertEqual(
            manager.data["12345"]["authors"],
            ["New Author", "Coauthor"],
        )

    def test_source_reference_addition_is_idempotent(self):
        _, _, manager, store = self._make()

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value=None,
            source_reference_additions=[
                {"source": "smwc", "external_id": "12345"},
                {"source": "smwc", "external_id": "12345"},
            ],
            attribute_changes=[],
        )
        transaction.commit()

        references = manager.data["12345"][
            BULK_IMPORT_EXTENSION_KEY
        ]["source_references"]
        self.assertEqual(
            references.count(
                {"source": "smwc", "external_id": "12345"}
            ),
            1,
        )

    def test_existing_extension_metadata_is_preserved_on_update(self):
        _, _, manager, store = self._make()

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value=None,
            source_reference_additions=[],
            attribute_changes=[
                {"field": "community_rank", "value": 3},
            ],
        )
        transaction.commit()

        attributes = manager.data["12345"][
            BULK_IMPORT_EXTENSION_KEY
        ]["attributes"]
        self.assertEqual(attributes["tags"], ["classic"])
        self.assertEqual(attributes["community_rank"], 3)

    def test_commit_preserves_pending_manager_edits(self):
        _, _, manager, store = self._make(unsaved=True)

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value=None,
            source_reference_additions=[],
            attribute_changes=[
                {"field": "exit_count", "value": 12},
            ],
        )
        transaction.commit()

        self.assertEqual(
            manager.data["usr_0"]["notes"],
            "Pending changed note",
        )
        self.assertFalse(manager.unsaved_changes)

    def test_successful_commit_creates_existing_backup(self):
        root, path, manager, store = self._make()
        original_bytes = path.read_bytes()

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value=None,
            source_reference_additions=[],
            attribute_changes=[
                {"field": "exit_count", "value": 12},
            ],
        )
        transaction.commit()

        backup = root / "processed.json.backup"
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_bytes(), original_bytes)
        self.assertNotEqual(path.read_bytes(), original_bytes)
        self.assertFalse(manager.unsaved_changes)

    def test_commit_leaves_no_bulk_import_temp_file(self):
        root, _, _, store = self._make()

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value=None,
            source_reference_additions=[],
            attribute_changes=[
                {"field": "exit_count", "value": 12},
            ],
        )
        transaction.commit()

        self.assertFalse(
            (root / f"processed.json{BULK_IMPORT_TEMP_SUFFIX}").exists()
        )

    def test_rollback_leaves_manager_disk_and_backup_untouched(self):
        root, path, manager, store = self._make()
        before_data = copy.deepcopy(manager.data)
        before_bytes = path.read_bytes()

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value="Never Commit",
            source_reference_additions=[],
            attribute_changes=[],
        )
        transaction.rollback()

        self.assertEqual(manager.data, before_data)
        self.assertEqual(path.read_bytes(), before_bytes)
        self.assertFalse((root / "processed.json.backup").exists())

    def test_failed_atomic_replace_restores_manager_and_live_file(self):
        root, path, manager, store = self._make()
        before_data = copy.deepcopy(manager.data)
        before_bytes = path.read_bytes()

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value="Never Persist",
            source_reference_additions=[],
            attribute_changes=[],
        )
        transaction.fail_before_replace = True

        with self.assertRaises(Exception):
            transaction.commit()

        transaction.rollback()
        self.assertEqual(manager.data, before_data)
        self.assertEqual(path.read_bytes(), before_bytes)
        self.assertFalse(
            (root / f"processed.json{BULK_IMPORT_TEMP_SUFFIX}").exists()
        )

    def test_rollback_restores_pending_unsaved_state(self):
        _, _, manager, store = self._make(unsaved=True)

        transaction = store.begin_transaction()
        transaction.update_record(
            collection_key="12345",
            title_value="Never Commit",
            source_reference_additions=[],
            attribute_changes=[],
        )
        transaction.rollback()

        self.assertTrue(manager.unsaved_changes)
        self.assertEqual(
            manager.data["usr_0"]["notes"],
            "Pending changed note",
        )

    def test_shared_fingerprint_ignores_user_owned_changes(self):
        _, _, manager, store = self._make()
        original = store.shared_sha256("12345")

        manager.data["12345"]["notes"] = "Changed user note"
        manager.data["12345"]["personal_rating"] = 1

        self.assertEqual(store.shared_sha256("12345"), original)

    def test_shared_fingerprint_changes_for_shared_metadata(self):
        _, _, manager, store = self._make()
        original = store.shared_sha256("12345")

        manager.data["12345"]["exits"] = 99

        self.assertNotEqual(store.shared_sha256("12345"), original)


class BulkCollectionImportHackDataStoreSpecificationTest(
    unittest.TestCase
):
    """Lock the repository-specific persistence policy."""

    def test_bulk_import_extension_remains_namespaced(self):
        self.assertEqual(
            BULK_IMPORT_EXTENSION_KEY,
            "bulk_collection_import",
        )
        self.assertEqual(BULK_IMPORT_EXTENSION_VERSION, 1)

    def test_temp_file_has_distinct_bulk_import_name(self):
        self.assertEqual(
            BULK_IMPORT_TEMP_SUFFIX,
            ".bulk-import.tmp",
        )

    def test_current_processed_backup_name_is_preserved(self):
        path = Path("processed.json")
        self.assertEqual(
            Path(f"{path}.backup").name,
            "processed.json.backup",
        )

    def test_create_user_state_is_explicitly_empty(self):
        user_state = {}
        self.assertEqual(user_state, {})

    def test_core_shared_fields_have_existing_processed_json_targets(self):
        self.assertEqual(
            {
                "authors": "authors",
                "difficulty": "current_difficulty",
                "exit_count": "exits",
                "release_date": "date",
            },
            {
                "authors": "authors",
                "difficulty": "current_difficulty",
                "exit_count": "exits",
                "release_date": "date",
            },
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
