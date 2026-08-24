from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent
COLLECTION_PAGE = ROOT / "ui" / "pages" / "collection_page.py"


class CollectionUpdateDiscoveryWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = COLLECTION_PAGE.read_text(encoding="utf-8")
        start = cls.source.index("    def _open_collection_update_discovery")
        end = cls.source.index("    def _collection_update_candidate_selected", start)
        cls.discovery_wiring = cls.source[start:end]

    def test_collection_exposes_explicit_find_update_action(self):
        self.assertIn('text="Find Update..."', self.source)
        self.assertIn("command=self._open_collection_update_discovery", self.source)

    def test_discovery_requires_existing_numeric_smwc_identity(self):
        self.assertIn("source_key.isdigit()", self.discovery_wiring)
        self.assertIn("Local usr_* entries", self.discovery_wiring)

    def test_explicit_check_prefers_current_index_but_accepts_provider_stale_fallback(self):
        self.assertIn("get_index(force_refresh=True)", self.discovery_wiring)
        self.assertIn("validated stale cache", self.discovery_wiring)

    def test_discovery_freezes_record_before_background_provider_work(self):
        self.assertIn("frozen_record = copy.deepcopy(source_record)", self.discovery_wiring)
        self.assertIn("threading.Thread(target=worker, daemon=True).start()", self.discovery_wiring)

    def test_discovery_itself_still_does_not_hydrate_or_apply(self):
        forbidden = (
            "finalize_collection_update_selection_plan",
            "apply_collection_change_plan",
            "apply_collection_ingestion_plan",
            "get_hack(",
            "patch_rom",
            "os.replace(",
            "os.remove(",
        )
        for token in forbidden:
            self.assertNotIn(token, self.discovery_wiring)


if __name__ == "__main__":
    unittest.main()
