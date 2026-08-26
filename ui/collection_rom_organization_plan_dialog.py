"""Read-only preview for an immutable Collection ROM organization move plan."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from collection_rom_organization_plan import CollectionRomOrganizationPlan


class CollectionRomOrganizationPlanDialog:
    """Modal preview of frozen safe ROM moves; no execution action is exposed."""

    def __init__(
        self,
        parent,
        plan: CollectionRomOrganizationPlan,
        on_close=None,
        on_review_save_impact=None,
    ):
        self.plan = plan
        self._on_close = on_close
        self._on_review_save_impact = on_review_save_impact
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Collection ROM Organization Plan")
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
            text="ROM Organization Move Plan",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Read-only immutable preview. No ROM or save files are moved, renamed, "
                "copied, deleted, or modified, and Collection metadata is not changed."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        summary = (
            f"Planned safe moves: {len(self.plan.moves)}    "
            f"Already in place: {self.plan.in_place_count}    "
            f"Excluded review/blocking rows: {self.plan.excluded_blocking_count}"
        )
        ttk.Label(outer, text=summary, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            outer,
            text=(
                "Each move is frozen against the current Collection revision, recorded "
                "SHA-256 and byte size, source modification time, and target-path absence. "
                "A later execution boundary must verify those exact preconditions again."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        table_frame = ttk.Frame(outer)
        table_frame.pack(fill="both", expand=True)
        columns = ("hack", "asset", "source", "target", "size", "sha")
        tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        tree.heading("hack", text="Collection Hack")
        tree.heading("asset", text="ROM Asset")
        tree.heading("source", text="Current Location")
        tree.heading("target", text="Planned Location")
        tree.heading("size", text="Size")
        tree.heading("sha", text="SHA-256")
        tree.column("hack", width=190, minwidth=130, anchor="w")
        tree.column("asset", width=150, minwidth=110, anchor="w")
        tree.column("source", width=270, minwidth=180, anchor="w")
        tree.column("target", width=270, minwidth=180, anchor="w")
        tree.column("size", width=90, minwidth=70, anchor="e")
        tree.column("sha", width=150, minwidth=120, anchor="w")

        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self._moves_by_item = {}
        for move in self.plan.moves:
            title = move.title + ("  ★" if move.primary else "")
            item = tree.insert(
                "",
                "end",
                values=(
                    title,
                    move.asset_name,
                    move.source_path,
                    move.target_path,
                    f"{move.size_bytes:,} B",
                    move.sha256[:16] + "…",
                ),
            )
            self._moves_by_item[item] = move

        detail_var = tk.StringVar(
            value=(
                "Select a move to inspect its frozen byte identity and source-state "
                "preconditions."
            )
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
            move = self._moves_by_item.get(selected[0])
            if move is None:
                return
            provenance = (
                f"SMWC {move.smwc_submission_id}"
                if move.smwc_submission_id is not None
                else "local/user-owned"
            )
            detail_var.set(
                f"Recorded SHA-256: {move.sha256}. Size: {move.size_bytes:,} bytes. "
                f"Source mtime_ns: {move.source_mtime_ns}. Provenance: {provenance}."
            )

        tree.bind("<<TreeviewSelect>>", show_detail)

        ttk.Label(
            outer,
            text=(
                "No save migration is planned here. Because organization can change ROM "
                "directories, save behavior must be reviewed explicitly before filesystem "
                "execution is introduced."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        if self._on_review_save_impact is not None:
            ttk.Button(
                buttons,
                text="Review Save Impact...",
                command=self._review_save_impact,
            ).pack(side="right", padx=(0, 8))

    def _review_save_impact(self):
        if self._on_review_save_impact is None:
            return
        self._on_review_save_impact(self.plan, self.dialog)

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
