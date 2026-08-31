from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
DISCOVERY = (ROOT / "ui" / "collection_update_discovery_dialog.py").read_text(encoding="utf-8")
PREVIEW = (ROOT / "ui" / "collection_update_current_refresh_dialog.py").read_text(encoding="utf-8")
PAGE = (ROOT / "ui" / "pages" / "collection_page.py").read_text(encoding="utf-8")


class CurrentSubmissionRefreshUiContractTests(unittest.TestCase):
    def test_discovery_exposes_same_id_refresh_separately_from_replacement(self):
        self.assertIn("Refresh / Re-download Current...", DISCOVERY)
        self.assertIn("This is not a replacement", DISCOVERY)
        self.assertIn("on_refresh_current", DISCOVERY)
        self.assertIn("select_possible_collection_replacement", DISCOVERY)

    def test_preview_keeps_same_identity_and_separates_network_from_apply(self):
        self.assertIn("This updates the existing Collection entry for this same SMWC ID", PREVIEW)
        self.assertIn("Download Current ROM...", PREVIEW)
        self.assertIn("Apply Update...", PREVIEW)
        self.assertIn("The ROM is prepared before anything is applied to Collection", PREVIEW)
        self.assertIn("Your Collection ID and personal Collection data are preserved", PREVIEW)
        self.assertNotIn("apply_collection_change_plan", PREVIEW)

    def test_collection_page_wires_same_id_plan_acquisition_and_apply(self):
        self.assertIn("on_refresh_current=self._collection_update_current_refresh_requested", PAGE)
        self.assertIn("finalize_current_submission_refresh_plan", PAGE)
        self.assertIn("acquire_current_submission_rom", PAGE)
        self.assertIn("apply_finalized_current_submission_refresh", PAGE)
        self.assertIn("same-ID current SMWC refresh", PAGE)


if __name__ == "__main__":
    unittest.main()
