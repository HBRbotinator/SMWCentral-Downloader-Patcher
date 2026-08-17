"""Specification for the read-only v5.1 bulk-import workflow preview."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy

import tempfile
from pathlib import Path

from bulk_collection_import_workflow_preview import (
    WORKFLOW_PREVIEW_SCHEMA as PRODUCTION_WORKFLOW_PREVIEW_SCHEMA,
    WORKFLOW_PREVIEW_VERSION as PRODUCTION_WORKFLOW_PREVIEW_VERSION,
    WORKFLOW_ROW_OUTCOMES as PRODUCTION_WORKFLOW_ROW_OUTCOMES,
    BulkCollectionImportWorkflowPreviewError,
    build_bulk_collection_import_workflow_preview,
    bulk_collection_import_workflow_preview_to_document,
    plan_v5_1_bulk_collection_import_workflow_preview,
    serialize_bulk_collection_import_workflow_preview,
)
from hack_data_manager import HackDataManager


WORKFLOW_PREVIEW_SCHEMA = "smwc-bulk-collection-workflow-preview"
WORKFLOW_PREVIEW_VERSION = 1

WORKFLOW_ROW_OUTCOMES = (
    "add_new",
    "match_existing",
    "review_required",
)

SOURCE_SHA256 = "c" * 64

PLANNING_SESSION_DOCUMENT = {
    "source_name": "bulk-list.json",
    "byte_count": 2048,
    "sha256": SOURCE_SHA256,
    "import": {
        "schema": "smwc-bulk-collection-import",
        "version": 1,
        "import_id": "workflow-preview-suite",
        "title": "Example Bulk List",
        "entries": [
            {
                "entry_key": "matched",
                "title": "Matched Hack",
                "source_references": [
                    {"source": "smwc", "external_id": "100"}
                ],
                "attributes": {
                    "authors": ["Author One"],
                    "exit_count": 10,
                },
            },
            {
                "entry_key": "new",
                "title": "New Hack",
                "source_references": [
                    {"source": "smwc", "external_id": "200"}
                ],
                "attributes": {
                    "authors": ["Author Two"],
                    "exit_count": 20,
                },
            },
            {
                "entry_key": "ambiguous",
                "title": "Ambiguous Hack",
                "source_references": [],
                "attributes": {
                    "authors": ["Author Three"],
                },
            },
            {
                "entry_key": "metadata-conflict",
                "title": "Metadata Conflict",
                "source_references": [
                    {"source": "smwc", "external_id": "300"}
                ],
                "attributes": {
                    "authors": ["Author Four"],
                    "exit_count": 15,
                },
            },
        ],
        "groups": [
            {
                "group_key": "queue",
                "title": "Queue",
                "entry_keys": [
                    "matched",
                    "new",
                    "ambiguous",
                    "metadata-conflict",
                ],
            }
        ],
    },
    "preview": {
        "schema": "smwc-bulk-collection-preview-plan",
        "version": 1,
        "import_id": "workflow-preview-suite",
        "summary": {
            "total": 4,
            "add_new": 1,
            "match_existing": 2,
            "review_required": 1,
        },
        "items": [
            {
                "entry_key": "matched",
                "outcome": "match_existing",
                "resolution_status": "matched_source",
                "collection_keys": ["100"],
                "proposed_source_references": [
                    {"source": "kaizoff", "external_id": "mirror-100"}
                ],
                "warnings": [],
            },
            {
                "entry_key": "new",
                "outcome": "add_new",
                "resolution_status": "new",
                "collection_keys": [],
                "proposed_source_references": [],
                "warnings": [],
            },
            {
                "entry_key": "ambiguous",
                "outcome": "review_required",
                "resolution_status": "ambiguous",
                "collection_keys": ["usr_1", "usr_2"],
                "proposed_source_references": [],
                "warnings": [
                    "identity_review_required",
                    "identity_ambiguous",
                ],
            },
            {
                "entry_key": "metadata-conflict",
                "outcome": "match_existing",
                "resolution_status": "matched_source",
                "collection_keys": ["300"],
                "proposed_source_references": [],
                "warnings": [],
            },
        ],
        "groups": [
            {
                "group_key": "queue",
                "title": "Queue",
                "entry_keys": [
                    "matched",
                    "new",
                    "ambiguous",
                    "metadata-conflict",
                ],
            }
        ],
    },
    "merge": {
        "schema": "smwc-bulk-collection-merge-plan",
        "version": 1,
        "import_id": "workflow-preview-suite",
        "summary": {
            "total": 4,
            "create_record": 1,
            "update_record": 1,
            "no_change": 0,
            "review_required": 2,
        },
        "items": [
            {
                "entry_key": "matched",
                "action": "update_record",
                "collection_keys": ["100"],
                "title_decision": {
                    "field": "title",
                    "action": "unchanged",
                    "existing_value": "Matched Hack",
                    "imported_value": "Matched Hack",
                },
                "source_reference_additions": [
                    {"source": "kaizoff", "external_id": "mirror-100"}
                ],
                "attribute_decisions": [
                    {
                        "field": "authors",
                        "action": "unchanged",
                        "existing_value": ["Author One"],
                        "imported_value": ["Author One"],
                    }
                ],
                "warnings": [],
            },
            {
                "entry_key": "new",
                "action": "create_record",
                "collection_keys": [],
                "title_decision": {
                    "field": "title",
                    "action": "set_new",
                    "existing_value": None,
                    "imported_value": "New Hack",
                },
                "source_reference_additions": [],
                "attribute_decisions": [],
                "warnings": [],
            },
            {
                "entry_key": "ambiguous",
                "action": "review_required",
                "collection_keys": ["usr_1", "usr_2"],
                "title_decision": None,
                "source_reference_additions": [],
                "attribute_decisions": [],
                "warnings": [
                    "identity_review_required",
                    "identity_ambiguous",
                ],
            },
            {
                "entry_key": "metadata-conflict",
                "action": "review_required",
                "collection_keys": ["300"],
                "title_decision": {
                    "field": "title",
                    "action": "review_conflict",
                    "existing_value": "Old Metadata Title",
                    "imported_value": "Metadata Conflict",
                },
                "source_reference_additions": [],
                "attribute_decisions": [
                    {
                        "field": "authors",
                        "action": "unchanged",
                        "existing_value": ["Author Four"],
                        "imported_value": ["Author Four"],
                    },
                    {
                        "field": "exit_count",
                        "action": "review_conflict",
                        "existing_value": 14,
                        "imported_value": 15,
                    },
                ],
                "warnings": ["metadata_conflict"],
            },
        ],
        "groups": [
            {
                "group_key": "queue",
                "title": "Queue",
                "entry_keys": [
                    "matched",
                    "new",
                    "ambiguous",
                    "metadata-conflict",
                ],
            }
        ],
    },
}

COLLECTION_SNAPSHOT = {
    "100": {
        "title": "Matched Hack",
        "current_difficulty": "Intermediate",
        "authors": ["Author One"],
        "exits": 10,
        "date": "",
        "completed": True,
        "personal_rating": 5,
        "notes": "preserve",
    },
    "300": {
        "title": "Old Metadata Title",
        "current_difficulty": "Advanced",
        "authors": ["Author Four"],
        "exits": 14,
        "date": "",
        "completed": False,
        "personal_rating": 3,
        "notes": "also preserve",
    },
    "usr_1": {
        "title": "Ambiguous Hack",
        "authors": ["Author Three"],
        "exits": 0,
        "completed": False,
        "notes": "candidate one",
    },
    "usr_2": {
        "title": "Ambiguous Hack",
        "authors": ["Author Three"],
        "exits": 0,
        "completed": True,
        "notes": "candidate two",
    },
}


class BulkCollectionImportWorkflowPreviewContractMixin:
    """Reusable contract for a UI-ready read-only preview session."""

    def build_preview(
        self,
        planning_session_document,
        collection_snapshot,
    ):
        raise NotImplementedError

    def preview_to_document(self, preview):
        raise NotImplementedError

    def serialize_preview(self, preview):
        raise NotImplementedError

    def assert_preview_error(
        self,
        planning_session_document,
        collection_snapshot,
    ):
        raise NotImplementedError

    def _build(self, **overrides):
        values = {
            "planning_session_document": deepcopy(
                PLANNING_SESSION_DOCUMENT
            ),
            "collection_snapshot": deepcopy(COLLECTION_SNAPSHOT),
        }
        values.update(overrides)
        return self.build_preview(**values)

    def test_source_and_import_identity_are_preserved(self):
        preview = self._build()

        self.assertEqual(preview.source_name, "bulk-list.json")
        self.assertEqual(preview.byte_count, 2048)
        self.assertEqual(preview.source_sha256, SOURCE_SHA256)
        self.assertEqual(
            preview.import_id,
            "workflow-preview-suite",
        )
        self.assertEqual(preview.title, "Example Bulk List")

    def test_rows_preserve_import_order(self):
        preview = self._build()

        self.assertEqual(
            tuple(row.entry_key for row in preview.rows),
            (
                "matched",
                "new",
                "ambiguous",
                "metadata-conflict",
            ),
        )

    def test_groups_preserve_import_order_and_membership(self):
        preview = self._build()

        self.assertEqual(len(preview.groups), 1)
        self.assertEqual(preview.groups[0].group_key, "queue")
        self.assertEqual(preview.groups[0].title, "Queue")
        self.assertEqual(
            preview.groups[0].entry_keys,
            (
                "matched",
                "new",
                "ambiguous",
                "metadata-conflict",
            ),
        )

    def test_safe_match_row_exposes_existing_target_and_link_addition(self):
        preview = self._build()
        row = preview.rows[0]

        self.assertEqual(row.outcome, "match_existing")
        self.assertEqual(row.merge_action, "update_record")
        self.assertEqual(row.collection_keys, ("100",))
        self.assertEqual(
            tuple(
                (ref.source, ref.external_id)
                for ref in row.proposed_source_references
            ),
            (("kaizoff", "mirror-100"),),
        )
        self.assertFalse(row.requires_review)

    def test_new_row_is_displayed_as_add_new(self):
        preview = self._build()
        row = preview.rows[1]

        self.assertEqual(row.outcome, "add_new")
        self.assertEqual(row.merge_action, "create_record")
        self.assertEqual(row.collection_keys, ())
        self.assertFalse(row.requires_review)

    def test_ambiguous_identity_row_exposes_candidates(self):
        preview = self._build()
        row = preview.rows[2]

        self.assertEqual(row.outcome, "review_required")
        self.assertEqual(row.merge_action, "review_required")
        self.assertEqual(
            row.collection_keys,
            ("usr_1", "usr_2"),
        )
        self.assertEqual(
            row.warnings,
            (
                "identity_review_required",
                "identity_ambiguous",
            ),
        )
        self.assertTrue(row.requires_review)
        self.assertEqual(row.conflicts, ())

    def test_metadata_conflicts_are_projected_for_ui(self):
        preview = self._build()
        row = preview.rows[3]

        self.assertEqual(row.outcome, "match_existing")
        self.assertEqual(row.merge_action, "review_required")
        self.assertTrue(row.requires_review)
        self.assertEqual(row.collection_keys, ("300",))
        self.assertEqual(
            tuple(
                (
                    conflict.field,
                    conflict.existing_value,
                    conflict.imported_value,
                )
                for conflict in row.conflicts
            ),
            (
                (
                    "title",
                    "Old Metadata Title",
                    "Metadata Conflict",
                ),
                ("exit_count", 14, 15),
            ),
        )

    def test_summary_is_derived_from_final_merge_actions(self):
        preview = self._build()

        self.assertEqual(
            dict(preview.summary),
            {
                "total": 4,
                "create_record": 1,
                "update_record": 1,
                "no_change": 0,
                "review_required": 2,
            },
        )
        self.assertEqual(preview.review_required_count, 2)
        self.assertTrue(preview.requires_review)

    def test_display_outcome_and_merge_action_remain_distinct(self):
        preview = self._build()
        metadata = preview.rows[3]

        self.assertEqual(metadata.outcome, "match_existing")
        self.assertEqual(metadata.merge_action, "review_required")

    def test_candidate_display_data_comes_from_collection_snapshot(self):
        preview = self._build()
        ambiguous = preview.rows[2]

        self.assertEqual(
            tuple(
                (
                    candidate.collection_key,
                    candidate.title,
                    candidate.authors,
                )
                for candidate in ambiguous.candidates
            ),
            (
                (
                    "usr_1",
                    "Ambiguous Hack",
                    ("Author Three",),
                ),
                (
                    "usr_2",
                    "Ambiguous Hack",
                    ("Author Three",),
                ),
            ),
        )

    def test_candidate_display_excludes_user_owned_state(self):
        preview = self._build()
        serialized = self.serialize_preview(preview)

        for forbidden in (
            "completed",
            "personal_rating",
            "notes",
            "save_paths",
            "rom_paths",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_missing_candidate_snapshot_fails_closed(self):
        snapshot = deepcopy(COLLECTION_SNAPSHOT)
        del snapshot["usr_2"]

        self.assert_preview_error(
            deepcopy(PLANNING_SESSION_DOCUMENT),
            snapshot,
        )

    def test_duplicate_or_unknown_rows_fail_closed(self):
        duplicate = deepcopy(PLANNING_SESSION_DOCUMENT)
        duplicate["merge"]["items"][1]["entry_key"] = "matched"

        self.assert_preview_error(
            duplicate,
            deepcopy(COLLECTION_SNAPSHOT),
        )

        unknown = deepcopy(PLANNING_SESSION_DOCUMENT)
        unknown["preview"]["items"][1]["entry_key"] = "missing"

        self.assert_preview_error(
            unknown,
            deepcopy(COLLECTION_SNAPSHOT),
        )

    def test_summary_mismatch_fails_closed(self):
        document = deepcopy(PLANNING_SESSION_DOCUMENT)
        document["merge"]["summary"]["review_required"] = 1

        self.assert_preview_error(
            document,
            deepcopy(COLLECTION_SNAPSHOT),
        )

    def test_preview_does_not_mutate_inputs(self):
        planning = deepcopy(PLANNING_SESSION_DOCUMENT)
        collection = deepcopy(COLLECTION_SNAPSHOT)
        original_planning = deepcopy(planning)
        original_collection = deepcopy(collection)

        self.build_preview(planning, collection)

        self.assertEqual(planning, original_planning)
        self.assertEqual(collection, original_collection)

    def test_preview_is_immutable_and_projection_detached(self):
        preview = self._build()

        with self.assertRaises((AttributeError, TypeError)):
            preview.title = "Changed"
        with self.assertRaises((AttributeError, TypeError)):
            preview.rows[0].title = "Changed"

        document = self.preview_to_document(preview)
        document["summary"]["review_required"] = 99
        document["rows"][0]["warnings"].append("changed")

        clean = self.preview_to_document(preview)
        self.assertEqual(clean["summary"]["review_required"], 2)
        self.assertNotIn("changed", clean["rows"][0]["warnings"])

    def test_serialization_is_stable_compact_json(self):
        preview = self._build()
        serialized = self.serialize_preview(preview)

        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )


class BulkCollectionImportWorkflowPreviewSpecificationTest(
    unittest.TestCase
):
    """Lock the first user-facing bulk-import workflow boundary."""

    def test_schema_version_and_outcomes_are_fixed(self):
        self.assertEqual(
            WORKFLOW_PREVIEW_SCHEMA,
            "smwc-bulk-collection-workflow-preview",
        )
        self.assertEqual(WORKFLOW_PREVIEW_VERSION, 1)
        self.assertEqual(
            WORKFLOW_ROW_OUTCOMES,
            (
                "add_new",
                "match_existing",
                "review_required",
            ),
        )

    def test_initial_workflow_is_read_only(self):
        self.assertEqual(
            PLANNING_SESSION_DOCUMENT["merge"]["summary"][
                "review_required"
            ],
            2,
        )
        self.assertNotIn(
            "application",
            PLANNING_SESSION_DOCUMENT,
        )
        self.assertNotIn(
            "persistence",
            PLANNING_SESSION_DOCUMENT,
        )

    def test_preview_outcome_is_not_a_write_decision(self):
        metadata = PLANNING_SESSION_DOCUMENT["preview"]["items"][3]
        merge = PLANNING_SESSION_DOCUMENT["merge"]["items"][3]

        self.assertEqual(metadata["outcome"], "match_existing")
        self.assertEqual(merge["action"], "review_required")


class BulkCollectionImportWorkflowPreviewImplementationTest(
    BulkCollectionImportWorkflowPreviewContractMixin,
    unittest.TestCase,
):
    """Run the Commit 112 contract against the production workflow model."""

    def build_preview(
        self,
        planning_session_document,
        collection_snapshot,
    ):
        return build_bulk_collection_import_workflow_preview(
            planning_session_document,
            collection_snapshot,
        )

    def preview_to_document(self, preview):
        return bulk_collection_import_workflow_preview_to_document(
            preview
        )

    def serialize_preview(self, preview):
        return serialize_bulk_collection_import_workflow_preview(
            preview
        )

    def assert_preview_error(
        self,
        planning_session_document,
        collection_snapshot,
    ):
        with self.assertRaises(BulkCollectionImportWorkflowPreviewError):
            build_bulk_collection_import_workflow_preview(
                planning_session_document,
                collection_snapshot,
            )

    def test_production_constants_match_specification(self):
        self.assertEqual(
            PRODUCTION_WORKFLOW_PREVIEW_SCHEMA,
            WORKFLOW_PREVIEW_SCHEMA,
        )
        self.assertEqual(
            PRODUCTION_WORKFLOW_PREVIEW_VERSION,
            WORKFLOW_PREVIEW_VERSION,
        )
        self.assertEqual(
            PRODUCTION_WORKFLOW_ROW_OUTCOMES,
            WORKFLOW_ROW_OUTCOMES,
        )

    def test_real_file_path_plans_against_live_hack_data_manager(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            processed = root / "processed.json"
            processed.write_text(
                json.dumps(
                    {
                        "100": {
                            "title": "Matched Hack",
                            "current_difficulty": "Intermediate",
                            "authors": ["Author One"],
                            "exits": 10,
                            "date": "",
                            "completed": True,
                            "personal_rating": 5,
                            "notes": "must not appear",
                        }
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            import_path = root / "bulk-list.json"
            import_path.write_text(
                json.dumps(
                    {
                        "schema": "smwc-bulk-collection-import",
                        "version": 1,
                        "import_id": "real-file-preview",
                        "title": "Real File Preview",
                        "entries": [
                            {
                                "entry_key": "matched",
                                "title": "Matched Hack",
                                "source_references": [
                                    {
                                        "source": "smwc",
                                        "external_id": "100",
                                    }
                                ],
                                "attributes": {
                                    "authors": ["Author One"],
                                    "exit_count": 10,
                                },
                            },
                            {
                                "entry_key": "new",
                                "title": "New Hack",
                                "source_references": [
                                    {
                                        "source": "smwc",
                                        "external_id": "200",
                                    }
                                ],
                                "attributes": {
                                    "authors": ["Author Two"],
                                    "exit_count": 20,
                                },
                            },
                        ],
                        "groups": [
                            {
                                "group_key": "all",
                                "title": "All",
                                "entry_keys": ["matched", "new"],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            manager = HackDataManager(str(processed))
            before = deepcopy(manager.data)

            preview = plan_v5_1_bulk_collection_import_workflow_preview(
                str(import_path),
                manager,
            )

            self.assertEqual(preview.import_id, "real-file-preview")
            self.assertEqual(
                tuple(row.outcome for row in preview.rows),
                ("match_existing", "add_new"),
            )
            self.assertEqual(manager.data, before)
            self.assertNotIn(
                "must not appear",
                serialize_bulk_collection_import_workflow_preview(
                    preview
                ),
            )

    def test_real_file_path_rejects_wrong_manager_type(self):
        with self.assertRaises(TypeError):
            plan_v5_1_bulk_collection_import_workflow_preview(
                "unused.json",
                object(),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
