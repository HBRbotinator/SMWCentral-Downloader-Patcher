from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
DIALOG = ROOT / "ui" / "collection_update_merge_review_dialog.py"


class CollectionUpdateMergeReviewDialogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DIALOG.read_text(encoding="utf-8")

    def test_dialog_is_explicitly_review_only(self):
        self.assertIn("does not hydrate KaizOFF", self.source)
        self.assertIn("does not", self.source)
        self.assertIn("build a change plan", self.source)
        self.assertIn("Nothing is applied", self.source)

    def test_dialog_requires_explicit_source_target_choices(self):
        self.assertIn("Keep source", self.source)
        self.assertIn("Keep target", self.source)
        self.assertIn("Save Merge Review", self.source)
        self.assertIn("Primary ROM after merge", self.source)

    def test_unsupported_conflicts_disable_save(self):
        self.assertIn("Cannot safely merge yet", self.source)
        self.assertIn('save.state(["disabled"])', self.source)

    def test_dialog_has_no_plan_apply_or_network_boundary(self):
        forbidden = (
            "KaizOffCatalogueProvider",
            "get_hack(",
            "finalize_collection_change_plan",
            "finalize_collection_update_selection_plan",
            "apply_collection_change_plan",
            "recover_interrupted_collection_apply",
            "download_url",
            "patch_rom",
            "os.replace(",
            "shutil.move(",
        )
        for token in forbidden:
            self.assertNotIn(token, self.source)


if __name__ == "__main__":
    unittest.main()
