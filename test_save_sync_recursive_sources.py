"""Regression coverage for optional recursive Save Data Sync sources."""
from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

import save_sync
import save_sync_sources
from collection_change_plan import ReferenceMigrationOperation
from save_sync_reference_participant import (
    SAVE_SYNC_ASSOCIATION_CONFIG_KEY,
    SAVE_SYNC_PATH_ASSOCIATION_CONFIG_KEY,
    SaveSyncAssociationReferenceParticipant,
)


class _Config:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value


class RecursiveSaveSourceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="save_sync_recursive_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def _config(self, *directories):
        return _Config(
            {
                save_sync.SAVE_DIRECTORIES_CONFIG_KEY: [str(path) for path in directories],
                save_sync.LEGACY_SAVE_DIRECTORY_CONFIG_KEY: str(directories[0]) if directories else "",
            }
        )

    def test_recursion_defaults_off_and_is_enabled_per_configured_folder(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        config = self._config(first, second)

        self.assertEqual([], save_sync_sources.get_recursive_save_directories(config))
        self.assertFalse(save_sync_sources.is_save_directory_recursive(config, first))

        self.assertTrue(
            save_sync_sources.set_save_directory_recursive(config, first, True)
        )
        self.assertTrue(save_sync_sources.is_save_directory_recursive(config, first))
        self.assertFalse(save_sync_sources.is_save_directory_recursive(config, second))
        self.assertFalse(
            save_sync_sources.set_save_directory_recursive(config, first, True)
        )

    def test_recursive_discovery_finds_nested_saves_without_changing_flat_default(self):
        source = self.root / "saves"
        nested = source / "nested" / "slot"
        nested.mkdir(parents=True)
        (source / "Top.srm").write_bytes(b"top")
        (nested / "Deep.sav").write_bytes(b"deep")
        (nested / "Ignore.txt").write_text("x", encoding="utf-8")

        flat = save_sync_sources.discover_save_files([str(source)], [])
        recursive = save_sync_sources.discover_save_files(
            [str(source)], [str(source)]
        )

        self.assertEqual(["Top.srm"], [Path(row.path).name for row in flat])
        self.assertEqual(
            ["Deep.sav", "Top.srm"],
            sorted(Path(row.path).name for row in recursive),
        )

    def test_overlapping_sources_scan_same_physical_save_once_under_specific_root(self):
        outer = self.root / "outer"
        inner = outer / "profile"
        inner.mkdir(parents=True)
        save = inner / "Same.srm"
        save.write_bytes(b"data")

        rows = save_sync_sources.discover_save_files(
            [str(outer), str(inner)],
            [str(outer)],
        )

        self.assertEqual(1, len(rows))
        self.assertEqual(os.path.realpath(inner), os.path.realpath(rows[0].source_root))

    def test_nested_same_name_matches_are_path_scoped_and_can_target_different_hacks(self):
        source = self.root / "saves"
        first = source / "a"
        second = source / "b"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        first_save = first / "Same.srm"
        second_save = second / "Same.srm"
        first_save.write_bytes(b"a")
        second_save.write_bytes(b"b")
        config = self._config(source)
        save_sync_sources.set_save_directory_recursive(config, source, True)

        first_key = save_sync_sources.scoped_association_key(source, first_save)
        second_key = save_sync_sources.scoped_association_key(source, second_save)
        config.set(
            save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY,
            {first_key: "100", second_key: "200"},
        )
        hacks = [
            {"id": "100", "title": "First"},
            {"id": "200", "title": "Second"},
        ]

        def fake_scan(paths, scan_hacks, mark_all=False, associations=None):
            del mark_all
            path = paths[0]
            key = save_sync.association_key(os.path.basename(path))
            target = str((associations or {}).get(key, ""))
            selected = next(
                (hack for hack in scan_hacks if str(hack.get("id")) == target),
                None,
            )
            return [
                SimpleNamespace(
                    save_path=path,
                    save_name=os.path.basename(path),
                    hack_id=target if selected else "",
                    title=selected.get("title", "") if selected else "",
                    collected_exits=1,
                    mtime=1.0,
                    match_source="",
                )
            ]

        with mock.patch.object(
            save_sync_sources.save_sync, "_scan_save_paths", side_effect=fake_scan
        ):
            candidates = save_sync_sources.scan_save_directories(
                config,
                [str(source)],
                hacks,
                associations={},
            )

        by_id = {candidate.hack_id: candidate for candidate in candidates}
        self.assertEqual({"100", "200"}, set(by_id))
        self.assertIn("a", by_id["100"].save_name)
        self.assertIn("b", by_id["200"].save_name)
        self.assertEqual(
            save_sync.MATCH_SOURCE_SAVED_ALIAS, by_id["100"].match_source
        )
        self.assertEqual(
            save_sync.MATCH_SOURCE_SAVED_ALIAS, by_id["200"].match_source
        )

    def test_legacy_filename_alias_is_not_applied_to_duplicate_recursive_basenames(self):
        source = self.root / "saves"
        first = source / "a"
        second = source / "b"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (first / "Same.srm").write_bytes(b"a")
        (second / "Same.srm").write_bytes(b"b")
        config = self._config(source)
        save_sync_sources.set_save_directory_recursive(config, source, True)
        captured = []

        def fake_scan(paths, _hacks, mark_all=False, associations=None):
            del mark_all
            captured.append(dict(associations or {}))
            return [
                SimpleNamespace(
                    save_path=paths[0],
                    save_name=os.path.basename(paths[0]),
                    hack_id="",
                    title="",
                    collected_exits=None,
                    mtime=0.0,
                    match_source="",
                )
            ]

        with mock.patch.object(
            save_sync_sources.save_sync, "_scan_save_paths", side_effect=fake_scan
        ):
            save_sync_sources.scan_save_directories(
                config,
                [str(source)],
                [],
                associations={save_sync.association_key("Same.srm"): "100"},
            )

        self.assertEqual([{}, {}], captured)

    def test_unique_top_level_manual_match_keeps_legacy_filename_alias(self):
        source = self.root / "saves"
        source.mkdir()
        save = source / "QW2.srm"
        save.write_bytes(b"save")
        config = self._config(source)
        candidate = SimpleNamespace(save_path=str(save), save_name="QW2.srm")

        self.assertTrue(
            save_sync_sources.remember_candidate_association(config, candidate, "123")
        )
        self.assertEqual(
            "123",
            config.get(save_sync.ASSOCIATION_CONFIG_KEY, {})[
                save_sync.association_key("QW2.srm")
            ],
        )
        self.assertEqual(
            {}, config.get(save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY, {})
        )

    def test_duplicate_top_level_manual_matches_are_source_scoped(self):
        first = self.root / "first"
        second = self.root / "second"
        first.mkdir()
        second.mkdir()
        first_save = first / "Same.srm"
        second_save = second / "Same.srm"
        first_save.write_bytes(b"a")
        second_save.write_bytes(b"b")
        config = self._config(first, second)
        first_candidate = SimpleNamespace(save_path=str(first_save), save_name="Same.srm")
        second_candidate = SimpleNamespace(save_path=str(second_save), save_name="Same.srm")

        self.assertTrue(
            save_sync_sources.remember_candidate_association(
                config, first_candidate, "100"
            )
        )
        self.assertTrue(
            save_sync_sources.remember_candidate_association(
                config, second_candidate, "200"
            )
        )
        scoped = config.get(save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY, {})
        self.assertEqual(
            "100",
            scoped[save_sync_sources.scoped_association_key(first, first_save)],
        )
        self.assertEqual(
            "200",
            scoped[save_sync_sources.scoped_association_key(second, second_save)],
        )
        self.assertEqual({}, config.get(save_sync.ASSOCIATION_CONFIG_KEY, {}))

    def test_nested_manual_match_is_scoped_without_creating_global_filename_alias(self):
        source = self.root / "saves"
        nested = source / "profile"
        nested.mkdir(parents=True)
        save = nested / "QW2.srm"
        save.write_bytes(b"save")
        config = self._config(source)
        save_sync_sources.set_save_directory_recursive(config, source, True)
        candidate = SimpleNamespace(save_path=str(save), save_name="profile/QW2.srm")

        self.assertTrue(
            save_sync_sources.remember_candidate_association(config, candidate, "123")
        )
        scoped = config.get(save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY, {})
        self.assertEqual(
            "123",
            scoped[save_sync_sources.scoped_association_key(source, save)],
        )
        self.assertEqual({}, config.get(save_sync.ASSOCIATION_CONFIG_KEY, {}))
        self.assertTrue(
            save_sync_sources.forget_candidate_association(config, candidate)
        )
        self.assertEqual(
            {}, config.get(save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY, {})
        )

    def test_removing_source_state_drops_only_that_sources_recursive_and_scoped_data(self):
        first = self.root / "first"
        second = self.root / "second"
        (first / "sub").mkdir(parents=True)
        (second / "sub").mkdir(parents=True)
        first_save = first / "sub" / "A.srm"
        second_save = second / "sub" / "B.srm"
        first_save.write_bytes(b"a")
        second_save.write_bytes(b"b")
        config = self._config(first, second)
        save_sync_sources.set_save_directory_recursive(config, first, True)
        save_sync_sources.set_save_directory_recursive(config, second, True)
        config.set(
            save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY,
            {
                save_sync_sources.scoped_association_key(first, first_save): "100",
                save_sync_sources.scoped_association_key(second, second_save): "200",
            },
        )

        self.assertTrue(save_sync_sources.remove_source_state(config, first))
        self.assertFalse(save_sync_sources.is_save_directory_recursive(config, first))
        self.assertTrue(save_sync_sources.is_save_directory_recursive(config, second))
        remaining = config.get(save_sync_sources.PATH_ASSOCIATIONS_CONFIG_KEY, {})
        self.assertEqual(1, len(remaining))
        self.assertEqual("200", next(iter(remaining.values())))


class RecursiveSaveReferenceMigrationTests(unittest.TestCase):
    def test_path_scoped_aliases_migrate_with_legacy_save_sync_references(self):
        temporary = tempfile.TemporaryDirectory(prefix="save_sync_recursive_ref_")
        self.addCleanup(temporary.cleanup)
        config = Path(temporary.name) / "config.json"
        config.write_text(
            json.dumps(
                {
                    SAVE_SYNC_ASSOCIATION_CONFIG_KEY: {"flat": "usr_1111111111111111"},
                    SAVE_SYNC_PATH_ASSOCIATION_CONFIG_KEY: {
                        "v1:0123456789abcdef:profile/qw2.srm": "usr_1111111111111111"
                    },
                    "unrelated": {"keep": True},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        participant = SaveSyncAssociationReferenceParticipant(config)

        prepared = participant.prepare_reference_migrations(
            (
                ReferenceMigrationOperation(
                    "usr_1111111111111111", "43123"
                ),
            )
        )

        self.assertEqual(1, len(prepared.writes))
        updated = json.loads(prepared.writes[0].content_bytes.decode("utf-8"))
        self.assertEqual("43123", updated[SAVE_SYNC_ASSOCIATION_CONFIG_KEY]["flat"])
        self.assertEqual(
            "43123",
            updated[SAVE_SYNC_PATH_ASSOCIATION_CONFIG_KEY][
                "v1:0123456789abcdef:profile/qw2.srm"
            ],
        )
        self.assertEqual({"keep": True}, updated["unrelated"])


class RecursiveSaveUiContractTests(unittest.TestCase):
    @staticmethod
    def _read(relative):
        return Path(relative).read_text(encoding="utf-8")

    def test_settings_exposes_per_folder_recursion_and_uses_source_scanner(self):
        source = self._read("ui/save_sync_panel.py")
        self.assertIn('text="Include subfolders"', source)
        self.assertIn("set_save_directory_recursive", source)
        self.assertIn("save_sync_sources.scan_save_directories", source)
        self.assertIn("[Subfolders] ", source)

    def test_review_uses_path_scoped_remember_forget_and_local_cleanup(self):
        source = self._read("ui/save_sync_dialog.py")
        self.assertIn("remember_candidate_association", source)
        self.assertIn("forget_candidate_association", source)
        self.assertIn("remove_associations_for_hack", source)

    def test_documentation_describes_opt_in_recursion_and_scoped_nested_aliases(self):
        source = self._read("SAVE_DATA_SYNC.md")
        self.assertIn("Include subfolders", source)
        self.assertIn("off by default", source)
        self.assertIn("source + relative path", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
