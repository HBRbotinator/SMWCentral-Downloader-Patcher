"""Contracts for synchronizing the native Wheel with an active browser."""

from __future__ import annotations

import unittest

from collection_wheel_animation import (
    build_spin_frames,
    build_timed_spin_frames,
    build_wheel_layout,
)


class CollectionWheelBrowserSyncTest(unittest.TestCase):
    @staticmethod
    def _layout():
        candidates = [
            {"id": f"hack-{index}", "title": f"Hack {index}"}
            for index in range(12)
        ]
        return build_wheel_layout(
            candidates,
            selected_id="hack-7",
        )

    def test_timed_frames_cover_exact_browser_duration(self):
        frames = build_timed_spin_frames(
            self._layout(),
            turns=9,
            duration_ms=5488,
            frame_delay_ms=28,
        )

        self.assertEqual(len(frames), 197)
        self.assertEqual((len(frames) - 1) * 28, 5488)
        self.assertEqual(frames[0], 0.0)
        self.assertGreaterEqual(frames[-1], 9 * 360.0)

    def test_timed_frames_land_at_same_fraction_as_browser(self):
        layout = self._layout()
        landing_offset = 0.975
        frames = build_timed_spin_frames(
            layout,
            turns=9,
            duration_ms=5488,
            frame_delay_ms=28,
            pointer_angle=90.0,
            landing_offset=landing_offset,
        )

        selected = layout.segments[layout.selected_index]
        target = (
            selected.start_angle
            + selected.extent * landing_offset
            + frames[-1]
        ) % 360.0
        self.assertAlmostEqual(target, 90.0, places=7)

    def test_timed_frames_are_monotonic_and_slow_to_zero(self):
        frames = build_timed_spin_frames(
            self._layout(),
            turns=9,
            duration_ms=5488,
            frame_delay_ms=28,
            acceleration_end=0.10,
            deceleration_start=0.27,
            deceleration_bias=-0.35,
        )
        deltas = [
            later - earlier
            for earlier, later in zip(frames, frames[1:])
        ]

        self.assertTrue(all(delta > 0.0 for delta in deltas))
        self.assertLess(deltas[0], max(deltas))
        self.assertLess(deltas[-1], deltas[-20])
        self.assertLess(deltas[-1], max(deltas) * 0.01)

    def test_quick_native_frames_remain_unchanged_for_browser_off(self):
        layout = self._layout()
        frames = build_spin_frames(
            layout,
            turns=5,
            frame_count=61,
            pointer_angle=90.0,
        )

        self.assertEqual(len(frames), 61)
        self.assertEqual(frames[0], 0.0)
        selected = layout.segments[layout.selected_index]
        target = (selected.center_angle + frames[-1]) % 360.0
        self.assertAlmostEqual(target, 90.0, places=7)

    def test_timed_frame_parameters_are_validated(self):
        layout = self._layout()
        invalid = (
            {"duration_ms": 0},
            {"frame_delay_ms": 0},
            {"landing_offset": -0.01},
            {"landing_offset": 1.01},
            {"acceleration_end": 0.0},
            {"deceleration_start": 0.10},
        )

        defaults = {
            "turns": 9,
            "duration_ms": 5488,
            "frame_delay_ms": 28,
            "acceleration_end": 0.10,
            "deceleration_start": 0.27,
        }
        for override in invalid:
            with self.subTest(override=override):
                options = {**defaults, **override}
                with self.assertRaises(ValueError):
                    build_timed_spin_frames(layout, **options)


if __name__ == "__main__":
    unittest.main(verbosity=2)
