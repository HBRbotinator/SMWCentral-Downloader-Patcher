"""Specification tests for real v5.1 bulk-import Collection key allocation."""

from __future__ import annotations

import json
import re
import unittest
from copy import deepcopy

from bulk_collection_import_key_allocation import (
    COLLECTION_IMPORT_LOCAL_KEY_HEX_LENGTH as PRODUCTION_LOCAL_KEY_HEX_LENGTH,
    COLLECTION_IMPORT_LOCAL_KEY_PREFIX as PRODUCTION_LOCAL_KEY_PREFIX,
    BulkCollectionImportKeyAllocationError,
    allocate_bulk_collection_import_keys,
    build_v5_1_bulk_collection_import_application_plan,
    bulk_collection_import_key_assignments_to_document,
    serialize_bulk_collection_import_key_assignments,
)


COLLECTION_IMPORT_LOCAL_KEY_PREFIX = "usr_import_"
COLLECTION_IMPORT_LOCAL_KEY_HEX_LENGTH = 16

SOURCE_SHA256 = "a" * 64

RESOLUTION_DOCUMENT = {
    "schema": "smwc-bulk-collection-resolution-plan",
    "version": 1,
    "import_id": "key-allocation-suite",
    "source_sha256": SOURCE_SHA256,
    "summary": {
        "total": 6,
        "create_record": 4,
        "update_record": 1,
        "no_change": 1,
        "review_required": 0,
        "skip": 0,
    },
    "items": [
        {
            "entry_key": "kaizoff-smwc-mirror",
            "action": "create_record",
            "collection_key": None,
            "title_value": "Mirrored Hack",
            "source_reference_additions": [
                {
                    "source": "kaizoff",
                    "external_id": "kaizoff-record-abc",
                },
                {
                    "source": "smwc",
                    "external_id": "12345",
                },
            ],
            "attributes": {
                "authors": ["Author One"],
            },
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "smwc-direct",
            "action": "create_record",
            "collection_key": None,
            "title_value": "Direct SMWC Hack",
            "source_reference_additions": [
                {
                    "source": "smwc",
                    "external_id": "67890",
                }
            ],
            "attributes": {
                "authors": ["Author Two"],
            },
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "kaizoff-only",
            "action": "create_record",
            "collection_key": None,
            "title_value": "KaizOFF Only Hack",
            "source_reference_additions": [
                {
                    "source": "kaizoff",
                    "external_id": "kaizoff-only-42",
                }
            ],
            "attributes": {
                "authors": ["Author Three"],
            },
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "source-less",
            "action": "create_record",
            "collection_key": None,
            "title_value": "Source-less Hack",
            "source_reference_additions": [],
            "attributes": {
                "authors": ["Author Four"],
            },
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "existing-update",
            "action": "update_record",
            "collection_key": "11111",
            "title_value": None,
            "source_reference_additions": [],
            "attributes": {},
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "existing-no-change",
            "action": "no_change",
            "collection_key": "usr_0",
            "title_value": None,
            "source_reference_additions": [],
            "attributes": {},
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
    ],
    "groups": [
        {
            "group_key": "all",
            "title": "All",
            "entry_keys": [
                "kaizoff-smwc-mirror",
                "smwc-direct",
                "kaizoff-only",
                "source-less",
                "existing-update",
                "existing-no-change",
            ],
        }
    ],
}

EXISTING_COLLECTION_KEYS = (
    "11111",
    "usr_0",
    "usr_save_0123456789abcdef",
)


class BulkCollectionImportKeyAllocationContractMixin:
    """Reusable behavior suite for v5.1 create-key allocation."""

    def allocate_keys(
        self,
        resolution_document,
        existing_collection_keys,
    ):
        raise NotImplementedError

    def assignments_to_document(self, assignments):
        raise NotImplementedError

    def serialize_assignments(self, assignments):
        raise NotImplementedError

    def assert_allocation_error(
        self,
        resolution_document,
        existing_collection_keys,
    ):
        raise NotImplementedError

    def _allocate(self, **overrides):
        values = {
            "resolution_document": deepcopy(RESOLUTION_DOCUMENT),
            "existing_collection_keys": tuple(
                EXISTING_COLLECTION_KEYS
            ),
        }
        values.update(overrides)
        return self.allocate_keys(**values)

    def test_only_create_rows_receive_keys(self):
        assignments = self._allocate()

        self.assertEqual(
            tuple(assignments),
            (
                "kaizoff-smwc-mirror",
                "smwc-direct",
                "kaizoff-only",
                "source-less",
            ),
        )

    def test_smwc_identity_wins_even_when_kaizoff_is_provider(self):
        assignments = self._allocate()

        self.assertEqual(
            assignments["kaizoff-smwc-mirror"],
            "12345",
        )

    def test_direct_smwc_create_uses_numeric_smwc_collection_key(self):
        assignments = self._allocate()

        self.assertEqual(
            assignments["smwc-direct"],
            "67890",
        )

    def test_source_reference_order_does_not_change_smwc_choice(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][0]["source_reference_additions"].reverse()

        assignments = self._allocate(
            resolution_document=document
        )

        self.assertEqual(
            assignments["kaizoff-smwc-mirror"],
            "12345",
        )

    def test_kaizoff_only_entry_uses_stable_local_import_key(self):
        assignments = self._allocate()
        key = assignments["kaizoff-only"]

        self.assertRegex(
            key,
            r"^usr_import_[0-9a-f]{16}$",
        )

        second = self._allocate()
        self.assertEqual(
            second["kaizoff-only"],
            key,
        )

    def test_kaizoff_only_key_is_source_identity_based(self):
        original = self._allocate()["kaizoff-only"]

        document = deepcopy(RESOLUTION_DOCUMENT)
        item = document["items"][2]
        item["title_value"] = "Renamed Display Title"
        item["attributes"]["authors"] = ["Different Display Author"]

        changed_display_metadata = self._allocate(
            resolution_document=document
        )["kaizoff-only"]

        self.assertEqual(
            changed_display_metadata,
            original,
        )

    def test_kaizoff_external_id_change_changes_local_key(self):
        original = self._allocate()["kaizoff-only"]

        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][2]["source_reference_additions"][0][
            "external_id"
        ] = "kaizoff-only-43"

        changed = self._allocate(
            resolution_document=document
        )["kaizoff-only"]

        self.assertNotEqual(changed, original)

    def test_source_less_entry_is_stable_for_same_import_entry(self):
        first = self._allocate()["source-less"]
        second = self._allocate()["source-less"]

        self.assertRegex(
            first,
            r"^usr_import_[0-9a-f]{16}$",
        )
        self.assertEqual(first, second)

    def test_source_less_key_is_bound_to_import_and_entry_identity(self):
        original = self._allocate()["source-less"]

        changed_import = deepcopy(RESOLUTION_DOCUMENT)
        changed_import["import_id"] = "another-import"
        changed_import["source_sha256"] = "b" * 64

        changed = self._allocate(
            resolution_document=changed_import
        )["source-less"]

        self.assertNotEqual(changed, original)

    def test_existing_numeric_smwc_key_blocks_create(self):
        self.assert_allocation_error(
            deepcopy(RESOLUTION_DOCUMENT),
            EXISTING_COLLECTION_KEYS + ("12345",),
        )

    def test_existing_generated_local_key_blocks_create(self):
        assignments = self._allocate()
        generated = assignments["kaizoff-only"]

        self.assert_allocation_error(
            deepcopy(RESOLUTION_DOCUMENT),
            EXISTING_COLLECTION_KEYS + (generated,),
        )

    def test_duplicate_allocated_keys_are_rejected(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][1]["source_reference_additions"] = [
            {
                "source": "smwc",
                "external_id": "12345",
            }
        ]

        self.assert_allocation_error(
            document,
            EXISTING_COLLECTION_KEYS,
        )

    def test_distinct_smwc_references_on_one_create_fail_closed(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][0]["source_reference_additions"].append(
            {
                "source": "smwc",
                "external_id": "54321",
            }
        )

        self.assert_allocation_error(
            document,
            EXISTING_COLLECTION_KEYS,
        )

    def test_smwc_external_id_must_be_decimal(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][1]["source_reference_additions"][0][
            "external_id"
        ] = "smwc-67890"

        self.assert_allocation_error(
            document,
            EXISTING_COLLECTION_KEYS,
        )

    def test_smwc_external_id_is_canonicalized_without_leading_zeroes(
        self,
    ):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][1]["source_reference_additions"][0][
            "external_id"
        ] = "00067890"

        assignments = self._allocate(
            resolution_document=document
        )

        self.assertEqual(
            assignments["smwc-direct"],
            "67890",
        )

    def test_zero_is_not_a_valid_smwc_collection_id(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][1]["source_reference_additions"][0][
            "external_id"
        ] = "0"

        self.assert_allocation_error(
            document,
            EXISTING_COLLECTION_KEYS,
        )

    def test_usr_and_usr_save_namespaces_are_not_allocated(self):
        assignments = self._allocate()

        for entry_key in ("kaizoff-only", "source-less"):
            key = assignments[entry_key]
            self.assertTrue(key.startswith("usr_import_"))
            self.assertFalse(
                re.fullmatch(r"usr_\d+", key)
            )
            self.assertFalse(
                key.startswith("usr_save_")
            )

    def test_unresolved_review_rows_block_key_allocation(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][5]["action"] = "review_required"
        document["summary"]["no_change"] = 0
        document["summary"]["review_required"] = 1

        self.assert_allocation_error(
            document,
            EXISTING_COLLECTION_KEYS,
        )

    def test_resolution_source_hash_must_be_exact(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["source_sha256"] = "invalid"

        self.assert_allocation_error(
            document,
            EXISTING_COLLECTION_KEYS,
        )

    def test_assignments_are_immutable_and_projection_detached(self):
        assignments = self._allocate()

        with self.assertRaises(TypeError):
            assignments["kaizoff-only"] = "changed"

        document = self.assignments_to_document(assignments)
        document["kaizoff-only"] = "changed"

        clean = self.assignments_to_document(assignments)
        self.assertNotEqual(
            clean["kaizoff-only"],
            "changed",
        )

    def test_serialization_is_stable_compact_json(self):
        assignments = self._allocate()
        serialized = self.serialize_assignments(assignments)

        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )


