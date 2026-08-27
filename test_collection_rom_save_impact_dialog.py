import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class CollectionRomSaveImpactDialogContractTests(unittest.TestCase):
    def test_plan_dialog_exposes_save_disposition_review_without_execution(self):
        source = (ROOT / "ui" / "collection_rom_organization_plan_dialog.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('text="Review Save Dispositions..."', source)
        self.assertIn("self._on_review_save_impact(self.plan, self.dialog)", source)
        self.assertIn("set_save_disposition_decision", source)
        self.assertNotIn('text="Apply', source)
        self.assertNotIn('text="Execute', source)

    def test_collection_page_reads_save_sync_settings_and_retains_detached_decision(self):
        source = (ROOT / "ui" / "pages" / "collection_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('self.config_manager.get("save_sync_dirs", [])', source)
        self.assertIn('self.config_manager.get("save_sync_dir", "")', source)
        self.assertIn('self.config_manager.get("save_sync_associations", {})', source)
        self.assertIn("build_collection_rom_save_impact_review(", source)
        self.assertIn("_collection_rom_save_dispositions_saved", source)
        self.assertIn("set_save_disposition_decision(decision)", source)
        method = source.split("def _review_collection_rom_save_impact", 1)[1].split(
            "def _collection_rom_save_dispositions_saved", 1
        )[0]
        self.assertNotIn("self.config_manager.set(", method)
        self.assertNotIn("self.config_manager.save(", method)

    def test_save_impact_and_disposition_models_contain_no_mutating_filesystem_calls(self):
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
        for relative in ("collection_rom_save_impact.py", "collection_rom_save_disposition.py"):
            source = (ROOT / relative).read_text(encoding="utf-8")
            tree = ast.parse(source)
            called = set()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name):
                    called.add(node.func.id)
                elif isinstance(node.func, ast.Attribute):
                    called.add(node.func.attr)
            self.assertTrue(forbidden.isdisjoint(called), (relative, sorted(called)))

    def test_save_disposition_dialog_requires_explicit_choices_but_has_no_execution(self):
        source = (ROOT / "ui" / "collection_rom_save_impact_dialog.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("Review-only decision boundary", source)
        self.assertIn('text="Migrate this save with the ROM"', source)
        self.assertIn('text="Leave this save in its current location"', source)
        self.assertIn('text="Block this ROM move"', source)
        self.assertIn('text="Save Disposition Review"', source)
        self.assertIn("Save Sync coverage warning", source)
        self.assertIn("save_sync_coverage_loss_acknowledgements=coverage_acknowledgements", source)
        self.assertIn("no colocated .srm/.sav companion was detected", source)
        self.assertNotIn('text="Apply', source)
        self.assertNotIn('text="Execute', source)


if __name__ == "__main__":
    unittest.main()
