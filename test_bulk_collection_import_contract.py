"""Specification tests for the bulk Collection import contract."""

from __future__ import annotations

import json
import re
import unittest
from copy import deepcopy

from bulk_collection_import import (
    BULK_COLLECTION_IMPORT_DOCUMENT_KEYS,
    BULK_COLLECTION_IMPORT_ENTRY_KEYS,
    BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS,
    BULK_COLLECTION_IMPORT_GROUP_KEYS,
    BULK_COLLECTION_IMPORT_SCHEMA,
    BULK_COLLECTION_IMPORT_SOURCE_REFERENCE_KEYS,
    BULK_COLLECTION_IMPORT_VERSION,
    BulkCollectionImportError,
    bulk_collection_import_to_document,
    parse_bulk_collection_import,
    serialize_bulk_collection_import,
)


IMPORT_SCHEMA = "smwc-bulk-collection-import"
IMPORT_VERSION = 1

DOCUMENT_KEYS = (
    "schema",
    "version",
    "import_id",
    "title",
    "entries",
    "groups",
)
ENTRY_KEYS = (
    "entry_key",
    "title",
    "source_references",
    "attributes",
)
SOURCE_REFERENCE_KEYS = (
    "source",
    "external_id",
)
GROUP_KEYS = (
    "group_key",
    "title",
    "entry_keys",
)

IMPORT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
ENTRY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
GROUP_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
SOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")

FORBIDDEN_ATTRIBUTE_KEYS = (
    "completed",
    "completed_date",
    "completion_date",
    "download_paths",
    "notes",
    "personal_rating",
    "planner",
    "planner_state",
    "rom_paths",
    "save_associations",
    "save_paths",
)

VALID_IMPORT_DOCUMENT = {
    "schema": IMPORT_SCHEMA,
    "version": IMPORT_VERSION,
    "import_id": "community-list:2026-08",
    "title": "Community progression",
    "entries": [
        {
            "entry_key": "beginner-hack",
            "title": "Beginner Hack",
            "source_references": [
                {
                    "source": "smwc",
                    "external_id": "12345",
                },
                {
                    "source": "kaizoff",
                    "external_id": "beginner-hack",
                },
            ],
            "attributes": {
                "authors": ["Example Author"],
                "difficulty": "Kaizo: Beginner",
                "exit_count": 12,
                "release_date": "2026-04-15",
                "tags": ["vanilla", "short"],
            },
        },
        {
            "entry_key": "local-training-hack",
            "title": "Local Training Hack",
            "source_references": [],
            "attributes": {
                "authors": ["Local Author"],
                "difficulty": "Training",
            },
        },
        {
            "entry_key": "advanced-hack",
            "title": "Advanced Hack",
            "source_references": [
                {
                    "source": "kaizoff",
                    "external_id": "advanced-hack-v2",
                },
            ],
            "attributes": {
                "authors": ["Another Author"],
                "difficulty": "Kaizo: Expert",
            },
        },
    ],
    "groups": [
        {
            "group_key": "start-here",
            "title": "Start here",
            "entry_keys": [
                "beginner-hack",
                "local-training-hack",
            ],
        },
        {
            "group_key": "advanced",
            "title": "Advanced",
            "entry_keys": [
                "advanced-hack",
            ],
        },
    ],
}

EMPTY_IMPORT_DOCUMENT = {
    "schema": IMPORT_SCHEMA,
    "version": IMPORT_VERSION,
    "import_id": "empty-import",
    "title": "Empty import",
    "entries": [],
    "groups": [],
}

INVALID_IMPORT_DOCUMENTS = (
    None,
    [],
    "collection",
    {},
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "schema": "other-schema",
    },
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "version": 2,
    },
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "version": True,
    },
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "import_id": "",
    },
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "import_id": "contains spaces",
    },
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "title": "",
    },
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "unexpected": True,
    },
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "entries": {},
    },
    {
        **deepcopy(EMPTY_IMPORT_DOCUMENT),
        "groups": {},
    },
)


