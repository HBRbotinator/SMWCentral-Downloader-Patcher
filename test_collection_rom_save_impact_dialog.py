import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class CollectionRomSaveImpactDialogContractTests(unittest.TestCase):
    def test_plan_dialog_exposes_save_impact_review_without_execution(self):
        source = (ROOT / "ui" / "collection_rom_organization_plan_dialog.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="Review Save Impact..."', source)
        self.assertIn("self._on_review_save_impact(self.plan, self.dialog)", source)
        self.assertNotIn('text="Apply', source)
        self.assertNotIn('text="Execute', source)

    def test_collection_page_reads_save_sync_settings_without_persisting_them(self):
        source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('self.config_manager.get("save_sync_dirs", [])', source)
        self.assertIn('self.config_manager.get("save_sync_dir", "")', source)
        self.assertIn('self.config_manager.get("save_sync_associations", {})', source)
        self.assertIn("build_collection_rom_save_impact_review(", source)
        method = source.split("def _review_collection_rom_save_impact", 1)[1].split(
            "def _collection_rom_organization_plan_closed", 1
        )[0]
        self.assertNotIn("self.config_manager.set(", method)
        self.assertNotIn("self.config_manager.save(", method)

    def test_save_impact_model_contains_no_mutating_filesystem_calls(self):
        source = (ROOT / "collection_rom_save_impact.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
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
            "write_bytes",
            "write_text",
        }
        called = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
        self.assertTrue(forbidden.isdisjoint(called), sorted(called))

    def test_save_impact_dialog_is_read_only(self):
        source = (ROOT / "ui" / "collection_rom_save_impact_dialog.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Read-only relationship review", source)
        self.assertIn("no save or ROM migration", source)
        self.assertIn('text="Close"', source)
        self.assertNotIn('text="Apply', source)
        self.assertNotIn('text="Execute', source)
        self.assertNotIn('text="Move', source)


if __name__ == "__main__":
    unittest.main()
