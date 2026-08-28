import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class LegacyRomMetadataPlanDialogContractTests(unittest.TestCase):
    def test_legacy_audit_dialog_exposes_read_only_plan_preview(self):
        source = (ROOT / "ui" / "collection_rom_legacy_metadata_dialog.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="Preview Modernization Plan..."', source)
        page_source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("build_legacy_rom_metadata_modernization_plan(", page_source)
        self.assertIn("CollectionRomLegacyMetadataPlanDialog", page_source)

    def test_plan_dialog_is_read_only_and_has_no_apply_action(self):
        path = ROOT / "ui" / "collection_rom_legacy_metadata_plan_dialog.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        called = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
        forbidden = {
            "move", "rename", "replace", "remove", "unlink", "copy", "copy2",
            "makedirs", "mkdir", "open", "write_text", "write_bytes",
        }
        self.assertTrue(forbidden.isdisjoint(called), sorted(called))
        self.assertNotIn('text="Apply', source)
        self.assertNotIn('text="Execute', source)
        self.assertIn("Read-only immutable preview", source)
        self.assertIn('text="Close"', source)

    def test_plan_model_hashes_but_contains_no_write_calls(self):
        source = (ROOT / "collection_rom_legacy_metadata_plan.py").read_text(encoding="utf-8")
        self.assertIn("hashlib.sha256()", source)
        self.assertIn('open(path, "rb")', source)
        for forbidden in (
            "os.replace(", "os.rename(", "os.remove(", "shutil.copy", "shutil.move",
            ".write_text(", ".write_bytes(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
