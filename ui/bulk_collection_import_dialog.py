"""Interactive review dialog for bulk Collection imports.

This dialog keeps review and preview stages read-only, then permits one
explicitly confirmed Apply attempt through an injected Collection callback.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from bulk_collection_import_application import (
    BulkCollectionImportApplicationPlan,
)
from bulk_collection_import_apply import (
    BulkCollectionImportApplyError,
    BulkCollectionImportApplySession,
    confirm_bulk_collection_import_apply_session,
    create_bulk_collection_import_apply_session,
)
from bulk_collection_import_persistence import (
    BulkCollectionImportPersistenceResult,
)
from bulk_collection_import_resolution import (
    BulkCollectionImportResolutionPlan,
)
from bulk_collection_import_second_review import (
    BulkCollectionImportSecondReviewError,
    build_bulk_collection_import_second_review_document,
    build_bulk_collection_import_second_review_form,
    refine_bulk_collection_import_resolution_plan,
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
        on_application_preview=None,
        on_apply=None,
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
        if (
            on_application_preview is not None
            and not callable(on_application_preview)
        ):
            raise TypeError(
                "on_application_preview must be callable or None"
            )
        if on_apply is not None and not callable(on_apply):
            raise TypeError("on_apply must be callable or None")

        self.parent = parent
        self.preview = preview
        self.logger = logger
        self.on_close = on_close
        self.on_review_ready = on_review_ready
        self.on_application_preview = on_application_preview
        self.on_apply = on_apply

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

        self.second_review_form = None
        self.second_review_items_by_key = {}
        self.validated_second_review_document = None
        self.second_review_frame = None
        self.second_review_status_var = None
        self.second_validate_button = None
        self._second_selections = {}
        self._second_action_vars = {}
        self._second_conflict_vars = {}

        self.application_preview = None
        self.application_frame = None
        self.application_summary_var = None
        self.application_tree = None
        self.application_detail_var = None
        self._application_operations_by_key = {}

        self.apply_session = None
        self.apply_result = None
        self.apply_status_var = None
        self.apply_button = None
        self._apply_terminal = False

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

    @property
    def second_review_selections(self):
        """Return detached current second-round selections."""

        result = {}
        for entry_key, selection in self._second_selections.items():
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
        self._build_second_review_panel(container)
        self._build_application_panel(container)
        self._build_footer(container)
        self._populate_rows()
        self._prepare_no_review_from_ui()

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

    def prepare_no_review_resolution(self):
        """Resolve a review-free import through the same fresh callback."""

        if self.review_form.items:
            raise BulkCollectionImportReviewFormError(
                "This import still requires explicit review decisions."
            )
        if self.resolution_plan is not None:
            return self.resolution_plan

        self.build_validated_review_document()
        return self.resolution_plan

    def set_second_review_action(
        self,
        entry_key: str,
        action: str,
    ):
        """Set one explicit follow-up metadata action."""

        item = self._require_second_review_item(entry_key)
        if action not in item.allowed_actions:
            raise BulkCollectionImportSecondReviewError(
                f"Action {action!r} is not allowed for {entry_key}."
            )

        if action == "resolve_metadata":
            selection = {
                "action": action,
                "choices": {},
            }
        else:
            selection = {"action": action}

        self._second_selections[entry_key] = selection
        self._invalidate_second_review_validation()

    def set_second_metadata_choice(
        self,
        entry_key: str,
        field: str,
        choice: str,
    ):
        """Set one explicit follow-up metadata field choice."""

        item = self._require_second_review_item(entry_key)
        conflict_fields = {
            conflict.field
            for conflict in item.conflicts
        }
        if field not in conflict_fields:
            raise BulkCollectionImportSecondReviewError(
                f"Unknown second-round conflict field: {field}"
            )
        if choice not in ("keep_existing", "use_imported"):
            raise BulkCollectionImportSecondReviewError(
                "Second-round metadata choice must be "
                "keep_existing or use_imported."
            )

        selection = self._second_selections.get(entry_key)
        if (
            selection is None
            or selection.get("action") != "resolve_metadata"
        ):
            raise BulkCollectionImportSecondReviewError(
                "Choose Resolve Metadata before setting "
                "follow-up field choices."
            )

        selection["choices"][field] = choice
        self._invalidate_second_review_validation()

    def clear_second_review_selection(self, entry_key: str):
        """Return one follow-up row to an unselected state."""

        self._require_second_review_item(entry_key)
        self._second_selections.pop(entry_key, None)
        self._invalidate_second_review_validation()

    def build_validated_second_review_document(self):
        """Validate follow-up choices and refine the read-only plan."""

        if self.second_review_form is None:
            raise BulkCollectionImportSecondReviewError(
                "No second-round review is currently required."
            )
        if self.resolution_plan is None:
            raise BulkCollectionImportSecondReviewError(
                "No resolution plan is available for second review."
            )

        document = build_bulk_collection_import_second_review_document(
            self.second_review_form,
            self.second_review_selections,
        )
        refined = refine_bulk_collection_import_resolution_plan(
            self.resolution_plan,
            document,
        )

        self.validated_second_review_document = document
        self.resolution_plan = refined
        self._show_resolution_plan(refined)
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
                "Review and preview remain read-only until Apply Import "
                "is explicitly confirmed."
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

    def _build_second_review_panel(self, parent):
        self.second_review_frame = ttk.LabelFrame(
            parent,
            text="Follow-up metadata review",
            padding=10,
        )
        self.second_review_frame.pack(fill="x", pady=(12, 0))

        self.second_review_status_var = tk.StringVar(
            value=(
                "No follow-up review is currently required."
            )
        )
        ttk.Label(
            self.second_review_frame,
            textvariable=self.second_review_status_var,
            anchor="w",
            justify="left",
            wraplength=1000,
        ).pack(fill="x")

    def _build_application_panel(self, parent):
        self.application_frame = ttk.LabelFrame(
            parent,
            text="Final application preview",
            padding=10,
        )
        self.application_frame.pack(fill="x", pady=(12, 0))

        self.application_summary_var = tk.StringVar(
            value=(
                "Complete all review rounds to build the final "
                "read-only application preview."
            )
        )
        ttk.Label(
            self.application_frame,
            textvariable=self.application_summary_var,
            anchor="w",
            justify="left",
            wraplength=1000,
        ).pack(fill="x")

        columns = (
            "action",
            "entry_key",
            "collection_key",
            "changes",
            "fingerprint",
        )
        self.application_tree = ttk.Treeview(
            self.application_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=5,
        )
        headings = {
            "action": ("Action", 95, "center", False),
            "entry_key": ("Import entry", 170, "w", True),
            "collection_key": ("Final Collection key", 170, "w", True),
            "changes": ("Shared changes", 360, "w", True),
            "fingerprint": ("Freshness", 120, "w", False),
        }
        for column, values in headings.items():
            label, width, anchor, stretch = values
            self.application_tree.heading(column, text=label)
            self.application_tree.column(
                column,
                width=width,
                anchor=anchor,
                stretch=stretch,
            )
        self.application_tree.pack(fill="x", pady=(8, 0))
        self.application_tree.bind(
            "<<TreeviewSelect>>",
            self._application_selection_changed,
        )

        self.application_detail_var = tk.StringVar(
            value="No final application operation is available yet."
        )
        ttk.Label(
            self.application_frame,
            textvariable=self.application_detail_var,
            anchor="w",
            justify="left",
            wraplength=1000,
        ).pack(fill="x", pady=(8, 0))

        self.apply_status_var = tk.StringVar(
            value=(
                "Apply is unavailable until the final application "
                "preview is ready."
            )
        )
        ttk.Label(
            self.application_frame,
            textvariable=self.apply_status_var,
            anchor="w",
            justify="left",
            wraplength=1000,
        ).pack(fill="x", pady=(8, 0))

    def _build_footer(self, parent):
        footer = ttk.Frame(parent)
        footer.pack(fill="x", pady=(12, 0))

        ttk.Label(
            footer,
            text=(
                "Collection changes occur only after Apply Import is "
                "explicitly confirmed."
            ),
        ).pack(side="left")

        ttk.Button(
            footer,
            text="Close",
            command=self.close,
        ).pack(side="right")

        self.apply_button = ttk.Button(
            footer,
            text="Apply Import",
            command=self._apply_from_ui,
            state="disabled",
        )
        self.apply_button.pack(
            side="right",
            padx=(0, 10),
        )

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

        self.second_validate_button = ttk.Button(
            footer,
            text="Validate Follow-up Review",
            command=self._validate_second_review_from_ui,
            state="disabled",
        )
        self.second_validate_button.pack(
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
            self._render_second_review_controls(first)

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
        self._render_second_review_controls(entry_key)

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

    def _render_second_review_controls(self, entry_key):
        if self.second_review_frame is None:
            return

        for child in self.second_review_frame.winfo_children()[1:]:
            child.destroy()

        item = self.second_review_items_by_key.get(entry_key)
        if item is None:
            if self.second_review_form is None:
                self.second_review_status_var.set(
                    "No follow-up review is currently required."
                )
            else:
                self.second_review_status_var.set(
                    "Select a row marked for follow-up metadata review."
                )
            return

        self.second_review_status_var.set(
            self._second_review_context_text(item)
        )

        action_var = tk.StringVar(value="")
        self._second_action_vars[entry_key] = action_var

        action_frame = ttk.Frame(self.second_review_frame)
        action_frame.pack(fill="x", pady=(8, 0))
        ttk.Label(
            action_frame,
            text="Follow-up decision:",
        ).pack(side="left")

        combo = ttk.Combobox(
            action_frame,
            textvariable=action_var,
            state="readonly",
            values=["Resolve Metadata", "Skip"],
            width=24,
        )
        combo.pack(side="left", padx=(8, 0))
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _event, key=entry_key: (
                self._second_action_changed_from_ui(key)
            ),
        )

        current = self._second_selections.get(entry_key)
        if current is not None:
            action_var.set(
                "Resolve Metadata"
                if current["action"] == "resolve_metadata"
                else "Skip"
            )

        if (
            current is not None
            and current["action"] == "resolve_metadata"
        ):
            self._render_second_metadata_controls(item)

    def _second_action_changed_from_ui(self, entry_key):
        variable = self._second_action_vars.get(entry_key)
        label = variable.get() if variable is not None else ""

        self.clear_second_review_selection(entry_key)
        if label == "Resolve Metadata":
            self.set_second_review_action(
                entry_key,
                "resolve_metadata",
            )
        elif label == "Skip":
            self.set_second_review_action(
                entry_key,
                "skip",
            )
        else:
            return

        self._render_second_review_controls(entry_key)

    def _render_second_metadata_controls(self, item):
        current_choices = self._second_selections[
            item.entry_key
        ].get("choices", {})

        self._second_conflict_vars[item.entry_key] = {}
        for conflict in item.conflicts:
            frame = ttk.Frame(self.second_review_frame)
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
            self._second_conflict_vars[item.entry_key][
                conflict.field
            ] = variable

            combo = ttk.Combobox(
                frame,
                textvariable=variable,
                state="readonly",
                values=[
                    "Keep Existing",
                    "Use Imported",
                ],
                width=18,
            )
            combo.pack(side="left", padx=(8, 0))
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _event,
                key=item.entry_key,
                field=conflict.field: (
                    self._second_metadata_changed_from_ui(
                        key,
                        field,
                    )
                ),
            )

            existing = current_choices.get(conflict.field)
            if existing == "keep_existing":
                variable.set("Keep Existing")
            elif existing == "use_imported":
                variable.set("Use Imported")

    def _second_metadata_changed_from_ui(
        self,
        entry_key,
        field,
    ):
        variable = self._second_conflict_vars.get(
            entry_key,
            {},
        ).get(field)
        label = variable.get() if variable is not None else ""
        if label == "Keep Existing":
            choice = "keep_existing"
        elif label == "Use Imported":
            choice = "use_imported"
        else:
            return

        self.set_second_metadata_choice(
            entry_key,
            field,
            choice,
        )

    def _prepare_no_review_from_ui(self):
        if self.review_form.items:
            return
        try:
            self.prepare_no_review_resolution()
        except Exception as error:
            self.validated_review_document = None
            self.resolution_plan = None
            self._clear_application_preview(
                "The review-free application preview could not be built."
            )
            if self.logger:
                self.logger.log(
                    "Bulk Collection review-free preview failed: "
                    f"{error}",
                    "Error",
                )
            messagebox.showerror(
                "Bulk Collection Import Preview",
                (
                    "The import requires no manual review, but its "
                    "final read-only application preview could not "
                    "be prepared.\n\n"
                    f"{error}\n\n"
                    "No Collection changes were applied."
                ),
                parent=self.window,
            )

    def _validate_second_review_from_ui(self):
        try:
            document = self.build_validated_second_review_document()
        except BulkCollectionImportSecondReviewError as error:
            self.validated_second_review_document = None
            if self.second_review_status_var is not None:
                self.second_review_status_var.set(
                    "Follow-up review is incomplete: " + str(error)
                )
            messagebox.showerror(
                "Bulk Collection Import Follow-up Review",
                (
                    "Every newly exposed metadata conflict must "
                    "have an explicit choice.\n\n"
                    f"{error}"
                ),
                parent=self.window,
            )
            return
        except Exception as error:
            self.validated_second_review_document = None
            if self.logger:
                self.logger.log(
                    f"Bulk Collection follow-up review failed: {error}",
                    "Error",
                )
            messagebox.showerror(
                "Bulk Collection Import Follow-up Review",
                (
                    "The follow-up review could not be refined.\n\n"
                    f"{error}\n\n"
                    "No Collection changes were applied."
                ),
                parent=self.window,
            )
            return

        messagebox.showinfo(
            "Bulk Collection Import Follow-up Review",
            (
                "Follow-up metadata decisions are complete.\n\n"
                "The read-only resolution preview has been refined. "
                "No Collection changes have been applied."
            ),
            parent=self.window,
        )
        return document

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
        self._clear_second_review_state()
        self._clear_application_preview(
            "Review changed. Validate again to rebuild the final preview."
        )
        if self.resolution_var is not None:
            self.resolution_var.set(
                "Review changed. Validate again to refresh the "
                "post-review resolution preview."
            )

    def _invalidate_second_review_validation(self):
        self.validated_second_review_document = None
        self._clear_application_preview(
            "Follow-up review changed. Validate again to rebuild "
            "the final preview."
        )
        if self.second_review_status_var is not None:
            self.second_review_status_var.set(
                "Follow-up review changed. Validate again to "
                "refine the read-only resolution preview."
            )

    def _clear_second_review_state(self):
        self.second_review_form = None
        self.second_review_items_by_key = {}
        self.validated_second_review_document = None
        self._second_selections = {}
        self._second_action_vars = {}
        self._second_conflict_vars = {}

        if self.second_validate_button is not None:
            self.second_validate_button.config(state="disabled")
        if self.second_review_status_var is not None:
            self.second_review_status_var.set(
                "No follow-up review is currently required."
            )

    def _show_resolution_plan(self, plan):
        if plan is None:
            self._clear_second_review_state()
            self._clear_application_preview(
                "No final application preview callback is connected."
            )
            if self.resolution_var is not None:
                self.resolution_var.set(
                    "Review decisions validated. No resolution callback "
                    "is connected."
                )
            return

        self._prepare_second_review(plan)
        if self.resolution_var is not None:
            self.resolution_var.set(
                self._resolution_summary_text(plan)
            )

        if plan.summary["review_required"]:
            self._clear_application_preview(
                "Resolve the follow-up metadata review before the "
                "final application preview is built."
            )
        else:
            self._refresh_application_preview(plan)

    def _prepare_second_review(self, plan):
        if not plan.summary["review_required"]:
            self._clear_second_review_state()
            return

        form = build_bulk_collection_import_second_review_form(plan)
        self.second_review_form = form
        self.second_review_items_by_key = {
            item.entry_key: item
            for item in form.items
        }
        self.validated_second_review_document = None
        self._second_selections = {}

        if self.second_validate_button is not None:
            self.second_validate_button.config(state="normal")
        if self.second_review_status_var is not None:
            self.second_review_status_var.set(
                "Further review is required. Select a blocked row "
                "and resolve its newly exposed metadata conflicts."
            )

        if self.tree is not None:
            selection = self.tree.selection()
            if selection:
                self._render_second_review_controls(selection[0])

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
                "The final application preview can now be prepared."
            )
        return text

    def _refresh_application_preview(self, resolution_plan):
        if self.on_application_preview is None:
            self._clear_application_preview(
                "Resolution is complete. No final application preview "
                "callback is connected."
            )
            return None

        preview = self.on_application_preview(resolution_plan)
        if preview is None:
            self._clear_application_preview(
                "Resolution is complete. No final application preview "
                "was returned."
            )
            return None
        if not isinstance(preview, BulkCollectionImportApplicationPlan):
            self._clear_application_preview(
                "The final application preview callback returned an "
                "invalid result."
            )
            raise TypeError(
                "on_application_preview must return "
                "BulkCollectionImportApplicationPlan or None"
            )

        self.application_preview = preview
        self._application_operations_by_key = {
            operation.entry_key: operation
            for operation in preview.operations
        }
        self._render_application_preview(preview)
        self._prepare_apply_session(preview)
        return preview

    def _clear_application_preview(self, status=None):
        self.application_preview = None
        self._application_operations_by_key = {}

        if not self._apply_terminal:
            self.apply_session = None
            self.apply_result = None
            if self.apply_button is not None:
                self.apply_button.config(state="disabled")
            if self.apply_status_var is not None:
                self.apply_status_var.set(
                    "Apply is unavailable until a fresh final "
                    "application preview is ready."
                )

        if self.application_tree is not None:
            for child in self.application_tree.get_children(""):
                self.application_tree.delete(child)
        if self.application_summary_var is not None and status is not None:
            self.application_summary_var.set(status)
        if self.application_detail_var is not None:
            self.application_detail_var.set(
                "No final application operation is available yet."
            )

    def _render_application_preview(self, preview):
        if self.application_summary_var is not None:
            self.application_summary_var.set(
                self._application_summary_text(preview)
            )
        if self.application_tree is None:
            return

        for child in self.application_tree.get_children(""):
            self.application_tree.delete(child)
        for operation in preview.operations:
            self.application_tree.insert(
                "",
                "end",
                iid=operation.entry_key,
                values=self._application_operation_values(operation),
            )

        children = self.application_tree.get_children("")
        if children:
            first = children[0]
            self.application_tree.selection_set(first)
            self.application_tree.focus(first)
            self.application_tree.see(first)
            operation = self._application_operations_by_key[first]
            if self.application_detail_var is not None:
                self.application_detail_var.set(
                    self._application_operation_detail_text(operation)
                )

    def _prepare_apply_session(self, preview):
        if self._apply_terminal:
            if self.apply_button is not None:
                self.apply_button.config(state="disabled")
            if self.apply_status_var is not None:
                self.apply_status_var.set(
                    "This dialog already attempted Apply. Close it and "
                    "open a fresh import preview for another attempt."
                )
            return None

        session = create_bulk_collection_import_apply_session(preview)
        self.apply_session = session
        self.apply_result = None

        if self.apply_status_var is not None:
            self.apply_status_var.set(
                "Ready for explicit confirmation.\n"
                "Application plan SHA-256:\n"
                f"{session.application_plan_sha256}"
            )

        if self.apply_button is not None:
            self.apply_button.config(
                state=(
                    "normal"
                    if self.on_apply is not None
                    else "disabled"
                )
            )
        return session

    def _apply_from_ui(self):
        session = self.apply_session
        if (
            self._apply_terminal
            or session is None
            or session.state != "awaiting_confirmation"
        ):
            return None

        if self.on_apply is None:
            if self.apply_status_var is not None:
                self.apply_status_var.set(
                    "No Collection Apply callback is connected."
                )
            return None

        fingerprint = session.application_plan_sha256
        summary = self.application_preview.summary
        confirmed = messagebox.askyesno(
            "Apply Bulk Collection Import",
            (
                "This will write the final reviewed bulk import to "
                "your Collection.\n\n"
                f"Create: {summary['create_record']}\n"
                f"Update: {summary['update_record']}\n"
                f"No Change: {summary['no_change']}\n"
                f"Skip: {summary['skip']}\n\n"
                "Confirm the exact displayed application plan:\n"
                f"{fingerprint}\n\n"
                "Apply these Collection changes now?"
            ),
            parent=self.window,
        )
        if not confirmed:
            if self.apply_status_var is not None:
                self.apply_status_var.set(
                    "Apply cancelled. No Collection store was accessed.\n"
                    "Application plan SHA-256:\n"
                    f"{fingerprint}"
                )
            return None

        try:
            confirm_bulk_collection_import_apply_session(
                session,
                fingerprint,
            )
        except BulkCollectionImportApplyError as error:
            if self.apply_status_var is not None:
                self.apply_status_var.set(
                    "Apply confirmation failed. No Collection write "
                    "was attempted."
                )
            messagebox.showerror(
                "Bulk Collection Import Apply",
                str(error),
                parent=self.window,
            )
            return None

        if self.apply_button is not None:
            self.apply_button.config(state="disabled")
        if self.validate_button is not None:
            self.validate_button.config(state="disabled")
        if self.second_validate_button is not None:
            self.second_validate_button.config(state="disabled")
        if self.apply_status_var is not None:
            self.apply_status_var.set(
                "Applying the explicitly confirmed plan..."
            )

        try:
            result = self.on_apply(session)
            if not isinstance(
                result,
                BulkCollectionImportPersistenceResult,
            ):
                raise TypeError(
                    "on_apply must return "
                    "BulkCollectionImportPersistenceResult"
                )
            if session.state != "succeeded":
                raise TypeError(
                    "on_apply returned without completing the "
                    "confirmed Apply session."
                )
        except Exception as error:
            self._apply_terminal = True
            self.apply_result = None
            if self.apply_status_var is not None:
                self.apply_status_var.set(
                    "Apply failed. This attempt is terminal; close this "
                    "dialog and build a fresh preview before retrying."
                )
            if self.logger:
                self.logger.log(
                    f"Bulk Collection import Apply failed: {error}",
                    "Error",
                )
            messagebox.showerror(
                "Bulk Collection Import Apply",
                (
                    "The confirmed Apply attempt failed.\n\n"
                    f"{error}\n\n"
                    "No automatic retry will occur. Close this dialog "
                    "and build a fresh application preview before "
                    "another attempt."
                ),
                parent=self.window,
            )
            return None

        self._apply_terminal = True
        self.apply_result = result
        if self.apply_status_var is not None:
            self.apply_status_var.set(
                self._apply_result_summary_text(result)
                + "\nApply succeeded. This dialog cannot apply again."
            )

        messagebox.showinfo(
            "Bulk Collection Import Applied",
            (
                self._apply_result_summary_text(result)
                + "\n\nThe Collection import was committed atomically. "
                "This dialog cannot apply the plan a second time."
            ),
            parent=self.window,
        )
        return result

    @staticmethod
    def _apply_result_summary_text(result):
        summary = result.summary
        return (
            f"{summary['total']} outcomes · "
            f"{summary['created']} created · "
            f"{summary['updated']} updated · "
            f"{summary['unchanged']} unchanged · "
            f"{summary['skipped']} skipped"
        )

    def _application_selection_changed(self, _event=None):
        if self.application_tree is None:
            return
        selection = self.application_tree.selection()
        if not selection:
            return
        operation = self._application_operations_by_key.get(
            selection[0]
        )
        if operation is not None and self.application_detail_var is not None:
            self.application_detail_var.set(
                self._application_operation_detail_text(operation)
            )

    @staticmethod
    def _application_summary_text(preview):
        summary = preview.summary
        return (
            f"{summary['total']} operations · "
            f"{summary['create_record']} create · "
            f"{summary['update_record']} update · "
            f"{summary['no_change']} unchanged · "
            f"{summary['skip']} skip\n"
            "Final Collection keys and freshness fingerprints are ready. "
            "Review them before explicitly applying the import."
        )

    @classmethod
    def _application_operation_values(cls, operation):
        labels = {
            "create_record": "Create",
            "update_record": "Update",
            "no_change": "No Change",
            "skip": "Skip",
        }
        fingerprint = (
            operation.expected_shared_sha256[:12] + "…"
            if operation.expected_shared_sha256
            else "—"
        )
        return (
            labels.get(operation.action, operation.action),
            operation.entry_key,
            operation.collection_key or "—",
            cls._application_change_summary(operation),
            fingerprint,
        )

    @classmethod
    def _application_change_summary(cls, operation):
        if operation.action == "skip":
            return "No write"
        if operation.action == "no_change":
            return "No shared changes"

        changes = []
        if operation.title_value is not None:
            changes.append("title")
        if operation.action == "create_record":
            if operation.source_references:
                changes.append(
                    f"{len(operation.source_references)} source link(s)"
                )
            if operation.attributes:
                changes.append(
                    "metadata: " + ", ".join(operation.attributes)
                )
        else:
            if operation.source_reference_additions:
                changes.append(
                    f"{len(operation.source_reference_additions)} "
                    "source link(s)"
                )
            if operation.attribute_changes:
                changes.append(
                    "metadata: "
                    + ", ".join(
                        change.field
                        for change in operation.attribute_changes
                    )
                )
        return "; ".join(changes) if changes else "Shared update"

    @classmethod
    def _application_operation_detail_text(cls, operation):
        lines = [
            f"Action: {operation.action}",
            "Final Collection key: " + (
                operation.collection_key or "none"
            ),
        ]

        if operation.expected_shared_sha256:
            lines.append(
                "Expected shared-state SHA-256: "
                + operation.expected_shared_sha256
            )
        if operation.title_value is not None:
            lines.append("Title: " + operation.title_value)
        if operation.source_references:
            lines.append(
                "Create source reference(s): "
                + ", ".join(
                    f"{value.source}:{value.external_id}"
                    for value in operation.source_references
                )
            )
        if operation.source_reference_additions:
            lines.append(
                "Source reference addition(s): "
                + ", ".join(
                    f"{value.source}:{value.external_id}"
                    for value in operation.source_reference_additions
                )
            )
        if operation.attributes:
            lines.append(
                "Create metadata: "
                + "; ".join(
                    f"{field}={cls._display_value(value)}"
                    for field, value in operation.attributes.items()
                )
            )
        if operation.attribute_changes:
            lines.append(
                "Metadata change(s): "
                + "; ".join(
                    f"{change.field}={cls._display_value(change.value)}"
                    for change in operation.attribute_changes
                )
            )
        if operation.warnings:
            lines.append("Warnings: " + ", ".join(operation.warnings))
        if operation.action == "no_change":
            lines.append("No shared Collection changes will be written.")
        if operation.action == "skip":
            lines.append("This entry has no Collection write operation.")
        return "\n".join(lines)

    def _require_second_review_item(self, entry_key):
        item = self.second_review_items_by_key.get(entry_key)
        if item is None:
            raise BulkCollectionImportSecondReviewError(
                f"Entry does not require follow-up review: {entry_key}"
            )
        return item

    @classmethod
    def _second_review_context_text(cls, item):
        lines = [
            (
                "Selected Collection target: "
                f"{item.collection_key}"
            ),
            (
                "Resolve every newly exposed metadata conflict "
                "explicitly, or skip this entry."
            ),
        ]

        if item.source_reference_additions:
            links = ", ".join(
                f"{value.source}:{value.external_id}"
                for value in item.source_reference_additions
            )
            lines.append(
                "Safe source link(s) preserved if resolved: " + links
            )

        if item.attribute_changes:
            changes = "; ".join(
                (
                    f"{change.field}="
                    f"{cls._display_value(change.value)}"
                )
                for change in item.attribute_changes
            )
            lines.append(
                "Safe metadata change(s) preserved if resolved: "
                + changes
            )

        return "\n".join(lines)

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
