"""Source contracts for Commit 011 final preview, confirmation, Apply and reload UI."""
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

    def test_preview_still_presents_the_exact_finalized_plan_before_apply(self):
        for required in (
            "class CollectionIngestionPlanPreviewDialog:",
            "CollectionIngestionPlanPreviewModel(plan)",
            "Final Collection Import Preview",
            "generated directly from the finalized immutable",
            "these exact planned changes",
            "Close Preview",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.dialog_source)

    def test_preview_requires_explicit_warning_confirmation_before_apply_callback(self):
        for required in (
            'text="Apply Import..."',
            "def _request_apply(self):",
            "messagebox.askyesno(",
            '"Apply Collection Import"',
            'icon="warning"',
            "Apply exactly the finalized changes shown in this preview?",
            "accepted = bool(self.on_apply())",
            "self.set_applying(True)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.dialog_source)

    def test_apply_is_serialized_on_tk_thread_and_uses_final_plan_only(self):
        for required in (
            "def _collection_ingestion_apply_requested(self):",
            "self.frame.after(1, self._execute_collection_ingestion_apply)",
            "def _execute_collection_ingestion_apply(self):",
            "apply_collection_ingestion_plan(",
            "plan,",
            "manager=self.data_manager",
            "CollectionPlanStaleStateError",
            "CollectionPlanRecoveryError",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.page_source)
        self.assertNotIn('name="collection-ingestion-apply"', self.page_source)

    def test_success_reloads_collection_config_save_sync_and_optional_planner(self):
        for required in (
            "def _reload_collection_ingestion_live_state(self):",
            "self.data_manager.reload_data()",
            "self.config_manager.reload()",
            'getattr(layout, "setup_section", None)',
            "setup_config.reload()",
            'getattr(layout, "settings_page", None)',
            "settings_page._load_save_sync_settings()",
            'getattr(layout, "planner_page", None)',
            "planner_page.refresh(reload_planner=True)",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.page_source)

    def test_recovery_requires_user_confirmation_that_other_instances_are_closed(self):
        for required in (
            "def _collection_ingestion_recovery_required(self, error):",
            '"Collection Import Recovery Required"',
            "Close every other SMWC Downloader & Patcher instance first",
            "choose Yes after you have confirmed no other instance is applying",
            "def _run_collection_ingestion_recovery(self):",
            "recover_collection_ingestion_apply(",
            "Start a new Collection import review",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.page_source)

    def test_live_optional_planner_unsaved_state_is_guarded_without_importing_planner(self):
        self.assertIn("def _planner_has_unsaved_changes(self):", self.page_source)
        self.assertIn('getattr(layout, "planner_page", None)', self.page_source)
        self.assertIn("Planner changes are still unsaved", self.page_source)
        self.assertNotIn("from planner_store import", self.page_source)
        self.assertNotIn("from planner_page_model import", self.page_source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
