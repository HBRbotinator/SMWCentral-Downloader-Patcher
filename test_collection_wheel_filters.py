"""Acceptance contract for Collection-owned Wheel filtering.

These contracts verify the production filtering and dialog behavior added by
Commit 49 alongside the existing Collection Wheel regression suite.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from collection_wheel_model import CollectionWheelModel
from planner_store import PlannerStore


class CollectionWheelFilterContractTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.store = PlannerStore(self.root / "planner_state.json")
        self.model = CollectionWheelModel(self.store)
        self.collection = [
            {
                "id": "alpha",
                "title": "Alpha World",
                "completed": False,
                "difficulty": "Intermediate",
                "hack_type": "kaizo",
                "hack_types": ["kaizo"],
                "authors": ["Ada"],
                "notes": "",
                "rating": 4.0,
                "personal_rating": 1,
                "date": "2020-05-16",
                "file_path": "roms/alpha.smc",
                "files": [],
                "obsolete": False,
            },
            {
                "id": "beta",
                "title": "Beta Quest",
                "completed": True,
                "difficulty": "Advanced",
                "hack_type": "kaizo",
                "hack_types": ["kaizo"],
                "authors": ["Bea"],
                "notes": "",
                "rating": "4.5",
                "personal_rating": 5,
                "date": "2021-08-01",
                "file_path": "",
                "files": [],
                "obsolete": False,
            },
            {
                "id": "gamma",
                "title": "Gamma Story",
                "completed": False,
                "difficulty": "Hard",
                "hack_type": "standard",
                "hack_types": ["standard"],
                "authors": ["Gus"],
                "notes": "",
                "rating": "N/A",
                "personal_rating": 4,
                "date": "",
                "file_path": "",
                "files": [],
                "obsolete": False,
            },
            {
                "id": "delta",
                "title": "Delta Challenge",
                "completed": True,
                "difficulty": "Expert",
                "hack_type": "kaizo",
                "hack_types": ["kaizo", "sa-1"],
                "authors": ["Dee"],
                "notes": "",
                "rating": 5,
                "personal_rating": 0,
                "date": "2019-12-31",
                "file_path": "",
                "files": [{"path": "roms/delta.smc"}],
                "obsolete": False,
            },
            {
                "id": "epsilon",
                "title": "Epsilon Demo",
                "completed": False,
                "difficulty": "Beginner",
                "hack_type": "standard",
                "hack_types": ["standard"],
                "authors": ["Eli"],
                "notes": "",
                "rating": 0,
                "personal_rating": 5,
                "date": "2022-01-01",
                "file_path": "",
                "files": [],
                "obsolete": False,
            },
        ]

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_existing_collection_filters_still_compose(self):
        pool = self.model.build_pool(
            self.collection,
            difficulties=["Intermediate", "Expert"],
            hack_types=["kaizo"],
            downloaded=True,
        )

        self.assertEqual(
            [record["id"] for record in pool],
            ["alpha", "delta"],
        )

    def test_custom_lists_remain_planner_owned(self):
        self.assertFalse(self.model.planner_refinements_available)

        self.store.create_list("Stream", list_id="stream")

        self.assertTrue(self.model.planner_refinements_available)
        self.assertFalse((self.root / "planner_state.json").exists())

    def test_completion_filter_is_independent_of_planner_lifecycle(self):
        incomplete = self.model.build_pool(
            self.collection,
            completed=False,
        )
        complete = self.model.build_pool(
            self.collection,
            completed=True,
        )

        self.assertEqual(
            [record["id"] for record in incomplete],
            ["alpha", "gamma", "epsilon"],
        )
        self.assertEqual(
            [record["id"] for record in complete],
            ["beta", "delta"],
        )
        self.assertFalse(self.model.planner_refinements_available)

    def test_smwc_rating_thresholds_are_inclusive_and_ignore_personal_rating(self):
        four_plus = self.model.build_pool(
            self.collection,
            smwc_rating_min=4.0,
        )
        four_point_five_plus = self.model.build_pool(
            self.collection,
            smwc_rating_min=4.5,
        )
        perfect = self.model.build_pool(
            self.collection,
            smwc_rating_min=5.0,
        )

        self.assertEqual(
            [record["id"] for record in four_plus],
            ["alpha", "beta", "delta"],
        )
        self.assertEqual(
            [record["id"] for record in four_point_five_plus],
            ["beta", "delta"],
        )
        self.assertEqual(
            [record["id"] for record in perfect],
            ["delta"],
        )

    def test_unrated_smwc_filter_accepts_missing_non_numeric_and_zero_values(self):
        unrated = self.model.build_pool(
            self.collection,
            smwc_rating_unrated=True,
        )

        self.assertEqual(
            [record["id"] for record in unrated],
            ["gamma", "epsilon"],
        )

    def test_release_year_range_is_inclusive_and_excludes_unknown_when_active(self):
        ranged = self.model.build_pool(
            self.collection,
            release_year_from=2020,
            release_year_to=2021,
        )
        from_only = self.model.build_pool(
            self.collection,
            release_year_from=2021,
        )
        through_only = self.model.build_pool(
            self.collection,
            release_year_to=2020,
        )

        self.assertEqual(
            [record["id"] for record in ranged],
            ["alpha", "beta"],
        )
        self.assertEqual(
            [record["id"] for record in from_only],
            ["beta", "epsilon"],
        )
        self.assertEqual(
            [record["id"] for record in through_only],
            ["alpha", "delta"],
        )

    def test_collection_filter_choices_include_rating_and_release_metadata(self):
        choices = self.model.available_filters(self.collection)

        self.assertEqual(
            choices["completion_states"],
            [False, True],
        )
        self.assertEqual(
            choices["smwc_rating_thresholds"],
            [1.0, 2.0, 3.0, 4.0, 4.5, 5.0],
        )
        self.assertTrue(choices["has_unrated_smwc_rating"])
        self.assertEqual(
            choices["release_years"],
            [2019, 2020, 2021, 2022],
        )
        self.assertEqual(
            choices["download_states"],
            [False, True],
        )

    def test_filtering_is_detached_and_has_no_persistence_side_effects(self):
        original_collection = copy.deepcopy(self.collection)
        original_state = copy.deepcopy(self.store.state)

        pool = self.model.build_pool(
            self.collection,
            completed=False,
            smwc_rating_min=4.0,
            release_year_from=2020,
            release_year_to=2022,
            downloaded=True,
        )
        pool[0]["title"] = "Changed result"

        self.assertEqual(self.collection, original_collection)
        self.assertEqual(self.store.state, original_state)
        self.assertFalse(self.store.unsaved_changes)
        self.assertFalse((self.root / "planner_state.json").exists())


class CollectionWheelFilterWiringContractTest(unittest.TestCase):
    def test_collection_page_supplies_the_full_collection_to_the_wheel(self):
        source = Path("ui/pages/collection_page.py").read_text(
            encoding="utf-8"
        )

        open_method = source.split(
            "def _open_collection_wheel(self):",
            1,
        )[1].split(
            "def _on_collection_wheel_closed(self):",
            1,
        )[0]

        self.assertIn(
            "self.data_manager.get_all_hacks(include_obsolete=True)",
            open_method,
        )
        self.assertIn("self.collection_wheel_model.reload_planner_state()", open_method)
        self.assertNotIn("self.filtered_data", open_method)

        manager_source = Path("hack_data_manager.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '"rating": hack_data.get("rating", 0)',
            manager_source,
        )

    def test_dialog_owns_collection_filters_and_hides_unused_planner_section(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        for required in (
            "Collection filters",
            "Completion:",
            "Type:",
            "Difficulty:",
            "SMWC rating:",
            "Released from:",
            "Released through:",
            "Download status:",
            "Planner refinements",
            "self.planner_frame",
            "pack_forget()",
        ):
            self.assertIn(required, source)

        self.assertNotIn(
            "Lifecycle remains available from Collection completion",
            source,
        )
        self.assertNotIn(
            "current Collection view owns the candidate pool",
            source,
        )

        page_source = Path("ui/pages/collection_page.py").read_text(
            encoding="utf-8"
        )
        focus_method = page_source.split(
            "def _focus_wheel_result(self, hack_id):",
            1,
        )[1].split(
            "def _select_hack_in_tree(self, hack_id):",
            1,
        )[0]
        self.assertIn("self.filters.clear_filters()", focus_method)


if __name__ == "__main__":
    unittest.main(verbosity=2)
