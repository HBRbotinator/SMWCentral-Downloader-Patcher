from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
COLLECTION_PAGE = ROOT / "ui" / "pages" / "collection_page.py"


class CollectionUpdateMergeReviewWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = COLLECTION_PAGE.read_text(encoding="utf-8")
        start = cls.source.index("    def _collection_update_candidate_selected")
        end = cls.source.index("    def _start_collection_update_plan_preview", start)
        cls.merge_wiring = cls.source[start:end]

    def test_existing_target_routes_to_merge_review_instead_of_plan(self):
        self.assertIn("selection.target_already_in_collection", self.merge_wiring)
        self.assertIn("_prepare_collection_update_existing_target_merge_review(selection)", self.merge_wiring)
        self.assertIn("build_collection_update_existing_target_merge_review", self.merge_wiring)
        self.assertIn("CollectionUpdateMergeReviewDialog", self.merge_wiring)

    def test_review_decision_feeds_the_next_read_only_plan_boundary(self):
        self.assertIn("_last_collection_update_merge_decision = decision", self.merge_wiring)
        self.assertIn("preparing immutable preview", self.merge_wiring)
        self.assertIn("merge_review=review", self.merge_wiring)
        self.assertIn("merge_decision=decision", self.merge_wiring)

    def test_merge_review_wiring_still_has_no_direct_provider_or_apply(self):
        forbidden = (
            "KaizOffCatalogueProvider",
            "get_hack(",
            "finalize_collection_change_plan",
            "apply_collection_change_plan",
            "recover_interrupted_collection_apply",
        )
        for token in forbidden:
            self.assertNotIn(token, self.merge_wiring)


if __name__ == "__main__":
    unittest.main()
