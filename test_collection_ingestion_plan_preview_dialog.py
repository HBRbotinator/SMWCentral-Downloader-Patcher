"""Source contracts for the read-only finalized Collection plan preview UI."""
from __future__ import annotations

from pathlib import Path
import unittest


_DIALOG = Path(__file__).parent / "ui" / "collection_ingestion_plan_preview_dialog.py"
_PAGE = Path(__file__).parent / "ui" / "pages" / "collection_page.py"


class CollectionIngestionPlanPreviewDialogContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dialog_source = _DIALOG.read_text(encoding="utf-8")
        cls.page_source = _PAGE.read_text(encoding="utf-8")

    def test_preview_is_explicitly_final_read_only_plan_presentation(self):
        for required in (
            "class CollectionIngestionPlanPreviewDialog:",
            "CollectionIngestionPlanPreviewModel(plan)",
            "Final Collection Import Preview",
            "generated directly from the finalized immutable",
            "Nothing is applied from this preview",
            "Close Preview",
            "Transactional Apply is a later boundary",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.dialog_source)

    def test_review_continue_finalizes_on_worker_then_opens_preview(self):
        for required in (
            "def _collection_ingestion_review_complete(self, decisions):",
            'name="collection-ingestion-finalization"',
            "finalize_collection_ingestion_review_plan(",
            'self._collection_ingestion_result_queue.put(("plan-ready", plan))',
            "CollectionIngestionPlanPreviewDialog(",
            "nothing applied",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.page_source)

    def test_commit_010_ui_has_no_apply_call_or_confirmation(self):
        forbidden = (
            "apply_collection_change_plan",
            "recover_interrupted_collection_apply",
            "Apply Changes",
            "Confirm Apply",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.dialog_source)
                self.assertNotIn(value, self.page_source)

    def test_live_optional_planner_unsaved_state_is_guarded_without_importing_planner(self):
        self.assertIn("def _planner_has_unsaved_changes(self):", self.page_source)
        self.assertIn('getattr(layout, "planner_page", None)', self.page_source)
        self.assertIn("Planner changes are still unsaved", self.page_source)
        self.assertNotIn("from planner_store import", self.page_source)
        self.assertNotIn("from planner_page_model import", self.page_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
