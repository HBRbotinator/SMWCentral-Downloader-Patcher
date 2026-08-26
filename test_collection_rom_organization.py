"""Regression coverage for non-destructive Collection ROM location assessment."""
from __future__ import annotations

import ast
import os
import tempfile
import unittest
from pathlib import Path

from collection_rom_organization import (
    assess_collection_rom_location,
    expected_collection_rom_path,
)


class CollectionRomOrganizationTest(unittest.TestCase):
    def test_expected_path_is_pure_and_does_not_create_layout_directories(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "library"

            expected = expected_collection_rom_path(
                str(output),
                "kaizo",
                "Expert",
                "Example.sfc",
            )

            self.assertTrue(expected.endswith(os.path.join("Kaizo", "05 - Expert", "Example.sfc")))
            self.assertFalse(output.exists())

    def test_existing_rom_drift_is_reported_without_moving_or_rewriting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current = root / "legacy" / "Example.sfc"
            current.parent.mkdir(parents=True)
            current.write_bytes(b"rom-bytes")
            record = {
                "file_path": str(current),
                "hack_type": "kaizo",
                "current_difficulty": "Expert",
                "files": [
                    {
                        "path": str(current),
                        "primary": True,
                        "sha256": "a" * 64,
                        "future_asset_field": {"keep": True},
                    }
                ],
                "additional_paths": [str(root / "other" / "Example.sfc")],
            }
            before = record.copy()
            before_files = [dict(row) for row in record["files"]]
            before_additional = list(record["additional_paths"])

            assessment = assess_collection_rom_location(record, str(root / "library"))

            self.assertIsNotNone(assessment)
            self.assertTrue(assessment.exists)
            self.assertTrue(assessment.needs_organization)
            self.assertTrue(current.exists())
            self.assertEqual(b"rom-bytes", current.read_bytes())
            self.assertEqual(before["file_path"], record["file_path"])
            self.assertEqual(before_files, record["files"])
            self.assertEqual(before_additional, record["additional_paths"])
            self.assertFalse((root / "library").exists())

    def test_single_download_pipeline_contains_no_rom_move_or_rename_call(self):
        tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
        target = next(
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "run_single_download_pipeline"
        )

        forbidden = []
        for node in ast.walk(target):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            if isinstance(owner, ast.Name):
                qualified = f"{owner.id}.{node.func.attr}"
                if qualified in {"shutil.move", "os.rename", "os.replace"}:
                    forbidden.append(qualified)

        self.assertEqual([], forbidden)
        source = ast.get_source_segment(Path("main.py").read_text(encoding="utf-8"), target) or ""
        self.assertIn("assess_collection_rom_location", source)
        self.assertIn("left in place for explicit", source)


if __name__ == "__main__":
    unittest.main()
