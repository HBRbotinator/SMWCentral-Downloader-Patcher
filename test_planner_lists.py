"""Custom-list management coverage for the Planner page model and UI."""

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
        self.hacks = hacks

    def get_all_hacks(self, include_obsolete=False):
        records = copy.deepcopy(self.hacks)
        if include_obsolete:
            return records
        return [item for item in records if not item.get("obsolete", False)]


class PlannerListManagementTest(unittest.TestCase):
    """Protect staged list definitions and bulk memberships."""

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
                    "hack_types": ["kaizo"],
                    "file_path": "",
                    "files": [],
                    "obsolete": False,
                },
            ]
        )
        self.store = PlannerStore(self.planner_path)
        self.model = PlannerPageModel(self.collection, self.store)
        self.model.refresh()

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_list_definitions_are_staged_with_stable_ids(self):
        original_bytes = self.planner_path.read_bytes()

        created = self.model.create_list("Short Hacks", list_id="short")
        renamed = self.model.rename_list("short", "Short Streams")

        self.assertEqual(created, {"id": "short", "name": "Short Hacks"})
        self.assertEqual(renamed, {"id": "short", "name": "Short Streams"})
        self.assertEqual(
            self.model.custom_lists(),
            [
                {"id": "stream", "name": "Stream Games"},
                {"id": "short", "name": "Short Streams"},
            ],
        )
        self.assertEqual(self.planner_path.read_bytes(), original_bytes)
        self.assertTrue(self.model.has_unsaved_changes)

        self.assertTrue(self.model.delete_list("short"))
        self.assertEqual(
            self.model.custom_lists(),
            [{"id": "stream", "name": "Stream Games"}],
        )
        self.assertEqual(self.planner_path.read_bytes(), original_bytes)

    def test_bulk_membership_preserves_other_lists_and_legacy_completion(self):
        self.model.create_list("Short Hacks", list_id="short")

        changed = self.model.apply_list_membership(
            ["alpha", "beta"],
            "short",
            "add",
        )

        self.assertEqual(changed, ["alpha", "beta"])
        self.assertEqual(self.store.get_entry("alpha")["list_ids"], ["short"])
        self.assertEqual(
            self.store.get_entry("beta")["list_ids"],
            ["stream", "short"],
        )
        self.assertEqual(
            self.store.get_entry("alpha")["lifecycle_status"],
            "Completed",
        )
        self.assertTrue(self.store.get_entry("alpha")["planned_at"])

        unchanged = self.model.apply_list_membership(
            ["alpha", "beta"],
            "short",
            "add",
        )
        removed = self.model.apply_list_membership(
            ["alpha", "beta"],
            "stream",
            "remove",
        )

        self.assertEqual(unchanged, [])
        self.assertEqual(removed, ["beta"])
        self.assertEqual(self.store.get_entry("alpha")["list_ids"], ["short"])
        self.assertEqual(self.store.get_entry("beta")["list_ids"], ["short"])

    def test_deleting_a_list_removes_every_membership(self):
        self.model.create_list("Short Hacks", list_id="short")
        self.model.apply_list_membership(
            ["alpha", "beta"],
            "short",
            "add",
        )

        self.model.delete_list("short")

        self.assertEqual(self.store.get_entry("alpha")["list_ids"], [])
        self.assertEqual(self.store.get_entry("beta")["list_ids"], ["stream"])
        projected = {item["id"]: item for item in self.model.projected_hacks}
        self.assertEqual(projected["alpha"]["planner_list_names"], [])
        self.assertEqual(
            projected["beta"]["planner_list_names"],
            ["Stream Games"],
        )

    def test_failed_membership_edit_restores_complete_state(self):
        original_state = copy.deepcopy(self.store.state)
        original_unsaved = self.store.unsaved_changes

        with self.assertRaisesRegex(ValueError, "Unknown custom list ID"):
            self.model.apply_list_membership(
                ["alpha", "beta"],
                "missing",
                "add",
            )

        self.assertEqual(self.store.state, original_state)
        self.assertEqual(self.store.unsaved_changes, original_unsaved)

        with self.assertRaisesRegex(ValueError, "mode must be"):
            self.model.apply_list_membership(
                ["alpha"],
                "stream",
                "replace",
            )

        self.assertEqual(self.store.state, original_state)
        self.assertEqual(self.store.unsaved_changes, original_unsaved)

    def test_list_changes_persist_only_after_explicit_save(self):
        original_bytes = self.planner_path.read_bytes()
        self.model.create_list("Short Hacks", list_id="short")
        self.model.apply_list_membership(["alpha"], "short", "add")

        self.assertEqual(self.planner_path.read_bytes(), original_bytes)
        self.assertTrue(self.model.save())

        saved = json.loads(self.planner_path.read_text(encoding="utf-8"))
        self.assertEqual(
            saved["lists"],
            [
                {"id": "stream", "name": "Stream Games"},
                {"id": "short", "name": "Short Hacks"},
            ],
        )
        self.assertEqual(saved["entries"]["alpha"]["list_ids"], ["short"])
        self.assertFalse(self.model.has_unsaved_changes)

    def test_reload_discards_list_definitions_and_memberships(self):
        self.model.create_list("Short Hacks", list_id="short")
        self.model.apply_list_membership(["alpha"], "short", "add")
        self.model.rename_list("stream", "Broadcast Games")

        self.model.reload_planner()

        self.assertEqual(
            self.model.custom_lists(),
            [{"id": "stream", "name": "Stream Games"}],
        )
        self.assertFalse(self.store.has_entry("alpha"))
        self.assertEqual(self.store.get_entry("beta")["list_ids"], ["stream"])
        self.assertFalse(self.model.has_unsaved_changes)


class PlannerListWiringTest(unittest.TestCase):
    """Keep custom-list controls connected to the staged page model."""

    def test_planner_page_exposes_list_management_and_membership_controls(self):
        repository_root = Path(__file__).resolve().parent
        page_source = (
            repository_root / "ui" / "pages" / "planner_page.py"
        ).read_text(encoding="utf-8")

        for required in (
            "Custom lists",
            "New List",
            "Rename List",
            "Delete List",
            "Add Selected to List",
            "Remove Selected from List",
            "model.create_list(",
            "model.rename_list(",
            "model.delete_list(",
            "model.apply_list_membership(",
            "The change remains staged until Save Changes is pressed.",
        ):
            self.assertIn(required, page_source)
        self.assertNotIn("processed.json", page_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
