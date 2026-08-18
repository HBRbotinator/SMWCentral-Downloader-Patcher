"""Specification for v5.1 bulk-import review form requirements."""

from __future__ import annotations

import json
import unittest
from copy import deepcopy
from types import MappingProxyType

from bulk_collection_import_workflow_preview import (
    BulkCollectionImportWorkflowCandidate,
    BulkCollectionImportWorkflowConflict,
    BulkCollectionImportWorkflowGroup,
    BulkCollectionImportWorkflowPreview,
    BulkCollectionImportWorkflowRow,
)


REVIEW_FORM_SCHEMA = "smwc-bulk-collection-review-form"
REVIEW_FORM_VERSION = 1

REVIEW_KIND_AMBIGUOUS_IDENTITY = "ambiguous_identity"
REVIEW_KIND_HARD_IDENTITY_CONFLICT = "hard_identity_conflict"
REVIEW_KIND_METADATA = "metadata"

REVIEW_SELECTION_ACTIONS = (
    "select_existing",
    "create_new",
    "resolve_metadata",
    "skip",
)

CONFLICT_CHOICES = (
    "keep_existing",
    "use_imported",
)

REVIEW_DECISION_SCHEMA = "smwc-bulk-collection-review-decisions"
REVIEW_DECISION_VERSION = 1

SOURCE_SHA256 = "e" * 64


def _preview():
    rows = (
        BulkCollectionImportWorkflowRow(
            entry_key="safe-add",
            title="Safe Add",
            outcome="add_new",
            merge_action="create_record",
            resolution_status="new",
            collection_keys=(),
            proposed_source_references=(),
            warnings=(),
            conflicts=(),
            candidates=(),
            requires_review=False,
        ),
        BulkCollectionImportWorkflowRow(
            entry_key="ambiguous",
            title="Ambiguous Hack",
            outcome="review_required",
            merge_action="review_required",
            resolution_status="ambiguous",
            collection_keys=("usr_1", "usr_2"),
            proposed_source_references=(),
            warnings=(
                "identity_review_required",
                "identity_ambiguous",
            ),
            conflicts=(),
            candidates=(
                BulkCollectionImportWorkflowCandidate(
                    collection_key="usr_1",
                    title="Ambiguous Hack",
                    authors=("Author One",),
                ),
                BulkCollectionImportWorkflowCandidate(
                    collection_key="usr_2",
                    title="Ambiguous Hack",
                    authors=("Author Two",),
                ),
            ),
            requires_review=True,
        ),
        BulkCollectionImportWorkflowRow(
            entry_key="hard-conflict",
            title="Conflicting Identity",
            outcome="review_required",
            merge_action="review_required",
            resolution_status="conflict",
            collection_keys=("100", "200"),
            proposed_source_references=(),
            warnings=(
                "identity_review_required",
                "identity_conflict",
                "source_identity_conflict",
            ),
            conflicts=(),
            candidates=(
                BulkCollectionImportWorkflowCandidate(
                    collection_key="100",
                    title="First Candidate",
                    authors=("Author Three",),
                ),
                BulkCollectionImportWorkflowCandidate(
                    collection_key="200",
                    title="Second Candidate",
                    authors=("Author Four",),
                ),
            ),
            requires_review=True,
        ),
        BulkCollectionImportWorkflowRow(
            entry_key="metadata",
            title="Metadata Conflict",
            outcome="match_existing",
            merge_action="review_required",
            resolution_status="matched_source",
            collection_keys=("300",),
            proposed_source_references=(),
            warnings=("metadata_conflict",),
            conflicts=(
                BulkCollectionImportWorkflowConflict(
                    field="title",
                    existing_value="Existing Title",
                    imported_value="Imported Title",
                ),
                BulkCollectionImportWorkflowConflict(
                    field="exit_count",
                    existing_value=14,
                    imported_value=15,
                ),
                BulkCollectionImportWorkflowConflict(
                    field="difficulty",
                    existing_value="Advanced",
                    imported_value="Expert",
                ),
            ),
            candidates=(
                BulkCollectionImportWorkflowCandidate(
                    collection_key="300",
                    title="Existing Title",
                    authors=("Author Five",),
                ),
            ),
            requires_review=True,
        ),
        BulkCollectionImportWorkflowRow(
            entry_key="unchanged",
            title="Already Safe",
            outcome="match_existing",
            merge_action="no_change",
            resolution_status="matched_source",
            collection_keys=("400",),
            proposed_source_references=(),
            warnings=(),
            conflicts=(),
            candidates=(
                BulkCollectionImportWorkflowCandidate(
                    collection_key="400",
                    title="Already Safe",
                    authors=("Author Six",),
                ),
            ),
            requires_review=False,
        ),
    )

    return BulkCollectionImportWorkflowPreview(
        schema="smwc-bulk-collection-workflow-preview",
        version=1,
        source_name="review-list.json",
        byte_count=4096,
        source_sha256=SOURCE_SHA256,
        import_id="review-form-suite",
        title="Review Form Suite",
        summary=MappingProxyType(
            {
                "total": 5,
                "create_record": 1,
                "update_record": 0,
                "no_change": 1,
                "review_required": 3,
            }
        ),
        rows=rows,
        groups=(
            BulkCollectionImportWorkflowGroup(
                group_key="all",
                title="All",
                entry_keys=tuple(row.entry_key for row in rows),
            ),
        ),
    )


