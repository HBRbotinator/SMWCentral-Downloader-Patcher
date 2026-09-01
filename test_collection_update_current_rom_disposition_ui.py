from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
PREVIEW = (ROOT / "ui" / "collection_update_current_refresh_dialog.py").read_text(encoding="utf-8")
DISPOSITION_UI = (ROOT / "ui" / "collection_update_current_rom_disposition_dialog.py").read_text(encoding="utf-8")
PAGE = (ROOT / "ui" / "pages" / "collection_page.py").read_text(encoding="utf-8")
REFRESH = (ROOT / "collection_update_current_refresh.py").read_text(encoding="utf-8")
APPLY = (ROOT / "collection_update_current_refresh_apply.py").read_text(encoding="utf-8")
STARTUP = (ROOT / "collection_startup_recovery.py").read_text(encoding="utf-8")
PLAN_APPLY = (ROOT / "collection_plan_apply.py").read_text(encoding="utf-8")
ORGANIZE_APPLY = (ROOT / "collection_rom_organization_apply.py").read_text(encoding="utf-8")


class CurrentRomDispositionUiContractTests(unittest.TestCase):
    def test_downloaded_rom_cannot_apply_before_explicit_handling_choice(self):
        self.assertIn('"Choose What Happens to the ROM..."', PREVIEW)
        self.assertIn("rom_disposition is None", PREVIEW)
        self.assertIn("replace your current primary ROM", PREVIEW)
        self.assertIn("keep both", PREVIEW)
        self.assertIn("unresolved_rom_choice", PREVIEW)

    def test_keep_both_primary_is_required_and_downloaded_is_only_a_ui_default(self):
        self.assertIn("Keep Both requires a primary choice", DISPOSITION_UI)
        self.assertIn("downloaded_default_primary_path", DISPOSITION_UI)
        self.assertIn("preselected as a convenience", DISPOSITION_UI)
        self.assertIn("not a version-ordering inference", DISPOSITION_UI)
        self.assertNotIn("higher ID", DISPOSITION_UI)
        self.assertNotIn("newer version", DISPOSITION_UI)

    def test_rom_disposition_copy_explains_separate_storage_locations(self):
        self.assertIn("keep its existing filename and location", DISPOSITION_UI)
        self.assertIn("Default ROM Output Folder", DISPOSITION_UI)
        self.assertIn("Existing Collection ROMs can be stored elsewhere", DISPOSITION_UI)
        self.assertIn("Which ROM should open by default", DISPOSITION_UI)

    def test_page_routes_rom_choice_through_read_only_review_then_finalization(self):
        self.assertIn("build_current_rom_disposition_review", PAGE)
        self.assertIn("finalize_current_rom_disposition", PAGE)
        self.assertIn("CollectionCurrentRomDispositionDialog", PAGE)
        self.assertIn("on_review_rom=self._collection_current_refresh_rom_disposition_requested", PAGE)

    def test_replace_is_frozen_into_plan_and_apply_has_dedicated_transaction(self):
        self.assertIn("CurrentRomReplacementPrecondition", REFRESH)
        self.assertIn("CurrentRomDisposition.REPLACE_CURRENT", APPLY)
        self.assertIn("apply_current_rom_replacement", APPLY)
        self.assertIn("Downloaded current ROM requires an explicit", APPLY)

    def test_current_rom_journal_participates_in_startup_and_cross_transaction_guards(self):
        self.assertIn("inspect_interrupted_current_rom_replacement", STARTUP)
        self.assertIn("recover_interrupted_current_rom_replacement", STARTUP)
        self.assertIn("current_rom_info", STARTUP)
        self.assertIn(".collection-current-rom-replace.journal.json", PLAN_APPLY)
        self.assertIn(".collection-current-rom-replace.journal.json", ORGANIZE_APPLY)


if __name__ == "__main__":
    unittest.main()
