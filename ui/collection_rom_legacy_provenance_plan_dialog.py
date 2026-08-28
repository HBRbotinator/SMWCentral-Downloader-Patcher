"""Read-only preview for legacy ROM metadata plans with explicit provenance."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from collection_rom_legacy_metadata_plan import ReviewedLegacyRomMetadataModernizationPlan


class CollectionRomLegacyProvenancePlanDialog:
    """Modal preview of hashed reviewed-provenance backfills; no Apply exists."""

    def __init__(self, parent, plan: ReviewedLegacyRomMetadataModernizationPlan, on_close=None, on_apply=None):
        self.plan = plan
        self._on_close = on_close
        self._on_apply = on_apply
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Reviewed Legacy ROM Metadata Plan")
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
            text="Reviewed Legacy ROM Metadata Modernization Plan",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Read-only immutable preview. Each ambiguous legacy ROM has an explicit "
                "recorded-history SMWC provenance choice and has now been SHA-256 hashed "
                "and revalidated. Collection files[] metadata has not been changed."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        ttk.Label(
            outer,
            text=f"Reviewed metadata backfills: {len(self.plan.operations)}",
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            outer,
            text=(
                "The plan is frozen against the exact Collection/provenance-review revision, "
                "legacy file_path ownership, selected SMWC provenance, canonical path, SHA-256, "
                "byte size, and source modification time. A later Apply boundary must verify "
                "these preconditions again before writing Collection metadata."
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
        tree.heading("provenance", text="Selected ROM Provenance")
        tree.heading("sha", text="SHA-256")
        tree.column("hack", width=190, minwidth=130, anchor="w")
        tree.column("asset", width=170, minwidth=120, anchor="w")
        tree.column("path", width=330, minwidth=200, anchor="w")
        tree.column("size", width=90, minwidth=70, anchor="e")
        tree.column("provenance", width=170, minwidth=130, anchor="w")
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
            item = tree.insert(
                "",
                "end",
                values=(
                    operation.title,
                    operation.asset_name,
                    operation.canonical_path,
                    f"{operation.size_bytes:,} B",
                    f"SMWC {operation.smwc_submission_id}",
                    operation.sha256[:16] + "…",
                ),
            )
            self._operations_by_item[item] = operation

        detail_var = tk.StringVar(value="Select a row to inspect its frozen provenance and files[] proposal.")
        ttk.Label(outer, textvariable=detail_var, wraplength=1080, justify="left").pack(
            fill="x", pady=(10, 8)
        )

        def show_detail(_event=None):
            selected = tree.selection()
            if not selected:
                return
            operation = self._operations_by_item.get(selected[0])
            if operation is None:
                return
            detail_var.set(
                f"SHA-256: {operation.sha256}. Size: {operation.size_bytes:,} bytes. "
                f"Source mtime_ns: {operation.source_mtime_ns}. Selected provenance: "
                f"SMWC {operation.smwc_submission_id}. Ingestion source: "
                f"{operation.ingestion_source}. file_path remains unchanged."
            )

        tree.bind("<<TreeviewSelect>>", show_detail)

        ttk.Label(
            outer,
            text=(
                "Apply writes only the frozen files[] metadata after revalidating the selected "
                "SMWC provenance and exact ROM bytes. ROM files, saves, file_path, and "
                "additional_paths are not moved or rewritten."
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
                text="Apply Reviewed Metadata Backfill...",
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
