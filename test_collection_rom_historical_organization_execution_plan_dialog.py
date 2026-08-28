import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


class HistoricalExecutionPlanDialogContractTests(unittest.TestCase):
    def test_historical_plan_dialog_enables_final_preview_only_after_save_decision(self):
        source = (ROOT / "ui" / "collection_rom_historical_organization_plan_dialog.py").read_text(encoding="utf-8")
        self.assertIn('text="Preview Final Execution Plan..."', source)
        self.assertIn('state="disabled"', source)
        self.assertIn('configure(state="normal")', source)
        self.assertNotIn('text="Apply', source)

    def test_collection_page_routes_historical_final_preview(self):
        source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(encoding="utf-8")
        self.assertIn("build_historical_rom_organization_execution_plan(", source)
        self.assertIn("HistoricalRomOrganizationExecutionPlanDialog(", source)
        self.assertIn("_last_collection_historical_rom_save_disposition_decision != decision", source)

    def test_final_dialog_has_no_mutating_or_apply_action(self):
        path = ROOT / "ui" / "collection_rom_historical_organization_execution_plan_dialog.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)
        forbidden = {"move", "rename", "replace", "remove", "unlink", "copy", "copy2", "mkdir", "makedirs"}
        self.assertTrue(forbidden.isdisjoint(called), sorted(called))
        self.assertNotIn('text="Apply', source)
        self.assertIn("No filesystem or Collection Apply action", source)


if __name__ == "__main__":
    unittest.main()
