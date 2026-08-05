"""Contracts for weighted near-boundary browser Wheel landings."""

from __future__ import annotations

import unittest

from wheel_runtime_landing import (
    BROWSER_LANDING_CENTER_BAND,
    BROWSER_LANDING_EARLY_BAND,
    BROWSER_LANDING_EXTREME_EARLY_BAND,
    BROWSER_LANDING_EXTREME_LATE_BAND,
    BROWSER_LANDING_HAIRLINE_EARLY_BAND,
    BROWSER_LANDING_HAIRLINE_LATE_BAND,
    BROWSER_LANDING_INNER_EARLY_BAND,
    BROWSER_LANDING_INNER_LATE_BAND,
    BROWSER_LANDING_LATE_BAND,
    BROWSER_LANDING_WEIGHTED_BANDS,
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
    def test_weighted_bands_sum_to_one(self):
        self.assertEqual(len(BROWSER_LANDING_WEIGHTED_BANDS), 9)
        self.assertAlmostEqual(
            sum(weight for _band, weight in BROWSER_LANDING_WEIGHTED_BANDS),
            1.0,
        )

    def test_weighted_bands_are_ordered_and_non_overlapping(self):
        previous_upper = 0.0
        for band, weight in BROWSER_LANDING_WEIGHTED_BANDS:
            lower, upper = band
            self.assertGreater(lower, previous_upper)
            self.assertGreater(upper, lower)
            self.assertGreater(weight, 0.0)
            previous_upper = upper

    def test_hairline_early_can_creep_just_inside_winner(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.02, 0.50)
        )
        self.assertEqual(offset, 0.04)
        self.assertGreaterEqual(offset, BROWSER_LANDING_HAIRLINE_EARLY_BAND[0])
        self.assertLessEqual(offset, BROWSER_LANDING_HAIRLINE_EARLY_BAND[1])

    def test_hairline_late_can_stop_just_before_next_entry(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.98, 0.50)
        )
        self.assertEqual(offset, 0.96)
        self.assertGreaterEqual(offset, BROWSER_LANDING_HAIRLINE_LATE_BAND[0])
        self.assertLessEqual(offset, BROWSER_LANDING_HAIRLINE_LATE_BAND[1])

    def test_every_visual_zone_is_reachable(self):
        draws = (
            (0.04, BROWSER_LANDING_HAIRLINE_EARLY_BAND),
            (0.10, BROWSER_LANDING_EXTREME_EARLY_BAND),
            (0.28, BROWSER_LANDING_EARLY_BAND),
            (0.42, BROWSER_LANDING_INNER_EARLY_BAND),
            (0.50, BROWSER_LANDING_CENTER_BAND),
            (0.58, BROWSER_LANDING_INNER_LATE_BAND),
            (0.70, BROWSER_LANDING_LATE_BAND),
            (0.84, BROWSER_LANDING_EXTREME_LATE_BAND),
            (0.96, BROWSER_LANDING_HAIRLINE_LATE_BAND),
        )
        for zone_draw, expected_band in draws:
            with self.subTest(zone_draw=zone_draw):
                offset = build_browser_landing_offset(
                    SequenceSupplier(zone_draw, 0.50)
                )
                self.assertGreaterEqual(offset, expected_band[0])
                self.assertLessEqual(offset, expected_band[1])

    def test_early_and_late_sides_are_favored_over_center(self):
        early_weight = sum(
            weight for _band, weight in BROWSER_LANDING_WEIGHTED_BANDS[:4]
        )
        center_weight = BROWSER_LANDING_WEIGHTED_BANDS[4][1]
        late_weight = sum(
            weight for _band, weight in BROWSER_LANDING_WEIGHTED_BANDS[5:]
        )
        self.assertAlmostEqual(early_weight, 0.47)
        self.assertAlmostEqual(center_weight, 0.06)
        self.assertAlmostEqual(late_weight, 0.47)
        self.assertGreater(early_weight, center_weight)
        self.assertGreater(late_weight, center_weight)

    def test_all_zones_keep_a_minimum_visible_margin(self):
        draws = (
            (0.00, 0.00), (0.07, 0.999999),
            (0.08, 0.00), (0.21, 0.999999),
            (0.22, 0.00), (0.36, 0.999999),
            (0.37, 0.00), (0.46, 0.999999),
            (0.47, 0.00), (0.52, 0.999999),
            (0.53, 0.00), (0.62, 0.999999),
            (0.63, 0.00), (0.77, 0.999999),
            (0.78, 0.00), (0.91, 0.999999),
            (0.92, 0.00), (0.99, 0.999999),
        )
        for zone, position in draws:
            with self.subTest(zone=zone, position=position):
                offset = build_browser_landing_offset(
                    SequenceSupplier(zone, position)
                )
                self.assertGreaterEqual(offset, 0.025)
                self.assertLessEqual(offset, 0.975)

    def test_same_supplied_draws_are_deterministic(self):
        first = build_browser_landing_offset(
            SequenceSupplier(0.81, 0.375)
        )
        second = build_browser_landing_offset(
            SequenceSupplier(0.81, 0.375)
        )
        self.assertEqual(first, second)

    def test_supplier_contract_rejects_invalid_draws(self):
        invalid_values = (-0.01, 1.0, float("nan"), float("inf"), True, "invalid")
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
