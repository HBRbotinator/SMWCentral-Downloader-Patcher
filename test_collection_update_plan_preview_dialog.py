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

    def test_target_rom_acquisition_is_explicit_and_apply_remains_network_free(self):
        self.assertIn("Acquire Target ROM...", self.source)
        self.assertIn("If you later close/cancel", self.source)
        self.assertIn("Existing files are never overwritten", self.source)
        self.assertIn("Apply Replacement...", self.source)
        self.assertIn("Apply SMWC Replacement", self.source)
        self.assertIn("No target ROM will be downloaded or patched during Apply", self.source)
        self.assertIn("performs no network or patching work", self.source)
        self.assertIn("keep the SMWC submission provenance", self.source)

    def test_preview_only_delegates_apply_and_contains_no_transaction_engine(self):
        self.assertIn("on_apply", self.source)
        self.assertIn("set_applying", self.source)
        forbidden = (
            "apply_collection_change_plan",
            "apply_finalized_collection_update",
            "recover_interrupted_collection_apply",
            "patch_rom",
            "os.replace(",
            "shutil.move(",
        )
        for token in forbidden:
            self.assertNotIn(token, self.source)


if __name__ == "__main__":
    unittest.main()
