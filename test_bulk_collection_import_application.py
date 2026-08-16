"""Specification tests for write-ready bulk Collection application planning."""

from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy

from bulk_collection_import_application import (
    BULK_COLLECTION_IMPORT_APPLICATION_ACTIONS,
    BULK_COLLECTION_IMPORT_APPLICATION_SCHEMA,
    BULK_COLLECTION_IMPORT_APPLICATION_VERSION,
    BulkCollectionImportApplicationError,
    build_bulk_collection_import_application_plan,
    bulk_collection_import_application_plan_to_document,
    bulk_collection_import_shared_record_sha256,
    serialize_bulk_collection_import_application_plan,
)

APPLICATION_PLAN_SCHEMA = "smwc-bulk-collection-application-plan"
APPLICATION_PLAN_VERSION = 1
APPLICATION_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "skip",
)
SOURCE_SHA256 = "d" * 64

RESOLUTION_DOCUMENT = {
    "schema": "smwc-bulk-collection-resolution-plan",
    "version": 1,
    "import_id": "application-suite",
    "source_sha256": SOURCE_SHA256,
    "summary": {
        "total": 6,
        "create_record": 2,
        "update_record": 2,
        "no_change": 1,
        "review_required": 0,
        "skip": 1,
    },
    "items": [
        {
            "entry_key": "new-hybrid",
            "action": "create_record",
            "collection_key": None,
            "title_value": "New Hybrid",
            "source_reference_additions": [
                {"source": "smwc", "external_id": "500"},
                {"source": "kaizoff", "external_id": "new-hybrid"},
            ],
            "attributes": {
                "authors": ["Author One"],
                "difficulty": "Kaizo: Beginner",
            },
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "new-local",
            "action": "create_record",
            "collection_key": None,
            "title_value": "New Local",
            "source_reference_additions": [],
            "attributes": {"authors": ["Author Two"]},
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "safe-update",
            "action": "update_record",
            "collection_key": "collection-update",
            "title_value": None,
            "source_reference_additions": [
                {"source": "kaizoff", "external_id": "safe-update"}
            ],
            "attributes": {},
            "attribute_changes": [
                {"field": "difficulty", "value": "Kaizo: Intermediate"}
            ],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "metadata-update",
            "action": "update_record",
            "collection_key": "collection-metadata",
            "title_value": "Metadata Update",
            "source_reference_additions": [],
            "attributes": {},
            "attribute_changes": [{"field": "exit_count", "value": 12}],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "unchanged",
            "action": "no_change",
            "collection_key": "collection-unchanged",
            "title_value": None,
            "source_reference_additions": [],
            "attributes": {},
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [],
        },
        {
            "entry_key": "skipped-conflict",
            "action": "skip",
            "collection_key": None,
            "title_value": None,
            "source_reference_additions": [],
            "attributes": {},
            "attribute_changes": [],
            "conflicts": [],
            "warnings": [
                "identity_review_required",
                "identity_conflict",
                "source_identity_conflict",
            ],
        },
    ],
    "groups": [
        {
            "group_key": "first",
            "title": "First",
            "entry_keys": ["new-hybrid", "new-local", "safe-update"],
        },
        {
            "group_key": "second",
            "title": "Second",
            "entry_keys": [
                "metadata-update",
                "unchanged",
                "skipped-conflict",
            ],
        },
    ],
}

NEW_COLLECTION_KEYS = {
    "new-hybrid": "collection-new-hybrid",
    "new-local": "collection-new-local",
}

COLLECTION_RECORDS = (
    {
        "collection_key": "collection-update",
        "title": "Safe Update",
        "source_references": [{"source": "smwc", "external_id": "700"}],
        "attributes": {"authors": ["Author Three"]},
        "user_state": {
            "completed": True,
            "personal_rating": 5,
            "notes": "must remain outside operation payloads",
        },
    },
    {
        "collection_key": "collection-metadata",
        "title": "Old Metadata Title",
        "source_references": [{"source": "smwc", "external_id": "800"}],
        "attributes": {"authors": ["Author Four"], "exit_count": 10},
        "user_state": {
            "completed": False,
            "save_paths": ["C:/saves/example.srm"],
        },
    },
    {
        "collection_key": "collection-unchanged",
        "title": "Unchanged",
        "source_references": [{"source": "smwc", "external_id": "900"}],
        "attributes": {"authors": ["Author Five"]},
        "user_state": {"planner_state": "playing"},
    },
)


