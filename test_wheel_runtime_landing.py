"""Contracts for dramatic but unambiguous browser Wheel landings."""

from __future__ import annotations

import unittest

from wheel_runtime_landing import (
    BROWSER_LANDING_CENTER_BAND,
    BROWSER_LANDING_EARLY_BAND,
    BROWSER_LANDING_EXTREME_EARLY_BAND,
    BROWSER_LANDING_EXTREME_LATE_BAND,
    BROWSER_LANDING_LATE_BAND,
    build_browser_landing_offset,
)


class SequenceSupplier:
    def __init__(self, *values):
        self.values = list(values)
        self.index = 0

    def __call__(self):
        value = self.values[self.index]
        self.index += 1
        return value


class WheelRuntimeLandingTest(unittest.TestCase):
    def test_extreme_early_zone_creeps_just_inside_winner(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.10, 0.50)
        )

        self.assertEqual(offset, 0.09)
        self.assertGreaterEqual(
            offset,
            BROWSER_LANDING_EXTREME_EARLY_BAND[0],
        )
        self.assertLessEqual(
            offset,
            BROWSER_LANDING_EXTREME_EARLY_BAND[1],
        )

    def test_early_zone_still_provides_less_extreme_finishes(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.30, 0.50)
        )

        self.assertEqual(offset, 0.26)
        self.assertGreaterEqual(offset, BROWSER_LANDING_EARLY_BAND[0])
        self.assertLessEqual(offset, BROWSER_LANDING_EARLY_BAND[1])

    def test_center_zone_remains_available_for_variety(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.50, 0.75)
        )

        self.assertEqual(offset, 0.55)
        self.assertGreaterEqual(offset, BROWSER_LANDING_CENTER_BAND[0])
        self.assertLessEqual(offset, BROWSER_LANDING_CENTER_BAND[1])

    def test_late_zone_stops_near_next_boundary(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.60, 0.25)
        )

        self.assertEqual(offset, 0.70)
        self.assertGreaterEqual(offset, BROWSER_LANDING_LATE_BAND[0])
        self.assertLessEqual(offset, BROWSER_LANDING_LATE_BAND[1])

    def test_extreme_late_zone_creeps_just_before_next_entry(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.90, 0.50)
        )

        self.assertEqual(offset, 0.91)
        self.assertGreaterEqual(
            offset,
            BROWSER_LANDING_EXTREME_LATE_BAND[0],
        )
        self.assertLessEqual(
            offset,
            BROWSER_LANDING_EXTREME_LATE_BAND[1],
        )

    def test_all_zones_keep_a_visible_boundary_margin(self):
        draws = (
            (0.00, 0.00),
            (0.25, 0.999999),
            (0.26, 0.00),
            (0.44, 0.999999),
            (0.45, 0.00),
            (0.54, 0.999999),
            (0.55, 0.00),
            (0.73, 0.999999),
            (0.74, 0.00),
            (0.99, 0.999999),
        )

        for zone, position in draws:
            with self.subTest(zone=zone, position=position):
                offset = build_browser_landing_offset(
                    SequenceSupplier(zone, position)
                )
                self.assertGreaterEqual(offset, 0.06)
                self.assertLessEqual(offset, 0.94)

    def test_extreme_edge_zones_are_more_common_than_center(self):
        extreme_draws = (0.00, 0.25, 0.74, 0.99)
        center_draws = (0.45, 0.54)

        extreme_offsets = [
            build_browser_landing_offset(
                SequenceSupplier(draw, 0.50)
            )
            for draw in extreme_draws
        ]
        center_offsets = [
            build_browser_landing_offset(
                SequenceSupplier(draw, 0.50)
            )
            for draw in center_draws
        ]

        self.assertTrue(
            all(
                offset <= 0.12 or offset >= 0.88
                for offset in extreme_offsets
            )
        )
        self.assertTrue(
            all(0.40 <= offset <= 0.60 for offset in center_offsets)
        )

    def test_same_supplied_draws_are_deterministic(self):
        first = build_browser_landing_offset(
            SequenceSupplier(0.80, 0.375)
        )
        second = build_browser_landing_offset(
            SequenceSupplier(0.80, 0.375)
        )

        self.assertEqual(first, second)

    def test_supplier_contract_rejects_invalid_draws(self):
        invalid_values = (
            -0.01,
            1.0,
            float("nan"),
            float("inf"),
            True,
            "invalid",
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_browser_landing_offset(
                        SequenceSupplier(value, 0.5)
                    )

    def test_supplier_must_be_callable(self):
        with self.assertRaises(TypeError):
            build_browser_landing_offset("not callable")


if __name__ == "__main__":
    unittest.main(verbosity=2)
