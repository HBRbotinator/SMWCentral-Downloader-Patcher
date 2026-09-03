"""Read-only historical SMWC provenance review for ROM organization."""
from __future__ import annotations

import tkinter as tk
from ui.window_positioning import reveal_window_on_parent

from tkinter import ttk

from collection_rom_historical_provenance import (
    HistoricalRomProvenanceReview,
    STATUS_IN_PLACE,
    STATUS_MISSING_SOURCE,
    STATUS_READY,
    STATUS_REVIEW_METADATA,
    STATUS_TARGET_COLLISION,
    STATUS_TARGET_OCCUPIED,
)

_STATUS_LABELS = {
    STATUS_READY: "Ready for plan",
    STATUS_IN_PLACE: "In place",
    STATUS_MISSING_SOURCE: "Missing source",
    STATUS_TARGET_OCCUPIED: "Target occupied",
    STATUS_TARGET_COLLISION: "Target collision",
    STATUS_REVIEW_METADATA: "Review metadata",
}


class HistoricalRomProvenanceProgressDialog:
    def __init__(self, parent):
        self.dialog = tk.Toplevel(parent)
        self.dialog.withdraw()
        self.dialog.title("Historical ROM Provenance")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)
        frame = ttk.Frame(self.dialog, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Loading historical SMWC metadata...", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text=(
                "The app is fetching metadata only for the submission IDs already recorded "
                "on retained ROM assets. No Collection or filesystem state is changed."
            ),
            wraplength=420,
            justify="left",
        ).pack(anchor="w", pady=(8, 10))
        progress = ttk.Progressbar(frame, mode="indeterminate")
        progress.pack(fill="x")
        progress.start(12)
        self._progress = progress
        self.dialog.protocol("WM_DELETE_WINDOW", lambda: None)
        reveal_window_on_parent(self.dialog, parent, grab=True)

    def close(self):
        try:
            self._progress.stop()
            if self.dialog.winfo_exists():
                self.dialog.grab_release()
                self.dialog.destroy()
        except tk.TclError:
            pass


class CollectionRomHistoricalProvenanceDialog:
    """Modal read-only preview of historical submission-owned ROM layout metadata."""

    def __init__(
        self,
        parent,
        review: HistoricalRomProvenanceReview,
        on_close=None,
        on_preview_plan=None,
    ):
        self.review = review
        self._on_close = on_close
        self._on_preview_plan = on_preview_plan
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Historical ROM Provenance Review")
        self.dialog.geometry("1250x700")
        self.dialog.minsize(980, 540)
        self.dialog.transient(parent)
        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Historical ROM Provenance Review", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Read-only metadata assistance for retained ROMs whose recorded SMWC submission "
                "differs from the Collection record's current submission. Targets below are derived "
                "from each ROM's own SMWC metadata, never from the current Collection metadata."
            ),
            wraplength=1160,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))
        summary = (
            f"Historical assets: {len(self.review.rows)}    "
            f"Ready for later plan: {self.review.ready_count}    "
            f"Already in historical layout: {self.review.in_place_count}    "
            f"Needs review/blocking: {self.review.blocking_count}"
        )
        ttk.Label(outer, text=summary, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 8))
        if self.review.excluded_unknown_provenance_count:
            ttk.Label(
                outer,
                text=(
                    f"{self.review.excluded_unknown_provenance_count} additional provenance-review "
                    "row(s) have no explicit historical SMWC ID and remain unresolved by this workflow."
                ),
                wraplength=1160,
                justify="left",
            ).pack(anchor="w", pady=(0, 8))

        frame = ttk.Frame(outer)
        frame.pack(fill="both", expand=True)
        columns = ("collection", "asset", "historical", "metadata", "status", "current", "expected")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=18)
        headings = {
            "collection": "Current Collection",
            "asset": "ROM Asset",
            "historical": "ROM Provenance",
            "metadata": "Historical Layout Metadata",
            "status": "Status",
            "current": "Current Location",
            "expected": "Historical Expected Location",
        }
        widths = {"collection": 180, "asset": 150, "historical": 130, "metadata": 210, "status": 125, "current": 250, "expected": 270}
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], minwidth=100, anchor="w")
        y_scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        rows_by_item = {}
        for row in self.review.rows:
            item = tree.insert(
                "",
                "end",
                values=(
                    row.collection_title,
                    row.asset_name + ("  ★" if row.primary else ""),
                    f"SMWC {row.historical_smwc_submission_id}",
                    f"{row.historical_hack_type} / {row.historical_difficulty}",
                    _STATUS_LABELS.get(row.status, row.status),
                    row.current_path,
                    row.expected_path,
                ),
            )
            rows_by_item[item] = row

        detail_var = tk.StringVar(value="Select a row to inspect the historical metadata decision boundary.")
        ttk.Label(outer, textvariable=detail_var, wraplength=1160, justify="left").pack(fill="x", pady=(10, 8))

        def show_detail(_event=None):
            selected = tree.selection()
            if not selected:
                return
            row = rows_by_item.get(selected[0])
            if row is None:
                return
            detail_var.set(
                f"{row.detail} Historical catalogue title: {row.historical_title}. "
                f"Recorded ROM provenance: SMWC {row.historical_smwc_submission_id}."
            )

        tree.bind("<<TreeviewSelect>>", show_detail)
        ttk.Label(
            outer,
            text=(
                "No Apply action exists in this review. Ready rows may be frozen into an immutable "
                "historical move-plan preview that revalidates the exact historical metadata, Collection "
                "revision, ROM bytes and target preconditions before any later save/filesystem boundary."
            ),
            wraplength=1160,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        if self._on_preview_plan is not None and self.review.ready_count:
            ttk.Button(
                buttons,
                text="Preview Historical Move Plan...",
                command=self._preview_plan,
            ).pack(side="right", padx=(0, 8))

    def _preview_plan(self):
        if self._on_preview_plan is not None:
            self._on_preview_plan(self.review)

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
