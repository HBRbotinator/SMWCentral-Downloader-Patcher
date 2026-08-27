import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class CollectionRomOrganizationExecutionPlanDialogContractTests(unittest.TestCase):
    def test_final_preview_is_read_only_and_has_no_apply_action(self):
        path = ROOT / "ui" / "collection_rom_organization_execution_plan_dialog.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        forbidden_names = {
            "move",
            "rename",
            "replace",
            "remove",
            "unlink",
            "copy",
            "copy2",
            "makedirs",
            "mkdir",
        }
        called = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Name):
                called.add(func.id)
            elif isinstance(func, ast.Attribute):
                called.add(func.attr)
        self.assertTrue(forbidden_names.isdisjoint(called), sorted(called))
        self.assertNotIn('text="Apply', source)
        self.assertNotIn('text="Execute', source)
        self.assertIn("Read-only final execution preview", source)
        self.assertIn('text="Close"', source)

    def test_reviewed_plan_dialog_enables_only_final_preview_after_dispositions(self):
        source = (ROOT / "ui" / "collection_rom_organization_plan_dialog.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="Preview Final Execution Plan..."', source)
        self.assertIn('state="disabled"', source)
        self.assertIn("decision.approved_move_count > 0", source)
        self.assertNotIn('text="Apply', source)
        self.assertNotIn('text="Execute', source)

    def test_collection_page_revalidates_against_live_collection_revision(self):
        source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("build_collection_rom_organization_execution_plan(", source)
        self.assertIn("current_collection_revision_token=collection_revision_token", source)
        self.assertIn("CollectionRomOrganizationExecutionPlanDialog", source)

    def test_final_plan_model_contains_no_mutating_filesystem_calls(self):
        source = (ROOT / "collection_rom_organization_execution_plan.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "os.makedirs(",
            "os.mkdir(",
            "os.rename(",
            "os.replace(",
            "os.remove(",
            "shutil.move(",
            "shutil.copy(",
            "shutil.copy2(",
            ".unlink(",
            ".write_bytes(",
            ".write_text(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
