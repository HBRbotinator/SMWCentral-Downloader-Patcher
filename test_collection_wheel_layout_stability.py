"""Regression tests for stable animated Wheel placement."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


def _load_dialog_class():
    if "collection_wheel" not in sys.modules:
        wheel_stub = types.ModuleType("collection_wheel")

        class _WheelError(ValueError):
            pass

        wheel_stub.EmptyWheelPoolError = _WheelError
        wheel_stub.ExhaustedWheelPoolError = _WheelError
        sys.modules["collection_wheel"] = wheel_stub

    if "collection_wheel_animation" not in sys.modules:
        animation_stub = types.ModuleType("collection_wheel_animation")
        animation_stub.build_spin_frames = lambda *_args, **_kwargs: ()
        animation_stub.build_wheel_layout = lambda *_args, **_kwargs: None
        sys.modules["collection_wheel_animation"] = animation_stub

    path = Path("ui/collection_wheel_dialog.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "collection_wheel_dialog_stability_under_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CollectionWheelDialog


CollectionWheelDialog = _load_dialog_class()


class CollectionWheelLayoutStabilityTest(unittest.TestCase):
    def test_result_details_have_a_fixed_reserved_width(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        for required in (
            "RESULT_DETAILS_WIDTH = 320",
            "RESULT_DETAILS_WRAP = 300",
            "result_frame.grid_columnconfigure(0, weight=1)",
            "minsize=self.RESULT_DETAILS_WIDTH",
            "width=self.RESULT_DETAILS_WIDTH",
            "result_details.grid_propagate(False)",
            "wraplength=self.RESULT_DETAILS_WRAP",
        ):
            self.assertIn(required, source)

        self.assertNotIn(
            "result_frame.grid_columnconfigure(1, weight=2)",
            source,
        )

    def test_wheel_geometry_is_deterministic_for_a_canvas_size(self):
        first = CollectionWheelDialog._wheel_geometry(440, 440)
        second = CollectionWheelDialog._wheel_geometry(440, 440)

        self.assertEqual(first, second)
        center_x, center_y, radius, bounds = first
        self.assertEqual(center_x, 220.0)
        self.assertEqual(center_y, 226.0)
        self.assertEqual(radius, 192.0)
        self.assertEqual(bounds, (28.0, 34.0, 412.0, 418.0))

    def test_wheel_remains_centered_when_canvas_is_resized(self):
        center_x, center_y, radius, bounds = (
            CollectionWheelDialog._wheel_geometry(500, 440)
        )

        self.assertEqual(center_x, 250.0)
        self.assertEqual(center_y, 226.0)
        self.assertEqual(radius, 192.0)
        self.assertAlmostEqual((bounds[0] + bounds[2]) / 2, center_x)
        self.assertAlmostEqual((bounds[1] + bounds[3]) / 2, center_y)

    def test_spin_state_changes_do_not_reconfigure_layout_managers(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        begin = source.split(
            "def _begin_spin_animation(self, layout, frames, result):",
            1,
        )[1].split(
            "def _advance_spin_animation(self):",
            1,
        )[0]
        finish = source.split(
            "def _finish_spin_animation(self):",
            1,
        )[1].split(
            "def _cancel_spin_animation(self):",
            1,
        )[0]

        for method_source in (begin, finish):
            self.assertNotIn(".grid(", method_source)
            self.assertNotIn(".pack(", method_source)
            self.assertNotIn(".place(", method_source)
            self.assertNotIn("grid_columnconfigure(", method_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
