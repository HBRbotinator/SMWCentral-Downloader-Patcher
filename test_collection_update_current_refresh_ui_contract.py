from __future__ import annotations

import ast
from pathlib import Path
import unittest


SOURCE = Path(__file__).resolve().parent / "ui" / "collection_update_current_refresh_dialog.py"


class CurrentRefreshUiContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_user_facing_update_language_replaces_acquire_refresh_buttons(self):
        self.assertIn('"Download Current ROM..."', self.source)
        self.assertIn('"Apply Update..."', self.source)
        self.assertIn('"Choose ROM Handling..."', self.source)
        self.assertIn('"Update Current Entry"', self.source)
        self.assertNotIn('"Acquire Current ROM..."', self.source)
        self.assertNotIn('"Apply Current Refresh..."', self.source)
        self.assertNotIn('title("Current SMWC Submission Refresh")', self.source)

    def test_preview_explains_same_identity_and_preserved_personal_data(self):
        self.assertIn("The Collection ID stays the same", self.source)
        self.assertIn("personal Collection data is preserved", self.source)
        self.assertIn("It does not replace the entry with another submission", self.source)

    def test_programmatic_close_is_not_blocked_by_busy_state(self):
        preview = next(
            node for node in self.tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "CollectionCurrentRefreshPreviewDialog"
        )
        close = next(
            node for node in preview.body
            if isinstance(node, ast.FunctionDef) and node.name == "close"
        )
        close_source = ast.get_source_segment(self.source, close) or ""
        self.assertIn("if self._closed:", close_source)
        self.assertNotIn("self._closed or self._busy", close_source)
        self.assertNotIn("if self._busy", close_source)

    def test_async_callback_exceptions_restore_interactive_state(self):
        acquire = self._method_source("_request_acquire")
        apply_update = self._method_source("_request_apply")
        self.assertGreaterEqual(acquire.count("self.set_busy(False)"), 2)
        self.assertGreaterEqual(apply_update.count("self.set_busy(False)"), 2)

    def test_progress_titles_hide_internal_refresh_acquire_apply_terms(self):
        self.assertIn(
            '"Refresh Current SMWC Submission": "Update Current Entry"',
            self.source,
        )
        self.assertIn(
            '"Acquire Current SMWC ROM": "Download Current ROM"',
            self.source,
        )
        self.assertIn(
            '"Apply Current SMWC Refresh": "Apply Update"',
            self.source,
        )

    def _method_source(self, name):
        preview = next(
            node for node in self.tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "CollectionCurrentRefreshPreviewDialog"
        )
        method = next(
            node for node in preview.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )
        return ast.get_source_segment(self.source, method) or ""


if __name__ == "__main__":
    unittest.main()
