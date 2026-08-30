"""Tk review for ROM variants that converge on one new Collection target.

The dialog is intentionally provider-free and write-free. It captures only the
combined keep/ignore/primary choices needed after separate identity review
items resolve to the same new Collection key.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from collection_ingestion_convergence_review import (
    CollectionIngestionConvergenceReviewError,
    ConvergedRomDecision,
    ConvergedRomReview,
    validate_converged_rom_decision,
)
from collection_reconciliation import IgnoredRomDecision, RomSelectionDecision


class CollectionIngestionConvergenceReviewDialog:
    """Capture one target-level ROM selection for every converged new target."""

    def __init__(
        self,
        parent,
        reviews,
        *,
        decisions=None,
        on_complete=None,
        on_close=None,
    ):
        self.parent = parent
        self.reviews = tuple(reviews)
        self.decisions = dict(decisions or {})
        self.on_complete = on_complete
        self.on_close = on_close
        self.win = None
        self.tree = None
        self.details = None
        self.summary_label = None
        self.done_button = None
        self._current_target = None
        self._action_vars = {}
        self._primary_var = None
        self._closed = False

    @property
    def is_open(self):
        try:
            return bool(self.win and self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self):
        if self.is_open:
            self.lift()
            return self.win

        self.win = tk.Toplevel(self.parent)
        self.win.title("Review Combined ROM Variants")
        self.win.geometry("900x610")
        self.win.minsize(760, 520)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)
        try:
            self.win.grab_set()
        except tk.TclError:
            pass

        root = ttk.Frame(self.win, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(
            root,
            text="Review Combined ROM Variants",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "Separate review items now resolve to the same new Collection target. "
                "Review their ROM variants together and choose exactly one primary. "
                "Nothing is written from this dialog."
            ),
            wraplength=840,
        ).pack(anchor="w", pady=(3, 10))

        self.summary_label = ttk.Label(root, font=("Segoe UI", 10, "bold"))
        self.summary_label.pack(anchor="w", pady=(0, 8))

        pane = ttk.Panedwindow(root, orient="horizontal")
        pane.pack(fill="both", expand=True)
        left = ttk.Frame(pane, padding=(0, 0, 8, 0))
        right = ttk.Frame(pane, padding=(8, 0, 0, 0))
        pane.add(left, weight=2)
        pane.add(right, weight=5)

        self.tree = ttk.Treeview(
            left,
            columns=("target", "roms", "status"),
            show="headings",
            selectmode="browse",
        )
        self.tree.heading("target", text="SMWC ID")
        self.tree.heading("roms", text="ROMs")
        self.tree.heading("status", text="Status")
        self.tree.column("target", width=95, anchor="w")
        self.tree.column("roms", width=55, anchor="center")
        self.tree.column("status", width=100, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_selected)

        self.details = ttk.Frame(right)
        self.details.pack(fill="both", expand=True)

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="Cancel", command=self.close).pack(side="right")
        self.done_button = ttk.Button(
            footer,
            text="Continue",
            command=self._complete,
        )
        self.done_button.pack(side="right", padx=(0, 8))

        self._refresh_rows()
        self._update_summary()
        if self.reviews:
            first = self.reviews[0].target_key
            self.tree.selection_set(first)
            self.tree.focus(first)
            self._render(first)
        self._center()
        return self.win

    def lift(self):
        if not self.is_open:
            return
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except tk.TclError:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.win and self.win.winfo_exists():
                try:
                    self.win.grab_release()
                except tk.TclError:
                    pass
                self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()

    def _review(self, target_key):
        for review in self.reviews:
            if review.target_key == target_key:
                return review
        raise KeyError(target_key)

    def _refresh_rows(self):
        if not self.tree:
            return
        selected = self._current_target
        for item in self.tree.get_children():
            self.tree.delete(item)
        for review in self.reviews:
            status = "Reviewed" if review.target_key in self.decisions else "Needs review"
            self.tree.insert(
                "",
                "end",
                iid=review.target_key,
                values=(review.target_key, len(review.rom_files), status),
            )
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)

    def _update_summary(self):
        remaining = sum(1 for review in self.reviews if review.target_key not in self.decisions)
        self.summary_label.configure(
            text=(
                f"{len(self.reviews)} converged target(s) · "
                f"{len(self.decisions)} reviewed · {remaining} remaining"
            )
        )
        self.done_button.configure(state="normal" if remaining == 0 else "disabled")

    def _on_selected(self, _event=None):
        selection = self.tree.selection()
        if selection:
            self._render(selection[0])

    def _render(self, target_key):
        self._current_target = target_key
        for child in self.details.winfo_children():
            child.destroy()
        review = self._review(target_key)
        decision = self.decisions.get(target_key)

        ttk.Label(
            self.details,
            text=f"New Collection target · SMWC {target_key}",
            font=("Segoe UI", 12, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            self.details,
            text=(
                f"{len(review.group_ids)} separate review groups resolved to this target. "
                "Different ROM hashes do not establish version order."
            ),
            wraplength=610,
        ).pack(anchor="w", pady=(3, 10))

        rows = ttk.LabelFrame(self.details, text="ROM variants", padding=8)
        rows.pack(fill="both", expand=True)
        self._action_vars = {}
        self._primary_var = tk.StringVar(
            value=(decision.selection.primary_path if decision is not None else "")
        )
        prior_kept = set(decision.selection.kept_paths) if decision is not None else set()
        prior_ignored = (
            {item.path for item in decision.selection.ignored}
            if decision is not None
            else set()
        )

        for index, rom in enumerate(review.rom_files):
            row = ttk.Frame(rows)
            row.pack(fill="x", pady=(0, 8))
            if decision is None:
                initial = "Keep"
            elif rom.path in prior_kept:
                initial = "Keep"
            elif rom.path in prior_ignored:
                initial = "Ignore"
            else:
                initial = "Leave out"
            action_var = tk.StringVar(value=initial)
            self._action_vars[rom.path] = action_var
            combo = ttk.Combobox(
                row,
                textvariable=action_var,
                values=("Keep", "Ignore", "Leave out"),
                state="readonly",
                width=11,
            )
            combo.grid(row=0, column=0, padx=(0, 8), sticky="w")
            ttk.Radiobutton(
                row,
                text="Primary",
                variable=self._primary_var,
                value=rom.path,
            ).grid(row=0, column=1, padx=(0, 8), sticky="w")
            ttk.Label(row, text=rom.filename or os.path.basename(rom.path)).grid(
                row=0, column=2, sticky="w"
            )
            ttk.Label(
                row,
                text=f"{rom.sha256[:12]}… · {rom.size_bytes} bytes",
                foreground="gray",
            ).grid(row=1, column=2, sticky="w")
            ttk.Label(
                row,
                text=rom.path,
                foreground="gray",
                wraplength=500,
            ).grid(row=2, column=2, sticky="w")
            row.columnconfigure(2, weight=1)

        actions = ttk.Frame(self.details)
        actions.pack(fill="x", pady=(10, 0))
        ttk.Button(actions, text="Reset", command=self._reset_current).pack(side="left")
        ttk.Button(actions, text="Save Decision", command=self._save_current).pack(side="right")

    def _build_current_decision(self):
        review = self._review(self._current_target)
        kept = []
        ignored = []
        for rom in review.rom_files:
            action = self._action_vars[rom.path].get()
            if action == "Keep":
                kept.append(rom.path)
            elif action == "Ignore":
                ignored.append(IgnoredRomDecision(path=rom.path, sha256=rom.sha256))
        if not kept:
            raise CollectionIngestionConvergenceReviewError(
                "Keep at least one ROM variant for this new Collection target."
            )
        primary = self._primary_var.get()
        if len(kept) == 1:
            primary = kept[0]
        if primary not in kept:
            raise CollectionIngestionConvergenceReviewError(
                "Choose one retained ROM as the primary variant."
            )
        result = ConvergedRomDecision(
            target_key=review.target_key,
            selection=RomSelectionDecision(
                kept_paths=tuple(kept),
                primary_path=primary,
                ignored=tuple(ignored),
            ),
        )
        validate_converged_rom_decision(review, result)
        return result

    def _save_current(self):
        if not self._current_target:
            return
        try:
            decision = self._build_current_decision()
        except CollectionIngestionConvergenceReviewError as error:
            messagebox.showerror("Review Incomplete", str(error), parent=self.win)
            return
        self.decisions[decision.target_key] = decision
        current = decision.target_key
        self._refresh_rows()
        self._update_summary()
        if self.tree.exists(current):
            self.tree.selection_set(current)
        for review in self.reviews:
            if review.target_key not in self.decisions:
                self.tree.selection_set(review.target_key)
                self.tree.focus(review.target_key)
                self._render(review.target_key)
                break

    def _reset_current(self):
        if not self._current_target:
            return
        self.decisions.pop(self._current_target, None)
        current = self._current_target
        self._refresh_rows()
        self._update_summary()
        self._render(current)

    def _complete(self):
        missing = [review.target_key for review in self.reviews if review.target_key not in self.decisions]
        if missing:
            messagebox.showwarning(
                "Review Incomplete",
                f"Resolve the remaining {len(missing)} combined ROM review item(s).",
                parent=self.win,
            )
            return
        if self.on_complete:
            result = self.on_complete(dict(self.decisions))
            if result is False:
                return
        self.close()

    def _center(self):
        if not self.win:
            return
        self.win.update_idletasks()
        try:
            parent_x = self.parent.winfo_rootx()
            parent_y = self.parent.winfo_rooty()
            parent_w = self.parent.winfo_width()
            parent_h = self.parent.winfo_height()
            width = self.win.winfo_width()
            height = self.win.winfo_height()
            x = parent_x + (parent_w - width) // 2
            y = parent_y + (parent_h - height) // 2
            self.win.geometry(f"+{max(0, x)}+{max(0, y)}")
            self.win.lift()
        except (tk.TclError, AttributeError):
            pass


__all__ = ["CollectionIngestionConvergenceReviewDialog"]
