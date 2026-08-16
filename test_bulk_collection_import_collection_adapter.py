"""Specification for projecting v5.1 Collection records into bulk import."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy

import tempfile
from pathlib import Path

from bulk_collection_import_collection_adapter import (
    COLLECTION_IMPORT_EXTENSION_KEY as PRODUCTION_EXTENSION_KEY,
    COLLECTION_IMPORT_EXTENSION_KEYS as PRODUCTION_EXTENSION_KEYS,
    COLLECTION_IMPORT_EXTENSION_VERSION as PRODUCTION_EXTENSION_VERSION,
    CORE_SHARED_ATTRIBUTE_KEYS as PRODUCTION_CORE_SHARED_ATTRIBUTE_KEYS,
    BulkCollectionImportCollectionProjectionError,
    bulk_collection_import_collection_identities_to_documents,
    bulk_collection_import_collection_records_to_documents,
    project_bulk_collection_import_collection,
    project_bulk_collection_import_hack_data_manager,
)
from hack_data_manager import HackDataManager


COLLECTION_IMPORT_EXTENSION_KEY = "bulk_collection_import"
COLLECTION_IMPORT_EXTENSION_VERSION = 1

COLLECTION_IMPORT_EXTENSION_KEYS = (
    "version",
    "aliases",
    "source_references",
    "attributes",
)

CORE_SHARED_ATTRIBUTE_KEYS = (
    "authors",
    "difficulty",
    "exit_count",
    "release_date",
)

RAW_COLLECTION = {
    "12345": {
        "title": "Downloaded Hybrid Hack",
        "current_difficulty": "Intermediate",
        "authors": ["Example Author"],
        "exits": 14,
        "date": "2025-05-12",
        "completed": True,
        "completed_date": "2026-08-01",
        "personal_rating": 5,
        "notes": "Keep this note",
        "time_to_beat": 3600,
        "file_path": "C:/roms/Downloaded Hybrid Hack.smc",
        "files": [
            {
                "path": "C:/roms/Downloaded Hybrid Hack.smc",
                "name": "Standard",
                "primary": True,
            }
        ],
        "additional_paths": ["C:/roms/copy.smc"],
        "save_sync_metadata": {
            "association": "downloaded hybrid hack.srm",
        },
        "provider_extension": {
            "future": {"keep": True},
        },
        COLLECTION_IMPORT_EXTENSION_KEY: {
            "version": COLLECTION_IMPORT_EXTENSION_VERSION,
            "aliases": ["Downloaded Hybrid Hack v1.0"],
            "source_references": [
                {"source": "smwc", "external_id": "12345"},
                {
                    "source": "kaizoff",
                    "external_id": "downloaded-hybrid-hack",
                },
            ],
            "attributes": {
                "tags": ["vanilla", "short"],
                "community_rank": 7,
            },
        },
    },
    "usr_0": {
        "title": "Manual Collection Hack",
        "current_difficulty": "Advanced",
        "authors": ["Manual Author"],
        "exits": 22,
        "date": "",
        "completed": False,
        "completed_date": "",
        "personal_rating": 3,
        "notes": "Manual record",
        "time_to_beat": 0,
        "file_path": "",
        "additional_paths": [],
    },
    "usr_save_0123456789abcdef": {
        "title": "Local Save Hack",
        "current_difficulty": "No Difficulty",
        "authors": [],
        "exits": 9,
        "date": "",
        "completed": True,
        "completed_date": "2026-07-27",
        "personal_rating": 0,
        "notes": "",
        "time_to_beat": 0,
        "file_path": "",
        "additional_paths": [],
        "local_save_entry": True,
    },
}

EXPECTED_IDENTITY_SNAPSHOTS = (
    {
        "collection_key": "12345",
        "title": "Downloaded Hybrid Hack",
        "aliases": ["Downloaded Hybrid Hack v1.0"],
        "source_references": [
            {"source": "smwc", "external_id": "12345"},
            {
                "source": "kaizoff",
                "external_id": "downloaded-hybrid-hack",
            },
        ],
        "attributes": {
            "authors": ["Example Author"],
            "difficulty": "Intermediate",
            "exit_count": 14,
            "release_date": "2025-05-12",
            "tags": ["vanilla", "short"],
            "community_rank": 7,
        },
    },
    {
        "collection_key": "usr_0",
        "title": "Manual Collection Hack",
        "aliases": [],
        "source_references": [],
        "attributes": {
            "authors": ["Manual Author"],
            "difficulty": "Advanced",
            "exit_count": 22,
        },
    },
    {
        "collection_key": "usr_save_0123456789abcdef",
        "title": "Local Save Hack",
        "aliases": [],
        "source_references": [],
        "attributes": {
            "authors": [],
            "exit_count": 9,
        },
    },
)

EXPECTED_RECORD_SNAPSHOTS = tuple(
    {
        "collection_key": item["collection_key"],
        "title": item["title"],
        "source_references": deepcopy(item["source_references"]),
        "attributes": deepcopy(item["attributes"]),
        "user_state": {},
    }
    for item in EXPECTED_IDENTITY_SNAPSHOTS
)


class BulkCollectionImportCollectionProjectionContractMixin:
    """Reusable contract for the real v5.1 Collection projection."""

    def project_collection(self, collection):
        raise NotImplementedError

    def identities_to_documents(self, projection):
        raise NotImplementedError

    def records_to_documents(self, projection):
        raise NotImplementedError

    def assert_projection_error(self, collection):
        raise NotImplementedError

    def _project(self, collection=None):
        return self.project_collection(
            deepcopy(
                RAW_COLLECTION
                if collection is None
                else collection
            )
        )

    def test_projection_preserves_processed_json_order(self):
        projection = self._project()

        self.assertEqual(
            tuple(
                item.collection_key
                for item in projection.identities
            ),
            tuple(RAW_COLLECTION),
        )
        self.assertEqual(
            tuple(
                item.collection_key
                for item in projection.records
            ),
            tuple(RAW_COLLECTION),
        )

    def test_numeric_collection_key_synthesizes_smwc_identity(self):
        projection = self._project()
        identity = projection.identities[0]

        self.assertEqual(
            tuple(
                (reference.source, reference.external_id)
                for reference in identity.source_references
            ),
            (
                ("smwc", "12345"),
                ("kaizoff", "downloaded-hybrid-hack"),
            ),
        )

    def test_duplicate_explicit_smwc_reference_is_deduplicated(self):
        projection = self._project()
        identity = projection.identities[0]

        smwc = [
            reference
            for reference in identity.source_references
            if reference.source == "smwc"
        ]
        self.assertEqual(len(smwc), 1)
        self.assertEqual(smwc[0].external_id, "12345")

    def test_user_and_local_save_ids_do_not_imply_smwc_identity(self):
        projection = self._project()

        for identity in projection.identities[1:]:
            with self.subTest(
                collection_key=identity.collection_key
            ):
                self.assertEqual(
                    tuple(identity.source_references),
                    (),
                )

    def test_extension_aliases_are_available_to_identity_matching(self):
        projection = self._project()

        self.assertEqual(
            projection.identities[0].aliases,
            ("Downloaded Hybrid Hack v1.0",),
        )

    def test_core_shared_fields_are_mapped_to_source_neutral_names(self):
        projection = self._project()
        first = projection.identities[0]

        self.assertEqual(
            dict(first.attributes),
            {
                "authors": ("Example Author",),
                "difficulty": "Intermediate",
                "exit_count": 14,
                "release_date": "2025-05-12",
                "tags": ("vanilla", "short"),
                "community_rank": 7,
            },
        )

    def test_no_difficulty_placeholder_is_not_shared_metadata(self):
        projection = self._project()
        local = projection.identities[2]

        self.assertNotIn("difficulty", local.attributes)
        self.assertEqual(local.attributes["exit_count"], 9)

    def test_blank_release_date_is_not_shared_metadata(self):
        projection = self._project()

        self.assertNotIn(
            "release_date",
            projection.identities[1].attributes,
        )

    def test_extension_attributes_cannot_shadow_core_shared_fields(self):
        collection = deepcopy(RAW_COLLECTION)
        collection["12345"][COLLECTION_IMPORT_EXTENSION_KEY][
            "attributes"
        ]["authors"] = ["Wrong Author"]

        self.assert_projection_error(collection)

    def test_numeric_key_rejects_conflicting_explicit_smwc_identity(self):
        collection = deepcopy(RAW_COLLECTION)
        extension = collection["12345"][
            COLLECTION_IMPORT_EXTENSION_KEY
        ]
        extension["source_references"] = [
            {"source": "smwc", "external_id": "99999"},
        ]

        self.assert_projection_error(collection)

    def test_missing_extension_is_valid(self):
        projection = self._project()

        manual = projection.identities[1]
        self.assertEqual(manual.aliases, ())
        self.assertEqual(manual.source_references, ())

    def test_malformed_extension_fails_closed(self):
        cases = (
            None,
            [],
            {"version": 2},
            {
                "version": 1,
                "aliases": "not-a-list",
                "source_references": [],
                "attributes": {},
            },
            {
                "version": 1,
                "aliases": [],
                "source_references": "not-a-list",
                "attributes": {},
            },
            {
                "version": 1,
                "aliases": [],
                "source_references": [],
                "attributes": [],
            },
        )

        for extension in cases:
            collection = deepcopy(RAW_COLLECTION)
            collection["usr_0"][
                COLLECTION_IMPORT_EXTENSION_KEY
            ] = extension

            with self.subTest(extension=extension):
                self.assert_projection_error(collection)

    def test_invalid_collection_record_fails_closed(self):
        cases = (
            {"bad": None},
            {"bad": []},
            {"bad": {}},
            {"bad": {"title": ""}},
            {" bad ": {"title": "Bad Key"}},
        )

        for collection in cases:
            with self.subTest(collection=collection):
                self.assert_projection_error(collection)

    def test_projection_does_not_mutate_collection(self):
        collection = deepcopy(RAW_COLLECTION)
        original = deepcopy(collection)

        self.project_collection(collection)

        self.assertEqual(collection, original)

    def test_identity_documents_match_generic_resolver_shape(self):
        projection = self._project()

        self.assertEqual(
            self.identities_to_documents(projection),
            list(EXPECTED_IDENTITY_SNAPSHOTS),
        )

    def test_record_documents_match_generic_merge_shape(self):
        projection = self._project()

        self.assertEqual(
            self.records_to_documents(projection),
            list(EXPECTED_RECORD_SNAPSHOTS),
        )

    def test_user_owned_and_download_state_never_enters_snapshots(self):
        projection = self._project()
        serialized = json.dumps(
            {
                "identities": self.identities_to_documents(
                    projection
                ),
                "records": self.records_to_documents(
                    projection
                ),
            },
            ensure_ascii=False,
        )

        for forbidden in (
            "completed",
            "completed_date",
            "personal_rating",
            "notes",
            "time_to_beat",
            "file_path",
            "files",
            "additional_paths",
            "save_sync_metadata",
            "provider_extension",
            "local_save_entry",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_projection_is_immutable_and_documents_are_detached(self):
        projection = self._project()

        with self.assertRaises((AttributeError, TypeError)):
            projection.identities[0].title = "Changed"

        identity_documents = self.identities_to_documents(
            projection
        )
        identity_documents[0]["aliases"].append("Changed")
        identity_documents[0]["attributes"]["tags"][0] = "Changed"

        clean = self.identities_to_documents(projection)
        self.assertEqual(
            clean[0]["aliases"],
            ["Downloaded Hybrid Hack v1.0"],
        )
        self.assertEqual(
            clean[0]["attributes"]["tags"],
            ["vanilla", "short"],
        )


class BulkCollectionImportCollectionProjectionSpecificationTest(
    unittest.TestCase
):
    """Lock repository-specific v5.1 Collection semantics."""

    def test_extension_contract_is_namespaced_and_versioned(self):
        self.assertEqual(
            COLLECTION_IMPORT_EXTENSION_KEY,
            "bulk_collection_import",
        )
        self.assertEqual(
            COLLECTION_IMPORT_EXTENSION_VERSION,
            1,
        )
        self.assertEqual(
            COLLECTION_IMPORT_EXTENSION_KEYS,
            (
                "version",
                "aliases",
                "source_references",
                "attributes",
            ),
        )

    def test_initial_core_shared_mapping_is_intentionally_narrow(self):
        self.assertEqual(
            CORE_SHARED_ATTRIBUTE_KEYS,
            (
                "authors",
                "difficulty",
                "exit_count",
                "release_date",
            ),
        )

    def test_numeric_processed_key_is_authoritative_smwc_identity(self):
        self.assertTrue("12345".isdigit())
        self.assertFalse("usr_0".isdigit())
        self.assertFalse(
            "usr_save_0123456789abcdef".isdigit()
        )

    def test_import_extension_does_not_replace_existing_provider_data(
        self,
    ):
        record = RAW_COLLECTION["12345"]

        self.assertIn("provider_extension", record)
        self.assertIn(COLLECTION_IMPORT_EXTENSION_KEY, record)
        self.assertNotEqual(
            record["provider_extension"],
            record[COLLECTION_IMPORT_EXTENSION_KEY],
        )

    def test_user_owned_state_is_present_only_in_raw_fixture(self):
        self.assertTrue(RAW_COLLECTION["12345"]["completed"])
        self.assertEqual(
            RAW_COLLECTION["12345"]["personal_rating"],
            5,
        )
        self.assertEqual(
            EXPECTED_RECORD_SNAPSHOTS[0]["user_state"],
            {},
        )


class BulkCollectionImportCollectionProjectionImplementationTest(
    BulkCollectionImportCollectionProjectionContractMixin,
    unittest.TestCase,
):
    """Run the v5.1 Collection projection contract against production."""

    def project_collection(self, collection):
        return project_bulk_collection_import_collection(
            collection
        )

    def identities_to_documents(self, projection):
        return (
            bulk_collection_import_collection_identities_to_documents(
                projection
            )
        )

    def records_to_documents(self, projection):
        return (
            bulk_collection_import_collection_records_to_documents(
                projection
            )
        )

    def assert_projection_error(self, collection):
        with self.assertRaises(
            BulkCollectionImportCollectionProjectionError
        ):
            project_bulk_collection_import_collection(collection)

    def test_production_constants_match_specification(self):
        self.assertEqual(
            PRODUCTION_EXTENSION_KEY,
            COLLECTION_IMPORT_EXTENSION_KEY,
        )
        self.assertEqual(
            PRODUCTION_EXTENSION_VERSION,
            COLLECTION_IMPORT_EXTENSION_VERSION,
        )
        self.assertEqual(
            PRODUCTION_EXTENSION_KEYS,
            COLLECTION_IMPORT_EXTENSION_KEYS,
        )
        self.assertEqual(
            PRODUCTION_CORE_SHARED_ATTRIBUTE_KEYS,
            CORE_SHARED_ATTRIBUTE_KEYS,
        )

    def test_live_hack_data_manager_projects_its_data_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "processed.json"
            path.write_text(
                json.dumps(RAW_COLLECTION, ensure_ascii=False),
                encoding="utf-8",
            )
            manager = HackDataManager(str(path))
            before = deepcopy(manager.data)

            projection = (
                project_bulk_collection_import_hack_data_manager(
                    manager
                )
            )

            self.assertEqual(
                tuple(
                    identity.collection_key
                    for identity in projection.identities
                ),
                tuple(RAW_COLLECTION),
            )
            self.assertEqual(manager.data, before)

    def test_wrong_manager_type_is_rejected(self):
        with self.assertRaises(TypeError):
            project_bulk_collection_import_hack_data_manager(
                object()
            )

    def test_extension_cannot_smuggle_user_owned_fields(self):
        for field in (
            "notes",
            "personal_rating",
            "time_to_beat",
            "file_path",
            "save_sync_metadata",
        ):
            collection = deepcopy(RAW_COLLECTION)
            collection["usr_0"][
                COLLECTION_IMPORT_EXTENSION_KEY
            ] = {
                "version": 1,
                "aliases": [],
                "source_references": [],
                "attributes": {field: "unsafe"},
            }

            with self.subTest(field=field):
                self.assert_projection_error(collection)

    def test_nonfinite_extension_metadata_is_rejected(self):
        collection = deepcopy(RAW_COLLECTION)
        collection["usr_0"][
            COLLECTION_IMPORT_EXTENSION_KEY
        ] = {
            "version": 1,
            "aliases": [],
            "source_references": [],
            "attributes": {"score": float("nan")},
        }

        self.assert_projection_error(collection)


if __name__ == "__main__":
    unittest.main(verbosity=2)
