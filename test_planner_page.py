"""Tests for the editable Planner page presentation layer."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from planner_page_model import PlannerPageModel
from planner_store import PlannerStore


class _CollectionManager:
    def __init__(self, hacks):
        self.hacks = copy.deepcopy(hacks)

    def get_all_hacks(self, include_obsolete=False):
        records = copy.deepcopy(self.hacks)
        if include_obsolete:
            return records
        return [item for item in records if not item.get("obsolete", False)]


class PlannerPageModelTest(unittest.TestCase):
    """Protect the read and edit contract used by the Planner table."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.planner_path = self.root / "planner_state.json"
        self.planner_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "entries": {
                        "beta": {
                            "lifecycle_status": "Playing",
                            "planning_horizon": "Next",
                            "list_ids": ["stream"],
                        }
                    },
                    "lists": [
                        {"id": "stream", "name": "Stream Games"}
                    ],
                    "next_queue": ["beta"],
                }
            ),
            encoding="utf-8",
        )
        self.collection = _CollectionManager(
            [
                {
                    "id": "alpha",
                    "title": "Alpha World",
                    "completed": True,
                    "difficulty": "Intermediate",
                    "hack_type": "standard",
                    "hack_types": ["standard"],
                    "file_path": "roms/alpha.smc",
                    "files": [],
                    "obsolete": False,
                },
                {
                    "id": "beta",
                    "title": "Beta Quest",
                    "completed": False,
                    "difficulty": "Advanced",
                    "hack_type": "kaizo",
                    "hack_types": ["kaizo", "puzzle"],
                    "file_path": "",
                    "files": [],
                    "obsolete": False,
                },
                {
                    "id": "old",
                    "title": "Old Version",
                    "completed": False,
                    "difficulty": "Casual",
                    "hack_type": "standard",
                    "hack_types": ["standard"],
                    "file_path": "",
                    "files": [],
                    "obsolete": True,
                },
            ]
        )
        self.store = PlannerStore(self.planner_path)
        self.model = PlannerPageModel(self.collection, self.store)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_refresh_projects_current_collection_and_legacy_completion(self):
        projected = self.model.refresh()
        by_id = {item["id"]: item for item in projected}

        self.assertEqual(len(projected), 3)
        self.assertEqual(
            by_id["alpha"]["planner_lifecycle_status"],
            "Completed",
        )
        self.assertEqual(
            by_id["beta"]["planner_lifecycle_status"],
            "Playing",
        )
        self.assertEqual(by_id["beta"]["planner_next_position"], 1)

    def test_visible_hacks_translate_page_controls_to_shared_query(self):
        self.model.refresh()

        next_entries = self.model.visible_hacks(
            lifecycle_status="Playing",
            planning_horizon="Next",
            list_id="stream",
            downloaded="not downloaded",
        )
        downloaded = self.model.visible_hacks(downloaded="downloaded")

        self.assertEqual([item["id"] for item in next_entries], ["beta"])
        self.assertEqual([item["id"] for item in downloaded], ["alpha"])

    def test_table_values_make_next_lists_and_types_readable(self):
        self.model.refresh()
        record = self.model.visible_hacks(text="Beta")[0]

        self.assertEqual(
            self.model.table_values(record),
            (
                "1",
                "Beta Quest",
                "Playing",
                "Next",
                "Stream Games",
                "Advanced",
                "Kaizo, Puzzle",
            ),
        )

    def test_refresh_and_filtering_do_not_write_or_mutate_sources(self):
        original_bytes = self.planner_path.read_bytes()
        original_collection = copy.deepcopy(self.collection.hacks)
        original_state = copy.deepcopy(self.store.state)

        self.model.refresh()
        results = self.model.visible_hacks(text="World")
        results[0]["title"] = "Changed"

        self.assertEqual(self.planner_path.read_bytes(), original_bytes)
        self.assertEqual(self.collection.hacks, original_collection)
        self.assertEqual(self.store.state, original_state)
        self.assertFalse(self.model.has_unsaved_changes)

    def test_horizon_edit_preserves_inferred_completed_status(self):
        original_bytes = self.planner_path.read_bytes()
        self.model.refresh()

        self.model.apply_updates(["alpha"], planning_horizon="Next")
        entry = self.store.get_entry("alpha")
        projected = {
            item["id"]: item for item in self.model.projected_hacks
        }

        self.assertEqual(entry["lifecycle_status"], "Completed")
        self.assertEqual(entry["planning_horizon"], "Next")
        self.assertEqual(entry["completed_at"], "")
        self.assertTrue(entry["planned_at"])
        self.assertEqual(projected["alpha"]["planner_next_position"], 2)
        self.assertEqual(self.planner_path.read_bytes(), original_bytes)
        self.assertTrue(self.model.has_unsaved_changes)

    def test_status_and_horizon_edits_are_staged_until_saved(self):
        original_bytes = self.planner_path.read_bytes()
        self.model.refresh()

        self.model.apply_updates(
            ["beta"],
            lifecycle_status="Paused",
            planning_horizon="Soon",
        )

        self.assertEqual(self.planner_path.read_bytes(), original_bytes)
        self.assertEqual(self.store.get_entry("beta")["lifecycle_status"], "Paused")
        self.assertEqual(self.store.get_entry("beta")["planning_horizon"], "Soon")
        self.assertTrue(self.model.has_unsaved_changes)

        self.assertTrue(self.model.save())
        saved = json.loads(self.planner_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["entries"]["beta"]["lifecycle_status"], "Paused")
        self.assertEqual(saved["entries"]["beta"]["planning_horizon"], "Soon")
        self.assertFalse(self.model.has_unsaved_changes)

    def test_reload_discards_all_staged_page_edits(self):
        self.model.refresh()
        self.model.apply_updates(
            ["beta"],
            lifecycle_status="Dropped",
            planning_horizon="Someday",
        )
        self.assertTrue(self.model.has_unsaved_changes)

        self.model.reload_planner()

        entry = self.store.get_entry("beta")
        self.assertEqual(entry["lifecycle_status"], "Playing")
        self.assertEqual(entry["planning_horizon"], "Next")
        self.assertFalse(self.model.has_unsaved_changes)

    def test_next_entries_can_be_moved_from_the_page_model(self):
        self.model.refresh()
        self.model.apply_updates(["alpha"], planning_horizon="Next")
        self.assertEqual(self.store.get_next_queue(), ["beta", "alpha"])

        position = self.model.move_next("alpha", -1)

        self.assertEqual(position, 1)
        self.assertEqual(self.store.get_next_queue(), ["alpha", "beta"])
        by_id = {item["id"]: item for item in self.model.projected_hacks}
        self.assertEqual(by_id["alpha"]["planner_next_position"], 1)
        self.assertEqual(by_id["beta"]["planner_next_position"], 2)

    def test_failed_page_edit_restores_the_complete_planner_state(self):
        self.model.refresh()
        original_state = copy.deepcopy(self.store.state)

        with self.assertRaisesRegex(ValueError, "Unknown lifecycle status"):
            self.model.apply_updates(
                ["alpha", "beta"],
                lifecycle_status="Almost Done",
            )

        self.assertEqual(self.store.state, original_state)
        self.assertFalse(self.model.has_unsaved_changes)

    def test_invalid_download_control_fails_clearly(self):
        self.model.refresh()

        with self.assertRaisesRegex(ValueError, "downloaded filter"):
            self.model.visible_hacks(downloaded="sometimes")


