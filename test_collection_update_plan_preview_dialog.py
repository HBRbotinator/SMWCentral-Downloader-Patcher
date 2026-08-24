from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
DIALOG = ROOT / "ui" / "collection_update_plan_preview_dialog.py"


class CollectionUpdatePlanPreviewDialogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DIALOG.read_text(encoding="utf-8")

    def test_preview_is_built_from_the_finalized_immutable_plan(self):
        self.assertIn("CollectionIngestionPlanPreviewModel", self.source)
        self.assertIn("FinalizedCollectionUpdatePlan", self.source)
        self.assertIn("self.model.rows()", self.source)

    def test_preview_keeps_lineage_language_explicitly_non_authoritative(self):
        self.assertIn("does not claim that the target submission is newer", self.source)
        self.assertIn("your explicit confirmation", self.source)

    def test_preview_explicitly_says_no_target_rom_was_acquired(self):
        self.assertIn("does not download or patch the target ROM", self.source)
        self.assertIn("Existing ROMs remain ", self.source)
        self.assertIn("attached; no ROM/save files", self.source)
        self.assertIn("no ROM/save files are moved, renamed, or deleted", self.source)

    def test_commit_014_dialog_has_no_apply_boundary(self):
        self.assertIn("Commit 014 is preview-only", self.source)
        self.assertNotIn("Apply Import", self.source)
        self.assertNotIn("Apply Replacement", self.source)
        forbidden = (
            "apply_collection_change_plan",
            "apply_collection_ingestion_plan",
            "recover_interrupted_collection_apply",
            "patch_rom",
            "download_url",
            "os.replace(",
            "shutil.move(",
        )
        for token in forbidden:
            self.assertNotIn(token, self.source)


if __name__ == "__main__":
    unittest.main()
