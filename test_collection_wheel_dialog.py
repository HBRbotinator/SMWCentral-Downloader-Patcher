"""Collection Wheel dialog and Collection-page wiring tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


def _load_dialog_class():
    path = Path("ui/collection_wheel_dialog.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "collection_wheel_dialog_under_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CollectionWheelDialog


CollectionWheelDialog = _load_dialog_class()


class CollectionWheelDialogContractTest(unittest.TestCase):
    def test_filter_choice_helpers_normalize_values(self):
        self.assertEqual(CollectionWheelDialog._optional_choice("All"), "")
        self.assertEqual(CollectionWheelDialog._optional_choice(""), "")
        self.assertEqual(
            CollectionWheelDialog._optional_choice("  Next  "),
            "Next",
        )
        self.assertEqual(
            CollectionWheelDialog._completion_choice("Completed"),
            True,
        )
        self.assertEqual(
            CollectionWheelDialog._completion_choice("Not completed"),
            False,
        )
        self.assertIsNone(
            CollectionWheelDialog._completion_choice("All")
        )
        self.assertEqual(
            CollectionWheelDialog._download_choice("Downloaded"),
            True,
        )
        self.assertEqual(
            CollectionWheelDialog._download_choice("Not downloaded"),
            False,
        )
        self.assertIsNone(
            CollectionWheelDialog._optional_year_choice("Any")
        )
        self.assertEqual(
            CollectionWheelDialog._optional_year_choice("2024"),
            2024,
        )

    def test_required_window_size_reserves_complete_filter_layout(self):
        self.assertEqual(
            CollectionWheelDialog._required_window_size(400, 300),
            (
                CollectionWheelDialog.MIN_WIDTH,
                CollectionWheelDialog.MIN_HEIGHT,
            ),
        )
        larger_width = CollectionWheelDialog.MIN_WIDTH + 120
        larger_height = CollectionWheelDialog.MIN_HEIGHT + 70
        self.assertEqual(
            CollectionWheelDialog._required_window_size(
                larger_width,
                larger_height,
            ),
            (larger_width, larger_height),
        )

    def test_dynamic_content_is_applied_before_window_is_shown(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        reload_index = source.index("self.model.reload_planner_state()")
        populate_index = source.index("self._populate_filter_choices()")
        refresh_index = source.index("self._refresh_pool_state()")
        finalize_index = source.index("self._finalize_window()")

        self.assertLess(reload_index, populate_index)
        self.assertLess(populate_index, finalize_index)
        self.assertLess(refresh_index, finalize_index)
        self.assertIn("self.window.withdraw()", source)
        self.assertIn("self.window.deiconify()", source)
        self.assertIn('buttons.pack(side="bottom"', source)

    def test_collection_filters_are_always_available(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "Collection filters",
            "Completion:",
            "Type:",
            "Difficulty:",
            "SMWC rating:",
            "Released from:",
            "Released through:",
            "Download status:",
            "Reset Filters",
            '"include_obsolete": False',
        ):
            self.assertIn(required, source)

    def test_planner_refinements_are_hidden_as_one_optional_section(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "Planner refinements",
            "self.planner_frame",
            "self.model.planner_refinements_available",
            "self.planner_frame.pack_forget()",
            "Lifecycle:",
            "Planning horizon:",
            "Custom list:",
        ):
            self.assertIn(required, source)

        self.assertNotIn(
            "Lifecycle remains available from Collection completion",
            source,
        )
        self.assertNotIn(
            "No Planner horizons or custom lists are configured",
            source,
        )

    def test_dialog_uses_model_without_wheel_persistence(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "self.model.build_pool(",
            "self.model.select_from_pool(",
            "excluded_ids=excluded_ids",
            "build_wheel_layout(",
            "build_spin_frames(",
            "Spin Wheel",
            "Spin Again",
            "Clear Result",
            "self.result_callback(result.candidate_id)",
        ):
            self.assertIn(required, source)
        for forbidden in (
            "wheel_enabled",
            "wheel_eligible",
            ".save(",
            "update_entry(",
            "processed.json",
        ):
            self.assertNotIn(forbidden, source)

    def test_dialog_draws_and_safely_animates_the_wheel(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "self.wheel_canvas = tk.Canvas(",
            "self.wheel_canvas.create_arc(",
            "self.wheel_canvas.create_polygon(",
            "self.window.after(",
            "self.window.after_cancel(",
            "self._set_spinning_state(True)",
            "self._set_spinning_state(False)",
        ):
            self.assertIn(required, source)
        self.assertNotIn("time.sleep(", source)
        self.assertNotIn("self.model.spin(", source)

    def test_collection_page_opens_wheel_from_full_collection(self):
        page_source = Path("ui/pages/collection_page.py").read_text(
            encoding="utf-8"
        )
        filter_source = Path(
            "ui/components/table_filters.py"
        ).read_text(encoding="utf-8")

        open_method = page_source.split(
            "def _open_collection_wheel(self):",
            1,
        )[1].split(
            "def _on_collection_wheel_closed(self):",
            1,
        )[0]
        for required in (
            "CollectionWheelModel",
            "CollectionWheelDialog",
            "self.collection_wheel_model.reload_planner_state()",
            "self.data_manager.get_all_hacks(include_obsolete=True)",
            "result_callback=self._focus_wheel_result",
        ):
            self.assertIn(required, page_source)
        self.assertNotIn("self.filtered_data", open_method)

        focus_method = page_source.split(
            "def _focus_wheel_result(self, hack_id):",
            1,
        )[1].split(
            "def _select_hack_in_tree(self, hack_id):",
            1,
        )[0]
        self.assertIn("self.filters.clear_filters()", focus_method)
        self.assertIn("self._select_hack_in_tree(hack_id)", focus_method)

        self.assertIn('text="Open Wheel"', filter_source)
        self.assertIn("self.wheel_callback", filter_source)
        self.assertNotIn("Random Hack", filter_source)
        self.assertNotIn("def _select_random_hack(", page_source)
        self.assertNotIn("random.choice(", page_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
