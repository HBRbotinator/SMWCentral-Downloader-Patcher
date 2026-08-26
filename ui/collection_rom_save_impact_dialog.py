"""Read-only save-impact review for Collection ROM organization plans."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from collection_rom_save_impact import (
    CollectionRomSaveImpactReview,
    SOURCE_COLOCATED,
    SOURCE_CONFIGURED_ASSOCIATION,
    SOURCE_CONFIGURED_NAME,
)


_SOURCE_LABELS = {
    SOURCE_COLOCATED: "Beside ROM",
    SOURCE_CONFIGURED_NAME: "Configured name match",
    SOURCE_CONFIGURED_ASSOCIATION: "Saved association",
}


class CollectionRomSaveImpactDialog:
    """Modal read-only presentation of plausible save impact."""

    def __init__(self, parent, review: CollectionRomSaveImpactReview):
        self.review = review
        self._parent = parent
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Collection ROM Organization — Save Impact")
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
            text="ROM Organization Save Impact",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Read-only relationship review. The application cannot infer an emulator's "
                "save-location policy from Save Sync settings, so this screen reports evidence "
                "only and performs no save or ROM migration."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        summary = (
            f"Planned ROM moves: {len(self.review.plan.moves)}    "
            f"Related saves detected: {len(self.review.rows)}    "
            f"Beside ROM: {self.review.colocated_count}    "
            f"Configured/external: {self.review.external_count}    "
            f"Possible target conflicts: {self.review.target_conflict_count}"
        )
        ttk.Label(outer, text=summary, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(0, 10)
        )

        if not self.review.rows:
            ttk.Label(
                outer,
                text=(
                    "No same-basename save beside a planned ROM and no matching or explicitly "
                    "associated save in the configured Save Sync folders was detected. This does "
                    "not prove that the emulator has no save state elsewhere."
                ),
                wraplength=1080,
                justify="left",
            ).pack(anchor="w", pady=(4, 12))
        else:
            table_frame = ttk.Frame(outer)
            table_frame.pack(fill="both", expand=True)
            columns = ("hack", "save", "relationship", "current", "possible_target", "target")
            tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
            tree.heading("hack", text="Collection Hack")
            tree.heading("save", text="Save File")
            tree.heading("relationship", text="Relationship Evidence")
            tree.heading("current", text="Current Save Location")
            tree.heading("possible_target", text="Possible Colocated Target")
            tree.heading("target", text="Target State")
            tree.column("hack", width=180, minwidth=130, anchor="w")
            tree.column("save", width=130, minwidth=100, anchor="w")
            tree.column("relationship", width=160, minwidth=130, anchor="w")
            tree.column("current", width=270, minwidth=180, anchor="w")
            tree.column("possible_target", width=270, minwidth=180, anchor="w")
            tree.column("target", width=110, minwidth=90, anchor="w")

            y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
            x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
            tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
            tree.grid(row=0, column=0, sticky="nsew")
            y_scroll.grid(row=0, column=1, sticky="ns")
            x_scroll.grid(row=1, column=0, sticky="ew")
            table_frame.grid_rowconfigure(0, weight=1)
            table_frame.grid_columnconfigure(0, weight=1)

            self._rows_by_item = {}
            for row in self.review.rows:
                target_state = (
                    "Occupied"
                    if row.target_occupied
                    else ("Available" if row.possible_target_path else "Not proposed")
                )
                item = tree.insert(
                    "",
                    "end",
                    values=(
                        row.title,
                        row.save_name,
                        _SOURCE_LABELS.get(row.source_kind, row.source_kind),
                        row.save_path,
                        row.possible_target_path or "—",
                        target_state,
                    ),
                )
                self._rows_by_item[item] = row

            detail_var = tk.StringVar(
                value="Select a save to inspect why it was related to the planned ROM move."
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
                row = self._rows_by_item.get(selected[0])
                if row is None:
                    return
                conflict = (
                    " The possible colocated destination is already occupied."
                    if row.target_occupied
                    else ""
                )
                detail_var.set(
                    f"{row.source_detail} Size: {row.size_bytes:,} bytes. "
                    f"mtime_ns: {row.mtime_ns}.{conflict}"
                )

            tree.bind("<<TreeviewSelect>>", show_detail)

        ttk.Label(
            outer,
            text=(
                "No save action is selected by this review. A later boundary must require an "
                "explicit disposition for any colocated companion before ROM filesystem execution."
            ),
            wraplength=1080,
            justify="left",
        ).pack(anchor="w", pady=(8, 10))

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
            try:
                if self._parent.winfo_exists():
                    self._parent.grab_set()
            except tk.TclError:
                pass
