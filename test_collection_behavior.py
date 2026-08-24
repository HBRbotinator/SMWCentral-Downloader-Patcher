"""Regression coverage for the pre-Planner collection contract.

These tests intentionally exercise the existing ``HackDataManager`` surface
before Planner persistence is introduced. They protect compatibility with
current downloaded records, completion metadata, and local save-backed entries.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from hack_data_manager import HackDataManager


class CollectionBehaviorTest(unittest.TestCase):
    """Lock collection behavior that Planner work must continue to support."""

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.collection_path = self.root / "processed.json"

    def tearDown(self):
        self._temporary_directory.cleanup()

    def _write_collection(self, data, *, indent=2):
        payload = (
            json.dumps(data, indent=indent, ensure_ascii=False) + "\n"
        ).encode("utf-8")
        self.collection_path.write_bytes(payload)
        return payload

    def _manager_without_delayed_save(self):
        manager = HackDataManager(str(self.collection_path))
        manager._schedule_delayed_save = lambda: None
        return manager

    def test_opening_existing_collection_does_not_rewrite_source(self):
        original = {
            "101": {
                "title": "Existing Hack",
                "current_difficulty": "Intermediate",
                "file_path": "roms/Existing Hack.smc",
                "provider_extension": {"source": "smwc", "revision": 4},
            }
        }
        original_bytes = self._write_collection(original, indent=None)

        manager = HackDataManager(str(self.collection_path))

        self.assertEqual(self.collection_path.read_bytes(), original_bytes)
        self.assertFalse((self.root / "processed.json.backup").exists())
        self.assertEqual(manager.data["101"]["title"], "Existing Hack")
        self.assertFalse(manager.data["101"]["completed"])
        self.assertEqual(manager.get_all_hacks()[0]["id"], "101")

    def test_completion_updates_fill_only_missing_completion_dates(self):
        self._write_collection(
            {
                "done": {
                    "title": "Already Done",
                    "completed": True,
                    "completed_date": "2024-03-02",
                },
                "new": {
                    "title": "New Completion",
                    "completed": False,
                    "completed_date": "",
                },
            }
        )
        manager = self._manager_without_delayed_save()

        with patch("hack_data_manager.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = datetime(2026, 7, 29)
            self.assertTrue(manager.update_hack("done", "completed", True))
            self.assertTrue(manager.update_hack("new", "completed", True))

        self.assertEqual(manager.data["done"]["completed_date"], "2024-03-02")
        self.assertEqual(manager.data["new"]["completed_date"], "2026-07-29")

        visible = {hack["id"]: hack for hack in manager.get_all_hacks()}
        self.assertTrue(visible["done"]["completed"])
        self.assertEqual(visible["done"]["completed_date"], "2024-03-02")
        self.assertTrue(visible["new"]["completed"])
        self.assertEqual(visible["new"]["completed_date"], "2026-07-29")

    def test_collection_update_preserves_download_and_extension_data(self):
        record = {
            "title": "Multi Patch Hack",
            "current_difficulty": "Advanced",
            "completed": False,
            "completed_date": "",
            "personal_rating": 0,
            "notes": "Before",
            "file_path": "roms/Multi Patch Hack.smc",
            "files": [
                {
                    "path": "roms/Multi Patch Hack.smc",
                    "name": "Standard",
                    "primary": True,
                },
                {
                    "path": "roms/Multi Patch Hack - Special.smc",
                    "name": "Special",
                    "primary": False,
                },
            ],
            "additional_paths": ["saves/Multi Patch Hack.srm"],
            "save_sync_metadata": {
                "association": "multi patch hack.srm",
                "slot": "C",
            },
            "provider_extension": {
                "catalogue": "smwc",
                "raw": {"future": [1, 2, 3]},
            },
        }
        self._write_collection({"202": record})
        preserved = copy.deepcopy(record)
        manager = self._manager_without_delayed_save()

        self.assertTrue(manager.update_hack("202", "notes", "After"))
        self.assertTrue(manager.force_save())

        saved = json.loads(self.collection_path.read_text(encoding="utf-8"))["202"]
        self.assertEqual(saved["notes"], "After")
        for key in (
            "file_path",
            "files",
            "additional_paths",
            "save_sync_metadata",
            "provider_extension",
        ):
            self.assertEqual(saved[key], preserved[key], key)

        backup = json.loads(
            (self.root / "processed.json.backup").read_text(encoding="utf-8")
        )
        self.assertEqual(backup["202"], record)

    def test_local_save_backed_entry_remains_a_valid_collection_record(self):
        local_id = "usr_0123456789abcdef"
        local_record = {
            "title": "Local Challenge",
            "current_difficulty": "No Difficulty",
            "hack_type": "standard",
            "hack_types": ["standard"],
            "authors": [],
            "exits": 14,
            "completed": True,
            "completed_date": "2026-07-27",
            "personal_rating": 0,
            "notes": "",
            "time_to_beat": 0,
            "obsolete": False,
            "file_path": "",
            "files": [],
            "additional_paths": [],
            "local_save_entry": True,
        }
        self._write_collection({local_id: local_record})
        manager = self._manager_without_delayed_save()

        visible = manager.get_all_hacks()
        self.assertEqual(len(visible), 1)
        self.assertEqual(visible[0]["id"], local_id)
        self.assertEqual(visible[0]["title"], "Local Challenge")
        self.assertEqual(visible[0]["exits"], 14)
        self.assertTrue(visible[0]["completed"])
        self.assertTrue(manager.data[local_id]["local_save_entry"])

        self.assertTrue(manager.update_hack(local_id, "notes", "Keep this"))
        self.assertTrue(manager.force_save())
        saved = json.loads(self.collection_path.read_text(encoding="utf-8"))
        self.assertTrue(saved[local_id]["local_save_entry"])
        self.assertEqual(saved[local_id]["notes"], "Keep this")


if __name__ == "__main__":
    unittest.main(verbosity=2)
