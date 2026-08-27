"""Read-only final preview for reviewed Collection ROM/save organization actions."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

from collection_rom_organization_execution_plan import (
    CollectionRomOrganizationExecutionPlan,
)


class CollectionRomOrganizationExecutionPlanDialog:
    """Modal final execution-plan preview with explicit transactional Apply."""

    def __init__(
        self,
        parent,
        plan: CollectionRomOrganizationExecutionPlan,
        on_close=None,
        on_apply=None,
    ):
        self.plan = plan
        self._parent = parent
        self._on_close = on_close
        self._on_apply = on_apply
        self._closed = False
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Final ROM Organization Execution Plan")
        self.dialog.geometry("1220x760")
        self.dialog.minsize(940, 560)
        self.dialog.transient(parent)

        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="Final ROM + Save Organization Plan",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Final reviewed execution preview. ROM and selected colocated-save bytes have "
                "been revalidated and frozen into exact source → target operations. Apply copies "
                "to new targets first, commits Collection paths second, and deletes old reviewed "
                "sources only after the transaction reaches its commit point."
            ),
            wraplength=1120,
            justify="left",
        ).pack(anchor="w", pady=(4, 8))

        summary = (
            f"ROM moves: {len(self.plan.rom_moves)}    "
            f"Save moves: {len(self.plan.save_moves)}    "
            f"Saves left in place: {len(self.plan.save_leaves)}    "
            f"Blocked ROM moves excluded: {self.plan.blocked_move_count}"
        )
        ttk.Label(outer, text=summary, font=("Segoe UI", 9, "bold")).pack(
            anchor="w", pady=(0, 4)
        )
        ttk.Label(
            outer,
            text=(
                f"External/configured Save Sync evidence retained as informational: "
                f"{self.plan.external_save_evidence_count}. ROM-only acknowledgements: "
                f"{self.plan.rom_only_acknowledgement_count}."
            ),
            wraplength=1120,
            justify="left",
        ).pack(anchor="w", pady=(0, 10))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        self._build_move_table(notebook, "ROM Moves", self.plan.rom_moves, is_save=False)
        self._build_move_table(notebook, "Save Moves", self.plan.save_moves, is_save=True)
        self._build_leave_table(notebook)

        ttk.Label(
            outer,
            text=(
                "Apply consumes only this immutable plan and verifies the same Collection revision, "
                "source hashes/sizes/mtimes, target absence, and colocated-save set again. Existing "
                "targets are never overwritten, and Apply does not re-run organization or "
                "save-disposition decisions."
            ),
            wraplength=1120,
            justify="left",
        ).pack(anchor="w", pady=(10, 8))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        if self._on_apply is not None:
            ttk.Button(
                buttons,
                text="Apply Organization...",
                command=self._confirm_apply,
            ).pack(side="right", padx=(0, 8))


    def _confirm_apply(self):
        if self._on_apply is None:
            return
        save_text = (
            f" and {len(self.plan.save_moves)} reviewed colocated save(s)"
            if self.plan.save_moves
            else ""
        )
        confirmed = messagebox.askyesno(
            "Apply ROM Organization",
            (
                f"Move {len(self.plan.rom_moves)} reviewed ROM(s){save_text}?\n\n"
                "The transaction will never overwrite an existing target. It copies and "
                "verifies every target first, atomically updates Collection paths, then "
                "removes only the reviewed old source files after the commit point.\n\n"
                "Saves explicitly marked Leave in place will not be moved. Apply exactly "
                "this finalized plan?"
            ),
            icon="warning",
            default=messagebox.NO,
            parent=self.dialog,
        )
        if confirmed:
            self._on_apply(self.plan, self.dialog)

    def _build_move_table(self, notebook, title, rows, *, is_save):
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text=f"{title} ({len(rows)})")
        columns = ("hack", "source", "target", "size", "sha")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=16)
        tree.heading("hack", text="Collection Hack")
        tree.heading("source", text="Source")
        tree.heading("target", text="Target")
        tree.heading("size", text="Size")
        tree.heading("sha", text="SHA-256")
        tree.column("hack", width=190, minwidth=130, anchor="w")
        tree.column("source", width=320, minwidth=200, anchor="w")
        tree.column("target", width=320, minwidth=200, anchor="w")
        tree.column("size", width=90, minwidth=70, anchor="e")
        tree.column("sha", width=170, minwidth=130, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        for row in rows:
            if is_save:
                title_text = row.title
                source = row.source_path
                target = row.target_path
                size = row.size_bytes
                sha = row.sha256
            else:
                title_text = row.title + ("  ★" if row.primary else "")
                source = row.source_path
                target = row.target_path
                size = row.size_bytes
                sha = row.sha256
            tree.insert(
                "",
                "end",
                values=(title_text, source, target, f"{size:,} B", sha),
            )

    def _build_leave_table(self, notebook):
        frame = ttk.Frame(notebook, padding=8)
        notebook.add(frame, text=f"Saves Left In Place ({len(self.plan.save_leaves)})")
        columns = ("hack", "save")
        tree = ttk.Treeview(frame, columns=columns, show="headings", height=16)
        tree.heading("hack", text="Collection Hack")
        tree.heading("save", text="Explicitly left at current path")
        tree.column("hack", width=220, minwidth=150, anchor="w")
        tree.column("save", width=760, minwidth=300, anchor="w")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)
        for row in self.plan.save_leaves:
            tree.insert("", "end", values=(row.title, row.save_path))

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
