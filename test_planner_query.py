"""Tests for composable Planner collection filtering and ordering."""

from __future__ import annotations

import copy
import unittest

from planner_query import PlannerCollectionQuery


class PlannerCollectionQueryTest(unittest.TestCase):
    """Protect the shared query contract for Planner and future Wheel views."""

    def setUp(self):
        self.query = PlannerCollectionQuery()
        self.hacks = [
            self._hack(
                "alpha",
                "Alpha Adventure",
                status="Playing",
                horizon="Soon",
                lists=[("stream", "Stream Games")],
                difficulty="Intermediate",
                hack_types=["Kaizo"],
                authors=["Ada"],
                notes="Practice on weekends",
                file_path="roms/alpha.smc",
            ),
            self._hack(
                "beta",
                "Beta Quest",
                status="Planned",
                horizon="Next",
                next_position=2,
                lists=[
                    ("stream", "Stream Games"),
                    ("short", "Short Hacks"),
                ],
                difficulty="Advanced",
                hack_types=["Kaizo", "Puzzle"],
                authors=["Bea"],
            ),
            self._hack(
                "gamma",
                "Gamma World",
                status="Planned",
                horizon="Next",
                next_position=1,
                lists=[("short", "Short Hacks")],
                difficulty="Intermediate",
                hack_types=["Standard"],
                authors=["Gus"],
                files=[{"path": "roms/gamma.smc", "primary": True}],
            ),
            self._hack(
                "delta",
                "Delta Demo",
                status="Completed",
                horizon="Someday",
                difficulty="Casual",
                hack_types=["Standard"],
                obsolete=True,
            ),
        ]

    def test_filters_or_within_groups_and_and_across_groups(self):
        matching = self.query.query_collection(
            self.hacks,
            lifecycle_statuses=["Planned", "Playing"],
            planning_horizons=["Next"],
            difficulties=["Intermediate", "Advanced"],
            hack_types=["Kaizo"],
            sort_mode="collection",
        )

        self.assertEqual([item["id"] for item in matching], ["beta"])

    def test_custom_lists_support_any_and_all_membership(self):
        any_match = self.query.query_collection(
            self.hacks,
            list_ids=["stream", "short"],
            list_match="any",
            sort_mode="collection",
        )
        all_match = self.query.query_collection(
            self.hacks,
            list_ids=["stream", "short"],
            list_match="all",
            sort_mode="collection",
        )

        self.assertEqual(
            [item["id"] for item in any_match],
            ["alpha", "beta", "gamma"],
        )
        self.assertEqual([item["id"] for item in all_match], ["beta"])

    def test_text_search_covers_collection_and_planner_display_fields(self):
        cases = {
            "weekends": ["alpha"],
            "ada intermediate": ["alpha"],
            "short puzzle": ["beta"],
            "gamma standard": ["gamma"],
            "beta": ["beta"],
        }

        for text, expected_ids in cases.items():
            with self.subTest(text=text):
                matching = self.query.query_collection(
                    self.hacks,
                    text=text,
                    sort_mode="collection",
                )
                self.assertEqual(
                    [item["id"] for item in matching],
                    expected_ids,
                )

    def test_download_filter_uses_recorded_single_and_multi_file_paths(self):
        downloaded = self.query.query_collection(
            self.hacks,
            downloaded=True,
            sort_mode="collection",
        )
        missing = self.query.query_collection(
            self.hacks,
            downloaded=False,
            include_obsolete=True,
            sort_mode="collection",
        )

        self.assertEqual(
            [item["id"] for item in downloaded],
            ["alpha", "gamma"],
        )
        self.assertEqual(
            [item["id"] for item in missing],
            ["beta", "delta"],
        )

    def test_planning_sort_respects_next_order_then_horizon_and_title(self):
        matching = self.query.query_collection(self.hacks)

        self.assertEqual(
            [item["id"] for item in matching],
            ["gamma", "beta", "alpha"],
        )

        title_sorted = self.query.query_collection(
            self.hacks,
            include_obsolete=True,
            sort_mode="title",
        )
        self.assertEqual(
            [item["id"] for item in title_sorted],
            ["alpha", "beta", "delta", "gamma"],
        )

    def test_available_filters_are_deduplicated_and_stable(self):
        filters = self.query.available_filters(self.hacks)

        self.assertEqual(
            filters["lifecycle_statuses"],
            ["Planned", "Playing", "Completed"],
        )
        self.assertEqual(
            filters["planning_horizons"],
            ["Someday", "Soon", "Next"],
        )
        self.assertEqual(
            filters["lists"],
            [
                {"id": "short", "name": "Short Hacks"},
                {"id": "stream", "name": "Stream Games"},
            ],
        )
        self.assertEqual(
            filters["difficulties"],
            ["Advanced", "Casual", "Intermediate"],
        )
        self.assertEqual(
            filters["hack_types"],
            ["Kaizo", "Puzzle", "Standard"],
        )

    def test_query_returns_copies_without_mutating_source_records(self):
        original = copy.deepcopy(self.hacks)

        matching = self.query.query_collection(
            self.hacks,
            planning_horizons=["Next"],
        )
        matching[0]["title"] = "Changed result"
        matching[0]["planner_list_ids"].append("changed")

        self.assertEqual(self.hacks, original)

    def test_invalid_filter_values_fail_clearly(self):
        cases = (
            ({"lifecycle_statuses": ["Unknown"]}, "lifecycle"),
            ({"planning_horizons": ["Later"]}, "horizon"),
            ({"list_match": "none"}, "any' or 'all"),
            ({"sort_mode": "random"}, "sort mode"),
            ({"downloaded": "yes"}, "downloaded"),
        )

        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaisesRegex(ValueError, message):
                    self.query.query_collection(self.hacks, **arguments)

    @staticmethod
    def _hack(
        hack_id,
        title,
        *,
        status,
        horizon,
        next_position=None,
        lists=None,
        difficulty="Unknown",
        hack_types=None,
        authors=None,
        notes="",
        file_path="",
        files=None,
        obsolete=False,
    ):
        list_pairs = lists or []
        return {
            "id": hack_id,
            "title": title,
            "difficulty": difficulty,
            "hack_type": (hack_types or ["Unknown"])[0],
            "hack_types": list(hack_types or []),
            "authors": list(authors or []),
            "notes": notes,
            "file_path": file_path,
            "files": copy.deepcopy(files or []),
            "obsolete": obsolete,
            "planner_lifecycle_status": status,
            "planner_horizon": horizon,
            "planner_list_ids": [item[0] for item in list_pairs],
            "planner_list_names": [item[1] for item in list_pairs],
            "planner_next_position": next_position,
        }


if __name__ == "__main__":
    unittest.main(verbosity=2)
