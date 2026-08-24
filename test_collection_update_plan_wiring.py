from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
COLLECTION_PAGE = ROOT / "ui" / "pages" / "collection_page.py"


class CollectionUpdatePlanWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = COLLECTION_PAGE.read_text(encoding="utf-8")
        start = cls.source.index("    def _collection_update_candidate_selected")
        end = cls.source.index("    def _open_collection_import", start)
        cls.update_plan_wiring = cls.source[start:end]

    def test_explicit_selection_starts_rich_detail_plan_finalization(self):
        self.assertIn("_start_collection_update_plan_preview(selection)", self.update_plan_wiring)
        self.assertIn("finalize_collection_update_selection_plan", self.update_plan_wiring)
        self.assertIn("force_detail_refresh=True", self.update_plan_wiring)
        self.assertIn("collection-update-plan-preview", self.update_plan_wiring)

    def test_existing_target_is_blocked_for_explicit_merge_review(self):
        self.assertIn("selection.target_already_in_collection", self.update_plan_wiring)
        self.assertIn("Existing Replacement Target Needs Merge Review", self.update_plan_wiring)
        self.assertIn("explicit review of conflicting user-owned state", self.update_plan_wiring)

    def test_unsaved_collection_or_planner_state_blocks_plan_finalization(self):
        self.assertIn("_collection_update_state_is_saved", self.update_plan_wiring)
        self.assertIn("unsaved_changes", self.update_plan_wiring)
        self.assertIn("_planner_has_unsaved_changes()", self.update_plan_wiring)

    def test_plan_preview_remains_read_only(self):
        self.assertIn("read-only preview", self.update_plan_wiring)
        forbidden = (
            "apply_collection_update",
            "apply_collection_change_plan",
            "apply_collection_ingestion_plan",
            "recover_interrupted_collection_apply",
            "patch_rom",
            "download_and_patch",
            "os.replace(",
            "os.remove(",
        )
        for token in forbidden:
            self.assertNotIn(token, self.update_plan_wiring)


if __name__ == "__main__":
    unittest.main()
