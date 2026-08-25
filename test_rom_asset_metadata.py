"""Tests for modern Collection ROM asset persistence helpers."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from rom_asset_metadata import (
    RomAssetMetadataError,
    build_tool_patch_rom_asset,
    merge_collection_rom_assets,
)


class RomAssetMetadataTest(unittest.TestCase):
    def test_build_tool_patch_asset_records_hash_size_source_and_submission(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "Example.sfc"
            payload = b"patched-rom-bytes"
            path.write_bytes(payload)

            row = build_tool_patch_rom_asset(
                str(path),
                smwc_submission_id=41022,
                primary=True,
            )

            self.assertEqual(str(path.resolve()), row["path"])
            self.assertEqual("Example.sfc", row["name"])
            self.assertEqual(hashlib.sha256(payload).hexdigest(), row["sha256"])
            self.assertEqual(len(payload), row["size_bytes"])
            self.assertTrue(row["primary"])
            self.assertEqual(41022, row["smwc_submission_id"])
            self.assertEqual(["tool_patch"], row["ingestion_sources"])

    def test_build_tool_patch_asset_resolves_filesystem_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            real_dir = root / "real"
            alias_dir = root / "alias"
            real_dir.mkdir()
            path = real_dir / "Example.sfc"
            path.write_bytes(b"patched-rom-bytes")
            try:
                alias_dir.symlink_to(real_dir, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("Filesystem symlinks are unavailable on this runner.")

            row = build_tool_patch_rom_asset(
                str(alias_dir / "Example.sfc"),
                smwc_submission_id=41022,
                primary=True,
            )

            self.assertEqual(str(path.resolve()), row["path"])

    def test_merge_preserves_existing_rows_and_promotes_new_primary(self):
        existing = [
            {
                "path": "C:/ROMs/old.sfc",
                "name": "old.sfc",
                "sha256": "a" * 64,
                "size_bytes": 10,
                "primary": True,
                "custom_local_field": "keep-me",
            }
        ]
        new = [
            {
                "path": "C:/ROMs/new.sfc",
                "name": "new.sfc",
                "sha256": "b" * 64,
                "size_bytes": 11,
                "primary": True,
                "smwc_submission_id": 41022,
                "ingestion_sources": ["tool_patch"],
            }
        ]

        merged = merge_collection_rom_assets(
            existing,
            new,
            primary_path="C:/ROMs/new.sfc",
        )

        self.assertEqual(2, len(merged))
        by_path = {row["path"]: row for row in merged}
        self.assertFalse(by_path["C:/ROMs/old.sfc"]["primary"])
        self.assertEqual("keep-me", by_path["C:/ROMs/old.sfc"]["custom_local_field"])
        self.assertTrue(by_path["C:/ROMs/new.sfc"]["primary"])

    def test_merge_updates_same_path_without_dropping_unknown_row_fields(self):
        existing = [
            {
                "path": "C:/ROMs/game.sfc",
                "name": "legacy-name",
                "primary": True,
                "unknown": {"future": True},
            }
        ]
        new = [
            {
                "path": "C:/ROMs/game.sfc",
                "name": "game.sfc",
                "sha256": "c" * 64,
                "size_bytes": 12,
                "primary": True,
                "smwc_submission_id": 41022,
                "ingestion_sources": ["tool_patch"],
            }
        ]

        merged = merge_collection_rom_assets(
            existing,
            new,
            primary_path="C:/ROMs/game.sfc",
        )

        self.assertEqual(1, len(merged))
        self.assertEqual({"future": True}, merged[0]["unknown"])
        self.assertEqual("c" * 64, merged[0]["sha256"])

    def test_invalid_existing_files_state_fails_closed(self):
        with self.assertRaises(RomAssetMetadataError):
            merge_collection_rom_assets(
                {"not": "an array"},
                [{"path": "C:/ROMs/new.sfc"}],
                primary_path="C:/ROMs/new.sfc",
            )


if __name__ == "__main__":
    unittest.main()
