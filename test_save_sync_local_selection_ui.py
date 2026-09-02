"""Source contracts for clearer existing-local selection in Save Data Sync."""
from pathlib import Path
import unittest


_DIALOG = Path(__file__).parent / "ui" / "save_sync_dialog.py"


class LocalSaveSelectionUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _DIALOG.read_text(encoding="utf-8")

    def test_existing_local_attach_requires_an_explicit_row_selection(self):
        self.assertIn("Choose the exact local Collection row below. Even a single ", self.source)
        self.assertIn("suggestion is not selected automatically.", self.source)
        self.assertIn('text="No existing local entry selected yet."', self.source)
        self.assertIn('text="Select a row above before continuing with Attach."', self.source)
        self.assertIn('mode == "attach" and bool(target)', self.source)
        self.assertIn('state="normal" if enabled else "disabled"', self.source)

    def test_selected_row_gets_visible_confirmation_without_auto_matching(self):
        self.assertIn('self.local_tree.tag_configure(', self.source)
        self.assertIn('"chosen", font=("Segoe UI", 9, "bold")', self.source)
        self.assertIn('tags=("chosen",) if iid in selected else ()', self.source)
        self.assertIn("Selected existing local entry:", self.source)
        self.assertIn("self.local_tree.focus(selected[0])", self.source)
        self.assertIn("self.local_tree.see(selected[0])", self.source)
        self.assertNotIn("self.local_tree.selection_set(self.local_tree.get_children()[0])", self.source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
