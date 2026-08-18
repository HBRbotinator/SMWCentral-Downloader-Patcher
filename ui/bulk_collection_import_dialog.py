"""Read-only Tk preview dialog for bulk Collection imports."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from bulk_collection_import_workflow_preview import (
    BulkCollectionImportWorkflowPreview,
    BulkCollectionImportWorkflowRow,
)


_STATUS_LABELS = {
    "add_new": "Add",
    "match_existing": "Match",
    "review_required": "Review",
}


class BulkCollectionImportDialog:
    """Modal preview of one planned bulk Collection import."""

    MIN_WIDTH = 980
    MIN_HEIGHT = 620

    def __init__(
        self,
        parent,
        preview: BulkCollectionImportWorkflowPreview,
        logger=None,
        on_close=None,
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

        self.parent = parent
        self.preview = preview
        self.logger = logger
        self.on_close = on_close

        self.window = None
        self.tree = None
        self.detail_var = None
        self._closed = False
        self._rows_by_key = {
            row.entry_key: row
            for row in preview.rows
        }
        self._group_titles = self._build_group_titles(preview)

    def show(self):
        """Create and show the review-only modal dialog."""

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
        self.window.title("Bulk Collection Import Preview")
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
        self._build_footer(container)
        self._populate_rows()

        self._center()
        self.window.deiconify()
        self.window.focus_force()
        return self.window

    def close(self):
        """Close the preview without changing Collection data."""

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
                "Review-only preview — no Collection changes "
                "will be made from this dialog."
            ),
            wraplength=920,
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
            "title": ("Hack", 360, "w", True),
            "target": ("Collection target", 260, "w", True),
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
            wraplength=900,
        ).pack(fill="x")

    def _build_footer(self, parent):
        footer = ttk.Frame(parent)
        footer.pack(fill="x", pady=(12, 0))

        ttk.Label(
            footer,
            text=(
                "No changes are applied until a later review "
                "and confirmation workflow is completed."
            ),
        ).pack(side="left")

        ttk.Button(
            footer,
            text="Close",
            command=self.close,
        ).pack(side="right")

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

    def _selection_changed(self, _event=None):
        if self.tree is None:
            return

        selection = self.tree.selection()
        if not selection:
            return

        row = self._rows_by_key.get(selection[0])
        if row is not None:
            self._show_row_details(row)

    def _show_row_details(self, row):
        if self.detail_var is None:
            return
        self.detail_var.set(self._detail_text(row))

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
