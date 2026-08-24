from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
DIALOG = ROOT / "ui" / "collection_update_discovery_dialog.py"


class CollectionUpdateDiscoveryDialogContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = DIALOG.read_text(encoding="utf-8")

    def test_dialog_searches_only_frozen_discovery_state(self):
        self.assertIn("search_collection_update_catalogue", self.source)
        self.assertNotIn("KaizOffCatalogueProvider", self.source)
        self.assertNotIn("get_index(", self.source)
        self.assertNotIn("get_hack(", self.source)

    def test_dialog_has_no_apply_download_or_migration_boundary(self):
        forbidden = (
            "apply_collection_change_plan",
            "apply_collection_ingestion_plan",
            "finalize_ingestion_session_plan",
            "finalize_collection_ingestion_review_plan",
            "download_url",
            "patch_rom",
            "IdentityMigrationOperation",
        )
        for token in forbidden:
            self.assertNotIn(token, self.source)

    def test_dialog_warns_that_lineage_is_not_proven(self):
        self.assertIn("cannot prove that another submission is newer", self.source)
        self.assertIn("Nothing is downloaded or changed", self.source)


if __name__ == "__main__":
    unittest.main()
