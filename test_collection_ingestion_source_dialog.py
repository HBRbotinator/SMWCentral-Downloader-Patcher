"""Source contracts for the Collection ingestion launch UI."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


_DIALOG = Path(__file__).parent / "ui" / "collection_ingestion_source_dialog.py"
_PAGE = Path(__file__).parent / "ui" / "pages" / "collection_page.py"


class CollectionIngestionSourceDialogContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dialog_source = _DIALOG.read_text(encoding="utf-8")
        cls.page_source = _PAGE.read_text(encoding="utf-8")
        cls.page_tree = ast.parse(cls.page_source)

    def test_source_dialog_exposes_both_real_input_types(self):
        self.assertIn("class CollectionIngestionSourceDialog:", self.dialog_source)
        self.assertIn("ROM folder (.sfc / .smc)", self.dialog_source)
        self.assertIn("GiganticBucket JSON export", self.dialog_source)
        self.assertIn("filedialog.askdirectory", self.dialog_source)
        self.assertIn("filedialog.askopenfilename", self.dialog_source)
        self.assertIn("Start Review", self.dialog_source)
        self.assertIn("KaizOFF is used automatically", self.dialog_source)

    def test_source_dialog_only_returns_validated_selection(self):
        self.assertIn("CollectionIngestionSourceSelection", self.dialog_source)
        self.assertIn(
            "validate_collection_ingestion_selection(selection)",
            self.dialog_source,
        )
        forbidden = (
            "HackDataManager",
            "KaizOffCatalogueProvider",
            "CollectionIdentityHintsStore",
            "create_collection_ingestion_session",
            "finalize_ingestion_session_plan",
            "apply_collection_change_plan",
            "processed.json",
            "config.json",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.dialog_source)

    def test_collection_page_exposes_import_entry_and_background_session_build(self):
        required = (
            'text="Import..."',
            "command=self._open_collection_import",
            "CollectionIngestionSourceDialog",
            "CollectionIngestionProgressDialog",
            "create_collection_ingestion_review_session",
            "CollectionIngestionReviewDialog",
            "threading.Thread",
            'name="collection-ingestion-review"',
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.page_source)

    def test_collection_page_still_cannot_finalize_or_apply_review(self):
        complete = next(
            node
            for node in ast.walk(self.page_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_collection_ingestion_review_complete"
        )
        text = ast.get_source_segment(self.page_source, complete)
        self.assertIn("dict(decisions)", text)
        self.assertIn("without applying changes", text)
        for forbidden in (
            "finalize_ingestion_session_plan",
            "fetch_required_catalogue_details",
            "apply_collection_change_plan",
            "CollectionIdentityHintsStore",
            "SaveSyncAssociationReferenceParticipant",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, text)
        self.assertIn("no Collection", text)
        self.assertIn("ROM files were changed", text)

    def test_worker_uses_queue_instead_of_touching_tk_from_worker(self):
        worker = next(
            node
            for node in ast.walk(self.page_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_collection_ingestion_worker"
        )
        text = ast.get_source_segment(self.page_source, worker)
        self.assertIn("self._collection_ingestion_result_queue.put", text)
        self.assertNotIn("self.frame.", text)
        self.assertNotIn("messagebox.", text)
        self.assertNotIn("Toplevel", text)
        self.assertIn("self.frame.after", self.page_source)
        self.assertIn("def _poll_collection_ingestion_worker(", self.page_source)

    def test_pending_collection_edits_block_new_review_snapshot(self):
        open_method = next(
            node
            for node in ast.walk(self.page_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_open_collection_import"
        )
        text = ast.get_source_segment(self.page_source, open_method)
        self.assertIn("self.data_manager.unsaved_changes", text)
        self.assertIn("stable Collection snapshot", text)
        self.assertNotIn("force_save", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
