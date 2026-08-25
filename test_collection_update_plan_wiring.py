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

    def test_existing_target_is_routed_through_merge_review_then_merge_plan(self):
        self.assertIn("selection.target_already_in_collection", self.update_plan_wiring)
        self.assertIn("_prepare_collection_update_existing_target_merge_review(selection)", self.update_plan_wiring)
        self.assertIn("build_collection_update_existing_target_merge_review", self.update_plan_wiring)
        self.assertIn("merge_review=review", self.update_plan_wiring)
        self.assertIn("merge_decision=decision", self.update_plan_wiring)
        self.assertIn(
            "finalize_collection_update_existing_target_selection_plan",
            self.update_plan_wiring,
        )

    def test_unsaved_collection_or_planner_state_blocks_plan_finalization(self):
        self.assertIn("_collection_update_state_is_saved", self.update_plan_wiring)
        self.assertIn("unsaved_changes", self.update_plan_wiring)
        self.assertIn("_planner_has_unsaved_changes()", self.update_plan_wiring)

    def test_finalized_preview_exposes_explicit_transactional_apply(self):
        self.assertIn("on_apply=self._collection_update_apply_requested", self.update_plan_wiring)
        self.assertIn("apply_finalized_collection_update", self.update_plan_wiring)
        self.assertIn("collection_update_apply_recovery_pending", self.update_plan_wiring)
        self.assertIn("recover_collection_update_apply", self.update_plan_wiring)
        self.assertIn("self.frame.after(1, self._execute_collection_update_apply)", self.update_plan_wiring)

    def test_replacement_apply_does_not_redo_discovery_hydration_or_rom_acquisition(self):
        apply_start = self.update_plan_wiring.index("    def _collection_update_apply_requested")
        apply_source = self.update_plan_wiring[apply_start:]
        forbidden = (
            "KaizOffCatalogueProvider",
            "get_hack(",
            "build_collection_update_discovery",
            "finalize_collection_update_selection_plan",
            "finalize_collection_update_existing_target_selection_plan",
            "patch_rom",
            "download_and_patch",
            "download_url",
            "shutil.move(",
            "os.remove(",
            "threading.Thread",
        )
        for token in forbidden:
            self.assertNotIn(token, apply_source)


if __name__ == "__main__":
    unittest.main()
