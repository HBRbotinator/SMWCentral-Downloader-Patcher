import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class CollectionRomOrganizationPlanDialogContractTests(unittest.TestCase):
    def test_audit_dialog_exposes_preview_plan_only_for_safe_candidates(self):
        source = (ROOT / "ui" / "collection_rom_organization_dialog.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="Preview Safe Move Plan..."', source)
        self.assertIn("self.audit.move_candidate_count", source)
        self.assertIn("self._on_preview_plan(self.audit)", source)

    def test_collection_page_freezes_plan_against_live_collection_revision(self):
        source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("collection_revision_token(self.data_manager)", source)
        self.assertIn("build_collection_rom_organization_plan(", source)
        self.assertIn("CollectionRomOrganizationPlanDialog", source)

    def test_plan_dialog_is_read_only_and_has_no_execution_action(self):
        path = ROOT / "ui" / "collection_rom_organization_plan_dialog.py"
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
        self.assertIn("Read-only immutable preview", source)
        self.assertIn('text="Review Save Dispositions..."', source)
        self.assertIn("Save dispositions: not reviewed", source)
        self.assertIn('text="Close"', source)

    def test_plan_model_contains_no_mutating_filesystem_calls(self):
        source = (ROOT / "collection_rom_organization_plan.py").read_text(encoding="utf-8")
        forbidden_calls = (
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
        )
        for forbidden_call in forbidden_calls:
            self.assertNotIn(forbidden_call, source)


if __name__ == "__main__":
    unittest.main()
