"""Read-only preview of legacy Collection ROM metadata modernization readiness."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from collection_rom_legacy_metadata import (
    LegacyRomMetadataAudit,
    STATUS_DUPLICATE_PATH,
    STATUS_MISSING_SOURCE,
    STATUS_READY,
    STATUS_REVIEW_METADATA,
    STATUS_REVIEW_PROVENANCE,
    STATUS_SYMLINK,
)


_STATUS_LABELS = {
    STATUS_READY: "Ready for planning",
    STATUS_MISSING_SOURCE: "Missing source",
    STATUS_REVIEW_PROVENANCE: "Review provenance",
    STATUS_REVIEW_METADATA: "Review metadata",
    STATUS_DUPLICATE_PATH: "Duplicate path",
    STATUS_SYMLINK: "Symbolic link",
}


class CollectionRomLegacyMetadataDialog:
    """Modal, read-only view of legacy file_path modernization readiness."""

    def __init__(self, parent, audit: LegacyRomMetadataAudit, on_close=None):
        self.audit = audit
        self._on_close = on_close
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Legacy Collection ROM Metadata")
        self.dialog.geometry("1080x650")
        self.dialog.minsize(840, 500)
        self.dialog.transient(parent)

        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Legacy ROM Metadata Audit",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Read-only preview for Collection records that still use file_path without "
                "modern files[] ROM metadata. No ROM is hashed, moved, renamed, copied, or "
                "deleted, and Collection data is not changed."
            ),
            wraplength=1000,
            justify="left",
        ).pack(anchor="w", pady=(4, 10))

        summary = (
            f"Legacy records: {len(self.audit.rows)}    "
            f"Ready for later planning: {self.audit.ready_count}    "
            f"Needs review/blocking: {self.audit.blocking_count}"
        )
        ttk.Label(outer, text=summary, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(0, 10)
        )

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("hack", "status", "size", "provenance", "path")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        tree.heading("hack", text="Collection Hack")
        tree.heading("status", text="Status")
        tree.heading("size", text="Current Size")
        tree.heading("provenance", text="Proposed Provenance")
        tree.heading("path", text="Legacy ROM Path")
        tree.column("hack", width=220, minwidth=140, anchor="w")
        tree.column("status", width=145, minwidth=120, anchor="w")
        tree.column("size", width=100, minwidth=90, anchor="e")
        tree.column("provenance", width=170, minwidth=140, anchor="w")
        tree.column("path", width=390, minwidth=220, anchor="w")

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
            size = "—" if row.size_bytes is None else f"{row.size_bytes:,} B"
            provenance = (
                f"SMWC {row.proposed_smwc_submission_id}"
                if row.proposed_smwc_submission_id is not None
                else (
                    "Local / none"
                    if row.status == STATUS_READY
                    else "Needs review"
                )
            )
            item = tree.insert(
                "",
                "end",
                values=(
                    row.title,
                    _STATUS_LABELS.get(row.status, row.status),
                    size,
                    provenance,
                    row.current_path,
                ),
            )
            self._rows_by_item[item] = row

        detail_var = tk.StringVar(
            value=(
                "Select a row for details. Ready rows still require exact SHA-256 hashing and "
                "a later immutable plan before Collection can be changed."
            )
        )
        ttk.Label(
            outer,
            textvariable=detail_var,
            wraplength=1000,
            justify="left",
        ).pack(fill="x", pady=(10, 8))

        def show_detail(_event=None):
            selected = tree.selection()
            if not selected:
                return
            row = self._rows_by_item.get(selected[0])
            if row is not None:
                detail_var.set(row.detail)

        tree.bind("<<TreeviewSelect>>", show_detail)

        ttk.Label(
            outer,
            text=(
                "This audit does not create files[] rows. A later explicit planning boundary "
                "must hash and revalidate the exact ROM bytes before any metadata backfill."
            ),
            wraplength=1000,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")

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
