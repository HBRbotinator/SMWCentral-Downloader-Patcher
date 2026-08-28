"""Read-only preview for immutable legacy Collection ROM metadata backfill plans."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from collection_rom_legacy_metadata_plan import LegacyRomMetadataModernizationPlan


class CollectionRomLegacyMetadataPlanDialog:
    """Modal preview of hashed modern ``files[]`` rows; no Apply action exists."""

    def __init__(self, parent, plan: LegacyRomMetadataModernizationPlan, on_close=None, on_apply=None):
        self.plan = plan
        self._on_close = on_close
        self._on_apply = on_apply
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Legacy ROM Metadata Modernization Plan")
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
            text="Legacy ROM Metadata Modernization Plan",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Read-only immutable preview. Ready legacy ROMs have now been SHA-256 hashed "
                "and revalidated, but Collection files[] metadata has not been changed."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        ttk.Label(
            outer,
            text=(
                f"Planned metadata backfills: {len(self.plan.operations)}    "
                f"Excluded review/blocking rows: {self.plan.excluded_blocking_count}"
            ),
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            outer,
            text=(
                "Each proposed row is frozen against the current Collection revision, exact "
                "legacy file_path ownership, canonical ROM path, SHA-256, byte size, and "
                "source modification time. A later explicit Apply boundary must verify these "
                "preconditions again before writing Collection metadata."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("hack", "asset", "path", "size", "provenance", "sha")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        tree.heading("hack", text="Collection Hack")
        tree.heading("asset", text="Proposed Primary Asset")
        tree.heading("path", text="Canonical ROM Path")
        tree.heading("size", text="Size")
        tree.heading("provenance", text="ROM Provenance")
        tree.heading("sha", text="SHA-256")
        tree.column("hack", width=190, minwidth=130, anchor="w")
        tree.column("asset", width=170, minwidth=120, anchor="w")
        tree.column("path", width=330, minwidth=200, anchor="w")
        tree.column("size", width=90, minwidth=70, anchor="e")
        tree.column("provenance", width=150, minwidth=120, anchor="w")
        tree.column("sha", width=170, minwidth=130, anchor="w")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self._operations_by_item = {}
        for operation in self.plan.operations:
            provenance = (
                f"SMWC {operation.smwc_submission_id}"
                if operation.smwc_submission_id is not None
                else "Local / none"
            )
            item = tree.insert(
                "",
                "end",
                values=(
                    operation.title,
                    operation.asset_name,
                    operation.canonical_path,
                    f"{operation.size_bytes:,} B",
                    provenance,
                    operation.sha256[:16] + "…",
                ),
            )
            self._operations_by_item[item] = operation

        detail_var = tk.StringVar(
            value="Select a row to inspect its frozen proposed files[] metadata."
        )
        ttk.Label(
            outer,
            textvariable=detail_var,
            wraplength=1080,
            justify="left",
        ).pack(fill="x", pady=(10, 8))

        def show_detail(_event=None):
            selected = tree.selection()
            if not selected:
                return
            operation = self._operations_by_item.get(selected[0])
            if operation is None:
                return
            provenance = (
                f"SMWC {operation.smwc_submission_id}"
                if operation.smwc_submission_id is not None
                else "local/user-owned"
            )
            detail_var.set(
                f"SHA-256: {operation.sha256}. Size: {operation.size_bytes:,} bytes. "
                f"Source mtime_ns: {operation.source_mtime_ns}. Provenance: {provenance}. "
                f"Ingestion source: {operation.ingestion_source}. file_path remains unchanged."
            )

        tree.bind("<<TreeviewSelect>>", show_detail)

        ttk.Label(
            outer,
            text=(
                "No Collection write is available in this preview. additional_paths are not "
                "interpreted as modern ROM variants by this plan."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        if self._on_apply is not None:
            ttk.Button(
                buttons,
                text="Apply Metadata Backfill...",
                command=self._apply,
            ).pack(side="right", padx=(0, 8))

    def _apply(self):
        if self._on_apply is not None:
            self._on_apply(self.plan, self.dialog)

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
