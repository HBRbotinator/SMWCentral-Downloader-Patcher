import unittest
from pathlib import Path


class ReviewedLegacyRomMetadataPlanDialogContractTests(unittest.TestCase):
    def test_provenance_dialog_exposes_preview_only_after_saved_decision(self):
        source = Path("ui/collection_rom_legacy_provenance_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Preview Modernization Plan...", source)
        self.assertIn('state="disabled"', source)
        self.assertIn('_preview_button.configure(state="normal")', source)
        self.assertIn("_saved_decision", source)

    def test_reviewed_plan_dialog_is_read_only_and_shows_selected_provenance(self):
        source = Path("ui/collection_rom_legacy_provenance_plan_dialog.py").read_text(encoding="utf-8")
        self.assertIn("Selected ROM Provenance", source)
        self.assertIn("No Apply action exists", source)
        self.assertNotIn("Apply Metadata Backfill", source)
        self.assertNotIn("on_apply", source)

    def test_collection_page_routes_review_and_decision_into_dedicated_plan(self):
        source = Path("ui/pages/collection_page.py").read_text(encoding="utf-8")
        self.assertIn("build_reviewed_legacy_rom_metadata_modernization_plan", source)
        self.assertIn("_preview_collection_legacy_rom_provenance_plan", source)
        self.assertIn("CollectionRomLegacyProvenancePlanDialog", source)
        self.assertIn("_last_collection_legacy_provenance_decision != decision", source)


if __name__ == "__main__":
    unittest.main()
