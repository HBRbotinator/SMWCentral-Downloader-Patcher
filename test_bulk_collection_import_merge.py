"""Specification tests for bulk Collection merge policy."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy

from bulk_collection_import import (
    parse_bulk_collection_import,
)
from bulk_collection_import_merge import (
    BULK_COLLECTION_IMPORT_MERGE_ACTIONS,
    BULK_COLLECTION_IMPORT_MERGE_GROUP_KEYS,
    BULK_COLLECTION_IMPORT_MERGE_ITEM_KEYS,
    BULK_COLLECTION_IMPORT_MERGE_PLAN_KEYS,
    BULK_COLLECTION_IMPORT_MERGE_SCHEMA,
    BULK_COLLECTION_IMPORT_MERGE_SUMMARY_KEYS,
    BULK_COLLECTION_IMPORT_MERGE_VALUE_ACTIONS,
    BULK_COLLECTION_IMPORT_MERGE_VALUE_DECISION_KEYS,
    BULK_COLLECTION_IMPORT_MERGE_VERSION,
    BulkCollectionImportMergeError,
    build_bulk_collection_import_merge_plan,
    bulk_collection_import_merge_plan_to_document,
    serialize_bulk_collection_import_merge_plan,
)
from bulk_collection_import_preview import (
    parse_bulk_collection_import_preview,
)


MERGE_PLAN_SCHEMA = "smwc-bulk-collection-merge-plan"
MERGE_PLAN_VERSION = 1

MERGE_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "review_required",
)
VALUE_ACTIONS = (
    "set_new",
    "add_missing",
    "unchanged",
    "review_conflict",
)

PLAN_KEYS = (
    "schema",
    "version",
    "import_id",
    "summary",
    "items",
    "groups",
)
SUMMARY_KEYS = (
    "total",
    "create_record",
    "update_record",
    "no_change",
    "review_required",
)
ITEM_KEYS = (
    "entry_key",
    "action",
    "collection_keys",
    "title_decision",
    "source_reference_additions",
    "attribute_decisions",
    "warnings",
)
VALUE_DECISION_KEYS = (
    "field",
    "action",
    "existing_value",
    "imported_value",
)
GROUP_KEYS = (
    "group_key",
    "title",
    "entry_keys",
)

IMPORT_DOCUMENT = {
    "schema": "smwc-bulk-collection-import",
    "version": 1,
    "import_id": "merge-policy-suite",
    "title": "Merge policy suite",
    "entries": [
        {
            "entry_key": "safe-update",
            "title": "Safe Update",
            "source_references": [
                {"source": "smwc", "external_id": "100"},
                {"source": "kaizoff", "external_id": "safe-update"},
            ],
            "attributes": {
                "authors": ["Author One"],
                "difficulty": "Kaizo: Beginner",
            },
        },
        {
            "entry_key": "unchanged",
            "title": "Unchanged Hack",
            "source_references": [
                {"source": "smwc", "external_id": "101"}
            ],
            "attributes": {
                "authors": ["Author Two"],
                "difficulty": "Kaizo: Intermediate",
            },
        },
        {
            "entry_key": "new-entry",
            "title": "Brand New Hack",
            "source_references": [
                {
                    "source": "kaizoff",
                    "external_id": "brand-new-hack",
                }
            ],
            "attributes": {
                "authors": ["New Author"],
                "difficulty": "Kaizo: Beginner",
            },
        },
        {
            "entry_key": "metadata-conflict",
            "title": "Conflict Hack",
            "source_references": [
                {"source": "smwc", "external_id": "102"}
            ],
            "attributes": {
                "authors": ["Conflict Author"],
                "exit_count": 12,
            },
        },
        {
            "entry_key": "identity-review",
            "title": "Shared Title",
            "source_references": [],
            "attributes": {
                "authors": ["Shared Author"],
            },
        },
    ],
    "groups": [
        {
            "group_key": "ready",
            "title": "Ready",
            "entry_keys": [
                "safe-update",
                "unchanged",
                "new-entry",
            ],
        },
        {
            "group_key": "review",
            "title": "Review",
            "entry_keys": [
                "metadata-conflict",
                "identity-review",
            ],
        },
    ],
}

PREVIEW_DOCUMENT = {
    "schema": "smwc-bulk-collection-preview-plan",
    "version": 1,
    "import_id": "merge-policy-suite",
    "title": "Merge policy suite",
    "summary": {
        "total": 5,
        "add_new": 1,
        "match_existing": 3,
        "review_required": 1,
    },
    "items": [
        {
            "entry_key": "safe-update",
            "title": "Safe Update",
            "outcome": "match_existing",
            "resolution_status": "matched_source",
            "collection_keys": ["collection-safe"],
            "proposed_source_references": [
                {
                    "source": "kaizoff",
                    "external_id": "safe-update",
                }
            ],
            "warnings": [],
        },
        {
            "entry_key": "unchanged",
            "title": "Unchanged Hack",
            "outcome": "match_existing",
            "resolution_status": "matched_source",
            "collection_keys": ["collection-unchanged"],
            "proposed_source_references": [],
            "warnings": [],
        },
        {
            "entry_key": "new-entry",
            "title": "Brand New Hack",
            "outcome": "add_new",
            "resolution_status": "new",
            "collection_keys": [],
            "proposed_source_references": [],
            "warnings": [],
        },
        {
            "entry_key": "metadata-conflict",
            "title": "Conflict Hack",
            "outcome": "match_existing",
            "resolution_status": "matched_source",
            "collection_keys": ["collection-conflict"],
            "proposed_source_references": [],
            "warnings": [],
        },
        {
            "entry_key": "identity-review",
            "title": "Shared Title",
            "outcome": "review_required",
            "resolution_status": "ambiguous",
            "collection_keys": [
                "collection-shared-a",
                "collection-shared-b",
            ],
            "proposed_source_references": [],
            "warnings": [],
        },
    ],
    "groups": deepcopy(IMPORT_DOCUMENT["groups"]),
}

COLLECTION_RECORDS = (
    {
        "collection_key": "collection-safe",
        "title": "Safe Update",
        "source_references": [
            {"source": "smwc", "external_id": "100"}
        ],
        "attributes": {
            "authors": ["Author One"],
            "release_date": "2025-11-01",
        },
        "user_state": {
            "completed": True,
            "completion_date": "2026-02-03",
            "personal_rating": 5,
            "notes": "Keep this note",
            "planner_state": "playing",
            "save_paths": ["C:/Saves/safe-update.srm"],
            "rom_paths": ["C:/Roms/safe-update.smc"],
        },
    },
    {
        "collection_key": "collection-unchanged",
        "title": "Unchanged Hack",
        "source_references": [
            {"source": "smwc", "external_id": "101"}
        ],
        "attributes": {
            "authors": ["Author Two"],
            "difficulty": "Kaizo: Intermediate",
            "release_date": "2025-08-10",
        },
        "user_state": {
            "completed": False,
            "personal_rating": 4,
            "notes": "Existing note",
        },
    },
    {
        "collection_key": "collection-conflict",
        "title": "Conflict Hack",
        "source_references": [
            {"source": "smwc", "external_id": "102"}
        ],
        "attributes": {
            "authors": ["Conflict Author"],
            "exit_count": 10,
            "release_date": "2024-04-20",
        },
        "user_state": {
            "completed": True,
            "personal_rating": 3,
            "save_paths": ["C:/Saves/conflict.srm"],
        },
    },
)

EXPECTED_MERGE_DOCUMENT = {
    "schema": MERGE_PLAN_SCHEMA,
    "version": MERGE_PLAN_VERSION,
    "import_id": "merge-policy-suite",
    "summary": {
        "total": 5,
        "create_record": 1,
        "update_record": 1,
        "no_change": 1,
        "review_required": 2,
    },
    "items": [
        {
            "entry_key": "safe-update",
            "action": "update_record",
            "collection_keys": ["collection-safe"],
            "title_decision": {
                "field": "title",
                "action": "unchanged",
                "existing_value": "Safe Update",
                "imported_value": "Safe Update",
            },
            "source_reference_additions": [
                {
                    "source": "kaizoff",
                    "external_id": "safe-update",
                }
            ],
            "attribute_decisions": [
                {
                    "field": "authors",
                    "action": "unchanged",
                    "existing_value": ["Author One"],
                    "imported_value": ["Author One"],
                },
                {
                    "field": "difficulty",
                    "action": "add_missing",
                    "existing_value": None,
                    "imported_value": "Kaizo: Beginner",
                },
            ],
            "warnings": [],
        },
        {
            "entry_key": "unchanged",
            "action": "no_change",
            "collection_keys": ["collection-unchanged"],
            "title_decision": {
                "field": "title",
                "action": "unchanged",
                "existing_value": "Unchanged Hack",
                "imported_value": "Unchanged Hack",
            },
            "source_reference_additions": [],
            "attribute_decisions": [
                {
                    "field": "authors",
                    "action": "unchanged",
                    "existing_value": ["Author Two"],
                    "imported_value": ["Author Two"],
                },
                {
                    "field": "difficulty",
                    "action": "unchanged",
                    "existing_value": "Kaizo: Intermediate",
                    "imported_value": "Kaizo: Intermediate",
                },
            ],
            "warnings": [],
        },
        {
            "entry_key": "new-entry",
            "action": "create_record",
            "collection_keys": [],
            "title_decision": {
                "field": "title",
                "action": "set_new",
                "existing_value": None,
                "imported_value": "Brand New Hack",
            },
            "source_reference_additions": [
                {
                    "source": "kaizoff",
                    "external_id": "brand-new-hack",
                }
            ],
            "attribute_decisions": [
                {
                    "field": "authors",
                    "action": "set_new",
                    "existing_value": None,
                    "imported_value": ["New Author"],
                },
                {
                    "field": "difficulty",
                    "action": "set_new",
                    "existing_value": None,
                    "imported_value": "Kaizo: Beginner",
                },
            ],
            "warnings": [],
        },
        {
            "entry_key": "metadata-conflict",
            "action": "review_required",
            "collection_keys": ["collection-conflict"],
            "title_decision": {
                "field": "title",
                "action": "unchanged",
                "existing_value": "Conflict Hack",
                "imported_value": "Conflict Hack",
            },
            "source_reference_additions": [],
            "attribute_decisions": [
                {
                    "field": "authors",
                    "action": "unchanged",
                    "existing_value": ["Conflict Author"],
                    "imported_value": ["Conflict Author"],
                },
                {
                    "field": "exit_count",
                    "action": "review_conflict",
                    "existing_value": 10,
                    "imported_value": 12,
                },
            ],
            "warnings": ["metadata_conflict"],
        },
        {
            "entry_key": "identity-review",
            "action": "review_required",
            "collection_keys": [
                "collection-shared-a",
                "collection-shared-b",
            ],
            "title_decision": None,
            "source_reference_additions": [],
            "attribute_decisions": [],
            "warnings": ["identity_review_required"],
        },
    ],
    "groups": deepcopy(IMPORT_DOCUMENT["groups"]),
}


class BulkCollectionImportMergeContractMixin:
    """Reusable behavior suite for the production merge planner."""

    def parse_import(self, document):
        raise NotImplementedError

    def parse_preview(self, document):
        raise NotImplementedError

    def build_merge_plan(
        self,
        import_document,
        preview,
        collection_records,
    ):
        raise NotImplementedError

    def merge_plan_to_document(self, plan):
        raise NotImplementedError

    def serialize_merge_plan(self, plan):
        raise NotImplementedError

    def assert_merge_error(
        self,
        import_document,
        preview,
        collection_records,
    ):
        raise NotImplementedError

    def _build(self):
        return self.build_merge_plan(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_preview(deepcopy(PREVIEW_DOCUMENT)),
            deepcopy(COLLECTION_RECORDS),
        )

    def test_safe_actions_conflicts_and_review_are_ordered(self):
        self.assertEqual(
            self.merge_plan_to_document(self._build()),
            EXPECTED_MERGE_DOCUMENT,
        )

    def test_missing_metadata_and_source_links_are_safe_updates(self):
        item = self._build().items[0]
        self.assertEqual(item.action, "update_record")
        self.assertEqual(
            [
                (reference.source, reference.external_id)
                for reference in item.source_reference_additions
            ],
            [("kaizoff", "safe-update")],
        )
        self.assertEqual(
            [
                (decision.field, decision.action)
                for decision in item.attribute_decisions
            ],
            [
                ("authors", "unchanged"),
                ("difficulty", "add_missing"),
            ],
        )

    def test_equal_values_do_not_create_an_update(self):
        item = self._build().items[1]
        self.assertEqual(item.action, "no_change")
        self.assertEqual(item.source_reference_additions, ())
        self.assertTrue(
            all(
                decision.action == "unchanged"
                for decision in item.attribute_decisions
            )
        )

    def test_new_record_uses_only_imported_shared_metadata(self):
        item = self._build().items[2]
        self.assertEqual(item.action, "create_record")
        self.assertEqual(item.title_decision.action, "set_new")
        self.assertTrue(
            all(
                decision.action == "set_new"
                for decision in item.attribute_decisions
            )
        )

    def test_differing_existing_metadata_requires_review(self):
        item = self._build().items[3]
        self.assertEqual(item.action, "review_required")
        exit_decision = next(
            decision
            for decision in item.attribute_decisions
            if decision.field == "exit_count"
        )
        self.assertEqual(exit_decision.action, "review_conflict")
        self.assertEqual(exit_decision.existing_value, 10)
        self.assertEqual(exit_decision.imported_value, 12)
        self.assertEqual(
            item.warnings,
            ("metadata_conflict",),
        )

    def test_identity_review_produces_no_mutation_decisions(self):
        item = self._build().items[4]
        self.assertEqual(item.action, "review_required")
        self.assertIsNone(item.title_decision)
        self.assertEqual(item.source_reference_additions, ())
        self.assertEqual(item.attribute_decisions, ())
        self.assertEqual(
            item.warnings,
            ("identity_review_required",),
        )

    def test_existing_only_shared_metadata_is_preserved(self):
        for item in self._build().items:
            fields = {
                decision.field
                for decision in item.attribute_decisions
            }
            self.assertNotIn("release_date", fields)

    def test_user_owned_state_never_enters_merge_plan(self):
        serialized = self.serialize_merge_plan(self._build())
        for forbidden in (
            "completed",
            "completion_date",
            "personal_rating",
            "notes",
            "planner_state",
            "save_paths",
            "rom_paths",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_matched_preview_requires_exactly_one_collection_record(self):
        missing_record = tuple(
            record
            for record in deepcopy(COLLECTION_RECORDS)
            if record["collection_key"] != "collection-safe"
        )
        duplicate_record = list(deepcopy(COLLECTION_RECORDS))
        duplicate_record.append(deepcopy(duplicate_record[0]))
        unknown_record = list(deepcopy(COLLECTION_RECORDS))
        unknown_record.append(
            {
                "collection_key": "collection-unreferenced",
                "title": "Unreferenced",
                "source_references": [],
                "attributes": {},
                "user_state": {},
            }
        )

        for records in (
            missing_record,
            duplicate_record,
            unknown_record,
        ):
            with self.subTest(records=records):
                self.assert_merge_error(
                    self.parse_import(
                        deepcopy(IMPORT_DOCUMENT)
                    ),
                    self.parse_preview(
                        deepcopy(PREVIEW_DOCUMENT)
                    ),
                    records,
                )

    def test_preview_must_match_import_identity_order_and_groups(self):
        invalid_previews = []

        wrong_id = deepcopy(PREVIEW_DOCUMENT)
        wrong_id["import_id"] = "different"
        invalid_previews.append(wrong_id)

        wrong_title = deepcopy(PREVIEW_DOCUMENT)
        wrong_title["title"] = "Different title"
        invalid_previews.append(wrong_title)

        reordered = deepcopy(PREVIEW_DOCUMENT)
        reordered["items"][0], reordered["items"][1] = (
            reordered["items"][1],
            reordered["items"][0],
        )
        invalid_previews.append(reordered)

        wrong_groups = deepcopy(PREVIEW_DOCUMENT)
        wrong_groups["groups"][0]["entry_keys"].reverse()
        invalid_previews.append(wrong_groups)

        for preview_document in invalid_previews:
            with self.subTest(
                preview_document=preview_document
            ):
                self.assert_merge_error(
                    self.parse_import(
                        deepcopy(IMPORT_DOCUMENT)
                    ),
                    self.parse_preview(preview_document),
                    deepcopy(COLLECTION_RECORDS),
                )

    def test_inputs_projection_and_decisions_are_detached(self):
        import_document = deepcopy(IMPORT_DOCUMENT)
        preview_document = deepcopy(PREVIEW_DOCUMENT)
        records = deepcopy(COLLECTION_RECORDS)
        plan = self.build_merge_plan(
            self.parse_import(import_document),
            self.parse_preview(preview_document),
            records,
        )

        import_document["entries"][0]["title"] = "Changed"
        preview_document["items"][0]["warnings"].append(
            "changed"
        )
        records[0]["user_state"]["notes"] = "Changed"
        projected = self.merge_plan_to_document(plan)
        projected["items"][0]["attribute_decisions"][0][
            "imported_value"
        ][0] = "Changed"
        projected["groups"][0]["entry_keys"].reverse()

        self.assertEqual(
            self.merge_plan_to_document(plan),
            EXPECTED_MERGE_DOCUMENT,
        )

    def test_merge_plan_graph_is_immutable(self):
        plan = self._build()
        with self.assertRaises((AttributeError, TypeError)):
            plan.import_id = "changed"
        with self.assertRaises((AttributeError, TypeError)):
            plan.items[0].action = "no_change"
        with self.assertRaises((AttributeError, TypeError)):
            plan.summary["total"] = 0
        with self.assertRaises((AttributeError, TypeError)):
            plan.items[0].attribute_decisions[0].action = (
                "review_conflict"
            )

    def test_serialization_is_stable_compact_json(self):
        serialized = self.serialize_merge_plan(self._build())
        self.assertEqual(
            json.loads(serialized),
            EXPECTED_MERGE_DOCUMENT,
        )
        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )

    def test_merge_planning_never_mutates_inputs(self):
        import_document = deepcopy(IMPORT_DOCUMENT)
        preview_document = deepcopy(PREVIEW_DOCUMENT)
        records = deepcopy(COLLECTION_RECORDS)
        original_import = deepcopy(import_document)
        original_preview = deepcopy(preview_document)
        original_records = deepcopy(records)

        self.build_merge_plan(
            self.parse_import(import_document),
            self.parse_preview(preview_document),
            records,
        )

        self.assertEqual(import_document, original_import)
        self.assertEqual(preview_document, original_preview)
        self.assertEqual(records, original_records)


class BulkCollectionImportMergeSpecificationTest(
    unittest.TestCase
):
    """Validate the conservative merge-policy specification."""

    def test_schema_version_and_actions_are_fixed(self):
        self.assertEqual(
            MERGE_PLAN_SCHEMA,
            "smwc-bulk-collection-merge-plan",
        )
        self.assertEqual(MERGE_PLAN_VERSION, 1)
        self.assertEqual(
            MERGE_ACTIONS,
            (
                "create_record",
                "update_record",
                "no_change",
                "review_required",
            ),
        )
        self.assertEqual(
            VALUE_ACTIONS,
            (
                "set_new",
                "add_missing",
                "unchanged",
                "review_conflict",
            ),
        )

    def test_plan_shapes_are_minimal(self):
        self.assertEqual(
            PLAN_KEYS,
            (
                "schema",
                "version",
                "import_id",
                "summary",
                "items",
                "groups",
            ),
        )
        self.assertEqual(
            SUMMARY_KEYS,
            (
                "total",
                "create_record",
                "update_record",
                "no_change",
                "review_required",
            ),
        )
        self.assertEqual(
            ITEM_KEYS,
            (
                "entry_key",
                "action",
                "collection_keys",
                "title_decision",
                "source_reference_additions",
                "attribute_decisions",
                "warnings",
            ),
        )
        self.assertEqual(
            VALUE_DECISION_KEYS,
            (
                "field",
                "action",
                "existing_value",
                "imported_value",
            ),
        )
        self.assertEqual(
            GROUP_KEYS,
            ("group_key", "title", "entry_keys"),
        )

    def test_safe_policy_never_overwrites_existing_values(self):
        decisions = [
            item["title_decision"]
            for item in EXPECTED_MERGE_DOCUMENT["items"]
            if item["title_decision"] is not None
        ]
        decisions.extend(
            decision
            for item in EXPECTED_MERGE_DOCUMENT["items"]
            for decision in item["attribute_decisions"]
        )

        self.assertNotIn(
            "overwrite",
            {decision["action"] for decision in decisions},
        )
        for decision in decisions:
            if (
                decision["existing_value"] is not None
                and decision["existing_value"]
                != decision["imported_value"]
            ):
                self.assertEqual(
                    decision["action"],
                    "review_conflict",
                )

    def test_existing_only_metadata_is_not_removed(self):
        planned_fields = {
            decision["field"]
            for item in EXPECTED_MERGE_DOCUMENT["items"]
            for decision in item["attribute_decisions"]
        }
        self.assertNotIn("release_date", planned_fields)

    def test_imported_groups_remain_destination_neutral(self):
        self.assertEqual(
            EXPECTED_MERGE_DOCUMENT["groups"],
            IMPORT_DOCUMENT["groups"],
        )
        for group in EXPECTED_MERGE_DOCUMENT["groups"]:
            self.assertNotIn("destination", group)
            self.assertNotIn("collection_position", group)
            self.assertNotIn("planner_list", group)
            self.assertNotIn("wheel_pool", group)

    def test_plan_contains_no_user_owned_collection_state(self):
        serialized = json.dumps(
            EXPECTED_MERGE_DOCUMENT,
            sort_keys=True,
        )
        for forbidden in (
            "completed",
            "completion_date",
            "personal_rating",
            "notes",
            "planner_state",
            "save_paths",
            "rom_paths",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_summary_matches_expected_actions(self):
        self.assertEqual(
            EXPECTED_MERGE_DOCUMENT["summary"],
            {
                "total": 5,
                "create_record": 1,
                "update_record": 1,
                "no_change": 1,
                "review_required": 2,
            },
        )

    def test_contract_mixin_exposes_required_implementation_tests(self):
        names = {
            name
            for name in dir(
                BulkCollectionImportMergeContractMixin
            )
            if name.startswith("test_")
        }

        self.assertEqual(
            names,
            {
                "test_differing_existing_metadata_requires_review",
                "test_equal_values_do_not_create_an_update",
                "test_existing_only_shared_metadata_is_preserved",
                "test_identity_review_produces_no_mutation_decisions",
                "test_inputs_projection_and_decisions_are_detached",
                "test_matched_preview_requires_exactly_one_collection_record",
                "test_merge_plan_graph_is_immutable",
                "test_merge_planning_never_mutates_inputs",
                "test_missing_metadata_and_source_links_are_safe_updates",
                "test_new_record_uses_only_imported_shared_metadata",
                "test_preview_must_match_import_identity_order_and_groups",
                "test_safe_actions_conflicts_and_review_are_ordered",
                "test_serialization_is_stable_compact_json",
                "test_user_owned_state_never_enters_merge_plan",
            },
        )


class BulkCollectionImportMergeImplementationTest(
    BulkCollectionImportMergeContractMixin,
    unittest.TestCase,
):
    """Run the merge specification against production code."""

    def parse_import(self, document):
        return parse_bulk_collection_import(document)

    def parse_preview(self, document):
        return parse_bulk_collection_import_preview(document)

    def build_merge_plan(
        self,
        import_document,
        preview,
        collection_records,
    ):
        return build_bulk_collection_import_merge_plan(
            import_document,
            preview,
            collection_records,
        )

    def merge_plan_to_document(self, plan):
        return bulk_collection_import_merge_plan_to_document(plan)

    def serialize_merge_plan(self, plan):
        return serialize_bulk_collection_import_merge_plan(plan)

    def assert_merge_error(
        self,
        import_document,
        preview,
        collection_records,
    ):
        with self.assertRaises(BulkCollectionImportMergeError):
            build_bulk_collection_import_merge_plan(
                import_document,
                preview,
                collection_records,
            )

    def test_production_constants_match_specification(self):
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_SCHEMA,
            MERGE_PLAN_SCHEMA,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_VERSION,
            MERGE_PLAN_VERSION,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_ACTIONS,
            MERGE_ACTIONS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_VALUE_ACTIONS,
            VALUE_ACTIONS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_PLAN_KEYS,
            PLAN_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_SUMMARY_KEYS,
            SUMMARY_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_ITEM_KEYS,
            ITEM_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_VALUE_DECISION_KEYS,
            VALUE_DECISION_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_MERGE_GROUP_KEYS,
            GROUP_KEYS,
        )

    def test_preview_parser_is_immutable_and_detached(self):
        document = deepcopy(PREVIEW_DOCUMENT)
        preview = parse_bulk_collection_import_preview(document)

        document["items"][0]["warnings"].append("changed")
        document["groups"][0]["entry_keys"].reverse()

        with self.assertRaises((AttributeError, TypeError)):
            preview.title = "changed"
        with self.assertRaises((AttributeError, TypeError)):
            preview.summary["total"] = 0

        self.assertEqual(
            preview.items[0].warnings,
            (),
        )
        self.assertEqual(
            preview.groups[0].entry_keys,
            (
                "safe-update",
                "unchanged",
                "new-entry",
            ),
        )

    def test_projection_requires_production_plan_type(self):
        with self.assertRaises(TypeError):
            bulk_collection_import_merge_plan_to_document(
                EXPECTED_MERGE_DOCUMENT
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