class BulkCollectionImportKeyAllocationSpecificationTest(
    unittest.TestCase
):
    """Lock repository-specific allocation policy."""

    def test_local_prefix_is_reserved_for_bulk_import(self):
        self.assertEqual(
            COLLECTION_IMPORT_LOCAL_KEY_PREFIX,
            "usr_import_",
        )
        self.assertEqual(
            COLLECTION_IMPORT_LOCAL_KEY_HEX_LENGTH,
            16,
        )

    def test_existing_manual_and_save_namespaces_remain_distinct(self):
        self.assertTrue("usr_0".startswith("usr_"))
        self.assertTrue(
            "usr_save_0123456789abcdef".startswith("usr_save_")
        )
        self.assertFalse(
            "usr_0".startswith(COLLECTION_IMPORT_LOCAL_KEY_PREFIX)
        )
        self.assertFalse(
            "usr_save_0123456789abcdef".startswith(
                COLLECTION_IMPORT_LOCAL_KEY_PREFIX
            )
        )

    def test_mirrored_fixture_contains_both_provider_and_identity_refs(
        self,
    ):
        references = RESOLUTION_DOCUMENT["items"][0][
            "source_reference_additions"
        ]

        self.assertEqual(
            {item["source"] for item in references},
            {"kaizoff", "smwc"},
        )

    def test_smwc_is_identity_authority_when_present(self):
        mirrored = RESOLUTION_DOCUMENT["items"][0]

        self.assertIn(
            {
                "source": "smwc",
                "external_id": "12345",
            },
            mirrored["source_reference_additions"],
        )

    def test_kaizoff_only_fixture_has_no_assumed_smwc_identity(self):
        references = RESOLUTION_DOCUMENT["items"][2][
            "source_reference_additions"
        ]

        self.assertEqual(
            references,
            [
                {
                    "source": "kaizoff",
                    "external_id": "kaizoff-only-42",
                }
            ],
        )


