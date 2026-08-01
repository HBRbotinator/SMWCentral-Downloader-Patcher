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
    def test_optional_choice_normalizes_all_and_real_values(self):
        self.assertEqual(CollectionWheelDialog._optional_choice("All"), "")
        self.assertEqual(CollectionWheelDialog._optional_choice(""), "")
        self.assertEqual(
            CollectionWheelDialog._optional_choice("  Next  "),
            "Next",
        )

    def test_dialog_is_collection_owned_with_optional_planner_refinements(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        for required in (
            "The current Collection view owns the candidate pool.",
            "Planner choices below are optional refinements.",
            "No Planner refinements are configured.",
            "self.model.build_pool(",
            "self.model.spin(",
            "excluded_ids=excluded_ids",
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

    def test_collection_page_opens_dialog_from_current_filtered_view(self):
        page_source = Path("ui/pages/collection_page.py").read_text(
            encoding="utf-8"
        )
        filter_source = Path(
            "ui/components/table_filters.py"
        ).read_text(encoding="utf-8")
        for required in (
            "CollectionWheelModel",
            "CollectionWheelDialog",
            "self._open_collection_wheel",
            "collection_records=list(self.filtered_data)",
            "result_callback=self._focus_wheel_result",
            "def _focus_wheel_result(",
            "self._select_hack_in_tree(hack_id)",
        ):
            self.assertIn(required, page_source)
        self.assertIn('text="Open Wheel"', filter_source)
        self.assertIn("self.wheel_callback", filter_source)
        self.assertNotIn("Random Hack", filter_source)
        self.assertNotIn("def _select_random_hack(", page_source)
        self.assertNotIn("random.choice(", page_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