class BulkCollectionImportContractMixin:
    """Reusable behavior suite for the production import contract."""

    def parse_import(self, document):
        raise NotImplementedError

    def import_to_document(self, import_document):
        raise NotImplementedError

    def serialize_import(self, import_document):
        raise NotImplementedError

    def assert_contract_error(self, document):
        raise NotImplementedError

    def test_valid_hybrid_import_is_parsed_exactly(self):
        document = deepcopy(VALID_IMPORT_DOCUMENT)

        parsed = self.parse_import(document)

        self.assertEqual(parsed.schema, IMPORT_SCHEMA)
        self.assertEqual(parsed.version, IMPORT_VERSION)
        self.assertEqual(parsed.import_id, "community-list:2026-08")
        self.assertEqual(
            self.import_to_document(parsed),
            VALID_IMPORT_DOCUMENT,
        )

    def test_empty_import_is_valid(self):
        parsed = self.parse_import(
            deepcopy(EMPTY_IMPORT_DOCUMENT)
        )

        self.assertEqual(parsed.entries, ())
        self.assertEqual(parsed.groups, ())
        self.assertEqual(
            self.import_to_document(parsed),
            EMPTY_IMPORT_DOCUMENT,
        )

    def test_input_and_projected_documents_are_detached(self):
        document = deepcopy(VALID_IMPORT_DOCUMENT)
        parsed = self.parse_import(document)

        document["entries"][0]["title"] = "Changed input"
        document["groups"][0]["entry_keys"].reverse()
        projected = self.import_to_document(parsed)
        projected["entries"][0]["attributes"]["authors"][0] = (
            "Changed projection"
        )
        projected["groups"][0]["entry_keys"].reverse()

        clean = self.import_to_document(parsed)
        self.assertEqual(
            clean["entries"][0]["title"],
            "Beginner Hack",
        )
        self.assertEqual(
            clean["entries"][0]["attributes"]["authors"],
            ["Example Author"],
        )
        self.assertEqual(
            clean["groups"][0]["entry_keys"],
            ["beginner-hack", "local-training-hack"],
        )

    def test_parsed_import_graph_is_immutable(self):
        parsed = self.parse_import(VALID_IMPORT_DOCUMENT)

        with self.assertRaises((AttributeError, TypeError)):
            parsed.title = "Changed"
        with self.assertRaises((AttributeError, TypeError)):
            parsed.entries[0].title = "Changed"
        with self.assertRaises((AttributeError, TypeError)):
            parsed.groups[0].entry_keys += ("advanced-hack",)

    def test_serialization_is_stable_compact_json(self):
        parsed = self.parse_import(VALID_IMPORT_DOCUMENT)

        serialized = self.serialize_import(parsed)

        self.assertEqual(
            json.loads(serialized),
            VALID_IMPORT_DOCUMENT,
        )
        self.assertNotIn("\n", serialized)
        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )
        self.assertEqual(
            serialized,
            self.serialize_import(
                self.parse_import(
                    deepcopy(VALID_IMPORT_DOCUMENT)
                )
            ),
        )

    def test_invalid_top_level_documents_are_rejected(self):
        for document in INVALID_IMPORT_DOCUMENTS:
            with self.subTest(document=document):
                self.assert_contract_error(deepcopy(document))

    def test_duplicate_entry_group_and_source_ids_are_rejected(self):
        duplicate_entry = deepcopy(VALID_IMPORT_DOCUMENT)
        duplicate_entry["entries"][1]["entry_key"] = (
            "beginner-hack"
        )

        duplicate_group = deepcopy(VALID_IMPORT_DOCUMENT)
        duplicate_group["groups"][1]["group_key"] = "start-here"

        duplicate_source = deepcopy(VALID_IMPORT_DOCUMENT)
        duplicate_source["entries"][1]["source_references"] = [
            {
                "source": "smwc",
                "external_id": "12345",
            }
        ]

        for document in (
            duplicate_entry,
            duplicate_group,
            duplicate_source,
        ):
            with self.subTest(document=document):
                self.assert_contract_error(document)

    def test_order_structure_must_cover_each_entry_exactly_once(self):
        missing = deepcopy(VALID_IMPORT_DOCUMENT)
        missing["groups"][0]["entry_keys"].remove(
            "local-training-hack"
        )

        repeated = deepcopy(VALID_IMPORT_DOCUMENT)
        repeated["groups"][1]["entry_keys"].append(
            "beginner-hack"
        )

        unknown = deepcopy(VALID_IMPORT_DOCUMENT)
        unknown["groups"][1]["entry_keys"].append(
            "not-an-entry"
        )

        for document in (missing, repeated, unknown):
            with self.subTest(document=document):
                self.assert_contract_error(document)

    def test_user_owned_collection_state_is_rejected(self):
        for forbidden in FORBIDDEN_ATTRIBUTE_KEYS:
            document = deepcopy(VALID_IMPORT_DOCUMENT)
            document["entries"][0]["attributes"][forbidden] = (
                "not-importable"
            )
            with self.subTest(forbidden=forbidden):
                self.assert_contract_error(document)


