"""Interactive bulk Collection import review dialog tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import MappingProxyType
from unittest.mock import Mock

from bulk_collection_import_resolution import (
    BulkCollectionImportResolutionGroup,
    BulkCollectionImportResolutionItem,
    BulkCollectionImportResolutionPlan,
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
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=(),
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
        ):
            self.assertIn(required, source)

    def test_dialog_has_no_resolution_application_or_persistence(self):
        source = Path(
            "ui/bulk_collection_import_dialog.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            'text="Apply',
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
            "Application remains disabled.",
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



if __name__ == "__main__":
    unittest.main(verbosity=2)
