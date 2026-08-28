import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class LegacyRomMetadataDialogContractTests(unittest.TestCase):
    def test_organization_audit_exposes_legacy_metadata_review(self):
        source = (ROOT / "ui" / "collection_rom_organization_dialog.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="Review Legacy ROM Metadata..."', source)

        page_source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("build_legacy_rom_metadata_audit(", page_source)
        self.assertIn("CollectionRomLegacyMetadataDialog", page_source)

    def test_dialog_is_read_only_and_has_no_apply_or_hashing(self):
        path = ROOT / "ui" / "collection_rom_legacy_metadata_dialog.py"
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
            "move",
            "rename",
            "replace",
            "remove",
            "unlink",
            "copy",
            "copy2",
            "makedirs",
            "mkdir",
            "sha256",
            "open",
        }
        self.assertTrue(forbidden.isdisjoint(called), sorted(called))
        self.assertNotIn("Apply", source)
        self.assertNotIn("Execute", source)
        self.assertIn("Read-only preview", source)
        self.assertIn('text="Close"', source)

    def test_model_contains_no_write_or_hash_calls(self):
        source = (ROOT / "collection_rom_legacy_metadata.py").read_text(encoding="utf-8")
        for forbidden in (
            "hashlib",
            "open(",
            "os.replace(",
            "os.rename(",
            "os.remove(",
            "shutil.copy",
            "shutil.move",
            ".write_text(",
            ".write_bytes(",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