class BulkCollectionImportContractSpecificationTest(
    unittest.TestCase
):
    """Validate the source-neutral import specification itself."""

    def test_schema_and_exact_shapes_are_fixed(self):
        self.assertEqual(
            IMPORT_SCHEMA,
            "smwc-bulk-collection-import",
        )
        self.assertEqual(IMPORT_VERSION, 1)
        self.assertEqual(
            DOCUMENT_KEYS,
            (
                "schema",
                "version",
                "import_id",
                "title",
                "entries",
                "groups",
            ),
        )
        self.assertEqual(
            ENTRY_KEYS,
            (
                "entry_key",
                "title",
                "source_references",
                "attributes",
            ),
        )
        self.assertEqual(
            SOURCE_REFERENCE_KEYS,
            ("source", "external_id"),
        )
        self.assertEqual(
            GROUP_KEYS,
            ("group_key", "title", "entry_keys"),
        )

    def test_hybrid_entry_can_reference_multiple_sources(self):
        hybrid = VALID_IMPORT_DOCUMENT["entries"][0]
        references = hybrid["source_references"]

        self.assertEqual(
            {(item["source"], item["external_id"]) for item in references},
            {
                ("smwc", "12345"),
                ("kaizoff", "beginner-hack"),
            },
        )

    def test_local_entry_can_exist_without_external_source(self):
        local_entry = VALID_IMPORT_DOCUMENT["entries"][1]

        self.assertEqual(local_entry["source_references"], [])
        self.assertEqual(
            local_entry["entry_key"],
            "local-training-hack",
        )

    def test_order_is_separate_from_entry_metadata(self):
        for entry in VALID_IMPORT_DOCUMENT["entries"]:
            self.assertNotIn("position", entry)
            self.assertNotIn("group", entry)
            self.assertNotIn("group_key", entry)

        ordered_keys = [
            entry_key
            for group in VALID_IMPORT_DOCUMENT["groups"]
            for entry_key in group["entry_keys"]
        ]
        self.assertEqual(
            ordered_keys,
            [
                "beginner-hack",
                "local-training-hack",
                "advanced-hack",
            ],
        )

    def test_source_names_are_generic_and_extensible(self):
        valid_sources = (
            "smwc",
            "kaizoff",
            "local",
            "custom-json",
            "community.archive",
        )
        for source in valid_sources:
            with self.subTest(source=source):
                self.assertIsNotNone(
                    SOURCE_PATTERN.fullmatch(source)
                )

        for source in (
            "",
            "SMWC",
            "contains spaces",
            "/api/source",
            "x" * 33,
        ):
            with self.subTest(source=source):
                self.assertIsNone(
                    SOURCE_PATTERN.fullmatch(source)
                )

    def test_identifiers_are_opaque_transport_safe_values(self):
        valid = (
            "1",
            "community-list:2026-08",
            "kaizoff.entry-42",
            "0fcb65f2-2298-4f84-b23a-46f2f9020b7a",
        )
        patterns = (
            IMPORT_ID_PATTERN,
            ENTRY_KEY_PATTERN,
            GROUP_KEY_PATTERN,
        )
        for pattern in patterns:
            for value in valid:
                with self.subTest(
                    pattern=pattern.pattern,
                    value=value,
                ):
                    self.assertIsNotNone(
                        pattern.fullmatch(value)
                    )

    def test_attributes_exclude_user_owned_collection_state(self):
        self.assertEqual(
            set(FORBIDDEN_ATTRIBUTE_KEYS),
            {
                "completed",
                "completed_date",
                "completion_date",
                "download_paths",
                "notes",
                "personal_rating",
                "planner",
                "planner_state",
                "rom_paths",
                "save_associations",
                "save_paths",
            },
        )
        attributes = VALID_IMPORT_DOCUMENT["entries"][0][
            "attributes"
        ]
        self.assertTrue(
            set(attributes).isdisjoint(FORBIDDEN_ATTRIBUTE_KEYS)
        )

    def test_valid_document_is_json_round_trip_safe(self):
        encoded = json.dumps(
            VALID_IMPORT_DOCUMENT,
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertEqual(
            json.loads(encoded),
            VALID_IMPORT_DOCUMENT,
        )

    def test_contract_mixin_exposes_required_implementation_tests(self):
        names = {
            name
            for name in dir(BulkCollectionImportContractMixin)
            if name.startswith("test_")
        }

        self.assertEqual(
            names,
            {
                "test_duplicate_entry_group_and_source_ids_are_rejected",
                "test_empty_import_is_valid",
                "test_input_and_projected_documents_are_detached",
                "test_invalid_top_level_documents_are_rejected",
                "test_order_structure_must_cover_each_entry_exactly_once",
                "test_parsed_import_graph_is_immutable",
                "test_serialization_is_stable_compact_json",
                "test_user_owned_collection_state_is_rejected",
                "test_valid_hybrid_import_is_parsed_exactly",
            },
        )


class BulkCollectionImportImplementationTest(
    BulkCollectionImportContractMixin,
    unittest.TestCase,
):
    """Run the reusable specification against production code."""

    def parse_import(self, document):
        return parse_bulk_collection_import(document)

    def import_to_document(self, import_document):
        return bulk_collection_import_to_document(
            import_document
        )

    def serialize_import(self, import_document):
        return serialize_bulk_collection_import(
            import_document
        )

    def assert_contract_error(self, document):
        with self.assertRaises(BulkCollectionImportError):
            parse_bulk_collection_import(document)

    def test_production_constants_match_specification(self):
        self.assertEqual(
            BULK_COLLECTION_IMPORT_SCHEMA,
            IMPORT_SCHEMA,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_VERSION,
            IMPORT_VERSION,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_DOCUMENT_KEYS,
            DOCUMENT_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_ENTRY_KEYS,
            ENTRY_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_SOURCE_REFERENCE_KEYS,
            SOURCE_REFERENCE_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_GROUP_KEYS,
            GROUP_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS,
            set(FORBIDDEN_ATTRIBUTE_KEYS),
        )

    def test_projection_requires_production_document_type(self):
        with self.assertRaises(TypeError):
            bulk_collection_import_to_document(
                VALID_IMPORT_DOCUMENT
            )

    def test_nested_attributes_are_immutable_and_detached(self):
        parsed = parse_bulk_collection_import(
            VALID_IMPORT_DOCUMENT
        )
        attributes = parsed.entries[0].attributes

        with self.assertRaises(TypeError):
            attributes["difficulty"] = "Changed"
        with self.assertRaises(TypeError):
            attributes["authors"][0] = "Changed"

        projected = bulk_collection_import_to_document(parsed)
        projected["entries"][0]["attributes"]["tags"].append(
            "changed"
        )
        self.assertEqual(
            bulk_collection_import_to_document(parsed)[
                "entries"
            ][0]["attributes"]["tags"],
            ["vanilla", "short"],
        )

    def test_non_json_and_non_finite_attributes_are_rejected(self):
        invalid_values = (
            object(),
            b"bytes",
            float("nan"),
            float("inf"),
            float("-inf"),
        )
        for invalid_value in invalid_values:
            document = deepcopy(VALID_IMPORT_DOCUMENT)
            document["entries"][0]["attributes"]["invalid"] = (
                invalid_value
            )
            with self.subTest(invalid_value=invalid_value):
                with self.assertRaises(
                    BulkCollectionImportError
                ):
                    parse_bulk_collection_import(document)


if __name__ == "__main__":
    unittest.main(verbosity=2)
