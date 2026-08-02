"""Acceptance contract for the animated Collection Wheel.

The eight new animation contracts are expected failures until Commit 53 adds
the production geometry, Canvas rendering, and non-blocking spin lifecycle.
Existing selection behavior remains covered by normal passing tests.
"""

from __future__ import annotations

import importlib
import unittest
from pathlib import Path

from collection_wheel import CollectionWheelSelectionService


class _LastCandidateRng:
    def __init__(self):
        self.stop = None

    def randrange(self, stop):
        self.stop = stop
        return stop - 1


class CollectionWheelAnimationFoundationTest(unittest.TestCase):
    def test_selection_service_still_uses_the_complete_candidate_pool(self):
        rng = _LastCandidateRng()
        service = CollectionWheelSelectionService(rng=rng)
        candidates = [
            {"id": "alpha", "title": "Alpha"},
            {"id": "beta", "title": "Beta"},
            {"id": "gamma", "title": "Gamma"},
        ]

        result = service.select(candidates)

        self.assertEqual(rng.stop, 3)
        self.assertEqual(result.pool_size, 3)
        self.assertEqual(result.eligible_size, 3)
        self.assertEqual(result.candidate_id, "gamma")

    def test_current_dialog_keeps_selection_model_owned_and_ephemeral(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("self.model.select_from_pool(", source)
        self.assertNotIn("import random", source)
        self.assertNotIn("processed.json", source)
        self.assertNotIn("wheel_eligible", source)


class CollectionWheelAnimationContractTest(unittest.TestCase):
    @staticmethod
    def _animation_module():
        return importlib.import_module("collection_wheel_animation")

    @staticmethod
    def _candidates(count):
        return [
            {
                "id": f"hack-{index:03d}",
                "title": f"Hack Number {index:03d}",
            }
            for index in range(count)
        ]

    def test_layout_represents_entire_pool_and_selected_segment(self):
        animation = self._animation_module()
        candidates = self._candidates(12)

        layout = animation.build_wheel_layout(
            candidates,
            selected_id="hack-007",
            max_labels=18,
        )
        candidates[7]["title"] = "Mutated after layout"

        self.assertEqual(len(layout.segments), 12)
        self.assertEqual(
            [segment.candidate_id for segment in layout.segments],
            [record["id"] for record in self._candidates(12)],
        )
        self.assertEqual(layout.selected_id, "hack-007")
        self.assertEqual(layout.selected_index, 7)
        self.assertEqual(
            layout.segments[7].title,
            "Hack Number 007",
        )
        self.assertTrue(all(segment.show_label for segment in layout.segments))
        self.assertAlmostEqual(
            sum(segment.extent for segment in layout.segments),
            360.0,
        )

    def test_large_pool_limits_labels_but_keeps_selected_label(self):
        animation = self._animation_module()
        candidates = self._candidates(137)

        layout = animation.build_wheel_layout(
            candidates,
            selected_id="hack-136",
            max_labels=18,
        )

        labeled = [
            segment
            for segment in layout.segments
            if segment.show_label
        ]
        self.assertEqual(len(layout.segments), 137)
        self.assertLessEqual(len(labeled), 18)
        self.assertTrue(layout.segments[136].show_label)
        self.assertEqual(
            {segment.candidate_id for segment in layout.segments},
            {record["id"] for record in candidates},
        )

    def test_spin_frames_decelerate_and_land_on_selected_segment(self):
        animation = self._animation_module()
        layout = animation.build_wheel_layout(
            self._candidates(20),
            selected_id="hack-013",
            max_labels=18,
        )

        frames = animation.build_spin_frames(
            layout,
            turns=5,
            frame_count=61,
            pointer_angle=90.0,
        )

        self.assertEqual(len(frames), 61)
        self.assertAlmostEqual(frames[0], 0.0)
        deltas = [
            later - earlier
            for earlier, later in zip(frames, frames[1:])
        ]
        self.assertTrue(all(delta > 0 for delta in deltas))
        self.assertTrue(
            all(
                earlier >= later
                for earlier, later in zip(deltas, deltas[1:])
            )
        )

        selected = layout.segments[layout.selected_index]
        landing_angle = (selected.center_angle + frames[-1]) % 360.0
        self.assertAlmostEqual(landing_angle, 90.0, places=7)
        self.assertGreaterEqual(frames[-1], 5 * 360.0)

    def test_dialog_renders_circular_wheel_with_pointer(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        for required in (
            "self.wheel_canvas = tk.Canvas(",
            "self.wheel_canvas.create_arc(",
            "self.wheel_canvas.create_text(",
            "self.wheel_canvas.create_polygon(",
            "build_wheel_layout",
            "build_spin_frames",
            '"<Configure>"',
        ):
            self.assertIn(required, source)

    def test_dialog_uses_one_filtered_pool_for_selection_and_animation(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        spin_method = source.split(
            "def _spin(self, exclude_current=False):",
            1,
        )[1].split(
            "def _begin_spin_animation(",
            1,
        )[0]

        self.assertEqual(
            spin_method.count("self.model.build_pool("),
            1,
        )
        self.assertIn("self.model.select_from_pool(", spin_method)
        self.assertIn("build_wheel_layout(", spin_method)
        self.assertNotIn("self.model.spin(", spin_method)

    def test_animation_is_non_blocking_and_cancelled_on_close(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        for required in (
            "self._animation_after_id",
            "self.window.after(",
            "self.window.after_cancel(",
            "self._cancel_spin_animation()",
        ):
            self.assertIn(required, source)
        self.assertNotIn("time.sleep(", source)

        close_method = source.split(
            "def close(self):",
            1,
        )[1].split(
            "def _create_window(self):",
            1,
        )[0]
        self.assertIn("self._cancel_spin_animation()", close_method)

    def test_spin_locks_interactions_until_animation_finishes(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        for required in (
            "self._spinning = False",
            "self._set_spinning_state(True)",
            "self._set_spinning_state(False)",
            "def _set_spinning_state(self, spinning):",
            "self.search_entry.configure(",
            "self.reset_filters_button.configure(",
            "for combo in (*self.collection_combos, *self.planner_combos):",
        ):
            self.assertIn(required, source)

    def test_result_callback_waits_for_animation_completion(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        spin_method = source.split(
            "def _spin(self, exclude_current=False):",
            1,
        )[1].split(
            "def _begin_spin_animation(",
            1,
        )[0]
        finish_method = source.split(
            "def _finish_spin_animation(self):",
            1,
        )[1].split(
            "def _cancel_spin_animation(self):",
            1,
        )[0]

        self.assertNotIn("self.result_callback(", spin_method)
        self.assertIn("self.result_callback(", finish_method)
        self.assertIn("self._show_result(", finish_method)
        self.assertIn("self._set_spinning_state(False)", finish_method)
        self.assertNotIn("self._refresh_pool_state()", finish_method)


if __name__ == "__main__":
    unittest.main(verbosity=2)
