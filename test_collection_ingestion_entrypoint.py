"""Tests for the real-source Collection ingestion launch boundary."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from collection_ingestion_entrypoint import (
    CollectionIngestionEntrypointError,
    CollectionIngestionSourceSelection,
    create_collection_ingestion_review_session,
    kaizoff_cache_dir_for_processed_json,
    known_difficulties_from_config,
    validate_collection_ingestion_selection,
)
from kaizoff_provider import KaizOffCatalogueProvider


class CollectionIngestionEntrypointTest(unittest.TestCase):
    def test_selection_requires_at_least_one_real_source(self):
        with self.assertRaises(CollectionIngestionEntrypointError):
            validate_collection_ingestion_selection(
                CollectionIngestionSourceSelection()
            )

    def test_selection_validates_rom_folder_and_giganticbucket_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            roms = root / "ROMs"
            roms.mkdir()
            export = root / "checkpoint.json"
            export.write_text(
                '{"serializationVersion":1,"playedHacks":[]}',
                encoding="utf-8",
            )

            selection = validate_collection_ingestion_selection(
                CollectionIngestionSourceSelection(
                    rom_root=str(roms),
                    giganticbucket_path=str(export),
                )
            )

            self.assertEqual(str(roms.resolve()), selection.rom_root)
            self.assertEqual(str(export.resolve()), selection.giganticbucket_path)

            wrong = root / "checkpoint.txt"
            wrong.write_text("{}", encoding="utf-8")
            with self.assertRaises(CollectionIngestionEntrypointError):
                validate_collection_ingestion_selection(
                    CollectionIngestionSourceSelection(
                        giganticbucket_path=str(wrong)
                    )
                )

    def test_known_difficulties_are_read_only_folder_hints(self):
        self.assertEqual(
            ("Newcomer", "Expert", "Grandmaster"),
            known_difficulties_from_config(
                {
                    "difficulty_lookup": {
                        "diff_1": "Newcomer",
                        "diff_5": "Expert",
                        "duplicate": "expert",
                        "diff_7": "Grandmaster",
                    }
                }
            ),
        )
        self.assertEqual((), known_difficulties_from_config(None))
        self.assertEqual(
            (),
            known_difficulties_from_config({"difficulty_lookup": "bad"}),
        )

    def test_default_wiring_uses_collection_adjacent_cache_and_reference_participants(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processed = root / "processed.json"
            processed.write_text("{}\n", encoding="utf-8")
            roms = root / "ROMs"
            roms.mkdir()
            selection = CollectionIngestionSourceSelection(rom_root=str(roms))

            fake_manager = Mock()
            fake_manager.json_path = str(processed.resolve())
            fake_hints = Mock()
            fake_provider = Mock()
            fake_save_sync = Mock()
            fake_planner = Mock()
            expected_session = object()

            with (
                patch(
                    "collection_ingestion_entrypoint.HackDataManager",
                    return_value=fake_manager,
                ) as manager_type,
                patch(
                    "collection_ingestion_entrypoint.CollectionIdentityHintsStore.beside_processed_json",
                    return_value=fake_hints,
                ) as hints_factory,
                patch(
                    "collection_ingestion_entrypoint.KaizOffCatalogueProvider",
                    return_value=fake_provider,
                ) as provider_type,
                patch(
                    "collection_ingestion_entrypoint.SaveSyncAssociationReferenceParticipant.beside_processed_json",
                    return_value=fake_save_sync,
                ) as save_sync_factory,
                patch(
                    "collection_ingestion_entrypoint.PlannerCollectionReferenceParticipant.beside_processed_json",
                    return_value=fake_planner,
                ) as planner_factory,
                patch(
                    "collection_ingestion_entrypoint.create_collection_ingestion_session",
                    return_value=expected_session,
                ) as create_session,
            ):
                actual = create_collection_ingestion_review_session(
                    processed,
                    selection,
                    known_difficulties=("Expert",),
                )

            self.assertIs(expected_session, actual)
            manager_type.assert_called_once_with(str(processed.resolve()))
            hints_factory.assert_called_once_with(processed.resolve())
            save_sync_factory.assert_called_once_with(processed.resolve())
            planner_factory.assert_called_once_with(processed.resolve())
            provider_type.assert_called_once_with(
                cache_dir=kaizoff_cache_dir_for_processed_json(processed)
            )
            create_session.assert_called_once_with(
                fake_manager,
                fake_hints,
                fake_provider,
                rom_root=str(roms.resolve()),
                giganticbucket_path=None,
                known_difficulties=("Expert",),
                participants=(fake_save_sync, fake_planner),
                force_catalogue_refresh=False,
            )

    def test_real_empty_rom_session_captures_optional_dependent_preconditions_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processed = root / "processed.json"
            config = root / "config.json"
            roms = root / "ROMs"
            roms.mkdir()
            processed_bytes = b"{}\n"
            config_bytes = json.dumps(
                {"save_sync_associations": {"QW2.srm": "19279"}},
                indent=2,
            ).encode("utf-8") + b"\n"
            processed.write_bytes(processed_bytes)
            config.write_bytes(config_bytes)

            provider = KaizOffCatalogueProvider(
                fetch_json=lambda _url, _timeout: {"data": [], "count": 0}
            )
            session = create_collection_ingestion_review_session(
                processed,
                CollectionIngestionSourceSelection(rom_root=str(roms)),
                provider=provider,
            )

            self.assertEqual((), session.groups)
            self.assertEqual(
                {
                    "collection",
                    "collection_identity_hints",
                    "save_sync_config",
                    "planner_state",
                },
                {item.store_name for item in session.preconditions},
            )
            self.assertEqual(processed_bytes, processed.read_bytes())
            self.assertEqual(config_bytes, config.read_bytes())
            self.assertFalse((root / "collection_identity_hints.json").exists())
            self.assertFalse((root / "planner_state.json").exists())

    def test_injected_manager_must_reference_same_collection_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processed = root / "processed.json"
            other = root / "other.json"
            roms = root / "ROMs"
            roms.mkdir()
            processed.write_text("{}", encoding="utf-8")
            other.write_text("{}", encoding="utf-8")
            manager = Mock(json_path=str(other))

            with self.assertRaises(CollectionIngestionEntrypointError):
                create_collection_ingestion_review_session(
                    processed,
                    CollectionIngestionSourceSelection(rom_root=str(roms)),
                    manager=manager,
                    provider=Mock(),
                    identity_hints=Mock(),
                    participants=(),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
