"""Read-only Collection ROM organization audit dialog."""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk

from collection_rom_organization import (
    CollectionRomOrganizationAudit,
    STATUS_IN_PLACE,
    STATUS_LEGACY_PATH,
    STATUS_MISSING_SOURCE,
    STATUS_NEEDS_ORGANIZATION,
    STATUS_REVIEW_PROVENANCE,
    STATUS_REVIEW_METADATA,
    STATUS_TARGET_COLLISION,
    STATUS_TARGET_OCCUPIED,
)


_STATUS_LABELS = {
    STATUS_IN_PLACE: "In place",
    STATUS_NEEDS_ORGANIZATION: "Would move",
    STATUS_MISSING_SOURCE: "Missing source",
    STATUS_TARGET_OCCUPIED: "Target occupied",
    STATUS_TARGET_COLLISION: "Target collision",
    STATUS_REVIEW_PROVENANCE: "Review provenance",
    STATUS_REVIEW_METADATA: "Review metadata",
    STATUS_LEGACY_PATH: "Legacy path",
}


class CollectionRomOrganizationAuditDialog:
    """Modal, read-only presentation of a Collection ROM organization audit."""

    def __init__(
        self,
        parent,
        audit: CollectionRomOrganizationAudit,
        on_close=None,
        on_preview_plan=None,
        on_review_legacy_metadata=None,
    ):
        self.audit = audit
        self._on_close = on_close
        self._on_preview_plan = on_preview_plan
        self._on_review_legacy_metadata = on_review_legacy_metadata
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Collection ROM Organization Audit")
        self.dialog.geometry("1180x680")
        self.dialog.minsize(900, 520)
        self.dialog.transient(parent)

        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="ROM Organization Audit",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Read-only preview. No ROM or save files are moved, renamed, copied, "
                "deleted, or modified, and Collection metadata is not changed."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))
        ttk.Label(
            outer,
            text=f"Configured ROM library: {self.audit.output_dir}",
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        summary = (
            f"Recorded assets: {len(self.audit.rows)}    "
            f"In place: {self.audit.in_place_count}    "
            f"Would move: {self.audit.move_candidate_count}    "
            f"Needs review/blocking: {self.audit.blocking_count}"
        )
        ttk.Label(outer, text=summary, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(0, 10)
        )

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("hack", "asset", "status", "current", "expected")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        tree.heading("hack", text="Collection Hack")
        tree.heading("asset", text="ROM Asset")
        tree.heading("status", text="Audit Status")
        tree.heading("current", text="Current Location")
        tree.heading("expected", text="Expected Location")
        tree.column("hack", width=210, minwidth=130, anchor="w")
        tree.column("asset", width=170, minwidth=120, anchor="w")
        tree.column("status", width=130, minwidth=110, anchor="w")
        tree.column("current", width=300, minwidth=180, anchor="w")
        tree.column("expected", width=300, minwidth=180, anchor="w")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self._rows_by_item = {}
        for row in self.audit.rows:
            display_title = row.title
            if row.primary:
                display_title += "  ★"
            item = tree.insert(
                "",
                "end",
                values=(
                    display_title,
                    row.asset_name,
                    _STATUS_LABELS.get(row.status, row.status),
                    row.current_path,
                    row.expected_path or "—",
                ),
            )
            self._rows_by_item[item] = row

        detail_var = tk.StringVar(
            value=(
                "Select a row to see why it is in that state. Historical-submission and "
                "legacy paths are intentionally not given an automatic move target."
            )
        )
        detail = ttk.Label(
            outer,
            textvariable=detail_var,
            wraplength=1080,
            justify="left",
        )
        detail.pack(fill="x", pady=(10, 8))

        def show_detail(_event=None):
            selected = tree.selection()
            if not selected:
                return
            row = self._rows_by_item.get(selected[0])
            if row is None:
                return
            provenance = (
                f" Recorded SMWC provenance: {row.smwc_submission_id}."
                if row.smwc_submission_id is not None
                else ""
            )
            detail_var.set(row.detail + provenance)

        tree.bind("<<TreeviewSelect>>", show_detail)

        ttk.Label(
            outer,
            text=(
                "Save-file migration is not part of this audit. A later execution boundary "
                "must review filesystem conflicts and any save implications explicitly."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        if self._on_preview_plan is not None and self.audit.move_candidate_count:
            ttk.Button(
                buttons,
                text="Preview Safe Move Plan...",
                command=self._preview_plan,
            ).pack(side="right", padx=(0, 8))
        if self._on_review_legacy_metadata is not None and self.audit.legacy_path_count:
            ttk.Button(
                buttons,
                text="Review Legacy ROM Metadata...",
                command=self._review_legacy_metadata,
            ).pack(side="right", padx=(0, 8))

    def _review_legacy_metadata(self):
        if self._on_review_legacy_metadata is not None:
            self._on_review_legacy_metadata()

    def _preview_plan(self):
        if self._on_preview_plan is None:
            return
        self._on_preview_plan(self.audit)

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.dialog.winfo_exists():
                self.dialog.grab_release()
                self.dialog.destroy()
        finally:
            if self._on_close is not None:
                self._on_close()