class PlannerPageWiringTest(unittest.TestCase):
    """Keep Planner navigation and explicit editing controls wired."""

    def test_planner_page_is_wired_into_navigation_and_layout(self):
        repository_root = Path(__file__).resolve().parent
        navigation = (repository_root / "ui" / "navigation.py").read_text(
            encoding="utf-8"
        )
        layout = (repository_root / "ui" / "layout.py").read_text(
            encoding="utf-8"
        )
        pages = (repository_root / "ui" / "pages" / "__init__.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"Planner"', navigation)
        self.assertIn("_refresh_planner_if_available", navigation)
        self.assertIn("PlannerPage", layout)
        self.assertIn('add_page("Planner"', layout)
        self.assertIn("PlannerPage", pages)

    def test_planner_page_exposes_staged_edit_and_save_controls(self):
        repository_root = Path(__file__).resolve().parent
        page_source = (
            repository_root / "ui" / "pages" / "planner_page.py"
        ).read_text(encoding="utf-8")

        for required in (
            "Apply to Selected",
            "Save Changes",
            "Discard Changes",
            "Move Next Up",
            "Move Next Down",
            "model.apply_updates(",
            "model.move_next(",
            "model.save()",
            "model.reload_planner()",
        ):
            self.assertIn(required, page_source)
        self.assertNotIn("processed.json", page_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
