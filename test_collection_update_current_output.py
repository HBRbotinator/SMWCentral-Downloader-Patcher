from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from collection_update_current_output import (
    CollectionCurrentOutputError,
    ensure_default_rom_output_directory,
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

    def test_blank_output_root_fails_with_user_facing_setting_name(self):
        with self.assertRaisesRegex(CollectionCurrentOutputError, "Default ROM Output Folder"):
            ensure_default_rom_output_directory("")

    def test_file_cannot_be_used_as_output_root(self):
        with tempfile.TemporaryDirectory(prefix="current_update_output_") as temp_name:
            target = Path(temp_name) / "not-a-folder"
            target.write_text("x", encoding="utf-8")
            with self.assertRaises(CollectionCurrentOutputError):
                ensure_default_rom_output_directory(target)


if __name__ == "__main__":
    unittest.main()
