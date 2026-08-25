"""Contracts for optional SMWC-ID metadata in newly patched ROM filenames."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import config_manager
from config_manager import ConfigManager
from rom_filename_policy import build_patched_rom_filename


class RomFilenamePolicyTest(unittest.TestCase):
    def test_default_filename_remains_unchanged(self):
        self.assertEqual(
            "Super Dram World 3.sfc",
            build_patched_rom_filename(
                "Super Dram World 3",
                ".sfc",
                smwc_id=41022,
                include_smwc_id=False,
            ),
        )

    def test_enabled_filename_uses_canonical_smwc_id_suffix(self):
        self.assertEqual(
            "Super Dram World 3 [SMWC-ID-41022].sfc",
            build_patched_rom_filename(
                "Super Dram World 3",
                "sfc",
                smwc_id="41022",
                include_smwc_id=True,
            ),
        )

    def test_existing_recognized_suffix_is_normalized_not_duplicated(self):
        self.assertEqual(
            "Quickie World 2 [SMWC-ID-19279].smc",
            build_patched_rom_filename(
                "Quickie World 2 [SMWC-19279]",
                ".smc",
                smwc_id=19279,
                include_smwc_id=True,
            ),
        )

    def test_enabled_suffix_requires_positive_numeric_smwc_id(self):
        for value in (None, "", "usr_abc", 0, -1):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    build_patched_rom_filename(
                        "Hack",
                        ".sfc",
                        smwc_id=value,
                        include_smwc_id=True,
                    )


class RomFilenameConfigTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.original_config_path = config_manager.CONFIG_PATH
        config_manager.CONFIG_PATH = str(self.root / "config.json")

    def tearDown(self):
        config_manager.CONFIG_PATH = self.original_config_path
        self.temporary_directory.cleanup()

    def test_setting_defaults_off_and_persists_on(self):
        manager = ConfigManager()
        self.assertIs(manager.get("include_smwc_id_in_filename"), False)

        manager.set("include_smwc_id_in_filename", True)
        reloaded = ConfigManager()

        self.assertIs(reloaded.get("include_smwc_id_in_filename"), True)
        stored = json.loads(Path(config_manager.CONFIG_PATH).read_text(encoding="utf-8"))
        self.assertIs(stored["include_smwc_id_in_filename"], True)

    def test_invalid_non_boolean_setting_falls_back_to_default_off(self):
        manager = ConfigManager()
        cleaned = manager._clean_config({"include_smwc_id_in_filename": "yes"})
        self.assertIs(cleaned["include_smwc_id_in_filename"], False)


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Config:
    def __init__(self, value=False):
        self.value = value
        self.values = {}

    def get(self, key, default=None):
        if key == "include_smwc_id_in_filename":
            return self.value
        return default

    def set(self, key, value):
        self.values[key] = value


class RomFilenameSettingsBehaviorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parent / "ui" / "pages" / "settings_page.py"
        spec = importlib.util.spec_from_file_location("_rom_filename_settings_page", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.settings_page_class = module.SettingsPage

    def test_load_and_save_use_shared_config(self):
        page = self.settings_page_class.__new__(self.settings_page_class)
        page.include_smwc_id_in_filename_var = _Value(False)
        config = _Config(True)
        page.setup_section = type("Setup", (), {"config": config})()

        page._load_rom_filename_setting()
        self.assertIs(page.include_smwc_id_in_filename_var.get(), True)

        page.include_smwc_id_in_filename_var.set(False)
        page._save_rom_filename_setting()
        self.assertEqual({"include_smwc_id_in_filename": False}, config.values)


class RomFilenameWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent

    def _source(self, relative):
        return (self.root / relative).read_text(encoding="utf-8")

    def test_current_download_paths_use_shared_filename_policy(self):
        main = self._source("main.py")
        pipeline = self._source("api_pipeline.py")

        for source in (main, pipeline):
            self.assertIn("build_patched_rom_filename", source)
            self.assertIn('include_smwc_id_in_filename', source)
            self.assertIn("smwc_id=hack_id", source)

    def test_settings_warn_about_basename_save_associations(self):
        settings = self._source("ui/pages/settings_page.py")
        for required in (
            "ROM File Naming",
            "Include SMWC ID in new patched ROM filenames",
            "Default: off",
            "Existing ROMs and save files are never renamed",
            "match saves by ROM basename",
        ):
            self.assertIn(required, settings)

    def test_setting_does_not_add_any_existing_file_rename_flow(self):
        policy = self._source("rom_filename_policy.py")
        for forbidden in ("os.rename", "os.replace", "shutil.move", "os.remove"):
            self.assertNotIn(forbidden, policy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