class BulkCollectionImportReviewFormContractMixin:
    """Reusable contract for explicit UI review requirements."""

    def build_form(self, preview):
        raise NotImplementedError

    def form_to_document(self, form):
        raise NotImplementedError

    def build_review_document(self, form, selections):
        raise NotImplementedError

    def serialize_review_document(self, document):
        raise NotImplementedError

    def assert_form_error(self, preview):
        raise NotImplementedError

    def assert_selection_error(self, form, selections):
        raise NotImplementedError

    def test_form_contains_only_review_required_rows(self):
        form = self.build_form(_preview())

        self.assertEqual(
            tuple(item.entry_key for item in form.items),
            (
                "ambiguous",
                "hard-conflict",
                "metadata",
            ),
        )

    def test_form_preserves_source_identity(self):
        form = self.build_form(_preview())

        self.assertEqual(form.import_id, "review-form-suite")
        self.assertEqual(form.source_sha256, SOURCE_SHA256)

    def test_ambiguous_identity_allows_three_explicit_actions(self):
        form = self.build_form(_preview())
        item = form.items[0]

        self.assertEqual(
            item.review_kind,
            REVIEW_KIND_AMBIGUOUS_IDENTITY,
        )
        self.assertEqual(
            item.allowed_actions,
            ("select_existing", "create_new", "skip"),
        )
        self.assertEqual(
            tuple(
                candidate.collection_key
                for candidate in item.candidates
            ),
            ("usr_1", "usr_2"),
        )
        self.assertEqual(item.conflicts, ())

    def test_hard_identity_conflict_is_skip_only(self):
        form = self.build_form(_preview())
        item = form.items[1]

        self.assertEqual(
            item.review_kind,
            REVIEW_KIND_HARD_IDENTITY_CONFLICT,
        )
        self.assertEqual(item.allowed_actions, ("skip",))
        self.assertEqual(
            item.warnings,
            (
                "identity_review_required",
                "identity_conflict",
                "source_identity_conflict",
            ),
        )

    def test_metadata_review_allows_resolve_or_skip(self):
        form = self.build_form(_preview())
        item = form.items[2]

        self.assertEqual(item.review_kind, REVIEW_KIND_METADATA)
        self.assertEqual(
            item.allowed_actions,
            ("resolve_metadata", "skip"),
        )
        self.assertEqual(item.collection_keys, ("300",))
        self.assertEqual(
            tuple(conflict.field for conflict in item.conflicts),
            ("title", "exit_count", "difficulty"),
        )

    def test_no_choice_is_preselected(self):
        document = self.form_to_document(
            self.build_form(_preview())
        )

        for item in document["items"]:
            self.assertIsNone(item["selected_action"])
            self.assertIsNone(
                item["selected_collection_key"]
            )
            for conflict in item["conflicts"]:
                self.assertIsNone(conflict["selected_choice"])

    def test_select_existing_emits_existing_review_contract(self):
        form = self.build_form(_preview())
        document = self.build_review_document(
            form,
            {
                "ambiguous": {
                    "action": "select_existing",
                    "selected_collection_key": "usr_2",
                },
                "hard-conflict": {
                    "action": "skip",
                },
                "metadata": {
                    "action": "skip",
                },
            },
        )

        self.assertEqual(
            document["decisions"][0],
            {
                "entry_key": "ambiguous",
                "action": "select_existing",
                "selected_collection_key": "usr_2",
                "title_choice": None,
                "attribute_choices": [],
            },
        )

    def test_create_new_emits_no_existing_target(self):
        form = self.build_form(_preview())
        document = self.build_review_document(
            form,
            {
                "ambiguous": {
                    "action": "create_new",
                },
                "hard-conflict": {
                    "action": "skip",
                },
                "metadata": {
                    "action": "skip",
                },
            },
        )

        self.assertEqual(
            document["decisions"][0],
            {
                "entry_key": "ambiguous",
                "action": "create_new",
                "selected_collection_key": None,
                "title_choice": None,
                "attribute_choices": [],
            },
        )

    def test_metadata_resolution_requires_every_conflict_choice(self):
        form = self.build_form(_preview())

        self.assert_selection_error(
            form,
            {
                "ambiguous": {"action": "skip"},
                "hard-conflict": {"action": "skip"},
                "metadata": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "use_imported",
                        "exit_count": "keep_existing",
                    },
                },
            },
        )

    def test_metadata_resolution_emits_title_and_attribute_choices(self):
        form = self.build_form(_preview())
        document = self.build_review_document(
            form,
            {
                "ambiguous": {"action": "skip"},
                "hard-conflict": {"action": "skip"},
                "metadata": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "use_imported",
                        "exit_count": "keep_existing",
                        "difficulty": "use_imported",
                    },
                },
            },
        )

        self.assertEqual(
            document["decisions"][2],
            {
                "entry_key": "metadata",
                "action": "resolve_metadata",
                "selected_collection_key": "300",
                "title_choice": "use_imported",
                "attribute_choices": [
                    {
                        "field": "exit_count",
                        "choice": "keep_existing",
                    },
                    {
                        "field": "difficulty",
                        "choice": "use_imported",
                    },
                ],
            },
        )

    def test_skip_discards_all_extra_selection_data(self):
        form = self.build_form(_preview())

        self.assert_selection_error(
            form,
            {
                "ambiguous": {
                    "action": "skip",
                    "selected_collection_key": "usr_1",
                },
                "hard-conflict": {"action": "skip"},
                "metadata": {"action": "skip"},
            },
        )

    def test_hard_conflict_rejects_select_existing(self):
        form = self.build_form(_preview())

        self.assert_selection_error(
            form,
            {
                "ambiguous": {"action": "skip"},
                "hard-conflict": {
                    "action": "select_existing",
                    "selected_collection_key": "100",
                },
                "metadata": {"action": "skip"},
            },
        )

    def test_ambiguous_selection_must_use_candidate_key(self):
        form = self.build_form(_preview())

        self.assert_selection_error(
            form,
            {
                "ambiguous": {
                    "action": "select_existing",
                    "selected_collection_key": "not-a-candidate",
                },
                "hard-conflict": {"action": "skip"},
                "metadata": {"action": "skip"},
            },
        )

    def test_every_review_row_requires_an_explicit_selection(self):
        form = self.build_form(_preview())

        self.assert_selection_error(
            form,
            {
                "ambiguous": {"action": "skip"},
                "hard-conflict": {"action": "skip"},
            },
        )

    def test_unknown_or_duplicate_selection_fields_fail_closed(self):
        form = self.build_form(_preview())

        self.assert_selection_error(
            form,
            {
                "ambiguous": {
                    "action": "skip",
                    "unexpected": True,
                },
                "hard-conflict": {"action": "skip"},
                "metadata": {"action": "skip"},
            },
        )

    def test_conflict_choice_is_limited_to_existing_contract(self):
        form = self.build_form(_preview())

        self.assert_selection_error(
            form,
            {
                "ambiguous": {"action": "skip"},
                "hard-conflict": {"action": "skip"},
                "metadata": {
                    "action": "resolve_metadata",
                    "choices": {
                        "title": "merge_both",
                        "exit_count": "keep_existing",
                        "difficulty": "use_imported",
                    },
                },
            },
        )

    def test_review_document_uses_existing_review_schema(self):
        form = self.build_form(_preview())
        document = self.build_review_document(
            form,
            {
                "ambiguous": {"action": "skip"},
                "hard-conflict": {"action": "skip"},
                "metadata": {"action": "skip"},
            },
        )

        self.assertEqual(
            document["schema"],
            REVIEW_DECISION_SCHEMA,
        )
        self.assertEqual(
            document["version"],
            REVIEW_DECISION_VERSION,
        )
        self.assertEqual(
            document["import_id"],
            "review-form-suite",
        )
        self.assertEqual(
            document["source_sha256"],
            SOURCE_SHA256,
        )

    def test_review_decisions_preserve_form_order(self):
        form = self.build_form(_preview())
        document = self.build_review_document(
            form,
            {
                "metadata": {"action": "skip"},
                "hard-conflict": {"action": "skip"},
                "ambiguous": {"action": "skip"},
            },
        )

        self.assertEqual(
            tuple(
                item["entry_key"]
                for item in document["decisions"]
            ),
            (
                "ambiguous",
                "hard-conflict",
                "metadata",
            ),
        )

    def test_form_is_immutable_and_documents_are_detached(self):
        form = self.build_form(_preview())

        with self.assertRaises((AttributeError, TypeError)):
            form.items[0].allowed_actions += ("unsafe",)

        document = self.form_to_document(form)
        document["items"][0]["allowed_actions"].append("unsafe")

        clean = self.form_to_document(form)
        self.assertNotIn(
            "unsafe",
            clean["items"][0]["allowed_actions"],
        )

    def test_review_serialization_is_stable_compact_json(self):
        form = self.build_form(_preview())
        document = self.build_review_document(
            form,
            {
                "ambiguous": {"action": "skip"},
                "hard-conflict": {"action": "skip"},
                "metadata": {"action": "skip"},
            },
        )
        serialized = self.serialize_review_document(document)

        self.assertEqual(
            serialized,
            json.dumps(
                json.loads(serialized),
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ),
        )

    def test_malformed_identity_warning_combinations_fail_closed(self):
        preview = _preview()
        rows = list(preview.rows)
        ambiguous = rows[1]
        rows[1] = BulkCollectionImportWorkflowRow(
            entry_key=ambiguous.entry_key,
            title=ambiguous.title,
            outcome=ambiguous.outcome,
            merge_action=ambiguous.merge_action,
            resolution_status=ambiguous.resolution_status,
            collection_keys=ambiguous.collection_keys,
            proposed_source_references=(
                ambiguous.proposed_source_references
            ),
            warnings=(
                "identity_review_required",
                "identity_ambiguous",
                "identity_conflict",
            ),
            conflicts=ambiguous.conflicts,
            candidates=ambiguous.candidates,
            requires_review=True,
        )
        malformed = BulkCollectionImportWorkflowPreview(
            schema=preview.schema,
            version=preview.version,
            source_name=preview.source_name,
            byte_count=preview.byte_count,
            source_sha256=preview.source_sha256,
            import_id=preview.import_id,
            title=preview.title,
            summary=preview.summary,
            rows=tuple(rows),
            groups=preview.groups,
        )

        self.assert_form_error(malformed)


class BulkCollectionImportReviewFormSpecificationTest(
    unittest.TestCase
):
    """Lock the safe decision surface before adding Tk controls."""

    def test_review_kinds_are_repository_specific_ui_concepts(self):
        self.assertEqual(
            (
                REVIEW_KIND_AMBIGUOUS_IDENTITY,
                REVIEW_KIND_HARD_IDENTITY_CONFLICT,
                REVIEW_KIND_METADATA,
            ),
            (
                "ambiguous_identity",
                "hard_identity_conflict",
                "metadata",
            ),
        )

    def test_existing_review_actions_are_reused(self):
        self.assertEqual(
            REVIEW_SELECTION_ACTIONS,
            (
                "select_existing",
                "create_new",
                "resolve_metadata",
                "skip",
            ),
        )
        self.assertEqual(
            CONFLICT_CHOICES,
            ("keep_existing", "use_imported"),
        )

    def test_form_does_not_invent_persistence_or_planner_actions(self):
        self.assertNotIn("apply", REVIEW_SELECTION_ACTIONS)
        self.assertNotIn("save", REVIEW_SELECTION_ACTIONS)
        self.assertNotIn("planner", REVIEW_SELECTION_ACTIONS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
