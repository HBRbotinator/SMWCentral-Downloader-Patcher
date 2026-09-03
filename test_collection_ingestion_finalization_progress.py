"""Source contracts for the user-facing Collection finalization progress window."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).parent
_PROGRESS = ROOT / "ui" / "collection_ingestion_finalization_progress_dialog.py"
_PAGE = ROOT / "ui" / "pages" / "collection_page.py"


class CollectionIngestionFinalizationProgressContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.progress_source = _PROGRESS.read_text(encoding="utf-8")
        cls.page_source = _PAGE.read_text(encoding="utf-8")
        cls.progress_tree = ast.parse(cls.progress_source)
        cls.page_tree = ast.parse(cls.page_source)

    def test_finalization_window_is_hidden_until_shared_reveal(self):
        self.assertIn("self.win.withdraw()", self.progress_source)
        self.assertIn("reveal_window_on_parent(self.win, self.parent, grab=True)", self.progress_source)
        self.assertLess(self.progress_source.index("self.win.withdraw()"),
                        self.progress_source.index("reveal_window_on_parent(self.win"))
        # Behavioral sizing/mapping/idle checks live in the shared positioning tests.


    def test_progress_copy_explains_user_task_not_provider_internals(self):
        self.assertIn("Preparing your final Collection preview", self.progress_source)
        self.assertIn("Checking your reviewed choices", self.progress_source)
        self.assertIn("Your Collection is not changed", self.progress_source)
        self.assertIn("during this step.", self.progress_source)
        for forbidden in ("Rich KaizOFF", "rich KaizOFF", "API", "immutable change plan", "store state"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.progress_source)

    def test_collection_page_uses_the_centered_finalization_progress_dialog(self):
        begin = next(
            node
            for node in ast.walk(self.page_tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_begin_collection_ingestion_finalization"
        )
        text = ast.get_source_segment(self.page_source, begin)
        self.assertIn("ui.collection_ingestion_finalization_progress_dialog", text)
        self.assertIn("CollectionIngestionFinalizationProgressDialog(parent)", text)
        self.assertNotIn("ui.collection_ingestion_plan_preview_dialog", text)
        self.assertNotIn("apply_collection_change_plan", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
