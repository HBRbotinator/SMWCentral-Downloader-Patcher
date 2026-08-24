"""Source contracts for the non-persisting Collection ingestion review dialog."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


_DIALOG = Path(__file__).parent / "ui" / "collection_ingestion_review_dialog.py"


class CollectionIngestionReviewDialogContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _DIALOG.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_dialog_is_real_tk_review_ui(self):
        self.assertIn("class CollectionIngestionReviewDialog:", self.source)
        self.assertIn('self.win.title("Review Collection Import")', self.source)
        self.assertIn("ttk.Treeview", self.source)
        self.assertIn("Review Remaining", self.source)
        self.assertIn("Save Decision", self.source)
        self.assertIn("Continue", self.source)

    def test_dialog_exposes_all_blocking_decision_families(self):
        required = (
            "ReviewAction.USE_TARGET",
            "ReviewAction.IMPORT_LOCAL",
            "ReviewAction.CONFIRM_MIGRATION",
            "ReviewAction.KEEP_SEPARATE",
            "ReviewAction.SKIP",
            "ReviewAction.IGNORE",
            "RomSelectionDecision",
            "UserFieldResolution",
            "FirstClearDecision",
            "RememberedAssociationDecision",
        )
        for value in required:
            with self.subTest(value=value):
                self.assertIn(value, self.source)

    def test_catalogue_search_is_session_local_not_network_or_provider_access(self):
        self.assertIn("self.model.search_catalogue", self.source)
        self.assertIn("frozen KaizOFF Index", self.source)
        forbidden = (
            "KaizOffCatalogueProvider",
            "requests.",
            "urllib",
            "urlopen",
            "get_hack(",
            "get_index(",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.source)

    def test_dialog_cannot_apply_or_persist_collection_state(self):
        forbidden = (
            "HackDataManager",
            "CollectionIdentityHintsStore",
            "apply_collection_change_plan",
            "finalize_ingestion_session_plan",
            "collection_plan_apply",
            "collection_transaction",
            "processed.json",
            "config.json",
            "save_sync_reference_participant",
            "filedialog",
        )
        for value in forbidden:
            with self.subTest(value=value):
                self.assertNotIn(value, self.source)
        self.assertIn("Nothing is ", self.source)
        self.assertIn("written from this dialog.", self.source)

    def test_completion_callback_receives_only_detached_review_decisions(self):
        complete = next(
            node
            for node in ast.walk(self.tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_complete"
        )
        text = ast.get_source_segment(self.source, complete)
        self.assertIn("decisions = self.model.decisions", text)
        self.assertIn("self.on_complete(decisions)", text)
        self.assertNotIn("finalize", text)
        self.assertNotIn("apply", text)

    def test_dialog_keeps_rom_ignore_path_hash_semantics(self):
        self.assertIn("IgnoredRomDecision(path=path, sha256=by_path[path].sha256)", self.source)
        self.assertIn('(\"Keep\", \"Ignore\", \"Leave out\")', self.source)
        self.assertIn("Primary", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
