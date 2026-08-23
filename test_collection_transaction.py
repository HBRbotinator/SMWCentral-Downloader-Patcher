"""Tests for source-neutral atomic Collection transactions."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collection_transaction import (
    COLLECTION_TRANSACTION_TEMP_MARKER,
    CollectionStaleStateError,
    CollectionTransactionError,
    HackDataManagerCollectionStore,
)
from hack_data_manager import HackDataManager


INITIAL_COLLECTION = {
    "100": {
        "title": "Existing Hack",
        "authors": ["Existing Author"],
        "current_difficulty": "Intermediate",
        "exits": 10,
        "completed": True,
        "completed_date": "2026-01-10",
        "personal_rating": 4,
        "notes": "keep me",
        "file_path": "C:/ROMs/existing.sfc",
        "files": [
            {
                "path": "C:/ROMs/existing.sfc",
                "label": "Default",
            }
        ],
        "save_sync_metadata": {
            "last_seen": "2026-08-20",
        },
    },
    "usr_local": {
        "title": "Local Hack",
        "authors": [],
        "current_difficulty": "Unknown",
        "exits": 0,
        "completed": False,
        "completed_date": "",
        "personal_rating": 0,
        "notes": "pending local note",
        "file_path": "D:/ROMs/local.sfc",
        "files": [],
    },
}


class CollectionTransactionTest(unittest.TestCase):
    """Lock source-neutral local Collection persistence behavior."""

    def _fixture(self, *, unsaved=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        path = root / "processed.json"
        path.write_text(
            json.dumps(
                INITIAL_COLLECTION,
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        manager = HackDataManager(str(path))
        manager.unsaved_changes = unsaved
        if unsaved:
            manager.data["usr_local"]["notes"] = (
                "unsaved manager edit"
            )
        manager._schedule_delayed_save = lambda: None

        store = HackDataManagerCollectionStore(manager)
        return root, path, manager, store

    @staticmethod
    def _temp_files(root):
        return tuple(
            path
            for path in root.iterdir()
            if COLLECTION_TRANSACTION_TEMP_MARKER in path.name
        )

    def test_store_returns_detached_record_snapshots(self):
        _, _, manager, store = self._fixture()

        snapshot = store.record_snapshot("100")
        snapshot["notes"] = "mutated snapshot"

        self.assertEqual(
            manager.data["100"]["notes"],
            "keep me",
        )
        self.assertTrue(store.record_exists("100"))
        self.assertFalse(store.record_exists("missing"))
        self.assertIsNone(store.record_snapshot("missing"))

    def test_create_accepts_local_asset_and_user_metadata(self):
        _, path, manager, store = self._fixture()
        transaction = store.begin_transaction()

        transaction.create_record(
            "usr_scanned",
            {
                "title": "Scanned ROM",
                "authors": [],
                "current_difficulty": "Unknown",
                "exits": 0,
                "completed": False,
                "completed_date": "",
                "personal_rating": 0,
                "notes": "",
                "file_path": "E:/ROM Library/Scanned ROM.sfc",
                "files": [
                    {
                        "path": "E:/ROM Library/Scanned ROM.sfc",
                        "sha256": "a" * 64,
                    }
                ],
                "save_sync_metadata": {
                    "save_path": "E:/Saves/Scanned ROM.srm",
                },
            },
        )
        transaction.commit()

        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(persisted, manager.data)
        self.assertEqual(
            persisted["usr_scanned"]["file_path"],
            "E:/ROM Library/Scanned ROM.sfc",
        )
        self.assertEqual(
            persisted["usr_scanned"]["save_sync_metadata"][
                "save_path"
            ],
            "E:/Saves/Scanned ROM.srm",
        )

    def test_update_changes_only_explicit_top_level_fields(self):
        _, path, manager, store = self._fixture()
        original = copy.deepcopy(manager.data["100"])
        transaction = store.begin_transaction()

        transaction.update_record(
            "100",
            {
                "file_path": "D:/Moved/existing.sfc",
                "notes": "updated by trusted local workflow",
                "personal_rating": 5,
            },
        )
        transaction.commit()

        record = manager.data["100"]
        self.assertEqual(
            record["file_path"],
            "D:/Moved/existing.sfc",
        )
        self.assertEqual(
            record["notes"],
            "updated by trusted local workflow",
        )
        self.assertEqual(record["personal_rating"], 5)
        self.assertEqual(record["authors"], original["authors"])
        self.assertEqual(record["exits"], original["exits"])
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8")),
            manager.data,
        )

    def test_transaction_preserves_pending_unsaved_manager_edits(self):
        root, path, manager, store = self._fixture(unsaved=True)
        disk_before = path.read_bytes()
        transaction = store.begin_transaction()

        transaction.update_record(
            "100",
            {
                "file_path": "D:/ROMs/new-location.sfc",
            },
        )
        transaction.commit()

        self.assertEqual(
            manager.data["usr_local"]["notes"],
            "unsaved manager edit",
        )
        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["usr_local"]["notes"],
            "unsaved manager edit",
        )
        self.assertFalse(manager.unsaved_changes)
        self.assertEqual(
            (root / "processed.json.backup").read_bytes(),
            disk_before,
        )

    def test_success_is_atomic_and_leaves_no_temp_file(self):
        root, path, manager, store = self._fixture()
        original_bytes = path.read_bytes()
        transaction = store.begin_transaction()

        transaction.update_record(
            "100",
            {"exits": 11},
        )
        transaction.commit()

        self.assertEqual(manager.data["100"]["exits"], 11)
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["100"][
                "exits"
            ],
            11,
        )
        self.assertEqual(
            (root / "processed.json.backup").read_bytes(),
            original_bytes,
        )
        self.assertEqual(self._temp_files(root), ())

    def test_rollback_discards_staged_changes(self):
        _, path, manager, store = self._fixture()
        original_data = copy.deepcopy(manager.data)
        original_bytes = path.read_bytes()
        transaction = store.begin_transaction()

        transaction.update_record(
            "100",
            {"file_path": "D:/Never/Committed.sfc"},
        )
        transaction.rollback()

        self.assertEqual(manager.data, original_data)
        self.assertEqual(path.read_bytes(), original_bytes)
        with self.assertRaises(CollectionTransactionError):
            transaction.update_record("100", {"notes": "too late"})

    def test_failure_before_replace_restores_manager_and_backup(self):
        root, path, manager, store = self._fixture()
        original_data = copy.deepcopy(manager.data)
        original_bytes = path.read_bytes()
        backup = root / "processed.json.backup"
        backup.write_text("previous-backup", encoding="utf-8")

        transaction = store.begin_transaction()
        transaction.update_record(
            "100",
            {"notes": "Never Persist"},
        )
        transaction.fail_before_replace = True

        with self.assertRaises(CollectionTransactionError):
            transaction.commit()

        self.assertEqual(manager.data, original_data)
        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual(
            backup.read_text(encoding="utf-8"),
            "previous-backup",
        )
        self.assertEqual(self._temp_files(root), ())

    def test_success_logger_failure_cannot_reverse_committed_write(self):
        root, path, manager, store = self._fixture()
        original_bytes = path.read_bytes()

        class FailingLogger:
            def log(self, _message, _level):
                raise RuntimeError("logger unavailable")

        manager.logger = FailingLogger()
        transaction = store.begin_transaction()
        transaction.update_record("100", {"exits": 77})

        transaction.commit()

        self.assertEqual(manager.data["100"]["exits"], 77)
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))["100"][
                "exits"
            ],
            77,
        )
        self.assertEqual(
            (root / "processed.json.backup").read_bytes(),
            original_bytes,
        )

        transaction.rollback()
        self.assertEqual(manager.data["100"]["exits"], 77)

    def test_partial_backup_copy_failure_restores_previous_backup(self):
        root, path, manager, store = self._fixture()
        original_bytes = path.read_bytes()
        original_data = copy.deepcopy(manager.data)
        backup = root / "processed.json.backup"
        backup.write_text("previous-backup", encoding="utf-8")

        transaction = store.begin_transaction()
        transaction.update_record(
            "100",
            {"notes": "Never Persist"},
        )

        def partial_copy_then_fail(_source, destination):
            Path(destination).write_text(
                "partial-new-backup",
                encoding="utf-8",
            )
            raise OSError("copy failed after destination changed")

        with patch(
            "collection_transaction.shutil.copy2",
            side_effect=partial_copy_then_fail,
        ):
            with self.assertRaises(OSError):
                transaction.commit()

        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual(manager.data, original_data)
        self.assertEqual(
            backup.read_text(encoding="utf-8"),
            "previous-backup",
        )
        self.assertEqual(self._temp_files(root), ())

    def test_manager_change_during_staging_is_preserved(self):
        _, path, manager, store = self._fixture()
        original_disk = path.read_bytes()
        transaction = store.begin_transaction()
        transaction.update_record(
            "100",
            {"file_path": "D:/Import/Update.sfc"},
        )

        original_write = transaction._write_staged_temp

        def write_then_edit_manager():
            original_write()
            manager.data["usr_local"]["notes"] = (
                "Concurrent UI edit"
            )
            manager.unsaved_changes = True

        transaction._write_staged_temp = write_then_edit_manager

        with self.assertRaises(CollectionStaleStateError):
            transaction.commit()

        self.assertEqual(path.read_bytes(), original_disk)
        self.assertEqual(
            manager.data["usr_local"]["notes"],
            "Concurrent UI edit",
        )
        self.assertTrue(manager.unsaved_changes)

        transaction.rollback()
        self.assertEqual(
            manager.data["usr_local"]["notes"],
            "Concurrent UI edit",
        )

    def test_disk_change_during_staging_is_preserved(self):
        root, path, manager, store = self._fixture()
        original_manager = copy.deepcopy(manager.data)
        transaction = store.begin_transaction()
        transaction.update_record(
            "100",
            {"file_path": "D:/Import/Update.sfc"},
        )

        external = copy.deepcopy(INITIAL_COLLECTION)
        external["usr_local"]["notes"] = "Concurrent disk edit"
        original_write = transaction._write_staged_temp

        def write_then_edit_disk():
            original_write()
            path.write_text(
                json.dumps(external, indent=2) + "\n",
                encoding="utf-8",
            )

        transaction._write_staged_temp = write_then_edit_disk

        with self.assertRaises(CollectionStaleStateError):
            transaction.commit()

        persisted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(
            persisted["usr_local"]["notes"],
            "Concurrent disk edit",
        )
        self.assertEqual(manager.data, original_manager)
        self.assertFalse(
            (root / "processed.json.backup").exists()
        )
        self.assertEqual(self._temp_files(root), ())

        transaction.rollback()
        self.assertEqual(
            json.loads(path.read_text(encoding="utf-8"))[
                "usr_local"
            ]["notes"],
            "Concurrent disk edit",
        )

    def test_stale_before_commit_never_opens_write_path(self):
        root, path, manager, store = self._fixture()
        original_bytes = path.read_bytes()
        transaction = store.begin_transaction()
        transaction.update_record(
            "100",
            {"file_path": "D:/Import/Update.sfc"},
        )

        manager.data["usr_local"]["notes"] = "newer UI state"

        with self.assertRaises(CollectionStaleStateError):
            transaction.commit()

        self.assertEqual(path.read_bytes(), original_bytes)
        self.assertEqual(
            manager.data["usr_local"]["notes"],
            "newer UI state",
        )
        self.assertFalse(
            (root / "processed.json.backup").exists()
        )
        self.assertEqual(self._temp_files(root), ())

    def test_replace_record_requires_existing_key(self):
        _, _, manager, store = self._fixture()
        transaction = store.begin_transaction()

        replacement = copy.deepcopy(manager.data["100"])
        replacement["title"] = "Replacement"
        transaction.replace_record("100", replacement)

        self.assertEqual(
            transaction.staged_record("100")["title"],
            "Replacement",
        )
        with self.assertRaises(CollectionTransactionError):
            transaction.replace_record(
                "missing",
                {"title": "No record"},
            )

    def test_invalid_or_nonfinite_data_fails_before_commit(self):
        _, _, _, store = self._fixture()
        transaction = store.begin_transaction()

        with self.assertRaises(CollectionTransactionError):
            transaction.create_record(
                "usr_bad",
                {
                    "title": "Bad",
                    "value": math.nan,
                },
            )
        with self.assertRaises(CollectionTransactionError):
            transaction.update_record(
                "100",
                {"value": object()},
            )

    def test_duplicate_create_and_missing_update_fail_closed(self):
        _, _, _, store = self._fixture()
        transaction = store.begin_transaction()

        with self.assertRaises(CollectionTransactionError):
            transaction.create_record(
                "100",
                {"title": "Duplicate"},
            )
        with self.assertRaises(CollectionTransactionError):
            transaction.update_record(
                "missing",
                {"notes": "No target"},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
