"""Read-only final preview for historical-provenance ROM/save organization."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from collection_rom_historical_organization_execution_plan import (
    HistoricalRomOrganizationExecutionPlan,
)


class HistoricalRomOrganizationExecutionPlanDialog:
    """Modal final historical execution preview; deliberately has no Apply action."""

    def __init__(self, parent, plan: HistoricalRomOrganizationExecutionPlan, on_close=None):
        self.plan = plan
        self._parent = parent
        self._on_close = on_close
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Final Historical ROM Organization Plan")
        self.dialog.geometry("1260x760")
        self.dialog.minsize(960, 560)
        self.dialog.transient(parent)
        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text="Final Historical ROM + Save Organization Plan",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Final read-only historical execution preview. Historical submission layout, "
                "ROM byte identity, save dispositions, and migrated-save hashes are frozen. "
                "No filesystem or Collection Apply action is exposed by this boundary."
            ),
            wraplength=1160,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))
        ttk.Label(
            outer,
            text=(
                f"Historical ROM moves: {len(self.plan.rom_moves)}    "
                f"Save moves: {len(self.plan.save_moves)}    "
                f"Saves left in place: {len(self.plan.save_leaves)}    "
                f"Blocked ROM moves excluded: {self.plan.blocked_move_count}"
            ),
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", pady=(0, 8))
        if self.plan.save_sync_coverage_loss_count:
            ttk.Label(
                outer,
                text=(
                    f"Save Sync warning: {self.plan.save_sync_coverage_loss_count} migrated save(s) "
                    "will leave configured scan coverage. That loss was explicitly acknowledged; "
                    "Save Sync folders remain unchanged."
                ),
                foreground="#B00020",
                wraplength=1160,
                justify="left",
            ).pack(anchor="w", pady=(0, 8))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)
        rom_frame = ttk.Frame(notebook, padding=8)
        notebook.add(rom_frame, text=f"Historical ROM Moves ({len(self.plan.rom_moves)})")
        columns = ("collection", "provenance", "layout", "source", "target", "sha")
        tree = ttk.Treeview(rom_frame, columns=columns, show="headings", height=16)
        labels = {
            "collection": "Current Collection", "provenance": "ROM Provenance",
            "layout": "Frozen Historical Layout", "source": "Source",
            "target": "Target", "sha": "SHA-256",
        }
        widths = {"collection": 170, "provenance": 120, "layout": 190, "source": 260, "target": 280, "sha": 170}
        for column in columns:
            tree.heading(column, text=labels[column])
            tree.column(column, width=widths[column], minwidth=100, anchor="w")
        scroll = ttk.Scrollbar(rom_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        rom_frame.grid_rowconfigure(0, weight=1)
        rom_frame.grid_columnconfigure(0, weight=1)
        for move in self.plan.rom_moves:
            tree.insert("", "end", values=(
                move.collection_title,
                f"SMWC {move.historical_smwc_submission_id}",
                f"{move.historical_hack_type} / {move.historical_difficulty}",
                move.source_path, move.target_path, move.sha256,
            ))

        save_frame = ttk.Frame(notebook, padding=8)
        notebook.add(save_frame, text=f"Save Moves ({len(self.plan.save_moves)})")
        save_tree = ttk.Treeview(save_frame, columns=("hack", "source", "target", "sha"), show="headings", height=16)
        for column, label, width in (("hack", "Collection Hack", 190), ("source", "Source", 330), ("target", "Target", 330), ("sha", "SHA-256", 180)):
            save_tree.heading(column, text=label)
            save_tree.column(column, width=width, minwidth=100, anchor="w")
        save_tree.pack(fill="both", expand=True)
        for move in self.plan.save_moves:
            save_tree.insert("", "end", values=(move.title, move.source_path, move.target_path, move.sha256))

        ttk.Label(
            outer,
            text=(
                "This plan is fully frozen for a future transactional historical Apply boundary, "
                "which must independently revalidate Collection ownership, historical per-ROM "
                "provenance, source bytes/mtimes, target absence, and colocated-save evidence."
            ),
            wraplength=1160,
            justify="left",
        ).pack(anchor="w", pady=(10, 8))
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
            try:
                if self._parent.winfo_exists():
                    self._parent.grab_set()
            except tk.TclError:
                pass
