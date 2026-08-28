import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class HistoricalRomProvenanceDialogContractTests(unittest.TestCase):
    def test_organization_dialog_exposes_historical_review_only_when_available(self):
        source = (ROOT / "ui" / "collection_rom_organization_dialog.py").read_text(encoding="utf-8")
        self.assertIn('text="Review Historical Provenance..."', source)
        self.assertIn("audit.historical_provenance_count", source)

    def test_collection_page_fetches_only_recorded_historical_ids(self):
        source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(encoding="utf-8")
        self.assertIn("required_historical_submission_ids(audit)", source)
        self.assertIn("provider.get_hack(identifier)", source)
        self.assertIn("collection-rom-historical-provenance", source)
        self.assertIn("collection_revision_token(self.data_manager)", source)

    def test_review_dialog_has_no_apply_or_filesystem_mutation_action(self):
        path = ROOT / "ui" / "collection_rom_historical_provenance_dialog.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {"move", "rename", "replace", "remove", "unlink", "copy", "copy2", "mkdir", "makedirs"}
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name): called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute): called.add(node.func.attr)
        self.assertTrue(forbidden.isdisjoint(called), sorted(called))
        self.assertNotIn('text="Apply', source)
        self.assertNotIn('text="Apply', source)
        self.assertIn('text="Preview Historical Move Plan..."', source)
        self.assertIn("No Apply action exists in this review", source)

    def test_model_has_no_mutating_filesystem_calls(self):
        source = (ROOT / "collection_rom_historical_provenance.py").read_text(encoding="utf-8")
        for forbidden in (
            "os.makedirs(", "os.mkdir(", "os.rename(", "os.replace(", "os.remove(",
            "shutil.move(", "shutil.copy(", "shutil.copy2(", ".unlink(", ".write_bytes(", ".write_text(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
