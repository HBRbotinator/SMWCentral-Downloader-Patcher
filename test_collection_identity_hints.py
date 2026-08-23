"""Tests for versioned source-scoped Collection identity hints."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collection_change_plan import (
    IgnoredRomOperation,
    ReferenceMigrationOperation,
    RememberedAssociationOperation,
)
from collection_identity_hints import (
    CollectionIdentityHintsStore,
    IDENTITY_HINTS_SCHEMA_VERSION,
    IdentityHintsError,
)
from collection_ingestion import IngestionSource


class CollectionIdentityHintsStoreTest(unittest.TestCase):
    def _store(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "collection_identity_hints.json"
        return path, CollectionIdentityHintsStore(path)

    def test_missing_store_is_empty_and_not_created_by_read(self):
        path, store = self._store()

        snapshot = store.snapshot()

        self.assertEqual(snapshot.remembered_associations, ())
        self.assertEqual(snapshot.ignored_roms, ())
        self.assertEqual(store.revision_token(), "missing")
        self.assertFalse(path.exists())

    def test_prepare_is_detached_and_does_not_write(self):
        path, store = self._store()

        prepared = store.prepare_plan_changes(
            remembered_associations=(
                RememberedAssociationOperation(
                    source=IngestionSource.ROM_SCAN,
                    value="QW2",
                    target_key="19279",
                ),
            ),
            ignored_roms=(
                IgnoredRomOperation(
                    path="D:/Backups/QW2.sfc",
                    sha256="a" * 64,
                ),
            ),
        )

        self.assertFalse(path.exists())
        self.assertTrue(prepared.changed)
        document = json.loads(prepared.content_bytes)
        self.assertEqual(document["schema_version"], IDENTITY_HINTS_SCHEMA_VERSION)
        self.assertEqual(document["remembered_associations"][0]["target_key"], "19279")
        self.assertEqual(document["ignored_roms"][0]["sha256"], "a" * 64)

    def test_reference_migration_repoints_existing_association(self):
        path, store = self._store()
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "remembered_associations": [
                        {
                            "source": "rom_scan",
                            "value": "OldName",
                            "target_key": "usr_1111111111111111",
                        }
                    ],
                    "ignored_roms": [],
                    "future_field": {"keep": True},
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        prepared = store.prepare_plan_changes(
            reference_migrations=(
                ReferenceMigrationOperation(
                    source_key="usr_1111111111111111",
                    target_key="43123",
                ),
            )
        )
        document = json.loads(prepared.content_bytes)

        self.assertEqual(document["remembered_associations"][0]["target_key"], "43123")
        self.assertEqual(document["future_field"], {"keep": True})
        self.assertIn("usr_1111111111111111", path.read_text(encoding="utf-8"))

    def test_new_explicit_association_replaces_conflicting_old_target(self):
        path, store = self._store()
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "remembered_associations": [
                        {"source": "rom_scan", "value": "QW2", "target_key": "111"}
                    ],
                    "ignored_roms": [],
                }
            ),
            encoding="utf-8",
        )

        prepared = store.prepare_plan_changes(
            remembered_associations=(
                RememberedAssociationOperation(
                    source=IngestionSource.ROM_SCAN,
                    value="QW2",
                    target_key="19279",
                ),
            )
        )
        document = json.loads(prepared.content_bytes)

        self.assertEqual(len(document["remembered_associations"]), 1)
        self.assertEqual(document["remembered_associations"][0]["target_key"], "19279")

    def test_ignore_identity_is_path_plus_hash(self):
        path, store = self._store()
        prepared = store.prepare_plan_changes(
            ignored_roms=(
                IgnoredRomOperation(path="D:/Hack.sfc", sha256="a" * 64),
                IgnoredRomOperation(path="D:/Hack.sfc", sha256="b" * 64),
            )
        )
        document = json.loads(prepared.content_bytes)

        self.assertEqual(len(document["ignored_roms"]), 2)
        self.assertNotEqual(
            document["ignored_roms"][0]["sha256"],
            document["ignored_roms"][1]["sha256"],
        )

    def test_future_schema_fails_closed_without_rewrite(self):
        path, store = self._store()
        original = '{"schema_version":99,"remembered_associations":[],"ignored_roms":[]}\n'
        path.write_text(original, encoding="utf-8")

        with self.assertRaises(IdentityHintsError):
            store.snapshot()
        with self.assertRaises(IdentityHintsError):
            store.prepare_plan_changes()

        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_duplicate_json_keys_and_nonfinite_numbers_are_rejected(self):
        path, store = self._store()
        path.write_text(
            '{"schema_version":1,"schema_version":1,"remembered_associations":[],"ignored_roms":[]}\n',
            encoding="utf-8",
        )
        with self.assertRaises(IdentityHintsError):
            store.snapshot()

        path.write_text(
            '{"schema_version":1,"remembered_associations":[],"ignored_roms":[],"x":NaN}\n',
            encoding="utf-8",
        )
        with self.assertRaises(IdentityHintsError):
            store.snapshot()

    def test_chained_reference_migration_is_rejected(self):
        _, store = self._store()

        with self.assertRaises(IdentityHintsError):
            store.prepare_plan_changes(
                reference_migrations=(
                    ReferenceMigrationOperation("usr_aaaaaaaaaaaaaaaa", "100"),
                    ReferenceMigrationOperation("100", "200"),
                )
            )


if __name__ == "__main__":
    unittest.main()
