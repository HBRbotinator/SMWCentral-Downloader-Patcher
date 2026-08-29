import unittest
from pathlib import Path


class ModernRomProvenanceApplyUiContractTests(unittest.TestCase):
    def test_dialog_exposes_apply_only_after_saved_decision(self):
        source = Path("ui/collection_rom_modern_provenance_dialog.py").read_text(encoding="utf-8")
        self.assertIn('text="Apply Provenance Repair..."', source)
        self.assertIn('state="disabled"', source)
        self.assertIn('self._apply_button.configure(state="normal")', source)
        self.assertIn('self._saved_decision is not None', source)

    def test_collection_page_routes_apply_to_metadata_only_boundary(self):
        source = Path("ui/pages/collection_page.py").read_text(encoding="utf-8")
        self.assertIn("on_apply=self._apply_collection_modern_rom_provenance", source)
        self.assertIn("apply_modern_rom_provenance_decision", source)
        self.assertIn("Collection files[] metadata only", source)
        self.assertIn("ROM and save files are not moved", source)


if __name__ == "__main__":
    unittest.main()
