import unittest
from pathlib import Path


class LegacyRomProvenanceDialogContractTests(unittest.TestCase):
    def test_legacy_audit_dialog_exposes_provenance_review_without_write_action(self):
        source = Path("ui/collection_rom_legacy_metadata_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Review Provenance...", source)
        self.assertIn("on_review_provenance", source)

    def test_provenance_dialog_is_explicit_and_read_only(self):
        source = Path("ui/collection_rom_legacy_provenance_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Save Provenance Decisions", source)
        self.assertIn("does not infer the answer", source)
        self.assertIn("Collection metadata and ROM files", source)
        self.assertNotIn("Apply", source)
        self.assertNotIn("KaizOFF", source.split("does not infer the answer")[0])

    def test_collection_page_routes_detached_decision_only(self):
        source = Path("ui/pages/collection_page.py").read_text(encoding="utf-8")
        self.assertIn("_review_collection_legacy_rom_provenance", source)
        self.assertIn("_last_collection_legacy_provenance_decision", source)
        self.assertIn("build_legacy_rom_provenance_review", source)


if __name__ == "__main__":
    unittest.main()
