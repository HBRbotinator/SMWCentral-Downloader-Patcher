"""Tests for validated Planner editing operations."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from planner_editor import PlannerEditor
from planner_store import PlannerStore


class PlannerEditorTest(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.planner_path = self.root / "planner_state.json"
        self.store = PlannerStore(self.planner_path)
        self.timestamps = iter(
            [
                "2026-07-29T20:00:00+02:00",
                "2026-07-30T20:00:00+02:00",
                "2026-07-31T20:00:00+02:00",
                "2026-08-01T20:00:00+02:00",
                "2026-08-02T20:00:00+02:00",
                "2026-08-03T20:00:00+02:00",
            ]
        )
        self.editor = PlannerEditor(self.store, lambda: next(self.timestamps))

    def tearDown(self):
        self._temporary_directory.cleanup()

    def test_first_edit_records_planned_time_without_saving(self):
        custom_list = self.store.create_list("Stream games", list_id="stream")

        entry = self.editor.update_entry(
            "101",
            planning_horizon="Soon",
            list_ids=[custom_list["id"]],
        )

        self.assertEqual(entry["lifecycle_status"], "Planned")
        self.assertEqual(entry["planning_horizon"], "Soon")
        self.assertEqual(entry["list_ids"], ["stream"])
        self.assertEqual(entry["planned_at"], "2026-07-29T20:00:00+02:00")
        self.assertFalse(self.planner_path.exists())
        self.assertTrue(self.store.unsaved_changes)

    def test_lifecycle_timestamps_are_added_once_and_history_is_preserved(self):
        playing = self.editor.update_entry("101", lifecycle_status="Playing")
        self.assertEqual(
            playing["planned_at"],
            "2026-07-29T20:00:00+02:00",
        )
        self.assertEqual(
            playing["started_at"],
            "2026-07-29T20:00:00+02:00",
        )
        self.assertEqual(
            playing["last_played_at"],
            "2026-07-29T20:00:00+02:00",
        )

        beaten = self.editor.update_entry("101", lifecycle_status="Beaten")
        self.assertEqual(
            beaten["started_at"],
            "2026-07-29T20:00:00+02:00",
        )
        self.assertEqual(
            beaten["beaten_at"],
            "2026-07-30T20:00:00+02:00",
        )
        self.assertEqual(
            beaten["last_played_at"],
            "2026-07-30T20:00:00+02:00",
        )

        completed = self.editor.update_entry(
            "101",
            lifecycle_status="Completed",
        )
        self.assertEqual(
            completed["beaten_at"],
            "2026-07-30T20:00:00+02:00",
        )
        self.assertEqual(
            completed["completed_at"],
            "2026-07-31T20:00:00+02:00",
        )

        replaying = self.editor.update_entry("101", lifecycle_status="Playing")
        self.assertEqual(
            replaying["completed_at"],
            "2026-07-31T20:00:00+02:00",
        )
        self.assertEqual(
            replaying["last_played_at"],
            "2026-08-01T20:00:00+02:00",
        )

    def test_bulk_edit_rolls_back_all_entries_when_one_update_fails(self):
        original_state = copy.deepcopy(self.store.state)
        original_unsaved = self.store.unsaved_changes
        original_update = self.store.update_entry

        def failing_update(hack_id, **changes):
            if str(hack_id) == "202":
                raise RuntimeError("simulated second-entry failure")
            return original_update(hack_id, **changes)

        with patch.object(self.store, "update_entry", side_effect=failing_update):
            with self.assertRaisesRegex(RuntimeError, "second-entry"):
                self.editor.update_entries(
                    ["101", "202"],
                    planning_horizon="Soon",
                )

        self.assertEqual(self.store.state, original_state)
        self.assertEqual(self.store.unsaved_changes, original_unsaved)
        self.assertEqual(self.store.get_entries(), {})

    def test_next_entries_can_be_reordered_explicitly(self):
        self.editor.update_entries(
            ["101", "202", "303"],
            planning_horizon="Next",
        )
        self.assertEqual(self.store.get_next_queue(), ["101", "202", "303"])

        queue = self.editor.move_next("303", 1)

        self.assertEqual(queue, ["303", "101", "202"])
        with self.assertRaisesRegex(ValueError, "between 1 and 3"):
            self.editor.move_next("101", 4)
        self.editor.update_entry("202", planning_horizon="Soon")
        with self.assertRaisesRegex(ValueError, "not in the Next queue"):
            self.editor.move_next("202", 1)

    def test_removing_explicit_state_keeps_the_collection_out_of_scope(self):
        self.editor.update_entry("101", lifecycle_status="Paused")

        self.assertTrue(self.editor.remove_entry("101"))
        self.assertFalse(self.store.has_entry("101"))
        self.assertFalse(self.editor.remove_entry("101"))

    def test_save_is_explicit(self):
        self.editor.update_entry("101", planning_horizon="Soon")

        self.assertFalse(self.planner_path.exists())
        self.assertTrue(self.editor.save())
        self.assertTrue(self.planner_path.exists())
        self.assertFalse(self.store.unsaved_changes)


if __name__ == "__main__":
    unittest.main(verbosity=2)
