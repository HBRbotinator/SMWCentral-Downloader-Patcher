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

    def test_user_facing_update_language_hides_internal_plan_and_provider_terms(self):
        self.assertIn('"Update SMWC information only"', self.source)
        self.assertIn('"Choose What Happens to the ROM..."', self.source)
        self.assertIn('text="Apply Update"', self.source)
        self.assertIn("Default ROM Output Folder", self.source)
        self.assertNotIn('"Download Current ROM..."', self.source)
        self.assertNotIn('"Choose ROM Handling..."', self.source)
        self.assertNotIn("Prepared changes", self.source)
        self.assertNotIn("Reviewed store preconditions", self.source)
        self.assertNotIn("SMWC information via KaizOFF", self.source)
        self.assertNotIn('title("Current SMWC Submission Refresh")', self.source)

    def test_preview_explains_same_identity_and_preserved_personal_data(self):
        self.assertIn("same SMWC ID", self.source)
        self.assertIn("does not replace it with another submission", self.source)
        self.assertIn("personal Collection data are preserved", self.source)

    def test_programmatic_close_is_not_blocked_by_busy_state(self):
        close_source = self._method_source("close")
        self.assertIn("if self._closed:", close_source)
        self.assertNotIn("self._closed or self._busy", close_source)
        self.assertNotIn("if self._busy", close_source)

    def test_async_callback_exceptions_restore_interactive_state(self):
        acquire = self._method_source("_request_acquire")
        apply_update = self._method_source("_request_apply")
        self.assertGreaterEqual(acquire.count("self.set_busy(False)"), 2)
        self.assertGreaterEqual(apply_update.count("self.set_busy(False)"), 2)

    def test_progress_titles_are_user_facing(self):
        self.assertIn(
            '"Refresh Current SMWC Submission": "Preparing Update"',
            self.source,
        )
        self.assertIn(
            '"Acquire Current SMWC ROM": "Downloading ROM"',
            self.source,
        )
        self.assertIn(
            '"Apply Current SMWC Refresh": "Applying Update"',
            self.source,
        )

    def test_download_choice_is_one_guided_continue_step(self):
        continue_method = self._method_source("_continue_initial_choice")
        self.assertIn('choice == "metadata_rom"', continue_method)
        self.assertIn("self._request_acquire()", continue_method)
        self.assertIn("self._request_apply()", continue_method)

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
