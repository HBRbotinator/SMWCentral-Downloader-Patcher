"""Tests for the Collection-owned Wheel selection service."""

from __future__ import annotations

import copy
import unittest

from collection_wheel import (
    CollectionWheelSelectionService,
    EmptyWheelPoolError,
    ExhaustedWheelPoolError,
    InvalidWheelCandidateError,
    WheelPoolSnapshot,
)


class CollectionWheelSelectionServiceTest(unittest.TestCase):
    def setUp(self):
        self.candidates = [
            {
                "id": "alpha",
                "title": "Alpha World",
                "completed": False,
                "planner_horizon": "Next",
                "planner_list_ids": ["stream"],
            },
            {
                "id": "beta",
                "title": "Beta Quest",
                "completed": True,
                "planner_horizon": "Someday",
                "planner_list_ids": [],
            },
            {
                "id": "gamma",
                "title": "Gamma Story",
                "completed": False,
                "planner_horizon": "Soon",
                "planner_list_ids": ["short"],
            },
            {
                "id": 400,
                "title": "Numeric Identity",
                "completed": False,
                "planner_horizon": "Someday",
                "planner_list_ids": [],
            },
        ]

    def test_snapshot_is_detached_and_preserves_collection_order(self):
        source = copy.deepcopy(self.candidates)
        snapshot = WheelPoolSnapshot(source)

        source[0]["title"] = "Changed source"
        source[1]["planner_list_ids"].append("changed")

        self.assertEqual(
            snapshot.candidate_ids,
            ("alpha", "beta", "gamma", "400"),
        )
        self.assertEqual(
            [record["title"] for record in snapshot.candidates()],
            [
                "Alpha World",
                "Beta Quest",
                "Gamma Story",
                "Numeric Identity",
            ],
        )

    def test_returned_snapshot_records_are_detached(self):
        snapshot = WheelPoolSnapshot(self.candidates)

        first_read = snapshot.candidates()
        first_read[0]["title"] = "Changed result"
        first_read[0]["planner_list_ids"].append("temporary")

        second_read = snapshot.candidates()
        self.assertEqual(second_read[0]["title"], "Alpha World")
        self.assertEqual(second_read[0]["planner_list_ids"], ["stream"])

    def test_missing_blank_and_duplicate_ids_fail_clearly(self):
        invalid_pools = [
            [{"title": "Missing"}],
            [{"id": "   ", "title": "Blank"}],
            [{"id": "same"}, {"id": "same"}],
            [{"id": 9}, {"id": "9"}],
        ]

        for invalid_pool in invalid_pools:
            with self.subTest(invalid_pool=invalid_pool):
                with self.assertRaises(InvalidWheelCandidateError):
                    WheelPoolSnapshot(invalid_pool)

    def test_empty_pool_is_valid_until_selection_is_requested(self):
        snapshot = WheelPoolSnapshot([])

        self.assertEqual(snapshot.size, 0)
        self.assertEqual(snapshot.candidate_ids, ())
        with self.assertRaises(EmptyWheelPoolError):
            CollectionWheelSelectionService(seed=1).select(snapshot)

    def test_single_candidate_is_selected_without_mutating_collection_data(self):
        source = [copy.deepcopy(self.candidates[0])]
        service = CollectionWheelSelectionService(seed=9)

        result = service.select(source)

        self.assertEqual(result.candidate_id, "alpha")
        self.assertEqual(result.pool_size, 1)
        self.assertEqual(result.eligible_size, 1)
        self.assertEqual(result.excluded_ids, ())
        self.assertEqual(source, [self.candidates[0]])

    def test_equal_seeds_produce_equal_selection_sequences(self):
        first = CollectionWheelSelectionService(seed=2026)
        second = CollectionWheelSelectionService(seed=2026)
        snapshot = first.snapshot(self.candidates)

        first_sequence = [
            first.select(snapshot).candidate_id
            for _ in range(12)
        ]
        second_sequence = [
            second.select(snapshot).candidate_id
            for _ in range(12)
        ]

        self.assertEqual(first_sequence, second_sequence)

    def test_exclusions_remove_candidates_from_only_this_selection(self):
        service = CollectionWheelSelectionService(seed=3)
        snapshot = service.snapshot(self.candidates)

        result = service.select(
            snapshot,
            excluded_ids=["alpha", "beta", "gamma", "unknown"],
        )

        self.assertEqual(result.candidate_id, "400")
        self.assertEqual(result.pool_size, 4)
        self.assertEqual(result.eligible_size, 1)
        self.assertEqual(
            result.excluded_ids,
            ("alpha", "beta", "gamma", "unknown"),
        )
        self.assertEqual(snapshot.size, 4)

    def test_fully_excluded_non_empty_pool_fails_clearly(self):
        service = CollectionWheelSelectionService(seed=4)
        snapshot = service.snapshot(self.candidates)

        with self.assertRaises(ExhaustedWheelPoolError):
            service.select(
                snapshot,
                excluded_ids=snapshot.candidate_ids,
            )

    def test_selection_result_is_detached_from_pool_and_callers(self):
        service = CollectionWheelSelectionService(seed=8)
        snapshot = service.snapshot([self.candidates[0]])

        result = service.select(snapshot)
        selected = result.candidate
        selected["title"] = "Changed selection"
        selected["planner_list_ids"].append("temporary")

        reread = result.candidate
        self.assertEqual(reread["title"], "Alpha World")
        self.assertEqual(reread["planner_list_ids"], ["stream"])
        self.assertEqual(snapshot.candidates()[0]["title"], "Alpha World")

    def test_completed_and_non_planner_candidates_are_not_special_cased(self):
        service = CollectionWheelSelectionService(
            rng=_LastCandidateRng()
        )
        candidates = [
            {"id": "completed", "title": "Completed", "completed": True},
            {"id": "plain", "title": "Plain Collection Record"},
        ]

        result = service.select(candidates)

        self.assertEqual(result.candidate_id, "plain")
        self.assertEqual(result.pool_size, 2)

    def test_custom_rng_contract_can_be_injected(self):
        service = CollectionWheelSelectionService(
            rng=_LastCandidateRng()
        )

        result = service.select(self.candidates)

        self.assertEqual(result.candidate_id, "400")

    def test_seed_and_rng_cannot_both_be_supplied(self):
        with self.assertRaises(ValueError):
            CollectionWheelSelectionService(
                seed=1,
                rng=object(),
            )

    def test_rng_requires_randrange(self):
        with self.assertRaises(TypeError):
            CollectionWheelSelectionService(rng=object())


class _LastCandidateRng:
    @staticmethod
    def randrange(stop):
        return stop - 1


if __name__ == "__main__":
    unittest.main(verbosity=2)
