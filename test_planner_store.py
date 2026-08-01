"""Tests for the Planner persistence foundation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from planner_store import (
    LIFECYCLE_STATUSES,
    PLANNING_HORIZONS,
    PlannerStore,
)


class PlannerStoreTest(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.planner_path = self.root / "planner_state.json"
        self.collection_path = self.root / "processed.json"

    def tearDown(self):
        self._temporary_directory.cleanup()

    def test_missing_store_loads_defaults_without_creating_a_file(self):
        store = PlannerStore(self.planner_path)

        self.assertFalse(self.planner_path.exists())
        self.assertEqual(store.get_entries(), {})
        self.assertEqual(store.get_lists(), [])
        self.assertEqual(store.get_next_queue(), [])
        self.assertEqual(
            store.get_entry("101")["lifecycle_status"],
            "Planned",
        )
        self.assertEqual(
            store.get_entry("101")["planning_horizon"],
            "Someday",
        )
        self.assertFalse(store.unsaved_changes)

    def test_opening_existing_store_does_not_rewrite_it(self):
        original = {
            "schema_version": 1,
            "entries": {
                "101": {
                    "lifecycle_status": "Playing",
                    "future_entry_field": {"keep": True},
                }
            },
            "lists": [],
            "next_queue": [],
            "future_root_field": [1, 2, 3],
        }
        original_bytes = (
            json.dumps(original, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        self.planner_path.write_bytes(original_bytes)

        store = PlannerStore(self.planner_path)

        self.assertEqual(self.planner_path.read_bytes(), original_bytes)
        self.assertEqual(
            store.get_entry("101")["lifecycle_status"],
            "Playing",
        )
        self.assertEqual(
            store.get_entry("101")["planning_horizon"],
            "Someday",
        )
        self.assertFalse(store.unsaved_changes)

    def test_entries_validate_status_horizon_and_next_queue(self):
        store = PlannerStore(self.planner_path)

        first = store.update_entry(
            "101",
            lifecycle_status="Playing",
            planning_horizon="Next",
            started_at="2026-07-29",
        )
        store.update_entry("202", planning_horizon="Next")

        self.assertEqual(first["lifecycle_status"], "Playing")
        self.assertEqual(first["planning_horizon"], "Next")
        self.assertEqual(store.get_next_queue(), ["101", "202"])
        self.assertEqual(store.set_next_queue(["202"]), ["202", "101"])

        store.update_entry("202", planning_horizon="Soon")
        self.assertEqual(store.get_next_queue(), ["101"])

        with self.assertRaises(ValueError):
            store.update_entry("101", lifecycle_status="Up Next")
        with self.assertRaises(ValueError):
            store.update_entry("101", planning_horizon="High")
        with self.assertRaises(ValueError):
            store.set_next_queue(["202"])

        self.assertEqual(
            LIFECYCLE_STATUSES,
            (
                "Planned",
                "Playing",
                "Paused",
                "Beaten",
                "Completed",
                "Dropped",
                "Archived",
            ),
        )
        self.assertEqual(PLANNING_HORIZONS, ("Someday", "Soon", "Next"))

    def test_custom_lists_use_stable_ids_and_clean_memberships(self):
        store = PlannerStore(self.planner_path)
        stream = store.create_list("Stream games", list_id="stream")
        short = store.create_list("Short hacks", list_id="short")

        store.update_entry(
            "101",
            list_ids=[stream["id"], short["id"], stream["id"]],
        )
        self.assertEqual(
            store.get_entry("101")["list_ids"],
            ["stream", "short"],
        )

        renamed = store.rename_list("stream", "Stream candidates")
        self.assertEqual(renamed["id"], "stream")
        self.assertEqual(renamed["name"], "Stream candidates")

        with self.assertRaises(ValueError):
            store.create_list("stream CANDIDATES")
        with self.assertRaises(ValueError):
            store.update_entry("101", list_ids=["missing"])

        self.assertTrue(store.delete_list("short"))
        self.assertEqual(store.get_entry("101")["list_ids"], ["stream"])
        self.assertFalse(store.delete_list("short"))

    def test_save_is_separate_atomic_and_preserves_unknown_fields(self):
        collection_bytes = b'{"101":{"title":"Core collection"}}\n'
        self.collection_path.write_bytes(collection_bytes)
        existing = {
            "schema_version": 1,
            "entries": {
                "101": {
                    "lifecycle_status": "Planned",
                    "future_entry_field": {"keep": True},
                }
            },
            "lists": [],
            "next_queue": [],
            "future_root_field": {"keep": True},
        }
        self.planner_path.write_text(
            json.dumps(existing, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        original_planner_bytes = self.planner_path.read_bytes()
        store = PlannerStore(self.planner_path)

        store.update_entry(
            "101",
            lifecycle_status="Paused",
            planning_horizon="Soon",
        )
        self.assertTrue(store.save())

        self.assertEqual(self.collection_path.read_bytes(), collection_bytes)
        saved = json.loads(self.planner_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["entries"]["101"]["lifecycle_status"], "Paused")
        self.assertEqual(
            saved["entries"]["101"]["future_entry_field"],
            {"keep": True},
        )
        self.assertEqual(saved["future_root_field"], {"keep": True})
        self.assertEqual(
            self.planner_path.with_suffix(".json.backup").read_bytes(),
            original_planner_bytes,
        )
        self.assertFalse((self.root / ".planner_state.json.tmp").exists())
        self.assertFalse(store.unsaved_changes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
