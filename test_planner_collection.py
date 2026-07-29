"""Tests for projecting Planner state onto collection records."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from planner_collection import PlannerCollectionProjection
from planner_store import PlannerStore


class PlannerCollectionProjectionTest(unittest.TestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.store = PlannerStore(self.root / "planner_state.json")
        self.projection = PlannerCollectionProjection(self.store)

    def tearDown(self):
        self._temporary_directory.cleanup()

    def test_legacy_completion_is_inferred_without_creating_planner_state(self):
        records = [
            {"id": "101", "title": "Done", "completed": True},
            {"id": "202", "title": "Backlog", "completed": False},
        ]

        projected = self.projection.project_collection(records)

        self.assertEqual(projected[0]["planner_lifecycle_status"], "Completed")
        self.assertEqual(projected[1]["planner_lifecycle_status"], "Planned")
        self.assertEqual(projected[0]["planner_horizon"], "Someday")
        self.assertFalse(projected[0]["planner_explicit"])
        self.assertFalse(projected[1]["planner_explicit"])
        self.assertEqual(self.store.get_entries(), {})
        self.assertFalse(self.store.path.exists())
        self.assertFalse(self.store.unsaved_changes)

    def test_explicit_planner_state_overrides_legacy_completion_inference(self):
        self.store.update_entry(
            "101",
            lifecycle_status="Playing",
            planning_horizon="Soon",
            started_at="2026-07-29",
        )

        projected = self.projection.project_hack(
            {"id": 101, "title": "Replay", "completed": True}
        )

        self.assertTrue(projected["planner_explicit"])
        self.assertEqual(projected["planner_lifecycle_status"], "Playing")
        self.assertEqual(projected["planner_horizon"], "Soon")
        self.assertEqual(
            projected["planner_timestamps"]["started_at"],
            "2026-07-29",
        )

    def test_custom_list_names_and_next_positions_are_resolved(self):
        self.store.create_list("Stream games", list_id="stream")
        self.store.create_list("Short hacks", list_id="short")
        self.store.update_entry(
            "101",
            planning_horizon="Next",
            list_ids=["stream", "short"],
        )
        self.store.update_entry("202", planning_horizon="Next")
        self.store.set_next_queue(["202", "101"])

        projected = self.projection.project_collection(
            [
                {"id": "101", "title": "First"},
                {"id": "202", "title": "Second"},
            ]
        )

        self.assertEqual(
            projected[0]["planner_list_names"],
            ["Stream games", "Short hacks"],
        )
        self.assertEqual(projected[0]["planner_next_position"], 2)
        self.assertEqual(projected[1]["planner_next_position"], 1)

    def test_projection_does_not_mutate_collection_or_planner_state(self):
        self.store.create_list("Stream games", list_id="stream")
        self.store.update_entry("101", list_ids=["stream"])
        collection = [
            {
                "id": "101",
                "title": "Original",
                "nested_extension": {"keep": [1, 2, 3]},
            }
        ]
        original_collection = copy.deepcopy(collection)
        original_state = copy.deepcopy(self.store.state)
        original_unsaved = self.store.unsaved_changes

        projected = self.projection.project_collection(collection)
        projected[0]["nested_extension"]["keep"].append(4)
        projected[0]["planner_list_ids"].append("other")

        self.assertEqual(collection, original_collection)
        self.assertEqual(self.store.state, original_state)
        self.assertEqual(self.store.unsaved_changes, original_unsaved)

    def test_invalid_collection_records_fail_clearly(self):
        with self.assertRaisesRegex(ValueError, "dictionaries"):
            self.projection.project_hack("not a record")
        with self.assertRaisesRegex(ValueError, "include an ID"):
            self.projection.project_hack({"title": "Missing ID"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
