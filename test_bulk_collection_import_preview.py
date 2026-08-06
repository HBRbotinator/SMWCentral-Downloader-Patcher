"""Specification tests for bulk Collection import preview planning."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy

from bulk_collection_import import (
    parse_bulk_collection_import,
)
from bulk_collection_import_identity import (
    parse_bulk_collection_identity_plan,
)
from bulk_collection_import_preview import (
    BULK_COLLECTION_IMPORT_PREVIEW_GROUP_KEYS,
    BULK_COLLECTION_IMPORT_PREVIEW_ITEM_KEYS,
    BULK_COLLECTION_IMPORT_PREVIEW_OUTCOMES,
    BULK_COLLECTION_IMPORT_PREVIEW_PLAN_KEYS,
    BULK_COLLECTION_IMPORT_PREVIEW_SCHEMA,
    BULK_COLLECTION_IMPORT_PREVIEW_SUMMARY_KEYS,
    BULK_COLLECTION_IMPORT_PREVIEW_VERSION,
    BulkCollectionImportPreviewError,
    build_bulk_collection_import_preview,
    bulk_collection_import_preview_to_document,
    serialize_bulk_collection_import_preview,
)


PREVIEW_PLAN_SCHEMA = "smwc-bulk-collection-preview-plan"
PREVIEW_PLAN_VERSION = 1

PREVIEW_OUTCOMES = (
    "add_new",
    "match_existing",
    "review_required",
)

PLAN_KEYS = (
    "schema",
    "version",
    "import_id",
    "title",
    "summary",
    "items",
    "groups",
)
SUMMARY_KEYS = (
    "total",
    "add_new",
    "match_existing",
    "review_required",
)
ITEM_KEYS = (
    "entry_key",
    "title",
    "outcome",
    "resolution_status",
    "collection_keys",
    "proposed_source_references",
    "warnings",
)
GROUP_KEYS = (
    "group_key",
    "title",
    "entry_keys",
)

IMPORT_DOCUMENT = {
    "schema": "smwc-bulk-collection-import",
    "version": 1,
    "import_id": "preview-suite",
    "title": "Preview suite",
    "entries": [
        {
            "entry_key": "source-match",
            "title": "Source Match",
            "source_references": [
                {
                    "source": "smwc",
                    "external_id": "100",
                },
                {
                    "source": "kaizoff",
                    "external_id": "source-match",
                },
            ],
            "attributes": {
                "authors": ["Author One"],
                "difficulty": "Kaizo: Beginner",
            },
        },
        {
            "entry_key": "metadata-match",
            "title": "Metadata Match",
            "source_references": [],
            "attributes": {
                "authors": ["Author Two"],
            },
        },
        {
            "entry_key": "new-entry",
            "title": "Brand New Hack",
            "source_references": [],
            "attributes": {
                "authors": ["New Author"],
            },
        },
        {
            "entry_key": "ambiguous-entry",
            "title": "Shared Title",
            "source_references": [],
            "attributes": {
                "authors": ["Shared Author"],
            },
        },
        {
            "entry_key": "conflicting-entry",
            "title": "Conflicting Sources",
            "source_references": [
                {
                    "source": "smwc",
                    "external_id": "200",
                },
                {
                    "source": "kaizoff",
                    "external_id": "other-record",
                },
            ],
            "attributes": {
                "authors": ["Conflict Author"],
            },
        },
    ],
    "groups": [
        {
            "group_key": "recommended",
            "title": "Recommended",
            "entry_keys": [
                "source-match",
                "metadata-match",
                "new-entry",
            ],
        },
        {
            "group_key": "review",
            "title": "Needs review",
            "entry_keys": [
                "ambiguous-entry",
                "conflicting-entry",
            ],
        },
    ],
}

IDENTITY_PLAN_DOCUMENT = {
    "schema": "smwc-bulk-collection-identity-plan",
    "version": 1,
    "import_id": "preview-suite",
    "resolutions": [
        {
            "entry_key": "source-match",
            "status": "matched_source",
            "collection_keys": ["collection-source"],
            "matched_source_references": [
                {
                    "source": "smwc",
                    "external_id": "100",
                }
            ],
            "proposed_source_references": [
                {
                    "source": "kaizoff",
                    "external_id": "source-match",
                }
            ],
            "warnings": ["title_mismatch"],
        },
        {
            "entry_key": "metadata-match",
            "status": "matched_metadata",
            "collection_keys": ["collection-metadata"],
            "matched_source_references": [],
            "proposed_source_references": [],
            "warnings": [],
        },
        {
            "entry_key": "new-entry",
            "status": "new",
            "collection_keys": [],
            "matched_source_references": [],
            "proposed_source_references": [],
            "warnings": [],
        },
        {
            "entry_key": "ambiguous-entry",
            "status": "ambiguous",
            "collection_keys": [
                "collection-shared-a",
                "collection-shared-b",
            ],
            "matched_source_references": [],
            "proposed_source_references": [],
            "warnings": [],
        },
        {
            "entry_key": "conflicting-entry",
            "status": "conflict",
            "collection_keys": [
                "collection-smwc-200",
                "collection-kaizoff-other",
            ],
            "matched_source_references": [
                {
                    "source": "smwc",
                    "external_id": "200",
                },
                {
                    "source": "kaizoff",
                    "external_id": "other-record",
                },
            ],
            "proposed_source_references": [],
            "warnings": ["source_identity_conflict"],
        },
    ],
}

EXPECTED_PREVIEW_DOCUMENT = {
    "schema": PREVIEW_PLAN_SCHEMA,
    "version": PREVIEW_PLAN_VERSION,
    "import_id": "preview-suite",
    "title": "Preview suite",
    "summary": {
        "total": 5,
        "add_new": 1,
        "match_existing": 2,
        "review_required": 2,
    },
    "items": [
        {
            "entry_key": "source-match",
            "title": "Source Match",
            "outcome": "match_existing",
            "resolution_status": "matched_source",
            "collection_keys": ["collection-source"],
            "proposed_source_references": [
                {
                    "source": "kaizoff",
                    "external_id": "source-match",
                }
            ],
            "warnings": ["title_mismatch"],
        },
        {
            "entry_key": "metadata-match",
            "title": "Metadata Match",
            "outcome": "match_existing",
            "resolution_status": "matched_metadata",
            "collection_keys": ["collection-metadata"],
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
            "entry_key": "ambiguous-entry",
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
        {
            "entry_key": "conflicting-entry",
            "title": "Conflicting Sources",
            "outcome": "review_required",
            "resolution_status": "conflict",
            "collection_keys": [
                "collection-smwc-200",
                "collection-kaizoff-other",
            ],
            "proposed_source_references": [],
            "warnings": ["source_identity_conflict"],
        },
    ],
    "groups": deepcopy(IMPORT_DOCUMENT["groups"]),
}


class BulkCollectionImportPreviewContractMixin:
    """Reusable behavior suite for the production preview planner."""

    def parse_import(self, document):
        raise NotImplementedError

    def parse_identity_plan(self, document):
        raise NotImplementedError

    def build_preview(self, import_document, identity_plan):
        raise NotImplementedError

    def preview_to_document(self, preview):
        raise NotImplementedError

    def serialize_preview(self, preview):
        raise NotImplementedError

    def assert_preview_error(
        self,
        import_document,
        identity_plan,
    ):
        raise NotImplementedError

    def test_preview_maps_resolution_statuses_to_outcomes(self):
        preview = self.build_preview(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_identity_plan(
                deepcopy(IDENTITY_PLAN_DOCUMENT)
            ),
        )

        self.assertEqual(
            self.preview_to_document(preview),
            EXPECTED_PREVIEW_DOCUMENT,
        )

    def test_summary_is_derived_from_preview_items(self):
        preview = self.build_preview(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_identity_plan(
                deepcopy(IDENTITY_PLAN_DOCUMENT)
            ),
        )
        document = self.preview_to_document(preview)

        counts = {
            outcome: sum(
                item["outcome"] == outcome
                for item in document["items"]
            )
            for outcome in PREVIEW_OUTCOMES
        }
        self.assertEqual(
            document["summary"],
            {
                "total": len(document["items"]),
                **counts,
            },
        )

    def test_entry_and_group_order_is_preserved(self):
        preview = self.build_preview(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_identity_plan(
                deepcopy(IDENTITY_PLAN_DOCUMENT)
            ),
        )
        document = self.preview_to_document(preview)

        self.assertEqual(
            [
                item["entry_key"]
                for item in document["items"]
            ],
            [
                entry["entry_key"]
                for entry in IMPORT_DOCUMENT["entries"]
            ],
        )
        self.assertEqual(
            document["groups"],
            IMPORT_DOCUMENT["groups"],
        )

    def test_proposed_source_links_are_shown_but_not_applied(self):
        preview = self.build_preview(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_identity_plan(
                deepcopy(IDENTITY_PLAN_DOCUMENT)
            ),
        )
        item = preview.items[0]

        self.assertEqual(item.outcome, "match_existing")
        self.assertEqual(
            [
                (reference.source, reference.external_id)
                for reference
                in item.proposed_source_references
            ],
            [("kaizoff", "source-match")],
        )
        self.assertEqual(
            item.warnings,
            ("title_mismatch",),
        )

    def test_review_items_preserve_all_candidates(self):
        preview = self.build_preview(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_identity_plan(
                deepcopy(IDENTITY_PLAN_DOCUMENT)
            ),
        )

        ambiguous = preview.items[3]
        conflict = preview.items[4]
        self.assertEqual(
            ambiguous.collection_keys,
            (
                "collection-shared-a",
                "collection-shared-b",
            ),
        )
        self.assertEqual(
            conflict.collection_keys,
            (
                "collection-smwc-200",
                "collection-kaizoff-other",
            ),
        )
        self.assertEqual(
            conflict.warnings,
            ("source_identity_conflict",),
        )

    def test_import_and_identity_plan_ids_must_match(self):
        identity_document = deepcopy(IDENTITY_PLAN_DOCUMENT)
        identity_document["import_id"] = "different-import"

        self.assert_preview_error(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_identity_plan(identity_document),
        )

    def test_identity_plan_must_cover_import_entries_exactly_once(self):
        missing = deepcopy(IDENTITY_PLAN_DOCUMENT)
        missing["resolutions"].pop()

        reordered = deepcopy(IDENTITY_PLAN_DOCUMENT)
        reordered["resolutions"][0], reordered["resolutions"][1] = (
            reordered["resolutions"][1],
            reordered["resolutions"][0],
        )

        duplicate = deepcopy(IDENTITY_PLAN_DOCUMENT)
        duplicate["resolutions"][1]["entry_key"] = "source-match"

        unknown = deepcopy(IDENTITY_PLAN_DOCUMENT)
        unknown["resolutions"][1]["entry_key"] = "unknown-entry"

        for identity_document in (
            missing,
            reordered,
            duplicate,
            unknown,
        ):
            with self.subTest(identity_document=identity_document):
                self.assert_preview_error(
                    self.parse_import(
                        deepcopy(IMPORT_DOCUMENT)
                    ),
                    self.parse_identity_plan(
                        identity_document
                    ),
                )

    def test_resolution_shape_must_match_status_semantics(self):
        invalid_documents = []

        matched_without_one_target = deepcopy(
            IDENTITY_PLAN_DOCUMENT
        )
        matched_without_one_target["resolutions"][0][
            "collection_keys"
        ] = []
        invalid_documents.append(matched_without_one_target)

        new_with_target = deepcopy(IDENTITY_PLAN_DOCUMENT)
        new_with_target["resolutions"][2][
            "collection_keys"
        ] = ["unexpected"]
        invalid_documents.append(new_with_target)

        ambiguous_without_candidate = deepcopy(
            IDENTITY_PLAN_DOCUMENT
        )
        ambiguous_without_candidate["resolutions"][3][
            "collection_keys"
        ] = []
        invalid_documents.append(ambiguous_without_candidate)

        conflict_without_candidate = deepcopy(
            IDENTITY_PLAN_DOCUMENT
        )
        conflict_without_candidate["resolutions"][4][
            "collection_keys"
        ] = []
        invalid_documents.append(conflict_without_candidate)

        proposed_on_new = deepcopy(IDENTITY_PLAN_DOCUMENT)
        proposed_on_new["resolutions"][2][
            "proposed_source_references"
        ] = [
            {
                "source": "kaizoff",
                "external_id": "not-allowed",
            }
        ]
        invalid_documents.append(proposed_on_new)

        for identity_document in invalid_documents:
            with self.subTest(identity_document=identity_document):
                self.assert_preview_error(
                    self.parse_import(
                        deepcopy(IMPORT_DOCUMENT)
                    ),
                    self.parse_identity_plan(
                        identity_document
                    ),
                )

    def test_inputs_and_projection_are_detached(self):
        import_document = deepcopy(IMPORT_DOCUMENT)
        identity_document = deepcopy(
            IDENTITY_PLAN_DOCUMENT
        )
        parsed_import = self.parse_import(import_document)
        parsed_identity = self.parse_identity_plan(
            identity_document
        )
        preview = self.build_preview(
            parsed_import,
            parsed_identity,
        )

        import_document["entries"][0]["title"] = "Changed"
        identity_document["resolutions"][0][
            "collection_keys"
        ].append("changed")
        projected = self.preview_to_document(preview)
        projected["items"][0]["collection_keys"].append(
            "changed"
        )
        projected["groups"][0]["entry_keys"].reverse()

        self.assertEqual(
            self.preview_to_document(preview),
            EXPECTED_PREVIEW_DOCUMENT,
        )

    def test_preview_graph_is_immutable(self):
        preview = self.build_preview(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_identity_plan(
                deepcopy(IDENTITY_PLAN_DOCUMENT)
            ),
        )

        with self.assertRaises((AttributeError, TypeError)):
            preview.title = "Changed"
        with self.assertRaises((AttributeError, TypeError)):
            preview.items[0].outcome = "add_new"
        with self.assertRaises((AttributeError, TypeError)):
            preview.groups[0].entry_keys += ("changed",)
        with self.assertRaises((AttributeError, TypeError)):
            preview.summary["total"] = 0

    def test_serialization_is_stable_compact_json(self):
        preview = self.build_preview(
            self.parse_import(deepcopy(IMPORT_DOCUMENT)),
            self.parse_identity_plan(
                deepcopy(IDENTITY_PLAN_DOCUMENT)
            ),
        )

        serialized = self.serialize_preview(preview)

        self.assertEqual(
            json.loads(serialized),
            EXPECTED_PREVIEW_DOCUMENT,
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
        self.assertEqual(
            serialized,
            self.serialize_preview(
                self.build_preview(
                    self.parse_import(
                        deepcopy(IMPORT_DOCUMENT)
                    ),
                    self.parse_identity_plan(
                        deepcopy(
                            IDENTITY_PLAN_DOCUMENT
                        )
                    ),
                )
            ),
        )

    def test_preview_planning_never_mutates_inputs(self):
        import_document = deepcopy(IMPORT_DOCUMENT)
        identity_document = deepcopy(
            IDENTITY_PLAN_DOCUMENT
        )
        original_import = deepcopy(import_document)
        original_identity = deepcopy(identity_document)
        parsed_import = self.parse_import(import_document)
        parsed_identity = self.parse_identity_plan(
            identity_document
        )

        self.build_preview(
            parsed_import,
            parsed_identity,
        )

        self.assertEqual(import_document, original_import)
        self.assertEqual(identity_document, original_identity)


class BulkCollectionImportPreviewSpecificationTest(
    unittest.TestCase
):
    """Validate the source-neutral preview-plan specification."""

    def test_schema_version_and_outcomes_are_fixed(self):
        self.assertEqual(
            PREVIEW_PLAN_SCHEMA,
            "smwc-bulk-collection-preview-plan",
        )
        self.assertEqual(PREVIEW_PLAN_VERSION, 1)
        self.assertEqual(
            PREVIEW_OUTCOMES,
            (
                "add_new",
                "match_existing",
                "review_required",
            ),
        )

    def test_preview_shapes_are_minimal(self):
        self.assertEqual(
            PLAN_KEYS,
            (
                "schema",
                "version",
                "import_id",
                "title",
                "summary",
                "items",
                "groups",
            ),
        )
        self.assertEqual(
            SUMMARY_KEYS,
            (
                "total",
                "add_new",
                "match_existing",
                "review_required",
            ),
        )
        self.assertEqual(
            ITEM_KEYS,
            (
                "entry_key",
                "title",
                "outcome",
                "resolution_status",
                "collection_keys",
                "proposed_source_references",
                "warnings",
            ),
        )
        self.assertEqual(
            GROUP_KEYS,
            ("group_key", "title", "entry_keys"),
        )

    def test_resolution_to_preview_mapping_is_explicit(self):
        mapping = {
            "matched_source": "match_existing",
            "matched_metadata": "match_existing",
            "new": "add_new",
            "ambiguous": "review_required",
            "conflict": "review_required",
        }

        self.assertEqual(
            [
                mapping[resolution["status"]]
                for resolution
                in IDENTITY_PLAN_DOCUMENT["resolutions"]
            ],
            [
                item["outcome"]
                for item
                in EXPECTED_PREVIEW_DOCUMENT["items"]
            ],
        )

    def test_preview_contains_no_merged_metadata_or_user_state(self):
        serialized = json.dumps(
            EXPECTED_PREVIEW_DOCUMENT,
            sort_keys=True,
        )
        for forbidden in (
            "attributes",
            "completed",
            "completion_date",
            "notes",
            "personal_rating",
            "planner",
            "rom_paths",
            "save_paths",
            "merged",
            "apply",
            "write",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_imported_groups_are_display_structure_only(self):
        self.assertEqual(
            EXPECTED_PREVIEW_DOCUMENT["groups"],
            IMPORT_DOCUMENT["groups"],
        )
        for group in EXPECTED_PREVIEW_DOCUMENT["groups"]:
            self.assertNotIn("destination", group)
            self.assertNotIn("position", group)
            self.assertNotIn("apply", group)

    def test_summary_matches_expected_outcome_counts(self):
        self.assertEqual(
            EXPECTED_PREVIEW_DOCUMENT["summary"],
            {
                "total": 5,
                "add_new": 1,
                "match_existing": 2,
                "review_required": 2,
            },
        )

    def test_contract_mixin_exposes_required_implementation_tests(self):
        names = {
            name
            for name in dir(
                BulkCollectionImportPreviewContractMixin
            )
            if name.startswith("test_")
        }

        self.assertEqual(
            names,
            {
                "test_entry_and_group_order_is_preserved",
                "test_identity_plan_must_cover_import_entries_exactly_once",
                "test_import_and_identity_plan_ids_must_match",
                "test_inputs_and_projection_are_detached",
                "test_preview_graph_is_immutable",
                "test_preview_maps_resolution_statuses_to_outcomes",
                "test_preview_planning_never_mutates_inputs",
                "test_proposed_source_links_are_shown_but_not_applied",
                "test_resolution_shape_must_match_status_semantics",
                "test_review_items_preserve_all_candidates",
                "test_serialization_is_stable_compact_json",
                "test_summary_is_derived_from_preview_items",
            },
        )


class BulkCollectionImportPreviewImplementationTest(
    BulkCollectionImportPreviewContractMixin,
    unittest.TestCase,
):
    """Run the preview specification against production code."""

    def parse_import(self, document):
        return parse_bulk_collection_import(document)

    def parse_identity_plan(self, document):
        return parse_bulk_collection_identity_plan(document)

    def build_preview(self, import_document, identity_plan):
        return build_bulk_collection_import_preview(
            import_document,
            identity_plan,
        )

    def preview_to_document(self, preview):
        return bulk_collection_import_preview_to_document(
            preview
        )

    def serialize_preview(self, preview):
        return serialize_bulk_collection_import_preview(
            preview
        )

    def assert_preview_error(
        self,
        import_document,
        identity_plan,
    ):
        with self.assertRaises(
            BulkCollectionImportPreviewError
        ):
            build_bulk_collection_import_preview(
                import_document,
                identity_plan,
            )

    def test_production_constants_match_specification(self):
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PREVIEW_SCHEMA,
            PREVIEW_PLAN_SCHEMA,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PREVIEW_VERSION,
            PREVIEW_PLAN_VERSION,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PREVIEW_OUTCOMES,
            PREVIEW_OUTCOMES,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PREVIEW_PLAN_KEYS,
            PLAN_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PREVIEW_SUMMARY_KEYS,
            SUMMARY_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PREVIEW_ITEM_KEYS,
            ITEM_KEYS,
        )
        self.assertEqual(
            BULK_COLLECTION_IMPORT_PREVIEW_GROUP_KEYS,
            GROUP_KEYS,
        )

    def test_identity_plan_parser_is_immutable_and_detached(self):
        document = deepcopy(IDENTITY_PLAN_DOCUMENT)
        plan = parse_bulk_collection_identity_plan(document)

        document["resolutions"][0]["collection_keys"].append(
            "changed"
        )
        with self.assertRaises((AttributeError, TypeError)):
            plan.import_id = "changed"
        with self.assertRaises((AttributeError, TypeError)):
            plan.resolutions[0].collection_keys += ("changed",)

        self.assertEqual(
            plan.resolutions[0].collection_keys,
            ("collection-source",),
        )

    def test_preview_rejects_source_reference_not_on_entry(self):
        identity_document = deepcopy(
            IDENTITY_PLAN_DOCUMENT
        )
        identity_document["resolutions"][0][
            "proposed_source_references"
        ][0]["external_id"] = "different-record"

        with self.assertRaises(
            BulkCollectionImportPreviewError
        ):
            build_bulk_collection_import_preview(
                parse_bulk_collection_import(
                    deepcopy(IMPORT_DOCUMENT)
                ),
                parse_bulk_collection_identity_plan(
                    identity_document
                ),
            )

    def test_projection_requires_production_preview_type(self):
        with self.assertRaises(TypeError):
            bulk_collection_import_preview_to_document(
                EXPECTED_PREVIEW_DOCUMENT
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
