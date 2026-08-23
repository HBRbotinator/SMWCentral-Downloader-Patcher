"""Interactive bulk Collection import review dialog tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import Mock, patch

from bulk_collection_import_apply import (
    execute_bulk_collection_import_apply_session,
)
from bulk_collection_import_persistence import (
    BulkCollectionImportPersistenceItem,
    BulkCollectionImportPersistenceResult,
)

from bulk_collection_import_application import (
    BulkCollectionImportApplicationAttributeChange,
    BulkCollectionImportApplicationGroup,
    BulkCollectionImportApplicationOperation,
    BulkCollectionImportApplicationPlan,
    BulkCollectionImportApplicationSourceReference,
)
from bulk_collection_import_resolution import (
    BulkCollectionImportResolutionAttributeChange,
    BulkCollectionImportResolutionConflict,
    BulkCollectionImportResolutionGroup,
    BulkCollectionImportResolutionItem,
    BulkCollectionImportResolutionPlan,
    BulkCollectionImportResolutionSourceReference,
)
from bulk_collection_import_second_review import (
    BulkCollectionImportSecondReviewError,
)
from bulk_collection_import_review_form import (
    BulkCollectionImportReviewFormError,
)
from bulk_collection_import_workflow_preview import (
    BulkCollectionImportWorkflowCandidate,
    BulkCollectionImportWorkflowConflict,
    BulkCollectionImportWorkflowGroup,
    BulkCollectionImportWorkflowPreview,
    BulkCollectionImportWorkflowRow,
    BulkCollectionImportWorkflowSourceReference,
)


def _load_dialog_class():
    path = Path("ui/bulk_collection_import_dialog.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "bulk_collection_import_dialog_under_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BulkCollectionImportDialog


BulkCollectionImportDialog = _load_dialog_class()


def _preview():
    rows = (
        BulkCollectionImportWorkflowRow(
            entry_key="matched",
            title="Matched Hack",
            outcome="match_existing",
            merge_action="update_record",
            resolution_status="matched_source",
            collection_keys=("100",),
            proposed_source_references=(
                BulkCollectionImportWorkflowSourceReference(
                    source="kaizoff",
                    external_id="mirror-100",
                ),
            ),
            warnings=(),
            conflicts=(),
            candidates=(
                BulkCollectionImportWorkflowCandidate(
                    collection_key="100",
                    title="Matched Hack",
                    authors=("Author One",),
                ),
            ),
            requires_review=False,
        ),
        BulkCollectionImportWorkflowRow(
            entry_key="new",
            title="New Hack",
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
                    authors=("Author Two",),
                ),
                BulkCollectionImportWorkflowCandidate(
                    collection_key="usr_2",
                    title="Ambiguous Hack",
                    authors=("Author Three",),
                ),
            ),
            requires_review=True,
        ),
        BulkCollectionImportWorkflowRow(
            entry_key="hard",
            title="Hard Identity Conflict",
            outcome="review_required",
            merge_action="review_required",
            resolution_status="conflict",
            collection_keys=("500", "501"),
            proposed_source_references=(),
            warnings=(
                "identity_review_required",
                "identity_conflict",
                "source_identity_conflict",
            ),
            conflicts=(),
            candidates=(
                BulkCollectionImportWorkflowCandidate(
                    collection_key="500",
                    title="First Identity",
                    authors=("Author Four",),
                ),
                BulkCollectionImportWorkflowCandidate(
                    collection_key="501",
                    title="Second Identity",
                    authors=("Author Five",),
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
                    existing_value="Old Title",
                    imported_value="Metadata Conflict",
                ),
                BulkCollectionImportWorkflowConflict(
                    field="exit_count",
                    existing_value=14,
                    imported_value=15,
                ),
            ),
            candidates=(
                BulkCollectionImportWorkflowCandidate(
                    collection_key="300",
                    title="Old Title",
                    authors=("Author Six",),
                ),
            ),
            requires_review=True,
        ),
    )

    return BulkCollectionImportWorkflowPreview(
        schema="smwc-bulk-collection-workflow-preview",
        version=1,
        source_name="bulk-list.json",
        byte_count=2048,
        source_sha256="f" * 64,
        import_id="dialog-review-suite",
        title="Example Bulk List",
        summary=MappingProxyType(
            {
                "total": 5,
                "create_record": 1,
                "update_record": 1,
                "no_change": 0,
                "review_required": 3,
            }
        ),
        rows=rows,
        groups=(
            BulkCollectionImportWorkflowGroup(
                group_key="queue",
                title="Queue",
                entry_keys=tuple(row.entry_key for row in rows),
            ),
        ),
    )




def _application_plan():
    operations = (
        BulkCollectionImportApplicationOperation(
            entry_key="matched",
            action="update_record",
            collection_key="100",
            expected_shared_sha256="c" * 64,
            title_value=None,
            source_references=(),
            source_reference_additions=(
                BulkCollectionImportApplicationSourceReference(
                    source="kaizoff",
                    external_id="mirror-100",
                ),
            ),
            attributes=MappingProxyType({}),
            attribute_changes=(
                BulkCollectionImportApplicationAttributeChange(
                    field="difficulty",
                    value="Expert",
                ),
            ),
            warnings=(),
        ),
        BulkCollectionImportApplicationOperation(
            entry_key="new",
            action="create_record",
            collection_key="usr_import_0123456789abcdef",
            expected_shared_sha256=None,
            title_value="New Hack",
            source_references=(
                BulkCollectionImportApplicationSourceReference(
                    source="kaizoff",
                    external_id="new-hack",
                ),
            ),
            source_reference_additions=(),
            attributes=MappingProxyType(
                {"authors": ("Author New",)}
            ),
            attribute_changes=(),
            warnings=(),
        ),
        BulkCollectionImportApplicationOperation(
            entry_key="ambiguous",
            action="no_change",
            collection_key="usr_1",
            expected_shared_sha256="d" * 64,
            title_value=None,
            source_references=(),
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            warnings=(),
        ),
        BulkCollectionImportApplicationOperation(
            entry_key="hard",
            action="skip",
            collection_key=None,
            expected_shared_sha256=None,
            title_value=None,
            source_references=(),
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            warnings=("source_identity_conflict",),
        ),
        BulkCollectionImportApplicationOperation(
            entry_key="metadata",
            action="update_record",
            collection_key="300",
            expected_shared_sha256="e" * 64,
            title_value="Metadata Conflict",
            source_references=(),
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            warnings=(),
        ),
    )
    return BulkCollectionImportApplicationPlan(
        schema="smwc-bulk-collection-application-plan",
        version=1,
        import_id="dialog-review-suite",
        source_sha256="f" * 64,
        summary=MappingProxyType(
            {
                "total": 5,
                "create_record": 1,
                "update_record": 2,
                "no_change": 1,
                "skip": 1,
            }
        ),
        operations=operations,
        groups=(
            BulkCollectionImportApplicationGroup(
                group_key="queue",
                title="Queue",
                entry_keys=tuple(
                    operation.entry_key
                    for operation in operations
                ),
            ),
        ),
    )


def _preview_without_reviews():
    preview = _preview()
    rows = preview.rows[:2]
    return BulkCollectionImportWorkflowPreview(
        schema=preview.schema,
        version=preview.version,
        source_name=preview.source_name,
        byte_count=preview.byte_count,
        source_sha256=preview.source_sha256,
        import_id=preview.import_id,
        title=preview.title,
        summary=MappingProxyType(
            {
                "total": 2,
                "create_record": 1,
                "update_record": 1,
                "no_change": 0,
                "review_required": 0,
            }
        ),
        rows=rows,
        groups=(
            BulkCollectionImportWorkflowGroup(
                group_key="queue",
                title="Queue",
                entry_keys=tuple(row.entry_key for row in rows),
            ),
        ),
    )


def _resolution_plan(*, further_review=0):
    actions = [
        BulkCollectionImportResolutionItem(
            entry_key="matched",
            action="update_record",
            collection_key="100",
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=(),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="new",
            action="create_record",
            collection_key=None,
            title_value="New Hack",
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=(),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="ambiguous",
            action=(
                "review_required"
                if further_review
                else "no_change"
            ),
            collection_key="usr_1",
            title_value=None,
            source_reference_additions=(
                (
                    BulkCollectionImportResolutionSourceReference(
                        source="kaizoff",
                        external_id="ko-ambiguous",
                    ),
                )
                if further_review
                else ()
            ),
            attributes=MappingProxyType({}),
            attribute_changes=(
                (
                    BulkCollectionImportResolutionAttributeChange(
                        field="release_date",
                        value="2025-04-03",
                    ),
                )
                if further_review
                else ()
            ),
            conflicts=(
                (
                    BulkCollectionImportResolutionConflict(
                        field="title",
                        existing_value="Existing Ambiguous Hack",
                        imported_value="Ambiguous Hack",
                    ),
                    BulkCollectionImportResolutionConflict(
                        field="exit_count",
                        existing_value=14,
                        imported_value=15,
                    ),
                )
                if further_review
                else ()
            ),
            warnings=(
                ("metadata_conflict",)
                if further_review
                else ()
            ),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="hard",
            action="skip",
            collection_key=None,
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=("source_identity_conflict",),
        ),
        BulkCollectionImportResolutionItem(
            entry_key="metadata",
            action="update_record",
            collection_key="300",
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=(),
        ),
    ]
    summary = {
        "total": 5,
        "create_record": 1,
        "update_record": 2,
        "no_change": 0 if further_review else 1,
        "review_required": 1 if further_review else 0,
        "skip": 1,
    }
    return BulkCollectionImportResolutionPlan(
        schema="smwc-bulk-collection-resolution-plan",
        version=1,
        import_id="dialog-review-suite",
        source_sha256="f" * 64,
        summary=MappingProxyType(summary),
        items=tuple(actions),
        groups=(
            BulkCollectionImportResolutionGroup(
                group_key="queue",
                title="Queue",
                entry_keys=tuple(item.entry_key for item in actions),
            ),
        ),
    )




class _DialogApplyStore:
    def __init__(self, plan):
        self.plan = plan
        self.begin_count = 0
        self.transaction = _DialogApplyTransaction()

    def record_exists(self, collection_key):
        return False

    def shared_sha256(self, collection_key):
        operation = next(
            operation
            for operation in self.plan.operations
            if operation.collection_key == collection_key
        )
        return operation.expected_shared_sha256

    def begin_transaction(self):
        self.begin_count += 1
        return self.transaction


class _DialogApplyTransaction:
    def __init__(self):
        self.created = []
        self.updated = []
        self.commit_count = 0
        self.rollback_count = 0

    def create_record(self, **kwargs):
        self.created.append(kwargs)

    def update_record(self, **kwargs):
        self.updated.append(kwargs)

    def commit(self):
        self.commit_count += 1

    def rollback(self):
        self.rollback_count += 1


def _apply_result():
    items = (
        BulkCollectionImportPersistenceItem(
            entry_key="matched",
            outcome="updated",
            collection_key="100",
            warnings=(),
        ),
        BulkCollectionImportPersistenceItem(
            entry_key="new",
            outcome="created",
            collection_key="usr_import_0123456789abcdef",
            warnings=(),
        ),
        BulkCollectionImportPersistenceItem(
            entry_key="ambiguous",
            outcome="unchanged",
            collection_key="usr_1",
            warnings=(),
        ),
        BulkCollectionImportPersistenceItem(
            entry_key="hard",
            outcome="skipped",
            collection_key=None,
            warnings=("source_identity_conflict",),
        ),
        BulkCollectionImportPersistenceItem(
            entry_key="metadata",
            outcome="updated",
            collection_key="300",
            warnings=(),
        ),
    )
    return BulkCollectionImportPersistenceResult(
        schema="smwc-bulk-collection-persistence-result",
        version=1,
        import_id="dialog-review-suite",
        source_sha256="f" * 64,
        summary=MappingProxyType(
            {
                "total": 5,
                "created": 1,
                "updated": 2,
                "unchanged": 1,
                "skipped": 1,
            }
        ),
        items=items,
    )


class BulkCollectionImportDialogContractTest(unittest.TestCase):
    def test_constructor_requires_real_workflow_preview(self):
        with self.assertRaises(TypeError):
            BulkCollectionImportDialog(None, object())

    def test_constructor_rejects_non_callable_callbacks(self):
        with self.assertRaises(TypeError):
            BulkCollectionImportDialog(
                None,
                _preview(),
                on_close="not callable",
            )

        with self.assertRaises(TypeError):
            BulkCollectionImportDialog(
                None,
                _preview(),
                on_review_ready="not callable",
            )

        with self.assertRaises(TypeError):
            BulkCollectionImportDialog(
                None,
                _preview(),
                on_application_preview="not callable",
            )

        with self.assertRaises(TypeError):
            BulkCollectionImportDialog(
                None,
                _preview(),
                on_apply="not callable",
            )

    def test_constructor_builds_review_form_without_defaults(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        self.assertEqual(
            tuple(item.entry_key for item in dialog.review_form.items),
            ("ambiguous", "hard", "metadata"),
        )
        self.assertEqual(dialog.selections, {})
        self.assertIsNone(dialog.validated_review_document)

    def test_safe_rows_cannot_receive_review_actions(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        with self.assertRaises(BulkCollectionImportReviewFormError):
            dialog.set_review_action("matched", "skip")

    def test_ambiguous_select_existing_requires_candidate(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        with self.assertRaises(BulkCollectionImportReviewFormError):
            dialog.set_review_action(
                "ambiguous",
                "select_existing",
            )

        with self.assertRaises(BulkCollectionImportReviewFormError):
            dialog.set_review_action(
                "ambiguous",
                "select_existing",
                "not-a-candidate",
            )

        dialog.set_review_action(
            "ambiguous",
            "select_existing",
            "usr_2",
        )

        self.assertEqual(
            dialog.selections["ambiguous"],
            {
                "action": "select_existing",
                "selected_collection_key": "usr_2",
            },
        )

    def test_ambiguous_create_new_and_skip_are_explicit(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        dialog.set_review_action("ambiguous", "create_new")
        self.assertEqual(
            dialog.selections["ambiguous"],
            {"action": "create_new"},
        )

        dialog.set_review_action("ambiguous", "skip")
        self.assertEqual(
            dialog.selections["ambiguous"],
            {"action": "skip"},
        )

    def test_hard_conflict_is_skip_only(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        with self.assertRaises(BulkCollectionImportReviewFormError):
            dialog.set_review_action("hard", "create_new")

        dialog.set_review_action("hard", "skip")
        self.assertEqual(
            dialog.selections["hard"],
            {"action": "skip"},
        )

    def test_metadata_requires_resolve_action_before_choices(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        with self.assertRaises(BulkCollectionImportReviewFormError):
            dialog.set_metadata_choice(
                "metadata",
                "title",
                "use_imported",
            )

        dialog.set_review_action(
            "metadata",
            "resolve_metadata",
        )
        dialog.set_metadata_choice(
            "metadata",
            "title",
            "use_imported",
        )

        self.assertEqual(
            dialog.selections["metadata"],
            {
                "action": "resolve_metadata",
                "choices": {
                    "title": "use_imported",
                },
            },
        )

    def test_metadata_rejects_unknown_field_or_choice(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.set_review_action(
            "metadata",
            "resolve_metadata",
        )

        with self.assertRaises(BulkCollectionImportReviewFormError):
            dialog.set_metadata_choice(
                "metadata",
                "authors",
                "use_imported",
            )

        with self.assertRaises(BulkCollectionImportReviewFormError):
            dialog.set_metadata_choice(
                "metadata",
                "title",
                "merge_both",
            )

    def test_validation_requires_every_review_row_and_field(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.set_review_action("ambiguous", "skip")
        dialog.set_review_action("hard", "skip")
        dialog.set_review_action(
            "metadata",
            "resolve_metadata",
        )
        dialog.set_metadata_choice(
            "metadata",
            "title",
            "use_imported",
        )

        with self.assertRaises(BulkCollectionImportReviewFormError):
            dialog.build_validated_review_document()

        self.assertIsNone(dialog.validated_review_document)

    def test_complete_review_builds_existing_review_document(self):
        callback = Mock(return_value=_resolution_plan())
        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_review_ready=callback,
        )
        dialog.set_review_action(
            "ambiguous",
            "select_existing",
            "usr_1",
        )
        dialog.set_review_action("hard", "skip")
        dialog.set_review_action(
            "metadata",
            "resolve_metadata",
        )
        dialog.set_metadata_choice(
            "metadata",
            "title",
            "use_imported",
        )
        dialog.set_metadata_choice(
            "metadata",
            "exit_count",
            "keep_existing",
        )

        document = dialog.build_validated_review_document()

        self.assertEqual(
            document["schema"],
            "smwc-bulk-collection-review-decisions",
        )
        self.assertEqual(document["version"], 1)
        self.assertEqual(
            tuple(
                decision["entry_key"]
                for decision in document["decisions"]
            ),
            ("ambiguous", "hard", "metadata"),
        )
        self.assertIs(
            dialog.validated_review_document,
            document,
        )
        self.assertIs(dialog.resolution_plan, callback.return_value)
        callback.assert_called_once_with(document)

    def test_new_edit_invalidates_previous_validation(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.set_review_action("ambiguous", "skip")
        dialog.set_review_action("hard", "skip")
        dialog.set_review_action("metadata", "skip")

        dialog.build_validated_review_document()
        self.assertIsNotNone(dialog.validated_review_document)

        dialog.set_review_action("ambiguous", "create_new")

        self.assertIsNone(dialog.validated_review_document)
        self.assertIsNone(dialog.resolution_plan)

    def test_clear_returns_row_to_unselected_state(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.set_review_action("ambiguous", "skip")

        dialog.clear_review_selection("ambiguous")

        self.assertNotIn("ambiguous", dialog.selections)

    def test_selections_projection_is_detached(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.set_review_action(
            "metadata",
            "resolve_metadata",
        )
        dialog.set_metadata_choice(
            "metadata",
            "title",
            "keep_existing",
        )

        projected = dialog.selections
        projected["metadata"]["choices"]["title"] = "use_imported"

        self.assertEqual(
            dialog.selections["metadata"]["choices"]["title"],
            "keep_existing",
        )

    def test_group_lookup_preserves_preview_membership(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        self.assertEqual(
            dialog._group_titles,
            {
                "matched": "Queue",
                "new": "Queue",
                "ambiguous": "Queue",
                "hard": "Queue",
                "metadata": "Queue",
            },
        )

    def test_row_values_still_distinguish_add_match_and_review(self):
        preview = _preview()

        self.assertEqual(
            BulkCollectionImportDialog._row_values(
                preview.rows[0],
                "Queue",
            ),
            ("Queue", "Match", "Matched Hack", "100"),
        )
        self.assertEqual(
            BulkCollectionImportDialog._row_values(
                preview.rows[1],
                "Queue",
            ),
            (
                "Queue",
                "Add",
                "New Hack",
                "New Collection entry",
            ),
        )
        self.assertEqual(
            BulkCollectionImportDialog._row_values(
                preview.rows[2],
                "Queue",
            ),
            (
                "Queue",
                "Review",
                "Ambiguous Hack",
                "usr_1, usr_2",
            ),
        )

    def test_dialog_source_exposes_review_controls_and_validation_only(self):
        source = Path(
            "ui/bulk_collection_import_dialog.py"
        ).read_text(encoding="utf-8")

        for required in (
            '"Select Existing"',
            '"Create New"',
            '"Resolve Metadata"',
            '"Skip"',
            '"Keep Existing"',
            '"Use Imported"',
            'text="Validate Review"',
            "build_bulk_collection_import_review_document(",
            "No Collection changes have been applied",
            "Post-review resolution preview",
            "_resolution_summary_text",
            "Follow-up metadata review",
        ):
            self.assertIn(required, source)

    def test_dialog_has_no_direct_persistence_implementation(self):
        source = Path(
            "ui/bulk_collection_import_dialog.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            'text="Save',
            "resolve_bulk_collection_import",
            "build_v5_1_bulk_collection_import_application_plan",
            "allocate_bulk_collection_import_keys",
            "execute_bulk_collection_import",
            "BulkCollectionImportHackDataStore",
            "save_data(",
            "force_save(",
            "update_hack(",
            "add_user_hack(",
            "planner_store",
        ):
            self.assertNotIn(forbidden, source)

    def test_dialog_never_displays_user_owned_collection_fields(self):
        source = Path(
            "ui/bulk_collection_import_dialog.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            "completed_date",
            "personal_rating",
            "save_paths",
            "rom_paths",
            "file_path",
            "time_to_beat",
        ):
            self.assertNotIn(forbidden, source)


    def test_resolution_summary_exposes_post_review_actions(self):
        text = BulkCollectionImportDialog._resolution_summary_text(
            _resolution_plan()
        )

        self.assertEqual(
            text,
            "5 entries · 1 add · 2 update · 1 unchanged · "
            "1 skip · 0 further review\n"
            "All post-review actions are resolved. "
            "The final application preview can now be prepared.",
        )

    def test_resolution_summary_calls_out_further_review(self):
        text = BulkCollectionImportDialog._resolution_summary_text(
            _resolution_plan(further_review=1)
        )

        self.assertIn("1 further review", text)
        self.assertIn(
            "Further review is required",
            text,
        )

    def test_resolution_callback_wrong_type_fails_closed(self):
        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_review_ready=lambda _document: object(),
        )
        dialog.set_review_action("ambiguous", "skip")
        dialog.set_review_action("hard", "skip")
        dialog.set_review_action("metadata", "skip")

        with self.assertRaises(TypeError):
            dialog.build_validated_review_document()

        self.assertIsNone(dialog.validated_review_document)
        self.assertIsNone(dialog.resolution_plan)



    def test_further_review_builds_second_round_form(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)

        self.assertIsNotNone(dialog.second_review_form)
        self.assertEqual(
            tuple(
                item.entry_key
                for item in dialog.second_review_form.items
            ),
            ("ambiguous",),
        )
        self.assertEqual(dialog.second_review_selections, {})

    def test_second_round_rejects_safe_rows(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)

        with self.assertRaises(BulkCollectionImportSecondReviewError):
            dialog.set_second_review_action("matched", "skip")

    def test_second_round_metadata_choices_are_explicit(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)

        with self.assertRaises(BulkCollectionImportSecondReviewError):
            dialog.set_second_metadata_choice(
                "ambiguous",
                "title",
                "use_imported",
            )

        dialog.set_second_review_action(
            "ambiguous",
            "resolve_metadata",
        )
        dialog.set_second_metadata_choice(
            "ambiguous",
            "title",
            "use_imported",
        )
        dialog.set_second_metadata_choice(
            "ambiguous",
            "exit_count",
            "keep_existing",
        )

        self.assertEqual(
            dialog.second_review_selections["ambiguous"],
            {
                "action": "resolve_metadata",
                "choices": {
                    "title": "use_imported",
                    "exit_count": "keep_existing",
                },
            },
        )

    def test_second_round_validation_refines_resolution_to_zero_review(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)

        dialog.set_second_review_action(
            "ambiguous",
            "resolve_metadata",
        )
        dialog.set_second_metadata_choice(
            "ambiguous",
            "title",
            "use_imported",
        )
        dialog.set_second_metadata_choice(
            "ambiguous",
            "exit_count",
            "keep_existing",
        )

        document = dialog.build_validated_second_review_document()

        self.assertEqual(
            document["schema"],
            "smwc-bulk-collection-second-review-decisions",
        )
        self.assertEqual(
            dialog.resolution_plan.summary["review_required"],
            0,
        )
        self.assertEqual(
            dialog.resolution_plan.items[2].action,
            "update_record",
        )
        self.assertEqual(
            dialog.resolution_plan.items[2].title_value,
            "Ambiguous Hack",
        )
        self.assertEqual(
            tuple(
                (change.field, change.value)
                for change
                in dialog.resolution_plan.items[2].attribute_changes
            ),
            (("release_date", "2025-04-03"),),
        )
        self.assertIsNone(dialog.second_review_form)
        self.assertEqual(dialog.second_review_selections, {})

    def test_second_round_skip_discards_pending_changes(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)

        dialog.set_second_review_action("ambiguous", "skip")
        dialog.build_validated_second_review_document()

        item = dialog.resolution_plan.items[2]
        self.assertEqual(item.action, "skip")
        self.assertEqual(item.source_reference_additions, ())
        self.assertEqual(item.attribute_changes, ())
        self.assertEqual(item.conflicts, ())
        self.assertEqual(
            dialog.resolution_plan.summary["review_required"],
            0,
        )

    def test_second_round_projection_is_detached(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)
        dialog.set_second_review_action(
            "ambiguous",
            "resolve_metadata",
        )
        dialog.set_second_metadata_choice(
            "ambiguous",
            "title",
            "keep_existing",
        )

        projected = dialog.second_review_selections
        projected["ambiguous"]["choices"]["title"] = "use_imported"

        self.assertEqual(
            dialog.second_review_selections[
                "ambiguous"
            ]["choices"]["title"],
            "keep_existing",
        )

    def test_first_round_edit_clears_follow_up_state(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)
        self.assertIsNotNone(dialog.second_review_form)

        dialog._invalidate_validation()

        self.assertIsNone(dialog.resolution_plan)
        self.assertIsNone(dialog.second_review_form)
        self.assertEqual(dialog.second_review_selections, {})

    def test_second_round_context_exposes_target_and_safe_pending_work(self):
        dialog = BulkCollectionImportDialog(None, _preview())
        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)
        item = dialog.second_review_form.items[0]

        text = dialog._second_review_context_text(item)

        self.assertIn("usr_1", text)
        self.assertIn("kaizoff:ko-ambiguous", text)
        self.assertIn("release_date=2025-04-03", text)

    def test_dialog_source_renders_follow_up_controls_without_apply(self):
        source = Path(
            "ui/bulk_collection_import_dialog.py"
        ).read_text(encoding="utf-8")

        for required in (
            "Follow-up metadata review",
            'text="Validate Follow-up Review"',
            "build_bulk_collection_import_second_review_form(",
            "build_bulk_collection_import_second_review_document(",
            "refine_bulk_collection_import_resolution_plan(",
            "No Collection changes have been applied",
        ):
            self.assertIn(required, source)

        for forbidden in (
            'text="Save',
            "build_v5_1_bulk_collection_import_application_plan",
            "allocate_bulk_collection_import_keys",
            "BulkCollectionImportHackDataStore",
        ):
            self.assertNotIn(forbidden, source)



    def test_resolved_plan_builds_final_application_preview(self):
        application_callback = Mock(return_value=_application_plan())
        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_application_preview=application_callback,
        )

        resolution = _resolution_plan()
        dialog._show_resolution_plan(resolution)

        application_callback.assert_called_once_with(resolution)
        self.assertIs(
            dialog.application_preview,
            application_callback.return_value,
        )
        self.assertEqual(
            dialog.application_preview.operations[1].collection_key,
            "usr_import_0123456789abcdef",
        )
        self.assertIsNotNone(dialog.apply_session)
        self.assertEqual(
            dialog.apply_session.state,
            "awaiting_confirmation",
        )
        self.assertEqual(
            len(dialog.apply_session.application_plan_sha256),
            64,
        )
        self.assertIsNone(dialog.apply_result)

    def test_further_review_delays_application_preview_until_refined(self):
        application_callback = Mock(return_value=_application_plan())
        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_application_preview=application_callback,
        )
        dialog.resolution_plan = _resolution_plan(further_review=1)
        dialog._show_resolution_plan(dialog.resolution_plan)

        application_callback.assert_not_called()
        self.assertIsNone(dialog.application_preview)

        dialog.set_second_review_action("ambiguous", "skip")
        dialog.build_validated_second_review_document()

        application_callback.assert_called_once_with(
            dialog.resolution_plan
        )
        self.assertIsNotNone(dialog.application_preview)

    def test_application_callback_wrong_type_fails_closed(self):
        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_application_preview=lambda _plan: object(),
        )

        with self.assertRaises(TypeError):
            dialog._show_resolution_plan(_resolution_plan())

        self.assertIsNone(dialog.application_preview)

    def test_application_summary_exposes_final_operation_counts(self):
        self.assertEqual(
            BulkCollectionImportDialog._application_summary_text(
                _application_plan()
            ),
            "5 operations · 1 create · 2 update · 1 unchanged · "
            "1 skip\nFinal Collection keys and freshness fingerprints "
            "are ready. Review them before explicitly applying the import.",
        )

    def test_application_rows_show_final_key_and_short_fingerprint(self):
        plan = _application_plan()

        self.assertEqual(
            BulkCollectionImportDialog._application_operation_values(
                plan.operations[0]
            ),
            (
                "Update",
                "matched",
                "100",
                "1 source link(s); metadata: difficulty",
                "cccccccccccc…",
            ),
        )
        self.assertEqual(
            BulkCollectionImportDialog._application_operation_values(
                plan.operations[1]
            )[2],
            "usr_import_0123456789abcdef",
        )

    def test_application_detail_shows_full_freshness_and_exact_changes(self):
        detail = (
            BulkCollectionImportDialog._application_operation_detail_text(
                _application_plan().operations[0]
            )
        )

        self.assertIn("Final Collection key: 100", detail)
        self.assertIn("c" * 64, detail)
        self.assertIn("kaizoff:mirror-100", detail)
        self.assertIn("difficulty=Expert", detail)

    def test_first_round_edit_clears_final_application_preview(self):
        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_application_preview=lambda _plan: _application_plan(),
        )
        dialog._show_resolution_plan(_resolution_plan())
        self.assertIsNotNone(dialog.application_preview)

        dialog._invalidate_validation()

        self.assertIsNone(dialog.application_preview)
        self.assertIsNone(dialog.apply_session)
        self.assertIsNone(dialog.apply_result)

    def test_review_free_import_can_prepare_resolution_without_fake_choices(self):
        resolution_callback = Mock(return_value=_resolution_plan())
        application_callback = Mock(return_value=_application_plan())
        dialog = BulkCollectionImportDialog(
            None,
            _preview_without_reviews(),
            on_review_ready=resolution_callback,
            on_application_preview=application_callback,
        )

        result = dialog.prepare_no_review_resolution()

        self.assertIs(result, resolution_callback.return_value)
        review_document = resolution_callback.call_args.args[0]
        self.assertEqual(review_document["decisions"], [])
        application_callback.assert_called_once_with(result)
        self.assertIsNotNone(dialog.application_preview)

    def test_apply_cancel_keeps_session_inert_and_does_not_call_callback(self):
        callback = Mock()
        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_application_preview=lambda _plan: _application_plan(),
            on_apply=callback,
        )
        dialog._show_resolution_plan(_resolution_plan())

        with patch(
            "tkinter.messagebox.askyesno",
            return_value=False,
        ):
            result = dialog._apply_from_ui()

        self.assertIsNone(result)
        callback.assert_not_called()
        self.assertEqual(
            dialog.apply_session.state,
            "awaiting_confirmation",
        )
        self.assertFalse(dialog._apply_terminal)
        self.assertIsNone(dialog.apply_result)

    def test_explicit_apply_confirms_before_callback_and_succeeds_once(self):
        plan = _application_plan()
        store = _DialogApplyStore(plan)
        callback_states = []

        def on_apply(session):
            callback_states.append(session.state)
            return execute_bulk_collection_import_apply_session(
                session,
                store,
            )

        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_application_preview=lambda _plan: plan,
            on_apply=on_apply,
        )
        dialog._show_resolution_plan(_resolution_plan())
        fingerprint = dialog.apply_session.application_plan_sha256

        with patch(
            "tkinter.messagebox.askyesno",
            return_value=True,
        ), patch("tkinter.messagebox.showinfo"):
            result = dialog._apply_from_ui()

        self.assertEqual(callback_states, ["confirmed"])
        self.assertIs(result, dialog.apply_result)
        self.assertEqual(dialog.apply_session.state, "succeeded")
        self.assertTrue(dialog._apply_terminal)
        self.assertEqual(store.begin_count, 1)
        self.assertEqual(
            len(fingerprint),
            64,
        )

        with patch("tkinter.messagebox.askyesno") as ask_again:
            second = dialog._apply_from_ui()

        self.assertIsNone(second)
        ask_again.assert_not_called()
        self.assertEqual(store.begin_count, 1)

    def test_failed_apply_is_terminal_and_never_auto_retries(self):
        callback = Mock(side_effect=RuntimeError("write failed"))
        dialog = BulkCollectionImportDialog(
            None,
            _preview(),
            on_application_preview=lambda _plan: _application_plan(),
            on_apply=callback,
        )
        dialog._show_resolution_plan(_resolution_plan())

        with patch(
            "tkinter.messagebox.askyesno",
            return_value=True,
        ), patch("tkinter.messagebox.showerror"):
            result = dialog._apply_from_ui()

        self.assertIsNone(result)
        self.assertTrue(dialog._apply_terminal)
        self.assertIsNone(dialog.apply_result)
        callback.assert_called_once()

        with patch("tkinter.messagebox.askyesno") as ask_again:
            dialog._apply_from_ui()

        ask_again.assert_not_called()
        callback.assert_called_once()

    def test_apply_result_summary_uses_persistence_outcomes(self):
        self.assertEqual(
            BulkCollectionImportDialog._apply_result_summary_text(
                _apply_result()
            ),
            "5 outcomes · 1 created · 2 updated · "
            "1 unchanged · 1 skipped",
        )

    def test_dialog_source_requires_explicit_confirmation_before_apply(self):
        source = Path(
            "ui/bulk_collection_import_dialog.py"
        ).read_text(encoding="utf-8")

        for required in (
            'text="Apply Import"',
            "messagebox.askyesno(",
            "Application plan SHA-256",
            "confirm_bulk_collection_import_apply_session(",
            "session.state != \"awaiting_confirmation\"",
            "This dialog cannot apply the plan a second time.",
            "No automatic retry will occur.",
        ):
            self.assertIn(required, source)

        for forbidden in (
            "BulkCollectionImportHackDataStore",
            "execute_bulk_collection_import_application_plan",
            "execute_bulk_collection_import_apply_session",
            ".save_data(",
            ".force_save(",
        ):
            self.assertNotIn(forbidden, source)



if __name__ == "__main__":
    unittest.main(verbosity=2)
