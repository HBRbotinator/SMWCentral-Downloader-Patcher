"""Contracts for safe varied browser Wheel landing positions."""

from __future__ import annotations

import unittest

from wheel_runtime_landing import (
    BROWSER_LANDING_CENTER_BAND,
    BROWSER_LANDING_EARLY_BAND,
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
    def test_early_zone_uses_safe_leading_edge_band(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.10, 0.50)
        )

        self.assertEqual(offset, 0.26)
        self.assertGreaterEqual(offset, BROWSER_LANDING_EARLY_BAND[0])
        self.assertLessEqual(offset, BROWSER_LANDING_EARLY_BAND[1])

    def test_late_zone_uses_safe_trailing_edge_band(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.60, 0.25)
        )

        self.assertEqual(offset, 0.70)
        self.assertGreaterEqual(offset, BROWSER_LANDING_LATE_BAND[0])
        self.assertLessEqual(offset, BROWSER_LANDING_LATE_BAND[1])

    def test_center_zone_remains_available_for_variety(self):
        offset = build_browser_landing_offset(
            SequenceSupplier(0.95, 0.75)
        )

        self.assertEqual(offset, 0.54)
        self.assertGreaterEqual(offset, BROWSER_LANDING_CENTER_BAND[0])
        self.assertLessEqual(offset, BROWSER_LANDING_CENTER_BAND[1])

    def test_all_bands_keep_a_clear_boundary_margin(self):
        draws = (
            (0.00, 0.00),
            (0.41, 0.999999),
            (0.42, 0.00),
            (0.83, 0.999999),
            (0.84, 0.00),
            (0.99, 0.999999),
        )

        for zone, position in draws:
            with self.subTest(zone=zone, position=position):
                offset = build_browser_landing_offset(
                    SequenceSupplier(zone, position)
                )
                self.assertGreaterEqual(offset, 0.18)
                self.assertLessEqual(offset, 0.82)
                self.assertNotEqual(offset, 0.5)

    def test_same_supplied_draws_are_deterministic(self):
        first = build_browser_landing_offset(
            SequenceSupplier(0.20, 0.375)
        )
        second = build_browser_landing_offset(
            SequenceSupplier(0.20, 0.375)
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
