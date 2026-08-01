"""Tests for the Collection-owned Wheel application model."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from collection_wheel import (
    CollectionWheelSelectionService,
    EmptyWheelPoolError,
)
from collection_wheel_model import CollectionWheelModel
from planner_store import PlannerStore


class _LastCandidateRng:
    @staticmethod
    def randrange(stop):
        return stop - 1


class CollectionWheelModelTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.planner_path = self.root / "planner_state.json"
        self.store = PlannerStore(self.planner_path)
        self.model = CollectionWheelModel(
            self.store,
            selection_service=CollectionWheelSelectionService(
                rng=_LastCandidateRng()
            ),
        )
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
                "file_path": "roms/alpha.smc",
                "files": [],
                "obsolete": False,
                "wheel_enabled": False,
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
                "file_path": "",
                "files": [],
                "obsolete": False,
                "wheel_eligible": False,
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
                "file_path": "",
                "files": [],
                "obsolete": True,
            },
        ]

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_collection_view_is_authoritative_without_planner_state(self):
        current_view = [self.collection[1], self.collection[0]]

        pool = self.model.build_pool(current_view)

        self.assertEqual(
            [record["id"] for record in pool],
            ["beta", "alpha"],
        )
        self.assertFalse(self.planner_path.exists())
        self.assertFalse(self.model.planner_refinements_available)

    def test_default_pool_retains_obsolete_entries_already_in_current_view(self):
        pool = self.model.build_pool(self.collection)

        self.assertEqual(
            [record["id"] for record in pool],
            ["alpha", "beta", "gamma"],
        )

    def test_planner_refinements_are_optional_and_do_not_own_the_pool(self):
        self.store.create_list("Stream", list_id="stream")
        self.store.update_entry(
            "alpha",
            lifecycle_status="Playing",
            planning_horizon="Next",
            list_ids=["stream"],
        )
        self.assertTrue(self.store.save())
        original_bytes = self.planner_path.read_bytes()

        next_pool = self.model.build_pool(
            self.collection,
            planning_horizons=["Next"],
        )
        list_pool = self.model.build_pool(
            self.collection,
            list_ids=["stream"],
        )
        plain_pool = self.model.build_pool(self.collection)

        self.assertEqual([record["id"] for record in next_pool], ["alpha"])
        self.assertEqual([record["id"] for record in list_pool], ["alpha"])
        self.assertEqual(
            [record["id"] for record in plain_pool],
            ["alpha", "beta", "gamma"],
        )
        self.assertTrue(self.model.planner_refinements_available)
        self.assertEqual(self.planner_path.read_bytes(), original_bytes)

    def test_available_filters_are_detached_and_collection_scoped(self):
        choices = self.model.available_filters(
            [self.collection[0], self.collection[2]]
        )

        self.assertEqual(
            choices["difficulties"],
            ["Hard", "Intermediate"],
        )
        self.assertEqual(
            choices["hack_types"],
            ["kaizo", "standard"],
        )

        choices["difficulties"].append("Changed")
        reread = self.model.available_filters(
            [self.collection[0], self.collection[2]]
        )
        self.assertNotIn("Changed", reread["difficulties"])

    def test_spin_selects_only_from_the_current_collection_view(self):
        result = self.model.spin(
            [self.collection[0], self.collection[2]],
        )

        self.assertEqual(result.candidate_id, "gamma")
        self.assertEqual(result.pool_size, 2)
        self.assertEqual(result.eligible_size, 2)

    def test_spin_supports_one_call_exclusions(self):
        result = self.model.spin(
            self.collection,
            excluded_ids=["gamma", "beta"],
        )

        self.assertEqual(result.candidate_id, "alpha")
        self.assertEqual(result.pool_size, 3)
        self.assertEqual(result.eligible_size, 1)

    def test_empty_refined_pool_fails_without_writing(self):
        original_collection = copy.deepcopy(self.collection)
        original_state = copy.deepcopy(self.store.state)

        with self.assertRaises(EmptyWheelPoolError):
            self.model.spin(
                self.collection,
                lifecycle_statuses=["Archived"],
            )

        self.assertEqual(self.collection, original_collection)
        self.assertEqual(self.store.state, original_state)
        self.assertFalse(self.store.unsaved_changes)
        self.assertFalse(self.planner_path.exists())

    def test_pool_and_selection_results_are_detached(self):
        original_collection = copy.deepcopy(self.collection)

        pool = self.model.build_pool(self.collection)
        pool[0]["title"] = "Changed pool"
        result = self.model.spin([self.collection[0]])
        selected = result.candidate
        selected["title"] = "Changed result"

        self.assertEqual(self.collection, original_collection)
        self.assertEqual(result.candidate["title"], "Alpha World")

    def test_legacy_eligibility_flags_do_not_gate_results(self):
        pool = self.model.build_pool(self.collection)

        self.assertEqual(
            [record["id"] for record in pool],
            ["alpha", "beta", "gamma"],
        )

    def test_missing_collection_records_fail_clearly(self):
        with self.assertRaises(ValueError):
            self.model.build_pool(None)


if __name__ == "__main__":
    unittest.main(verbosity=2)
