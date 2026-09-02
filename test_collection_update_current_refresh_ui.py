from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
DISCOVERY = (ROOT / "ui" / "collection_update_discovery_dialog.py").read_text(encoding="utf-8")
PREVIEW = (ROOT / "ui" / "collection_update_current_refresh_dialog.py").read_text(encoding="utf-8")
PAGE = (ROOT / "ui" / "pages" / "collection_page.py").read_text(encoding="utf-8")


def _method_source(source, name):
    marker = f"    def {name}("
    start = source.index(marker)
    next_method = source.find("\n    def ", start + len(marker))
    return source[start:] if next_method < 0 else source[start:next_method]


class CurrentSubmissionRefreshUiContractTests(unittest.TestCase):
    def test_discovery_makes_same_id_update_primary_and_replacements_secondary(self):
        self.assertIn("Update this Collection entry", DISCOVERY)
        self.assertIn("Update This Entry...", DISCOVERY)
        self.assertIn("Other SMWC submissions", DISCOVERY)
        self.assertIn("This is not a replacement", DISCOVERY)
        self.assertIn("on_refresh_current", DISCOVERY)
        self.assertIn("select_possible_collection_replacement", DISCOVERY)
        self.assertNotIn("Refresh / Re-download Current...", DISCOVERY)
        self.assertNotIn("Search frozen KaizOFF Index:", DISCOVERY)

    def test_preview_is_a_guided_nontechnical_same_id_update(self):
        self.assertIn("Update SMWC information only", PREVIEW)
        self.assertIn(
            "Update SMWC information and download the ROM offered for this SMWC entry",
            PREVIEW,
        )
        self.assertIn("Default ROM Output Folder", PREVIEW)
        self.assertIn("Alongside my current primary ROM", PREVIEW)
        self.assertIn("Choose What Happens to the ROM...", PREVIEW)
        self.assertIn("Apply Update", PREVIEW)
        self.assertIn("Your Collection ID", PREVIEW)
        self.assertIn("personal Collection data", PREVIEW)
        self.assertNotIn("Prepared changes", PREVIEW)
        self.assertNotIn("Reviewed store preconditions", PREVIEW)
        self.assertNotIn("SMWC information via KaizOFF", PREVIEW)
        self.assertNotIn("apply_collection_change_plan", PREVIEW)

    def test_collection_page_supports_default_or_current_rom_download_location(self):
        method = _method_source(PAGE, "_collection_current_refresh_acquire_requested")
        self.assertIn("resolve_current_rom_download_directory", method)
        self.assertIn('config.get("output_dir", "")', method)
        self.assertIn("current_record", method)
        self.assertIn("destination", method)
        self.assertIn("ROM_DOWNLOAD_DESTINATION_ALONGSIDE_PRIMARY", method)
        self.assertNotIn("os.path.isdir(output_dir)", method)
        self.assertIn("Default ROM Output Folder", method)
        self.assertIn("alongside your current primary ROM", method)


    def test_update_preview_uses_pre_map_and_post_map_centering(self):
        preview_class = PREVIEW[PREVIEW.index("class CollectionCurrentRefreshPreviewDialog"):]
        show = _method_source(preview_class, "show")
        self.assertIn("self.win.withdraw()", show)
        self.assertIn("center_window_on_parent(self.win, self.parent)", show)
        self.assertIn("self.win.deiconify()", show)
        self.assertIn("self.win.after_idle", show)

    def test_collection_page_keeps_same_id_review_apply_boundaries(self):
        self.assertIn("on_refresh_current=self._collection_update_current_refresh_requested", PAGE)
        self.assertIn("finalize_current_submission_refresh_plan", PAGE)
        self.assertIn("acquire_current_submission_rom", PAGE)
        self.assertIn("apply_finalized_current_submission_refresh", PAGE)
        self.assertIn("build_current_rom_disposition_review", PAGE)
        self.assertIn("finalize_current_rom_disposition", PAGE)
        self.assertIn("same-ID current SMWC refresh", PAGE)


if __name__ == "__main__":
    unittest.main()
