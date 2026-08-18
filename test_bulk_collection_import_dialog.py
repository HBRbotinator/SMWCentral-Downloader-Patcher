"""Read-only bulk Collection import Tk dialog tests."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import MappingProxyType

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
                    authors=("Author Two",),
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
                    field="exit_count",
                    existing_value=14,
                    imported_value=15,
                ),
            ),
            candidates=(
                BulkCollectionImportWorkflowCandidate(
                    collection_key="300",
                    title="Metadata Conflict",
                    authors=("Author Three",),
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
        source_sha256="d" * 64,
        import_id="dialog-suite",
        title="Example Bulk List",
        summary=MappingProxyType(
            {
                "total": 4,
                "create_record": 1,
                "update_record": 1,
                "no_change": 0,
                "review_required": 2,
            }
        ),
        rows=rows,
        groups=(
            BulkCollectionImportWorkflowGroup(
                group_key="queue",
                title="Queue",
                entry_keys=(
                    "matched",
                    "new",
                    "ambiguous",
                    "metadata",
                ),
            ),
        ),
    )


class BulkCollectionImportDialogContractTest(unittest.TestCase):
    def test_constructor_requires_real_workflow_preview(self):
        with self.assertRaises(TypeError):
            BulkCollectionImportDialog(None, object())

    def test_constructor_rejects_non_callable_close_callback(self):
        with self.assertRaises(TypeError):
            BulkCollectionImportDialog(
                None,
                _preview(),
                on_close="not callable",
            )

    def test_group_lookup_preserves_preview_membership(self):
        dialog = BulkCollectionImportDialog(None, _preview())

        self.assertEqual(
            dialog._group_titles,
            {
                "matched": "Queue",
                "new": "Queue",
                "ambiguous": "Queue",
                "metadata": "Queue",
            },
        )

    def test_row_values_distinguish_add_match_and_review(self):
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

    def test_match_with_metadata_conflict_displays_as_review(self):
        row = _preview().rows[3]

        self.assertEqual(
            BulkCollectionImportDialog._status_label(row),
            "Review",
        )
        self.assertEqual(row.outcome, "match_existing")

    def test_detail_text_exposes_safe_candidate_and_source_data(self):
        row = _preview().rows[0]
        text = BulkCollectionImportDialog._detail_text(row)

        self.assertIn("Collection target(s): 100", text)
        self.assertIn("100: Matched Hack — Author One", text)
        self.assertIn("kaizoff:mirror-100", text)

    def test_detail_text_exposes_metadata_conflict(self):
        text = BulkCollectionImportDialog._detail_text(
            _preview().rows[3]
        )

        self.assertIn("Conflicts:", text)
        self.assertIn("exit_count: 14 → 15", text)
        self.assertIn("metadata_conflict", text)

    def test_ambiguous_detail_lists_candidates_and_flags(self):
        text = BulkCollectionImportDialog._detail_text(
            _preview().rows[2]
        )

        self.assertIn("usr_1: Ambiguous Hack", text)
        self.assertIn("usr_2: Ambiguous Hack", text)
        self.assertIn("identity_review_required", text)
        self.assertIn("identity_ambiguous", text)

    def test_summary_uses_merge_actions_not_identity_outcomes(self):
        text = BulkCollectionImportDialog._summary_text(_preview())

        self.assertEqual(
            text,
            "4 entries · 1 add · 1 update · "
            "0 unchanged · 2 review",
        )

    def test_source_summary_is_short_and_bound_to_selected_file(self):
        text = BulkCollectionImportDialog._source_summary(_preview())

        self.assertIn("bulk-list.json", text)
        self.assertIn("2.0 KiB", text)
        self.assertIn("dddddddddddd…", text)
        self.assertNotIn("d" * 64, text)

    def test_dialog_source_builds_modal_scrollable_preview(self):
        source = Path(
            "ui/bulk_collection_import_dialog.py"
        ).read_text(encoding="utf-8")

        for required in (
            "tk.Toplevel(self.parent)",
            "self.window.transient(self.parent)",
            "self.window.grab_set()",
            "ttk.Treeview(",
            'orient="vertical"',
            'orient="horizontal"',
            '"Bulk Collection Import Preview"',
            "Review-only preview",
            'text="Close"',
            "self.window.withdraw()",
            "self.window.deiconify()",
        ):
            self.assertIn(required, source)

    def test_dialog_has_no_write_or_review_decision_controls(self):
        source = Path(
            "ui/bulk_collection_import_dialog.py"
        ).read_text(encoding="utf-8")

        for forbidden in (
            'text="Apply',
            'text="Save',
            'text="Import',
            'text="Use Selected',
            "filedialog",
            "messagebox",
            "execute_bulk_collection_import_application_plan",
            "build_bulk_collection_import_application_plan",
            "save_data(",
            "force_save(",
            "update_hack(",
            "add_user_hack(",
            "review_decision",
            "create_new",
            "select_existing",
            "use_imported",
            "keep_existing",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