def canonical_shared_record(record):
    return {
        "collection_key": record["collection_key"],
        "title": record["title"],
        "source_references": record["source_references"],
        "attributes": record["attributes"],
    }


def shared_record_sha256(record):
    payload = json.dumps(
        canonical_shared_record(record),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class BulkCollectionImportApplicationContractMixin:
    """Reusable behavior suite for a write-ready application planner."""

    def build_application_plan(self, resolution_document, new_collection_keys, collection_records):
        raise NotImplementedError

    def application_to_document(self, plan):
        raise NotImplementedError

    def serialize_application(self, plan):
        raise NotImplementedError

    def assert_application_error(self, resolution_document, new_collection_keys, collection_records):
        raise NotImplementedError

    def _build(self, **overrides):
        values = {
            "resolution_document": deepcopy(RESOLUTION_DOCUMENT),
            "new_collection_keys": deepcopy(NEW_COLLECTION_KEYS),
            "collection_records": deepcopy(COLLECTION_RECORDS),
        }
        values.update(overrides)
        return self.build_application_plan(**values)

    def test_plan_is_bound_to_import_and_source_hash(self):
        plan = self._build()
        self.assertEqual(plan.import_id, "application-suite")
        self.assertEqual(plan.source_sha256, SOURCE_SHA256)

    def test_create_rows_require_explicit_new_collection_keys(self):
        plan = self._build()
        creates = [item for item in plan.operations if item.action == "create_record"]
        self.assertEqual(
            tuple(item.collection_key for item in creates),
            ("collection-new-hybrid", "collection-new-local"),
        )
        missing = deepcopy(NEW_COLLECTION_KEYS)
        missing.pop("new-local")
        self.assert_application_error(
            deepcopy(RESOLUTION_DOCUMENT), missing, deepcopy(COLLECTION_RECORDS)
        )

    def test_new_collection_keys_must_be_unique_and_unused(self):
        duplicate = {
            "new-hybrid": "collection-new",
            "new-local": "collection-new",
        }
        self.assert_application_error(
            deepcopy(RESOLUTION_DOCUMENT), duplicate, deepcopy(COLLECTION_RECORDS)
        )
        existing = deepcopy(NEW_COLLECTION_KEYS)
        existing["new-local"] = "collection-update"
        self.assert_application_error(
            deepcopy(RESOLUTION_DOCUMENT), existing, deepcopy(COLLECTION_RECORDS)
        )

    def test_extra_new_collection_key_assignments_are_rejected(self):
        assignments = deepcopy(NEW_COLLECTION_KEYS)
        assignments["safe-update"] = "collection-extra"
        self.assert_application_error(
            deepcopy(RESOLUTION_DOCUMENT), assignments, deepcopy(COLLECTION_RECORDS)
        )

    def test_create_operations_carry_only_imported_shared_data(self):
        first = self._build().operations[0]
        self.assertEqual(first.action, "create_record")
        self.assertEqual(first.title_value, "New Hybrid")
        self.assertEqual(
            tuple((r.source, r.external_id) for r in first.source_references),
            (("smwc", "500"), ("kaizoff", "new-hybrid")),
        )
        self.assertEqual(
            dict(first.attributes),
            {"authors": ("Author One",), "difficulty": "Kaizo: Beginner"},
        )
        self.assertIsNone(first.expected_shared_sha256)

    def test_update_operations_are_bound_to_existing_shared_state(self):
        plan = self._build()
        updates = {
            item.entry_key: item
            for item in plan.operations
            if item.action == "update_record"
        }
        self.assertEqual(
            updates["safe-update"].expected_shared_sha256,
            shared_record_sha256(COLLECTION_RECORDS[0]),
        )
        self.assertEqual(
            updates["metadata-update"].expected_shared_sha256,
            shared_record_sha256(COLLECTION_RECORDS[1]),
        )

    def test_no_change_rows_are_also_fingerprinted(self):
        unchanged = next(
            item for item in self._build().operations
            if item.entry_key == "unchanged"
        )
        self.assertEqual(
            unchanged.expected_shared_sha256,
            shared_record_sha256(COLLECTION_RECORDS[2]),
        )

    def test_skip_rows_have_no_write_target_or_fingerprint(self):
        skipped = next(
            item for item in self._build().operations
            if item.action == "skip"
        )
        self.assertIsNone(skipped.collection_key)
        self.assertIsNone(skipped.expected_shared_sha256)
        self.assertIsNone(skipped.title_value)
        self.assertEqual(skipped.attribute_changes, ())

    def test_existing_targets_must_be_present_exactly_once(self):
        missing = tuple(
            record for record in COLLECTION_RECORDS
            if record["collection_key"] != "collection-update"
        )
        self.assert_application_error(
            deepcopy(RESOLUTION_DOCUMENT), deepcopy(NEW_COLLECTION_KEYS), missing
        )
        duplicate = COLLECTION_RECORDS + (deepcopy(COLLECTION_RECORDS[0]),)
        self.assert_application_error(
            deepcopy(RESOLUTION_DOCUMENT), deepcopy(NEW_COLLECTION_KEYS), duplicate
        )

    def test_unrelated_collection_records_are_allowed_but_ignored(self):
        records = COLLECTION_RECORDS + ({
            "collection_key": "collection-unrelated",
            "title": "Unrelated",
            "source_references": [],
            "attributes": {},
            "user_state": {"notes": "not part of this import"},
        },)
        plan = self._build(collection_records=records)
        self.assertEqual(len(plan.operations), 6)
        self.assertNotIn(
            "collection-unrelated",
            tuple(
                item.collection_key for item in plan.operations
                if item.collection_key is not None
            ),
        )

    def test_unresolved_review_rows_block_application_planning(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["items"][5]["action"] = "review_required"
        document["summary"]["skip"] = 0
        document["summary"]["review_required"] = 1
        self.assert_application_error(
            document, deepcopy(NEW_COLLECTION_KEYS), deepcopy(COLLECTION_RECORDS)
        )

    def test_resolution_summary_must_match_actual_actions(self):
        document = deepcopy(RESOLUTION_DOCUMENT)
        document["summary"]["update_record"] = 99
        self.assert_application_error(
            document, deepcopy(NEW_COLLECTION_KEYS), deepcopy(COLLECTION_RECORDS)
        )

    def test_operation_and_group_order_are_preserved(self):
        plan = self._build()
        self.assertEqual(
            tuple(item.entry_key for item in plan.operations),
            tuple(item["entry_key"] for item in RESOLUTION_DOCUMENT["items"]),
        )
        self.assertEqual(
            tuple((group.group_key, group.entry_keys) for group in plan.groups),
            tuple(
                (group["group_key"], tuple(group["entry_keys"]))
                for group in RESOLUTION_DOCUMENT["groups"]
            ),
        )

    def test_user_owned_state_never_enters_application_plan(self):
        serialized = self.serialize_application(self._build())
        for forbidden in (
            "completed", "personal_rating", "notes", "save_paths",
            "rom_paths", "planner_state",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_plan_is_immutable_and_projection_is_detached(self):
        plan = self._build()
        with self.assertRaises((AttributeError, TypeError)):
            plan.import_id = "changed"
        with self.assertRaises((AttributeError, TypeError)):
            plan.operations[0].collection_key = "changed"
        projected = self.application_to_document(plan)
        projected["summary"]["create_record"] = 99
        projected["operations"][0]["attributes"]["authors"][0] = "Changed"
        clean = self.application_to_document(plan)
        self.assertEqual(clean["summary"]["create_record"], 2)
        self.assertEqual(
            clean["operations"][0]["attributes"]["authors"],
            ["Author One"],
        )

    def test_serialization_is_stable_compact_json(self):
        serialized = self.serialize_application(self._build())
        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )


class BulkCollectionImportApplicationSpecificationTest(unittest.TestCase):
    """Validate the write-ready application-plan contract itself."""

    def test_schema_version_and_actions_are_fixed(self):
        self.assertEqual(
            APPLICATION_PLAN_SCHEMA,
            "smwc-bulk-collection-application-plan",
        )
        self.assertEqual(APPLICATION_PLAN_VERSION, 1)
        self.assertEqual(
            APPLICATION_ACTIONS,
            ("create_record", "update_record", "no_change", "skip"),
        )

    def test_existing_fingerprint_excludes_user_owned_state(self):
        first = COLLECTION_RECORDS[0]
        changed = deepcopy(first)
        changed["user_state"]["notes"] = "different"
        changed["user_state"]["completed"] = False
        self.assertEqual(shared_record_sha256(first), shared_record_sha256(changed))

    def test_existing_fingerprint_changes_with_shared_metadata(self):
        first = COLLECTION_RECORDS[0]
        changed = deepcopy(first)
        changed["attributes"]["difficulty"] = "Kaizo: Expert"
        self.assertNotEqual(shared_record_sha256(first), shared_record_sha256(changed))

    def test_no_review_required_action_is_write_ready(self):
        self.assertNotIn("review_required", APPLICATION_ACTIONS)

    def test_plan_is_not_itself_a_write_api(self):
        for action in ("save", "persist", "delete", "overwrite"):
            self.assertNotIn(action, APPLICATION_ACTIONS)


class BulkCollectionImportApplicationImplementationTest(
    BulkCollectionImportApplicationContractMixin,
    unittest.TestCase,
):
    """Run the application-plan contract against production code."""

    def build_application_plan(
        self,
        resolution_document,
        new_collection_keys,
        collection_records,
    ):
        return build_bulk_collection_import_application_plan(
            resolution_document,
            new_collection_keys,
            collection_records,
        )

    def application_to_document(self, plan):
        return bulk_collection_import_application_plan_to_document(
            plan
        )

    def serialize_application(self, plan):
        return serialize_bulk_collection_import_application_plan(
            plan
        )

    def assert_application_error(
        self,
        resolution_document,
        new_collection_keys,
        collection_records,
    ):
        with self.assertRaises(BulkCollectionImportApplicationError):
            build_bulk_collection_import_application_plan(
                resolution_document,
                new_collection_keys,
                collection_records,
            )

    def test_production_constants_match_specification(self):
        self.assertEqual(
            BULK_COLLECTION_IMPORT_APPLICATION_SCHEMA,
            APPLICATION_PLAN_SCHEMA,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_APPLICATION_VERSION,
            APPLICATION_PLAN_VERSION,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_APPLICATION_ACTIONS,
            APPLICATION_ACTIONS,
        )

    def test_production_shared_fingerprint_matches_contract(self):
        for record in COLLECTION_RECORDS:
            with self.subTest(
                collection_key=record["collection_key"]
            ):
                self.assertEqual(
                    bulk_collection_import_shared_record_sha256(
                        record
                    ),
                    shared_record_sha256(record),
                )

    def test_user_state_changes_do_not_change_production_fingerprint(self):
        record = deepcopy(COLLECTION_RECORDS[0])
        changed = deepcopy(record)
        changed["user_state"]["completed"] = False
        changed["user_state"]["notes"] = "Changed"

        self.assertEqual(
            bulk_collection_import_shared_record_sha256(record),
            bulk_collection_import_shared_record_sha256(changed),
        )

    def test_nonfinite_shared_state_is_rejected(self):
        records = list(deepcopy(COLLECTION_RECORDS))
        records[0]["attributes"]["score"] = float("nan")

        self.assert_application_error(
            deepcopy(RESOLUTION_DOCUMENT),
            deepcopy(NEW_COLLECTION_KEYS),
            tuple(records),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
