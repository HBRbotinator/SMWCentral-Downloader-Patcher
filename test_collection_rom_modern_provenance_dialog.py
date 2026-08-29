import unittest
from pathlib import Path


class ModernRomProvenanceDialogContractTests(unittest.TestCase):
    def test_organization_audit_exposes_missing_provenance_review(self):
        source = Path("ui/collection_rom_organization_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Review Missing Provenance...", source)
        self.assertIn("on_review_missing_provenance", source)

    def test_review_dialog_is_explicit_and_apply_is_separate(self):
        source = Path("ui/collection_rom_modern_provenance_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Save Provenance Decisions", source)
        self.assertIn("already-recorded SMWC submission", source)
        self.assertIn("No provider lookup, hashing, Collection write", source)
        self.assertIn("Apply Provenance Repair...", source)
        self.assertIn('state="disabled"', source)
        self.assertNotIn("Preview", source)

    def test_collection_page_routes_review_and_explicit_apply(self):
        source = Path("ui/pages/collection_page.py").read_text(encoding="utf-8")
        self.assertIn("_review_collection_modern_rom_provenance", source)
        self.assertIn("_last_collection_modern_provenance_decision", source)
        self.assertIn("build_modern_rom_provenance_review", source)
        self.assertIn("on_review_missing_provenance", source)
        self.assertIn("_apply_collection_modern_rom_provenance", source)


if __name__ == "__main__":
    unittest.main()
