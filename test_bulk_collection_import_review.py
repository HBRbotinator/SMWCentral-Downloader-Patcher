"""Specification tests for bulk Collection import review decisions."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy

from bulk_collection_import import (
    BulkCollectionImportSourceReference,
)
from bulk_collection_import_merge import (
    BulkCollectionImportMergeGroup,
    BulkCollectionImportMergeItem,
    BulkCollectionImportMergePlan,
    BulkCollectionImportMergeValueDecision,
)
from bulk_collection_import_review import (
    BULK_COLLECTION_IMPORT_REVIEW_ACTIONS,
    BULK_COLLECTION_IMPORT_REVIEW_CONFLICT_CHOICES,
    BULK_COLLECTION_IMPORT_REVIEW_SCHEMA,
    BULK_COLLECTION_IMPORT_REVIEW_VERSION,
    BulkCollectionImportReviewError,
    bulk_collection_import_review_decisions_to_document,
    parse_bulk_collection_import_review_decisions,
    serialize_bulk_collection_import_review_decisions,
)


REVIEW_DECISION_SCHEMA = "smwc-bulk-collection-review-decisions"
REVIEW_DECISION_VERSION = 1

REVIEW_ACTIONS = (
    "resolve_metadata",
    "select_existing",
    "create_new",
    "skip",
)
CONFLICT_CHOICES = (
    "keep_existing",
    "use_imported",
)

DOCUMENT_KEYS = (
    "schema",
    "version",
    "import_id",
    "source_sha256",
    "decisions",
)
DECISION_KEYS = (
    "entry_key",
    "action",
    "selected_collection_key",
    "title_choice",
    "attribute_choices",
)
ATTRIBUTE_CHOICE_KEYS = (
    "field",
    "choice",
)

SOURCE_SHA256 = "a" * 64

MERGE_DOCUMENT = {
    "schema": "smwc-bulk-collection-merge-plan",
    "version": 1,
    "import_id": "review-suite",
    "summary": {
        "total": 5,
        "create_record": 1,
        "update_record": 1,
        "no_change": 0,
        "review_required": 3,
    },
    "items": [
        {
            "entry_key": "safe-update",
            "action": "update_record",
            "collection_keys": ["collection-safe"],
            "title_decision": {
                "field": "title",
                "action": "unchanged",
                "existing_value": "Safe",
                "imported_value": "Safe",
            },
            "source_reference_additions": [
                {
                    "source": "kaizoff",
                    "external_id": "safe",
                }
            ],
            "attribute_decisions": [],
            "warnings": [],
        },
        {
            "entry_key": "brand-new",
            "action": "create_record",
            "collection_keys": [],
            "title_decision": {
                "field": "title",
                "action": "set_new",
                "existing_value": None,
                "imported_value": "Brand New",
            },
            "source_reference_additions": [],
            "attribute_decisions": [],
            "warnings": [],
        },
        {
            "entry_key": "metadata-review",
            "action": "review_required",
            "collection_keys": ["collection-metadata"],
            "title_decision": {
                "field": "title",
                "action": "unchanged",
                "existing_value": "Metadata Review",
                "imported_value": "Metadata Review",
            },
            "source_reference_additions": [],
            "attribute_decisions": [
                {
                    "field": "authors",
                    "action": "unchanged",
                    "existing_value": ["Author"],
                    "imported_value": ["Author"],
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
            "entry_key": "title-review",
            "action": "review_required",
            "collection_keys": ["collection-title"],
            "title_decision": {
                "field": "title",
                "action": "review_conflict",
                "existing_value": "Old Title",
                "imported_value": "New Title",
            },
            "source_reference_additions": [],
            "attribute_decisions": [],
            "warnings": ["metadata_conflict"],
        },
        {
            "entry_key": "identity-review",
            "action": "review_required",
            "collection_keys": [
                "collection-a",
                "collection-b",
            ],
            "title_decision": None,
            "source_reference_additions": [],
            "attribute_decisions": [],
            "warnings": ["identity_review_required"],
        },
    ],
    "groups": [
        {
            "group_key": "all",
            "title": "All",
            "entry_keys": [
                "safe-update",
                "brand-new",
                "metadata-review",
                "title-review",
                "identity-review",
            ],
        }
    ],
}

VALID_DECISION_DOCUMENT = {
    "schema": REVIEW_DECISION_SCHEMA,
    "version": REVIEW_DECISION_VERSION,
    "import_id": "review-suite",
    "source_sha256": SOURCE_SHA256,
    "decisions": [
        {
            "entry_key": "metadata-review",
            "action": "resolve_metadata",
            "selected_collection_key": "collection-metadata",
            "title_choice": None,
            "attribute_choices": [
                {
                    "field": "exit_count",
                    "choice": "keep_existing",
                }
            ],
        },
        {
            "entry_key": "title-review",
            "action": "resolve_metadata",
            "selected_collection_key": "collection-title",
            "title_choice": "use_imported",
            "attribute_choices": [],
        },
        {
            "entry_key": "identity-review",
            "action": "select_existing",
            "selected_collection_key": "collection-b",
            "title_choice": None,
            "attribute_choices": [],
        },
    ],
}


class BulkCollectionImportReviewContractMixin:
    """Reusable behavior suite for production review decisions."""

    def parse_merge_plan(self, document):
        raise NotImplementedError

    def parse_review_decisions(
        self,
        document,
        merge_plan,
        source_sha256,
    ):
        raise NotImplementedError

    def review_to_document(self, decisions):
        raise NotImplementedError

    def serialize_review(self, decisions):
        raise NotImplementedError

    def assert_review_error(
        self,
        document,
        merge_plan,
        source_sha256=SOURCE_SHA256,
    ):
        raise NotImplementedError

    def _parse_valid(self):
        return self.parse_review_decisions(
            deepcopy(VALID_DECISION_DOCUMENT),
            self.parse_merge_plan(deepcopy(MERGE_DOCUMENT)),
            SOURCE_SHA256,
        )

    def test_valid_decisions_preserve_review_order_and_choices(self):
        decisions = self._parse_valid()

        self.assertEqual(
            tuple(item.entry_key for item in decisions.decisions),
            (
                "metadata-review",
                "title-review",
                "identity-review",
            ),
        )
        self.assertEqual(
            decisions.decisions[0].attribute_choices[0].field,
            "exit_count",
        )
        self.assertEqual(
            decisions.decisions[0].attribute_choices[0].choice,
            "keep_existing",
        )
        self.assertEqual(
            decisions.decisions[1].title_choice,
            "use_imported",
        )
        self.assertEqual(
            decisions.decisions[2].selected_collection_key,
            "collection-b",
        )

    def test_decisions_are_bound_to_import_id_and_source_sha256(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )

        wrong_id = deepcopy(VALID_DECISION_DOCUMENT)
        wrong_id["import_id"] = "different"
        self.assert_review_error(
            wrong_id,
            merge_plan,
        )

        wrong_hash = deepcopy(VALID_DECISION_DOCUMENT)
        wrong_hash["source_sha256"] = "b" * 64
        self.assert_review_error(
            wrong_hash,
            merge_plan,
        )

        self.assert_review_error(
            deepcopy(VALID_DECISION_DOCUMENT),
            merge_plan,
            "b" * 64,
        )

    def test_every_review_required_item_must_be_covered_once(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )

        missing = deepcopy(VALID_DECISION_DOCUMENT)
        missing["decisions"].pop()
        self.assert_review_error(missing, merge_plan)

        duplicate = deepcopy(VALID_DECISION_DOCUMENT)
        duplicate["decisions"].append(
            deepcopy(duplicate["decisions"][0])
        )
        self.assert_review_error(duplicate, merge_plan)

        reordered = deepcopy(VALID_DECISION_DOCUMENT)
        reordered["decisions"][0], reordered["decisions"][1] = (
            reordered["decisions"][1],
            reordered["decisions"][0],
        )
        self.assert_review_error(reordered, merge_plan)

    def test_safe_items_cannot_receive_review_decisions(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )
        document = deepcopy(VALID_DECISION_DOCUMENT)
        document["decisions"][0] = {
            "entry_key": "safe-update",
            "action": "skip",
            "selected_collection_key": None,
            "title_choice": None,
            "attribute_choices": [],
        }

        self.assert_review_error(document, merge_plan)

    def test_metadata_review_requires_exact_conflict_coverage(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )

        missing = deepcopy(VALID_DECISION_DOCUMENT)
        missing["decisions"][0]["attribute_choices"] = []
        self.assert_review_error(missing, merge_plan)

        extra = deepcopy(VALID_DECISION_DOCUMENT)
        extra["decisions"][0]["attribute_choices"].append(
            {
                "field": "authors",
                "choice": "use_imported",
            }
        )
        self.assert_review_error(extra, merge_plan)

        duplicate = deepcopy(VALID_DECISION_DOCUMENT)
        duplicate["decisions"][0]["attribute_choices"].append(
            {
                "field": "exit_count",
                "choice": "use_imported",
            }
        )
        self.assert_review_error(duplicate, merge_plan)

    def test_metadata_review_cannot_select_a_different_record(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )
        document = deepcopy(VALID_DECISION_DOCUMENT)
        document["decisions"][0][
            "selected_collection_key"
        ] = "collection-other"

        self.assert_review_error(document, merge_plan)

    def test_title_conflict_requires_exactly_one_title_choice(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )

        missing = deepcopy(VALID_DECISION_DOCUMENT)
        missing["decisions"][1]["title_choice"] = None
        self.assert_review_error(missing, merge_plan)

        unnecessary = deepcopy(VALID_DECISION_DOCUMENT)
        unnecessary["decisions"][0][
            "title_choice"
        ] = "keep_existing"
        self.assert_review_error(unnecessary, merge_plan)

    def test_identity_selection_must_use_a_candidate(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )
        document = deepcopy(VALID_DECISION_DOCUMENT)
        document["decisions"][2][
            "selected_collection_key"
        ] = "collection-not-a-candidate"

        self.assert_review_error(document, merge_plan)

    def test_identity_review_can_create_new_or_skip(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )

        for action in ("create_new", "skip"):
            document = deepcopy(VALID_DECISION_DOCUMENT)
            document["decisions"][2] = {
                "entry_key": "identity-review",
                "action": action,
                "selected_collection_key": None,
                "title_choice": None,
                "attribute_choices": [],
            }

            with self.subTest(action=action):
                decisions = self.parse_review_decisions(
                    document,
                    merge_plan,
                    SOURCE_SHA256,
                )
                self.assertEqual(
                    decisions.decisions[2].action,
                    action,
                )

    def test_metadata_review_can_be_skipped_explicitly(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )
        document = deepcopy(VALID_DECISION_DOCUMENT)
        document["decisions"][0] = {
            "entry_key": "metadata-review",
            "action": "skip",
            "selected_collection_key": None,
            "title_choice": None,
            "attribute_choices": [],
        }

        decisions = self.parse_review_decisions(
            document,
            merge_plan,
            SOURCE_SHA256,
        )

        self.assertEqual(decisions.decisions[0].action, "skip")

    def test_invalid_choice_shapes_are_rejected(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )
        invalid_documents = []

        bad_choice = deepcopy(VALID_DECISION_DOCUMENT)
        bad_choice["decisions"][0]["attribute_choices"][0][
            "choice"
        ] = "overwrite"
        invalid_documents.append(bad_choice)

        identity_with_metadata = deepcopy(
            VALID_DECISION_DOCUMENT
        )
        identity_with_metadata["decisions"][2][
            "attribute_choices"
        ] = [
            {
                "field": "exit_count",
                "choice": "keep_existing",
            }
        ]
        invalid_documents.append(identity_with_metadata)

        create_with_target = deepcopy(
            VALID_DECISION_DOCUMENT
        )
        create_with_target["decisions"][2] = {
            "entry_key": "identity-review",
            "action": "create_new",
            "selected_collection_key": "collection-a",
            "title_choice": None,
            "attribute_choices": [],
        }
        invalid_documents.append(create_with_target)

        for document in invalid_documents:
            with self.subTest(document=document):
                self.assert_review_error(
                    document,
                    merge_plan,
                )

    def test_decision_graph_and_projection_are_detached(self):
        document = deepcopy(VALID_DECISION_DOCUMENT)
        merge_document = deepcopy(MERGE_DOCUMENT)
        decisions = self.parse_review_decisions(
            document,
            self.parse_merge_plan(merge_document),
            SOURCE_SHA256,
        )

        document["decisions"][0]["attribute_choices"][0][
            "choice"
        ] = "use_imported"
        merge_document["items"][2]["warnings"].append(
            "changed"
        )
        projected = self.review_to_document(decisions)
        projected["decisions"][0]["attribute_choices"][0][
            "choice"
        ] = "use_imported"

        self.assertEqual(
            self.review_to_document(decisions),
            VALID_DECISION_DOCUMENT,
        )

    def test_decision_graph_is_immutable(self):
        decisions = self._parse_valid()

        with self.assertRaises((AttributeError, TypeError)):
            decisions.import_id = "changed"
        with self.assertRaises((AttributeError, TypeError)):
            decisions.decisions[0].action = "skip"
        with self.assertRaises((AttributeError, TypeError)):
            decisions.decisions[0].attribute_choices[0].choice = (
                "use_imported"
            )

    def test_serialization_is_stable_compact_json(self):
        decisions = self._parse_valid()
        serialized = self.serialize_review(decisions)

        self.assertEqual(
            json.loads(serialized),
            VALID_DECISION_DOCUMENT,
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


class BulkCollectionImportReviewSpecificationTest(
    unittest.TestCase
):
    """Validate the review-decision specification itself."""

    def test_schema_version_and_actions_are_fixed(self):
        self.assertEqual(
            REVIEW_DECISION_SCHEMA,
            "smwc-bulk-collection-review-decisions",
        )
        self.assertEqual(REVIEW_DECISION_VERSION, 1)
        self.assertEqual(
            REVIEW_ACTIONS,
            (
                "resolve_metadata",
                "select_existing",
                "create_new",
                "skip",
            ),
        )
        self.assertEqual(
            CONFLICT_CHOICES,
            (
                "keep_existing",
                "use_imported",
            ),
        )

    def test_document_shapes_are_minimal(self):
        self.assertEqual(
            DOCUMENT_KEYS,
            (
                "schema",
                "version",
                "import_id",
                "source_sha256",
                "decisions",
            ),
        )
        self.assertEqual(
            DECISION_KEYS,
            (
                "entry_key",
                "action",
                "selected_collection_key",
                "title_choice",
                "attribute_choices",
            ),
        )
        self.assertEqual(
            ATTRIBUTE_CHOICE_KEYS,
            ("field", "choice"),
        )

    def test_review_document_contains_no_apply_or_destination_data(self):
        serialized = json.dumps(
            VALID_DECISION_DOCUMENT,
            sort_keys=True,
        )
        for forbidden in (
            "destination",
            "planner",
            "wheel",
            "collection_position",
            "applied",
            "write",
            "completed",
            "personal_rating",
            "notes",
            "save_paths",
            "rom_paths",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_review_choices_never_offer_silent_overwrite(self):
        self.assertNotIn("overwrite", CONFLICT_CHOICES)
        self.assertNotIn("auto", CONFLICT_CHOICES)

    def test_contract_mixin_exposes_required_tests(self):
        names = {
            name
            for name in dir(
                BulkCollectionImportReviewContractMixin
            )
            if name.startswith("test_")
        }

        self.assertEqual(
            names,
            {
                "test_decision_graph_and_projection_are_detached",
                "test_decision_graph_is_immutable",
                "test_decisions_are_bound_to_import_id_and_source_sha256",
                "test_every_review_required_item_must_be_covered_once",
                "test_identity_review_can_create_new_or_skip",
                "test_identity_selection_must_use_a_candidate",
                "test_invalid_choice_shapes_are_rejected",
                "test_metadata_review_can_be_skipped_explicitly",
                "test_metadata_review_cannot_select_a_different_record",
                "test_metadata_review_requires_exact_conflict_coverage",
                "test_safe_items_cannot_receive_review_decisions",
                "test_serialization_is_stable_compact_json",
                "test_title_conflict_requires_exactly_one_title_choice",
                "test_valid_decisions_preserve_review_order_and_choices",
            },
        )


def _freeze_test_value(value):
    if isinstance(value, list):
        return tuple(_freeze_test_value(item) for item in value)
    if isinstance(value, dict):
        return {
            key: _freeze_test_value(item)
            for key, item in value.items()
        }
    return value


def _merge_value_decision_from_document(document):
    if document is None:
        return None
    return BulkCollectionImportMergeValueDecision(
        field=document["field"],
        action=document["action"],
        existing_value=_freeze_test_value(
            document["existing_value"]
        ),
        imported_value=_freeze_test_value(
            document["imported_value"]
        ),
    )


def _merge_plan_from_document(document):
    return BulkCollectionImportMergePlan(
        schema=document["schema"],
        version=document["version"],
        import_id=document["import_id"],
        summary=dict(document["summary"]),
        items=tuple(
            BulkCollectionImportMergeItem(
                entry_key=item["entry_key"],
                action=item["action"],
                collection_keys=tuple(
                    item["collection_keys"]
                ),
                title_decision=(
                    _merge_value_decision_from_document(
                        item["title_decision"]
                    )
                ),
                source_reference_additions=tuple(
                    BulkCollectionImportSourceReference(
                        source=reference["source"],
                        external_id=reference["external_id"],
                    )
                    for reference
                    in item["source_reference_additions"]
                ),
                attribute_decisions=tuple(
                    _merge_value_decision_from_document(
                        decision
                    )
                    for decision in item["attribute_decisions"]
                ),
                warnings=tuple(item["warnings"]),
            )
            for item in document["items"]
        ),
        groups=tuple(
            BulkCollectionImportMergeGroup(
                group_key=group["group_key"],
                title=group["title"],
                entry_keys=tuple(group["entry_keys"]),
            )
            for group in document["groups"]
        ),
    )


class BulkCollectionImportReviewImplementationTest(
    BulkCollectionImportReviewContractMixin,
    unittest.TestCase,
):
    """Run the review contract against production code."""

    def parse_merge_plan(self, document):
        return _merge_plan_from_document(document)

    def parse_review_decisions(
        self,
        document,
        merge_plan,
        source_sha256,
    ):
        return parse_bulk_collection_import_review_decisions(
            document,
            merge_plan,
            source_sha256,
        )

    def review_to_document(self, decisions):
        return bulk_collection_import_review_decisions_to_document(
            decisions
        )

    def serialize_review(self, decisions):
        return serialize_bulk_collection_import_review_decisions(
            decisions
        )

    def assert_review_error(
        self,
        document,
        merge_plan,
        source_sha256=SOURCE_SHA256,
    ):
        with self.assertRaises(BulkCollectionImportReviewError):
            parse_bulk_collection_import_review_decisions(
                document,
                merge_plan,
                source_sha256,
            )

    def test_production_constants_match_specification(self):
        self.assertEqual(
            BULK_COLLECTION_IMPORT_REVIEW_SCHEMA,
            REVIEW_DECISION_SCHEMA,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_REVIEW_VERSION,
            REVIEW_DECISION_VERSION,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_REVIEW_ACTIONS,
            REVIEW_ACTIONS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_REVIEW_CONFLICT_CHOICES,
            CONFLICT_CHOICES,
        )

    def test_uppercase_or_malformed_hash_is_rejected(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )

        for value in (
            SOURCE_SHA256.upper(),
            "not-a-hash",
            "a" * 63,
            "a" * 65,
        ):
            document = deepcopy(VALID_DECISION_DOCUMENT)
            document["source_sha256"] = value

            with self.subTest(value=value):
                self.assert_review_error(
                    document,
                    merge_plan,
                )

    def test_metadata_create_new_is_not_a_conflict_resolution(self):
        merge_plan = self.parse_merge_plan(
            deepcopy(MERGE_DOCUMENT)
        )
        document = deepcopy(VALID_DECISION_DOCUMENT)
        document["decisions"][0] = {
            "entry_key": "metadata-review",
            "action": "create_new",
            "selected_collection_key": None,
            "title_choice": None,
            "attribute_choices": [],
        }

        self.assert_review_error(document, merge_plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
