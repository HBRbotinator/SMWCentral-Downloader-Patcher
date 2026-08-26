import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class CollectionRomOrganizationDialogContractTests(unittest.TestCase):
    def test_collection_page_exposes_read_only_audit_action(self):
        source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="Audit ROM Layout..."', source)
        self.assertIn("build_collection_rom_organization_audit(", source)
        self.assertIn("CollectionRomOrganizationAuditDialog", source)

    def test_dialog_has_no_execution_or_filesystem_mutation_action(self):
        path = ROOT / "ui" / "collection_rom_organization_dialog.py"
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
        self.assertNotIn("Apply", source)
        self.assertNotIn("Execute", source)
        self.assertIn("Read-only preview", source)
        self.assertIn('text="Close"', source)

    def test_audit_model_has_no_mutating_filesystem_calls(self):
        path = ROOT / "collection_rom_organization.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
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
