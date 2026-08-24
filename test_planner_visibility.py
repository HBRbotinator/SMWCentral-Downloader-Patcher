"""Contracts for optional Planner UI visibility without weakening Collection ownership."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import config_manager
from config_manager import ConfigManager


class PlannerVisibilityConfigTest(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.original_config_path = config_manager.CONFIG_PATH
        config_manager.CONFIG_PATH = str(self.root / "config.json")

    def tearDown(self):
        config_manager.CONFIG_PATH = self.original_config_path
        self.temporary_directory.cleanup()

    def test_planner_visibility_defaults_on_and_persists_off(self):
        manager = ConfigManager()
        self.assertIs(manager.get("show_planner"), True)

        manager.set("show_planner", False)
        reloaded = ConfigManager()

        self.assertIs(reloaded.get("show_planner"), False)
        stored = json.loads(Path(config_manager.CONFIG_PATH).read_text(encoding="utf-8"))
        self.assertIs(stored["show_planner"], False)

    def test_clean_config_preserves_visibility_without_accepting_unknown_keys(self):
        manager = ConfigManager()
        cleaned = manager._clean_config(
            {
                "show_planner": False,
                "planner_deletes_collection": True,
            }
        )

        self.assertIs(cleaned["show_planner"], False)
        self.assertNotIn("planner_deletes_collection", cleaned)

        invalid = manager._clean_config({"show_planner": "false"})
        self.assertIs(invalid["show_planner"], True)


class _Value:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Config:
    def __init__(self):
        self.values = {}

    def set(self, key, value):
        self.values[key] = value


class PlannerVisibilitySettingsBehaviorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parent / "ui" / "pages" / "settings_page.py"
        spec = importlib.util.spec_from_file_location(
            "_planner_visibility_settings_page", source
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.settings_page_class = module.SettingsPage

    def _page(self, visible, callback):
        page = self.settings_page_class.__new__(self.settings_page_class)
        page.show_planner_var = _Value(visible)
        page.planner_visibility_callback = callback
        page.setup_section = type("Setup", (), {"config": _Config()})()
        return page

    def test_rejected_hide_restores_checkbox_and_does_not_persist(self):
        page = self._page(False, lambda _visible: False)

        page._save_planner_visibility_setting()

        self.assertIs(page.show_planner_var.get(), True)
        self.assertEqual({}, page.setup_section.config.values)

    def test_accepted_visibility_change_is_persisted_after_callback(self):
        calls = []
        page = self._page(False, lambda visible: calls.append(visible) or True)

        page._save_planner_visibility_setting()

        self.assertEqual([False], calls)
        self.assertEqual({"show_planner": False}, page.setup_section.config.values)



class PlannerVisibilityWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent

    def _source(self, relative):
        return (self.root / relative).read_text(encoding="utf-8")

    def test_navigation_and_layout_treat_planner_as_optional_ui(self):
        navigation = self._source("ui/navigation.py")
        layout = self._source("ui/layout.py")

        for required in (
            "planner_visible=True",
            "def _visible_tabs(self):",
            "def set_planner_visible(self, visible):",
            'tabs.remove("Planner")',
        ):
            self.assertIn(required, navigation)

        for required in (
            'planner_visible=self.setup_section.config.get("show_planner", True)',
            "self.settings_page.planner_visibility_callback",
            "Planner changes are still unsaved",
            "return False",
        ):
            self.assertIn(required, layout)

    def test_settings_explains_visibility_does_not_delete_planner_state(self):
        settings = self._source("ui/pages/settings_page.py")

        for required in (
            "Optional Features",
            "Show Planner in the application",
            'config.set("show_planner", visible)',
            "Existing planner_state.json data is preserved",
            "still follows Collection identity migrations safely",
        ):
            self.assertIn(required, settings)

    def test_hidden_planner_also_hides_planner_specific_wheel_refinements(self):
        dialog = self._source("ui/collection_wheel_dialog.py")
        collection_page = self._source("ui/pages/collection_page.py")

        self.assertIn("planner_features_visible=True", dialog)
        self.assertIn("self.planner_features_visible", dialog)
        self.assertIn("and self.model.planner_refinements_available", dialog)
        self.assertIn("self.config_manager.reload()", collection_page)
        self.assertIn('"show_planner", True', collection_page)
        self.assertIn("planner_features_visible=", collection_page)

    def test_visibility_never_opts_planner_out_of_identity_migration(self):
        entrypoint = self._source("collection_ingestion_entrypoint.py")
        participant = self._source("planner_reference_participant.py")

        self.assertIn("PlannerCollectionReferenceParticipant.beside_processed_json", entrypoint)
        self.assertNotIn("show_planner", entrypoint)
        self.assertNotIn("show_planner", participant)

    def test_documentation_states_collection_remains_authoritative(self):
        guide = self._source("PLANNER.md")

        for required in (
            "Optional visibility",
            "Settings → Optional Features",
            "does **not** delete `planner_state.json`",
            "Collection identity migrations",
            "Planner is an optional application view over Collection-owned hacks",
        ):
            self.assertIn(required, guide)


if __name__ == "__main__":
    unittest.main(verbosity=2)