APPLICATION_COLLECTION_RECORDS = (
    {
        "collection_key": "11111",
        "title": "Existing Update",
        "source_references": [
            {"source": "smwc", "external_id": "11111"}
        ],
        "attributes": {},
        "user_state": {"notes": "ignored by generic planner"},
    },
    {
        "collection_key": "usr_0",
        "title": "Existing No Change",
        "source_references": [],
        "attributes": {},
        "user_state": {"completed": True},
    },
)


class BulkCollectionImportKeyAllocationImplementationTest(
    BulkCollectionImportKeyAllocationContractMixin,
    unittest.TestCase,
):
    """Run the Commit 108 allocation contract against production."""

    def allocate_keys(
        self,
        resolution_document,
        existing_collection_keys,
    ):
        return allocate_bulk_collection_import_keys(
            resolution_document,
            existing_collection_keys,
        )

    def assignments_to_document(self, assignments):
        return bulk_collection_import_key_assignments_to_document(
            assignments
        )

    def serialize_assignments(self, assignments):
        return serialize_bulk_collection_import_key_assignments(
            assignments
        )

    def assert_allocation_error(
        self,
        resolution_document,
        existing_collection_keys,
    ):
        with self.assertRaises(BulkCollectionImportKeyAllocationError):
            allocate_bulk_collection_import_keys(
                resolution_document,
                existing_collection_keys,
            )

    def test_production_constants_match_specification(self):
        self.assertEqual(
            PRODUCTION_LOCAL_KEY_PREFIX,
            COLLECTION_IMPORT_LOCAL_KEY_PREFIX,
        )
        self.assertEqual(
            PRODUCTION_LOCAL_KEY_HEX_LENGTH,
            COLLECTION_IMPORT_LOCAL_KEY_HEX_LENGTH,
        )

    def test_provider_reference_order_does_not_change_local_hash(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        item = document["items"][2]
        item["source_reference_additions"].append(
            {
                "source": "catalogue-mirror",
                "external_id": "mirror-42",
            }
        )
        first = allocate_bulk_collection_import_keys(
            document,
            EXISTING_COLLECTION_KEYS,
        )["kaizoff-only"]

        item["source_reference_additions"].reverse()
        second = allocate_bulk_collection_import_keys(
            document,
            EXISTING_COLLECTION_KEYS,
        )["kaizoff-only"]

        self.assertEqual(first, second)

    def test_application_helper_feeds_allocator_into_generic_planner(self):
        plan = build_v5_1_bulk_collection_import_application_plan(
            deepcopy(RESOLUTION_DOCUMENT),
            deepcopy(APPLICATION_COLLECTION_RECORDS),
        )

        creates = {
            operation.entry_key: operation.collection_key
            for operation in plan.operations
            if operation.action == "create_record"
        }

        self.assertEqual(
            creates["kaizoff-smwc-mirror"],
            "12345",
        )
        self.assertEqual(
            creates["smwc-direct"],
            "67890",
        )
        self.assertRegex(
            creates["kaizoff-only"],
            r"^usr_import_[0-9a-f]{16}$",
        )
        self.assertRegex(
            creates["source-less"],
            r"^usr_import_[0-9a-f]{16}$",
        )

    def test_application_helper_preserves_existing_operation_targets(self):
        plan = build_v5_1_bulk_collection_import_application_plan(
            deepcopy(RESOLUTION_DOCUMENT),
            deepcopy(APPLICATION_COLLECTION_RECORDS),
        )

        existing = {
            operation.entry_key: operation.collection_key
            for operation in plan.operations
            if operation.action in ("update_record", "no_change")
        }

        self.assertEqual(
            existing,
            {
                "existing-update": "11111",
                "existing-no-change": "usr_0",
            },
        )

    def test_application_helper_rejects_existing_smwc_collision(self):
        records = list(deepcopy(APPLICATION_COLLECTION_RECORDS))
        records.append(
            {
                "collection_key": "12345",
                "title": "Already Exists",
                "source_references": [
                    {"source": "smwc", "external_id": "12345"}
                ],
                "attributes": {},
                "user_state": {},
            }
        )

        with self.assertRaises(BulkCollectionImportKeyAllocationError):
            build_v5_1_bulk_collection_import_application_plan(
                deepcopy(RESOLUTION_DOCUMENT),
                tuple(records),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
