import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class HistoricalRomOrganizationPlanDialogContractTests(unittest.TestCase):
    def test_historical_review_exposes_preview_only_when_ready(self):
        source = (
            ROOT / "ui" / "collection_rom_historical_provenance_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertIn('text="Preview Historical Move Plan..."', source)
        self.assertIn("self.review.ready_count", source)
        self.assertIn("self._on_preview_plan(self.review)", source)

    def test_collection_page_builds_plan_from_live_collection_revision(self):
        source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(encoding="utf-8")
        self.assertIn("build_historical_rom_organization_plan(", source)
        self.assertIn("collection_revision_token(self.data_manager)", source)
        self.assertIn("copy.deepcopy(self.data_manager.data)", source)
        self.assertIn("CollectionRomHistoricalOrganizationPlanDialog(", source)

    def test_plan_dialog_has_no_save_review_execution_or_apply_action(self):
        path = ROOT / "ui" / "collection_rom_historical_organization_plan_dialog.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden = {
            "move", "rename", "replace", "remove", "unlink",
            "copy", "copy2", "mkdir", "makedirs",
        }
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)
        self.assertTrue(forbidden.isdisjoint(called), sorted(called))
        self.assertNotIn('text="Apply', source)
        self.assertNotIn("Review Save", source)
        self.assertNotIn("Final Execution", source)
        self.assertIn("No save review, final execution plan, or Apply action", source)

    def test_plan_model_has_no_mutating_filesystem_calls(self):
        source = (
            ROOT / "collection_rom_historical_organization_plan.py"
        ).read_text(encoding="utf-8")
        for forbidden in (
            "os.makedirs(", "os.mkdir(", "os.rename(", "os.replace(", "os.remove(",
            "shutil.move(", "shutil.copy(", "shutil.copy2(", ".unlink(",
            ".write_bytes(", ".write_text(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
