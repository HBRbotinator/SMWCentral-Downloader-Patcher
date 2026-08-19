"""Interactive review dialog for bulk Collection imports.

This dialog can collect and validate review decisions, but it never resolves,
applies, or persists Collection changes.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from bulk_collection_import_resolution import (
    BulkCollectionImportResolutionPlan,
)
from bulk_collection_import_review_form import (
    REVIEW_KIND_AMBIGUOUS_IDENTITY,
    REVIEW_KIND_HARD_IDENTITY_CONFLICT,
    REVIEW_KIND_METADATA,
    BulkCollectionImportReviewFormError,
    build_bulk_collection_import_review_document,
    build_bulk_collection_import_review_form,
)
from bulk_collection_import_workflow_preview import (
    BulkCollectionImportWorkflowPreview,
    BulkCollectionImportWorkflowRow,
)


_STATUS_LABELS = {
    "add_new": "Add",
    "match_existing": "Match",
    "review_required": "Review",
}

_ACTION_LABELS = {
    "select_existing": "Select Existing",
    "create_new": "Create New",
    "resolve_metadata": "Resolve Metadata",
    "skip": "Skip",
}

_CHOICE_LABELS = {
    "keep_existing": "Keep Existing",
    "use_imported": "Use Imported",
}

_LABEL_TO_ACTION = {
    label: action for action, label in _ACTION_LABELS.items()
}
_LABEL_TO_CHOICE = {
    label: choice for choice, label in _CHOICE_LABELS.items()
}


class BulkCollectionImportDialog:
    """Modal preview and explicit review-decision editor."""

    MIN_WIDTH = 1080
    MIN_HEIGHT = 700

    def __init__(
        self,
        parent,
        preview: BulkCollectionImportWorkflowPreview,
        logger=None,
        on_close=None,
        on_review_ready=None,
    ):
        if not isinstance(
            preview,
            BulkCollectionImportWorkflowPreview,
        ):
            raise TypeError(
                "preview must be BulkCollectionImportWorkflowPreview"
            )
        if on_close is not None and not callable(on_close):
            raise TypeError("on_close must be callable or None")
        if on_review_ready is not None and not callable(on_review_ready):
            raise TypeError("on_review_ready must be callable or None")

        self.parent = parent
        self.preview = preview
        self.logger = logger
        self.on_close = on_close
        self.on_review_ready = on_review_ready

        self.review_form = build_bulk_collection_import_review_form(
            preview
        )
        self.review_items_by_key = {
            item.entry_key: item
            for item in self.review_form.items
        }

        self.window = None
        self.tree = None
        self.detail_var = None
        self.review_frame = None
        self.review_status_var = None
        self.validate_button = None
        self._closed = False

        self._rows_by_key = {
            row.entry_key: row
            for row in preview.rows
        }
        self._group_titles = self._build_group_titles(preview)

        # Plain-Python state mirrors the Tk controls and is intentionally
        # initialized with no decisions.
        self._selections = {}
        self._action_vars = {}
        self._candidate_vars = {}
        self._conflict_vars = {}

        self.validated_review_document = None
        self.resolution_plan = None
        self.resolution_var = None

    @property
    def selections(self):
        """Return detached current review selections."""

        result = {}
        for entry_key, selection in self._selections.items():
            copied = dict(selection)
            choices = copied.get("choices")
            if choices is not None:
                copied["choices"] = dict(choices)
            result[entry_key] = copied
        return result

    def show(self):
        """Create and show the modal review dialog."""

        if self.window is not None:
            try:
                if self.window.winfo_exists():
                    self.window.lift()
                    self.window.focus_force()
                    return self.window
            except tk.TclError:
                self.window = None

        self.window = tk.Toplevel(self.parent)
        self.window.withdraw()
        self.window.title("Bulk Collection Import Review")
        self.window.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.window.geometry(
            f"{self.MIN_WIDTH}x{self.MIN_HEIGHT}"
        )
        self.window.transient(self.parent)
        self.window.grab_set()
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        container = ttk.Frame(self.window, padding=15)
        container.pack(fill="both", expand=True)

        self._build_header(container)
        self._build_table(container)
        self._build_detail(container)
        self._build_review_panel(container)
        self._build_resolution_panel(container)
        self._build_footer(container)
        self._populate_rows()

        self._center()
        self.window.deiconify()
        self.window.focus_force()
        return self.window

    def close(self):
        """Close without applying Collection changes."""

        if self._closed:
            return
        self._closed = True

        window = self.window
        self.window = None
        if window is not None:
            try:
                if window.winfo_exists():
                    window.grab_release()
                    window.destroy()
            except tk.TclError:
                pass

        if self.on_close is not None:
            self.on_close()

    def set_review_action(
        self,
        entry_key: str,
        action: str,
        selected_collection_key: str | None = None,
    ):
        """Set one explicit identity/row action in plain review state."""

        item = self._require_review_item(entry_key)
        if action not in item.allowed_actions:
            raise BulkCollectionImportReviewFormError(
                f"Action {action!r} is not allowed for {entry_key}."
            )

        if action == "select_existing":
            if selected_collection_key is None:
                raise BulkCollectionImportReviewFormError(
                    "Select Existing requires a Collection candidate."
                )
            candidate_keys = {
                candidate.collection_key
                for candidate in item.candidates
            }
            if selected_collection_key not in candidate_keys:
                raise BulkCollectionImportReviewFormError(
                    "Select Existing must use a displayed candidate."
                )
            selection = {
                "action": action,
                "selected_collection_key": selected_collection_key,
            }
        elif action == "resolve_metadata":
            selection = {
                "action": action,
                "choices": {},
            }
        else:
            selection = {"action": action}

        self._selections[entry_key] = selection
        self._invalidate_validation()

    def set_metadata_choice(
        self,
        entry_key: str,
        field: str,
        choice: str,
    ):
        """Set one explicit Keep Existing / Use Imported field choice."""

        item = self._require_review_item(entry_key)
        if item.review_kind != REVIEW_KIND_METADATA:
            raise BulkCollectionImportReviewFormError(
                "Metadata choices are allowed only for metadata review."
            )
        conflict_fields = {
            conflict.field for conflict in item.conflicts
        }
        if field not in conflict_fields:
            raise BulkCollectionImportReviewFormError(
                f"Unknown metadata conflict field: {field}"
            )
        if choice not in ("keep_existing", "use_imported"):
            raise BulkCollectionImportReviewFormError(
                "Metadata choice must be keep_existing or use_imported."
            )

        selection = self._selections.get(entry_key)
        if (
            selection is None
            or selection.get("action") != "resolve_metadata"
        ):
            raise BulkCollectionImportReviewFormError(
                "Choose Resolve Metadata before setting field choices."
            )

        selection["choices"][field] = choice
        self._invalidate_validation()

    def clear_review_selection(self, entry_key: str):
        """Return one review row to the deliberately-unselected state."""

        self._require_review_item(entry_key)
        self._selections.pop(entry_key, None)
        self._invalidate_validation()

    def build_validated_review_document(self):
        """Validate every explicit decision without resolving or applying it."""

        document = build_bulk_collection_import_review_document(
            self.review_form,
            self.selections,
        )

        resolution_plan = None
        if self.on_review_ready is not None:
            resolution_plan = self.on_review_ready(document)
            if (
                resolution_plan is not None
                and not isinstance(
                    resolution_plan,
                    BulkCollectionImportResolutionPlan,
                )
            ):
                raise TypeError(
                    "on_review_ready must return "
                    "BulkCollectionImportResolutionPlan or None"
                )

        self.validated_review_document = document
        self.resolution_plan = resolution_plan
        self._show_resolution_plan(resolution_plan)

        return document

    def _build_header(self, parent):
        title = ttk.Label(
            parent,
            text=self.preview.title,
            font=("Segoe UI", 13, "bold"),
        )
        title.pack(anchor="w")

        source = ttk.Label(
            parent,
            text=self._source_summary(self.preview),
        )
        source.pack(anchor="w", pady=(2, 0))

        summary = ttk.Label(
            parent,
            text=self._summary_text(self.preview),
            font=("Segoe UI", 10, "bold"),
        )
        summary.pack(anchor="w", pady=(8, 0))

        notice = ttk.Label(
            parent,
            text=(
                "Review decisions can be validated here, but no "
                "Collection changes are applied from this dialog."
            ),
            wraplength=1000,
        )
        notice.pack(anchor="w", pady=(4, 12))

    def _build_table(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)

        columns = (
            "group",
            "status",
            "title",
            "target",
        )
        self.tree = ttk.Treeview(
            frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )

        headings = {
            "group": ("Group", 150, "w", False),
            "status": ("Status", 90, "center", False),
            "title": ("Hack", 380, "w", True),
            "target": ("Collection target", 280, "w", True),
        }
        for column, values in headings.items():
            label, width, anchor, stretch = values
            self.tree.heading(column, text=label)
            self.tree.column(
                column,
                width=width,
                anchor=anchor,
                stretch=stretch,
            )

        vertical = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=self.tree.yview,
        )
        horizontal = ttk.Scrollbar(
            frame,
            orient="horizontal",
            command=self.tree.xview,
        )
        self.tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.tree.bind(
            "<<TreeviewSelect>>",
            self._selection_changed,
        )

    def _build_detail(self, parent):
        detail_frame = ttk.LabelFrame(
            parent,
            text="Selected entry",
            padding=10,
        )
        detail_frame.pack(fill="x", pady=(12, 0))

        self.detail_var = tk.StringVar(
            value=(
                "Select an entry to inspect its match, "
                "candidate, source-link, and conflict details."
            )
        )
        ttk.Label(
            detail_frame,
            textvariable=self.detail_var,
            justify="left",
            anchor="w",
            wraplength=1000,
        ).pack(fill="x")

    def _build_review_panel(self, parent):
        self.review_frame = ttk.LabelFrame(
            parent,
            text="Review decision",
            padding=10,
        )
        self.review_frame.pack(fill="x", pady=(12, 0))

        self.review_status_var = tk.StringVar(
            value=(
                "Select a Review row to make an explicit decision."
                if self.review_form.items
                else "No review decisions are required."
            )
        )
        ttk.Label(
            self.review_frame,
            textvariable=self.review_status_var,
            anchor="w",
            justify="left",
            wraplength=1000,
        ).pack(fill="x")

    def _build_resolution_panel(self, parent):
        frame = ttk.LabelFrame(
            parent,
            text="Post-review resolution preview",
            padding=10,
        )
        frame.pack(fill="x", pady=(12, 0))

        self.resolution_var = tk.StringVar(
            value=(
                "Validate the review to replan the selected file "
                "against the current Collection."
            )
        )
        ttk.Label(
            frame,
            textvariable=self.resolution_var,
            anchor="w",
            justify="left",
            wraplength=1000,
        ).pack(fill="x")

    def _build_footer(self, parent):
        footer = ttk.Frame(parent)
        footer.pack(fill="x", pady=(12, 0))

        ttk.Label(
            footer,
            text=(
                "Validation only — resolution and Collection writes "
                "remain disabled."
            ),
        ).pack(side="left")

        ttk.Button(
            footer,
            text="Close",
            command=self.close,
        ).pack(side="right")

        if self.review_form.items:
            self.validate_button = ttk.Button(
                footer,
                text="Validate Review",
                command=self._validate_review_from_ui,
            )
            self.validate_button.pack(
                side="right",
                padx=(0, 10),
            )

    def _populate_rows(self):
        if self.tree is None:
            return

        for row in self.preview.rows:
            self.tree.insert(
                "",
                "end",
                iid=row.entry_key,
                values=self._row_values(
                    row,
                    self._group_titles.get(row.entry_key, ""),
                ),
            )

        children = self.tree.get_children("")
        if children:
            first = children[0]
            self.tree.selection_set(first)
            self.tree.focus(first)
            self.tree.see(first)
            self._show_row_details(self._rows_by_key[first])
            self._render_review_controls(first)

    def _selection_changed(self, _event=None):
        if self.tree is None:
            return

        selection = self.tree.selection()
        if not selection:
            return

        entry_key = selection[0]
        row = self._rows_by_key.get(entry_key)
        if row is not None:
            self._show_row_details(row)
        self._render_review_controls(entry_key)

    def _render_review_controls(self, entry_key):
        if self.review_frame is None:
            return

        for child in self.review_frame.winfo_children()[1:]:
            child.destroy()

        item = self.review_items_by_key.get(entry_key)
        if item is None:
            self.review_status_var.set(
                "This row does not require a review decision."
            )
            return

        self.review_status_var.set(
            self._review_instruction(item)
        )

        action_var = tk.StringVar(value="")
        self._action_vars[entry_key] = action_var

        action_frame = ttk.Frame(self.review_frame)
        action_frame.pack(fill="x", pady=(8, 0))

        ttk.Label(
            action_frame,
            text="Decision:",
        ).pack(side="left")

        action_combo = ttk.Combobox(
            action_frame,
            textvariable=action_var,
            state="readonly",
            values=[
                _ACTION_LABELS[action]
                for action in item.allowed_actions
            ],
            width=24,
        )
        action_combo.pack(side="left", padx=(8, 0))
        action_combo.bind(
            "<<ComboboxSelected>>",
            lambda _event, key=entry_key: (
                self._action_changed_from_ui(key)
            ),
        )

        current = self._selections.get(entry_key)
        if current is not None:
            action_var.set(
                _ACTION_LABELS[current["action"]]
            )

        self._render_action_specific_controls(item)

    def _action_changed_from_ui(self, entry_key):
        item = self._require_review_item(entry_key)
        action_var = self._action_vars.get(entry_key)
        label = action_var.get() if action_var is not None else ""
        action = _LABEL_TO_ACTION.get(label)

        self.clear_review_selection(entry_key)
        if action is None:
            self._render_review_controls(entry_key)
            return

        if action == "select_existing":
            # No candidate is silently selected.
            self._selections[entry_key] = {
                "action": action,
            }
            self._invalidate_validation()
        else:
            self.set_review_action(entry_key, action)

        self._render_review_controls(entry_key)

    def _render_action_specific_controls(self, item):
        selection = self._selections.get(item.entry_key)
        if selection is None:
            return

        action = selection.get("action")
        if action == "select_existing":
            self._render_candidate_control(item)
        elif action == "resolve_metadata":
            self._render_metadata_controls(item)

    def _render_candidate_control(self, item):
        frame = ttk.Frame(self.review_frame)
        frame.pack(fill="x", pady=(8, 0))

        ttk.Label(
            frame,
            text="Existing Collection entry:",
        ).pack(side="left")

        candidate_var = tk.StringVar(value="")
        self._candidate_vars[item.entry_key] = candidate_var
        values = [
            self._candidate_label(candidate)
            for candidate in item.candidates
        ]
        combo = ttk.Combobox(
            frame,
            textvariable=candidate_var,
            state="readonly",
            values=values,
            width=55,
        )
        combo.pack(side="left", padx=(8, 0))
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _event, key=item.entry_key: (
                self._candidate_changed_from_ui(key)
            ),
        )

        selected_key = self._selections[item.entry_key].get(
            "selected_collection_key"
        )
        if selected_key:
            candidate = next(
                candidate
                for candidate in item.candidates
                if candidate.collection_key == selected_key
            )
            candidate_var.set(self._candidate_label(candidate))

    def _candidate_changed_from_ui(self, entry_key):
        item = self._require_review_item(entry_key)
        variable = self._candidate_vars.get(entry_key)
        label = variable.get() if variable is not None else ""

        candidate = next(
            (
                candidate
                for candidate in item.candidates
                if self._candidate_label(candidate) == label
            ),
            None,
        )
        if candidate is None:
            return

        self.set_review_action(
            entry_key,
            "select_existing",
            candidate.collection_key,
        )

    def _render_metadata_controls(self, item):
        current_choices = self._selections[
            item.entry_key
        ].get("choices", {})

        self._conflict_vars[item.entry_key] = {}
        for conflict in item.conflicts:
            frame = ttk.Frame(self.review_frame)
            frame.pack(fill="x", pady=(8, 0))

            ttk.Label(
                frame,
                text=(
                    f"{conflict.field}: "
                    f"{self._display_value(conflict.existing_value)} "
                    "→ "
                    f"{self._display_value(conflict.imported_value)}"
                ),
                width=70,
                anchor="w",
            ).pack(side="left")

            variable = tk.StringVar(value="")
            self._conflict_vars[item.entry_key][
                conflict.field
            ] = variable

            combo = ttk.Combobox(
                frame,
                textvariable=variable,
                state="readonly",
                values=[
                    _CHOICE_LABELS["keep_existing"],
                    _CHOICE_LABELS["use_imported"],
                ],
                width=18,
            )
            combo.pack(side="left", padx=(8, 0))
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _event,
                key=item.entry_key,
                field=conflict.field: (
                    self._metadata_choice_changed_from_ui(
                        key,
                        field,
                    )
                ),
            )

            existing_choice = current_choices.get(
                conflict.field
            )
            if existing_choice:
                variable.set(_CHOICE_LABELS[existing_choice])

    def _metadata_choice_changed_from_ui(
        self,
        entry_key,
        field,
    ):
        variable = self._conflict_vars.get(
            entry_key,
            {},
        ).get(field)
        label = variable.get() if variable is not None else ""
        choice = _LABEL_TO_CHOICE.get(label)
        if choice is None:
            return

        self.set_metadata_choice(
            entry_key,
            field,
            choice,
        )

    def _validate_review_from_ui(self):
        try:
            document = self.build_validated_review_document()
        except BulkCollectionImportReviewFormError as error:
            self.validated_review_document = None
            self.resolution_plan = None
            if self.review_status_var is not None:
                self.review_status_var.set(
                    "Review is incomplete: " + str(error)
                )
            messagebox.showerror(
                "Bulk Collection Import Review",
                (
                    "Every Review row must have a valid explicit "
                    "decision before continuing.\n\n"
                    f"{error}"
                ),
                parent=self.window,
            )
            return
        except Exception as error:
            self.validated_review_document = None
            self.resolution_plan = None
            if self.resolution_var is not None:
                self.resolution_var.set(
                    "Resolution preview failed: " + str(error)
                )
            if self.logger:
                self.logger.log(
                    f"Bulk Collection import resolution failed: {error}",
                    "Error",
                )
            messagebox.showerror(
                "Bulk Collection Import Review",
                (
                    "The review was valid, but the import could not "
                    "be resolved against the current Collection.\n\n"
                    f"{error}\n\n"
                    "No Collection changes were applied."
                ),
                parent=self.window,
            )
            return

        if self.review_status_var is not None:
            self.review_status_var.set(
                "Review decisions validated. No Collection "
                "changes have been applied."
            )
        messagebox.showinfo(
            "Bulk Collection Import Review",
            (
                "Review decisions are complete and valid.\n\n"
                "The post-review resolution preview is ready. "
                "No Collection changes have been applied."
            ),
            parent=self.window,
        )
        return document

    def _invalidate_validation(self):
        self.validated_review_document = None
        self.resolution_plan = None
        if self.resolution_var is not None:
            self.resolution_var.set(
                "Review changed. Validate again to refresh the "
                "post-review resolution preview."
            )

    def _show_resolution_plan(self, plan):
        if self.resolution_var is None:
            return
        if plan is None:
            self.resolution_var.set(
                "Review decisions validated. No resolution callback "
                "is connected."
            )
            return

        self.resolution_var.set(
            self._resolution_summary_text(plan)
        )

    @staticmethod
    def _resolution_summary_text(plan):
        summary = plan.summary
        text = (
            f"{summary['total']} entries · "
            f"{summary['create_record']} add · "
            f"{summary['update_record']} update · "
            f"{summary['no_change']} unchanged · "
            f"{summary['skip']} skip · "
            f"{summary['review_required']} further review"
        )
        if summary["review_required"]:
            text += (
                "\nFurther review is required before an "
                "application plan can be prepared."
            )
        else:
            text += (
                "\nAll post-review actions are resolved. "
                "Application remains disabled."
            )
        return text

    def _require_review_item(self, entry_key):
        item = self.review_items_by_key.get(entry_key)
        if item is None:
            raise BulkCollectionImportReviewFormError(
                f"Entry does not require review: {entry_key}"
            )
        return item

    @staticmethod
    def _review_instruction(item):
        if item.review_kind == REVIEW_KIND_AMBIGUOUS_IDENTITY:
            return (
                "Choose an existing candidate, create a distinct "
                "new Collection record, or skip this entry."
            )
        if item.review_kind == REVIEW_KIND_HARD_IDENTITY_CONFLICT:
            return (
                "This identity conflict is unsafe to resolve "
                "automatically or by choosing a side. Skip is the "
                "only allowed action."
            )
        if item.review_kind == REVIEW_KIND_METADATA:
            return (
                "Resolve every conflicting shared field explicitly, "
                "or skip this entry."
            )
        return "Choose an explicit review decision."

    @staticmethod
    def _candidate_label(candidate):
        authors = (
            " — " + ", ".join(candidate.authors)
            if candidate.authors
            else ""
        )
        return (
            f"{candidate.collection_key}: "
            f"{candidate.title}{authors}"
        )

    @staticmethod
    def _build_group_titles(preview):
        result = {}
        for group in preview.groups:
            for entry_key in group.entry_keys:
                result[entry_key] = group.title
        return result

    @staticmethod
    def _source_summary(preview):
        kib = preview.byte_count / 1024
        return (
            f"Source: {preview.source_name} · "
            f"{kib:.1f} KiB · SHA-256 "
            f"{preview.source_sha256[:12]}…"
        )

    @staticmethod
    def _summary_text(preview):
        summary = preview.summary
        return (
            f"{summary['total']} entries · "
            f"{summary['create_record']} add · "
            f"{summary['update_record']} update · "
            f"{summary['no_change']} unchanged · "
            f"{summary['review_required']} review"
        )

    @classmethod
    def _row_values(cls, row, group_title=""):
        return (
            group_title,
            cls._status_label(row),
            row.title,
            cls._target_text(row),
        )

    @staticmethod
    def _status_label(row):
        if row.requires_review:
            return "Review"
        return _STATUS_LABELS.get(
            row.outcome,
            row.outcome.replace("_", " ").title(),
        )

    @staticmethod
    def _target_text(row):
        if row.collection_keys:
            return ", ".join(row.collection_keys)
        if row.merge_action == "create_record":
            return "New Collection entry"
        return "—"

    @staticmethod
    def _detail_text(row):
        sections = []

        if row.collection_keys:
            sections.append(
                "Collection target(s): "
                + ", ".join(row.collection_keys)
            )
        elif row.merge_action == "create_record":
            sections.append("Collection target: new entry")

        if row.candidates:
            candidate_text = "; ".join(
                (
                    f"{candidate.collection_key}: "
                    f"{candidate.title}"
                    + (
                        " — " + ", ".join(candidate.authors)
                        if candidate.authors
                        else ""
                    )
                )
                for candidate in row.candidates
            )
            sections.append("Candidates: " + candidate_text)

        if row.proposed_source_references:
            source_text = ", ".join(
                (
                    f"{reference.source}:"
                    f"{reference.external_id}"
                )
                for reference in row.proposed_source_references
            )
            sections.append(
                "Proposed source link(s): " + source_text
            )

        if row.conflicts:
            conflicts = "; ".join(
                (
                    f"{conflict.field}: "
                    f"{BulkCollectionImportDialog._display_value(conflict.existing_value)} "
                    "→ "
                    f"{BulkCollectionImportDialog._display_value(conflict.imported_value)}"
                )
                for conflict in row.conflicts
            )
            sections.append("Conflicts: " + conflicts)

        if row.warnings:
            sections.append(
                "Review flags: " + ", ".join(row.warnings)
            )

        if not sections:
            sections.append(
                "No additional review details for this entry."
            )

        return "\n".join(sections)

    @staticmethod
    def _display_value(value: Any) -> str:
        if value is None:
            return "not set"
        if isinstance(value, tuple):
            return ", ".join(
                BulkCollectionImportDialog._display_value(item)
                for item in value
            )
        if isinstance(value, dict):
            return ", ".join(
                (
                    f"{key}="
                    f"{BulkCollectionImportDialog._display_value(item)}"
                )
                for key, item in value.items()
            )
        return str(value)

    def _show_row_details(self, row):
        if self.detail_var is not None:
            self.detail_var.set(self._detail_text(row))

    def _center(self):
        if self.window is None:
            return

        self.window.update_idletasks()
        width = max(
            self.window.winfo_width(),
            self.MIN_WIDTH,
        )
        height = max(
            self.window.winfo_height(),
            self.MIN_HEIGHT,
        )
        screen_width = self.window.winfo_screenwidth()
        screen_height = self.window.winfo_screenheight()
        x = max(0, (screen_width - width) // 2)
        y = max(0, (screen_height - height) // 2)
        self.window.geometry(f"{width}x{height}+{x}+{y}")
