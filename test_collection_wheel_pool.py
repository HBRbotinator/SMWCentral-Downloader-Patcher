"""Regression contract for the Collection-owned Wheel candidate pool.

Collection is the authoritative Wheel source. Planner projection may enrich and
optionally refine that source, but the Wheel must remain usable when the user
has never created Planner state.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from planner_collection import PlannerCollectionProjection
from planner_query import PlannerCollectionQuery
from planner_store import PlannerStore


class CollectionWheelPoolContractTest(unittest.TestCase):
    """Lock Collection ownership before adding Wheel selection code."""

    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.planner_path = self.root / "planner_state.json"
        self.store = PlannerStore(self.planner_path)
        self.projection = PlannerCollectionProjection(self.store)
        self.query = PlannerCollectionQuery()
        self.collection_view = [
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
                "obsolete": False,
            },
        ]

    def tearDown(self):
        self._temporary_directory.cleanup()

    def _pool(self, records=None, **filters):
        projected = self.projection.project_collection(
            self.collection_view if records is None else records
        )
        return self.query.query_collection(
            projected,
            sort_mode="collection",
            **filters,
        )

    def test_collection_view_is_available_without_planner_state(self):
        pool = self._pool()

        self.assertEqual(
            [record["id"] for record in pool],
            ["alpha", "beta", "gamma"],
        )
        self.assertEqual(
            [record["planner_lifecycle_status"] for record in pool],
            ["Planned", "Completed", "Planned"],
        )
        self.assertFalse(self.planner_path.exists())
        self.assertFalse(self.store.unsaved_changes)

    def test_current_collection_order_is_preserved(self):
        reordered = [
            self.collection_view[2],
            self.collection_view[0],
            self.collection_view[1],
        ]

        pool = self._pool(reordered)

        self.assertEqual(
            [record["id"] for record in pool],
            ["gamma", "alpha", "beta"],
        )

    def test_planner_data_can_optionally_refine_the_collection_pool(self):
        self.store.create_list("Stream", list_id="stream")
        self.store.update_entry(
            "alpha",
            lifecycle_status="Playing",
            planning_horizon="Next",
            list_ids=["stream"],
        )
        self.store.update_entry(
            "gamma",
            lifecycle_status="Planned",
            planning_horizon="Soon",
        )

        next_pool = self._pool(planning_horizons=["Next"])
        list_pool = self._pool(list_ids=["stream"])
        status_pool = self._pool(lifecycle_statuses=["Playing"])

        self.assertEqual([record["id"] for record in next_pool], ["alpha"])
        self.assertEqual([record["id"] for record in list_pool], ["alpha"])
        self.assertEqual([record["id"] for record in status_pool], ["alpha"])

    def test_legacy_wheel_flags_do_not_gate_collection_candidates(self):
        pool = self._pool()

        self.assertEqual(
            [record["id"] for record in pool],
            ["alpha", "beta", "gamma"],
        )

    def test_collection_filters_work_without_explicit_planner_entries(self):
        downloaded = self._pool(downloaded=True)
        standard = self._pool(hack_types=["standard"])
        intermediate = self._pool(difficulties=["Intermediate"])
        searched = self._pool(text="gamma gus")

        self.assertEqual([record["id"] for record in downloaded], ["alpha"])
        self.assertEqual([record["id"] for record in standard], ["gamma"])
        self.assertEqual([record["id"] for record in intermediate], ["alpha"])
        self.assertEqual([record["id"] for record in searched], ["gamma"])
        self.assertFalse(self.planner_path.exists())

    def test_empty_and_singleton_collection_views_are_valid_pools(self):
        empty_pool = self._pool([])
        singleton_pool = self._pool([self.collection_view[0]])

        self.assertEqual(empty_pool, [])
        self.assertEqual(
            [record["id"] for record in singleton_pool],
            ["alpha"],
        )

    def test_pool_building_is_detached_and_has_no_persistence_side_effect(self):
        original_collection = copy.deepcopy(self.collection_view)
        original_state = copy.deepcopy(self.store.state)

        pool = self._pool()
        pool[0]["title"] = "Changed result"
        pool[0]["hack_types"].append("temporary")
        pool[0]["planner_list_ids"].append("temporary")

        self.assertEqual(self.collection_view, original_collection)
        self.assertEqual(self.store.state, original_state)
        self.assertFalse(self.store.unsaved_changes)
        self.assertFalse(self.planner_path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
