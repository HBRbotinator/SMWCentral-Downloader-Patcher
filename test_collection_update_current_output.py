from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from collection_update_current_output import (
    CollectionCurrentOutputError,
    ROM_DOWNLOAD_DESTINATION_ALONGSIDE_PRIMARY,
    ROM_DOWNLOAD_DESTINATION_DEFAULT,
    current_primary_rom_directory,
    ensure_default_rom_output_directory,
    resolve_current_rom_download_directory,
)


class CurrentUpdateOutputTests(unittest.TestCase):
    def test_configured_output_root_is_created_without_requiring_collection_rom_location(self):
        with tempfile.TemporaryDirectory(prefix="current_update_output_") as temp_name:
            root = Path(temp_name)
            imported_rom_dir = root / "Imported" / "Collection"
            imported_rom_dir.mkdir(parents=True)
            existing_rom = imported_rom_dir / "Quickie World.sfc"
            existing_rom.write_bytes(b"existing")

            configured_output = root / "Downloads" / "SMWC"
            self.assertFalse(configured_output.exists())
            resolved = ensure_default_rom_output_directory(configured_output)

            self.assertTrue(resolved.is_dir())
            self.assertEqual(configured_output.resolve(), resolved)
            self.assertNotEqual(existing_rom.parent.resolve(), resolved)
            self.assertEqual(b"existing", existing_rom.read_bytes())

    def test_alongside_destination_uses_explicit_current_primary_without_default_output(self):
        with tempfile.TemporaryDirectory(prefix="current_update_output_") as temp_name:
            root = Path(temp_name)
            imported_dir = root / "Imported" / "Kaizo"
            imported_dir.mkdir(parents=True)
            current = imported_dir / "Super Dram World.sfc"
            current.write_bytes(b"current")
            record = {
                "file_path": str(current),
                "files": [
                    {
                        "path": str(current),
                        "primary": True,
                        "sha256": "1" * 64,
                        "size_bytes": len(b"current"),
                    }
                ],
            }

            resolved = resolve_current_rom_download_directory(
                "",
                record,
                ROM_DOWNLOAD_DESTINATION_ALONGSIDE_PRIMARY,
            )

            self.assertEqual(imported_dir.resolve(), resolved)
            self.assertEqual(imported_dir.resolve(), current_primary_rom_directory(record))
            self.assertEqual(b"current", current.read_bytes())

    def test_default_destination_remains_independent_of_current_primary(self):
        with tempfile.TemporaryDirectory(prefix="current_update_output_") as temp_name:
            root = Path(temp_name)
            imported_dir = root / "Imported"
            imported_dir.mkdir()
            current = imported_dir / "Quickie World.sfc"
            current.write_bytes(b"current")
            configured = root / "Downloads"
            record = {"file_path": str(current), "files": []}

            resolved = resolve_current_rom_download_directory(
                configured,
                record,
                ROM_DOWNLOAD_DESTINATION_DEFAULT,
            )

            self.assertEqual(configured.resolve(), resolved)
            self.assertNotEqual(imported_dir.resolve(), resolved)

    def test_alongside_destination_fails_closed_on_ambiguous_primary_state(self):
        with tempfile.TemporaryDirectory(prefix="current_update_output_") as temp_name:
            root = Path(temp_name)
            first = root / "first.sfc"
            second = root / "second.sfc"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            record = {
                "files": [
                    {"path": str(first), "primary": True},
                    {"path": str(second), "primary": True},
                ]
            }

            self.assertIsNone(current_primary_rom_directory(record))
            with self.assertRaisesRegex(CollectionCurrentOutputError, "current primary ROM"):
                resolve_current_rom_download_directory(
                    root / "Downloads",
                    record,
                    ROM_DOWNLOAD_DESTINATION_ALONGSIDE_PRIMARY,
                )

    def test_blank_output_root_fails_with_user_facing_setting_name(self):
        with self.assertRaisesRegex(CollectionCurrentOutputError, "Default ROM Output Folder"):
            ensure_default_rom_output_directory("")

    def test_file_cannot_be_used_as_output_root(self):
        with tempfile.TemporaryDirectory(prefix="current_update_output_") as temp_name:
            target = Path(temp_name) / "not-a-folder"
            target.write_text("x", encoding="utf-8")
            with self.assertRaises(CollectionCurrentOutputError):
                ensure_default_rom_output_directory(target)

    def test_unknown_destination_is_rejected(self):
        with self.assertRaisesRegex(CollectionCurrentOutputError, "Choose where"):
            resolve_current_rom_download_directory("", {}, "somewhere_else")


if __name__ == "__main__":
    unittest.main()
