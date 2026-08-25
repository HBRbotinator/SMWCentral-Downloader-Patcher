import copy
import os
import tempfile
import unittest

from collection_rom_assets import (
    CollectionRomAssetError,
    build_primary_rom_updates,
    collection_rom_asset_views,
    current_primary_rom_path,
    format_rom_asset_size,
)


class CollectionRomAssetsTests(unittest.TestCase):
    def test_views_expose_modern_asset_facts_without_mutating_record(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            rom_path = os.path.join(temp_dir, "Hack.sfc")
            with open(rom_path, "wb") as handle:
                handle.write(b"rom")

            record = {
                "file_path": rom_path,
                "files": [
                    {
                        "path": rom_path,
                        "name": "Hack.sfc",
                        "sha256": "a" * 64,
                        "size_bytes": 3,
                        "primary": True,
                        "smwc_submission_id": 41022,
                        "ingestion_sources": ["tool_patch", "rom_scan"],
                        "future_field": {"keep": True},
                    }
                ],
            }
            before = copy.deepcopy(record)

            views = collection_rom_asset_views(record)

            self.assertEqual(record, before)
            self.assertEqual(len(views), 1)
            view = views[0]
            self.assertEqual(view.path, rom_path)
            self.assertTrue(view.exists)
            self.assertTrue(view.primary)
            self.assertEqual(view.smwc_submission_id, 41022)
            self.assertEqual(view.ingestion_sources, ("tool_patch", "rom_scan"))

    def test_primary_update_preserves_unknown_row_fields_and_input(self):
        record = {
            "file_path": "A.sfc",
            "files": [
                {
                    "path": "A.sfc",
                    "primary": True,
                    "future": {"nested": [1, 2]},
                },
                {
                    "path": "B.sfc",
                    "primary": False,
                    "future": {"nested": [3, 4]},
                },
            ],
        }
        before = copy.deepcopy(record)

        files, file_path = build_primary_rom_updates(record, "B.sfc")

        self.assertEqual(record, before)
        self.assertEqual(file_path, "B.sfc")
        self.assertFalse(files[0]["primary"])
        self.assertTrue(files[1]["primary"])
        self.assertEqual(files[0]["future"], {"nested": [1, 2]})
        files[0]["future"]["nested"].append(99)
        self.assertEqual(record, before)

    def test_primary_selection_must_reference_recorded_asset(self):
        record = {"files": [{"path": "A.sfc", "primary": True}]}
        with self.assertRaisesRegex(CollectionRomAssetError, "existing Collection files"):
            build_primary_rom_updates(record, "B.sfc")

    def test_duplicate_paths_fail_closed(self):
        record = {
            "files": [
                {"path": "A.sfc", "primary": True},
                {"path": "A.sfc", "primary": False},
            ]
        }
        with self.assertRaisesRegex(CollectionRomAssetError, "duplicated"):
            collection_rom_asset_views(record)

    def test_multiple_primary_rows_fail_closed_when_reading_current_primary(self):
        record = {
            "files": [
                {"path": "A.sfc", "primary": True},
                {"path": "B.sfc", "primary": True},
            ]
        }
        with self.assertRaisesRegex(CollectionRomAssetError, "multiple primary"):
            current_primary_rom_path(record)

    def test_file_path_can_identify_primary_when_legacy_rows_have_no_primary_flag(self):
        record = {
            "file_path": "B.sfc",
            "files": [
                {"path": "A.sfc", "primary": False},
                {"path": "B.sfc", "primary": False},
            ],
        }
        self.assertEqual(current_primary_rom_path(record), "B.sfc")

    def test_size_formatting_is_stable(self):
        self.assertEqual(format_rom_asset_size(None), "size unknown")
        self.assertEqual(format_rom_asset_size(12), "12 B")
        self.assertEqual(format_rom_asset_size(2048), "2.0 KiB")
        self.assertEqual(format_rom_asset_size(2 * 1024 * 1024), "2.00 MiB")


if __name__ == "__main__":
    unittest.main()
