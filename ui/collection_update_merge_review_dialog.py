"""Read-only review UI for explicit replacement into an existing numeric target."""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import messagebox, ttk

from collection_update_merge_review import (
    CollectionUpdateExistingTargetMergeReview,
    CollectionUpdateMergeReviewError,
    MergeValueOrigin,
    finalize_collection_update_existing_target_merge_decision,
)


class CollectionUpdateMergeReviewDialog:
    """Resolve user/local state conflicts without building or applying a migration plan."""

    def __init__(self, parent, review, *, on_save=None, on_close=None):
        if not isinstance(review, CollectionUpdateExistingTargetMergeReview):
            raise TypeError("review must be CollectionUpdateExistingTargetMergeReview")
        self.parent = parent
        self.review = review
        self.on_save = on_save
        self.on_close = on_close
        self.win = None
        self._closed = False
        self._field_vars = {}
        self._primary_var = None

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

        source = self.review.selection.source_entry
        target = self.review.selection.target_entry
        self.win = tk.Toplevel(self.parent)
        self.win.title("Review Existing Collection Merge")
        self.win.geometry("1060x760")
        self.win.minsize(840, 620)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        outer = ttk.Frame(self.win, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(
            outer,
            text="Review Existing Collection Merge",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                f"Possible relationship: SMWC {source.smwc_submission_id} — {source.title} → "
                f"SMWC {target.smwc_submission_id} — {target.title}. Both identities already "
                "have Collection state, so user-owned conflicts must be resolved explicitly."
            ),
            wraplength=1000,
        ).pack(anchor="w", pady=(4, 3))
        ttk.Label(
            outer,
            text=(
                "This step does not claim the target is newer and does not hydrate KaizOFF, "
                "build a change plan, migrate identity, or write any user data."
            ),
            foreground="#C47F00",
            wraplength=1000,
        ).pack(anchor="w", pady=(0, 10))

        canvas_frame = ttk.Frame(outer)
        canvas_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(canvas_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas, padding=(2, 2, 8, 2))
        window_id = canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        body.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind(
            "<Configure>",
            lambda event: canvas.itemconfigure(window_id, width=event.width),
        )

        if self.review.unsupported_conflicts:
            blocker = ttk.LabelFrame(body, text="Cannot safely merge yet", padding=10)
            blocker.pack(fill="x", pady=(0, 10))
            ttk.Label(
                blocker,
                text=(
                    "The records contain conflicting state that this review model cannot resolve "
                    "without inventing semantics. Keep the records separate for now."
                ),
                foreground="#B00020",
                wraplength=940,
            ).pack(anchor="w", pady=(0, 6))
            for item in self.review.unsupported_conflicts:
                ttk.Label(blocker, text=f"• {item}", wraplength=930).pack(anchor="w", pady=1)

        safe = ttk.LabelFrame(body, text="State that can be preserved safely", padding=10)
        safe.pack(fill="x", pady=(0, 10))
        if self.review.safe_combination_notes:
            for item in self.review.safe_combination_notes:
                ttk.Label(safe, text=f"• {item}", wraplength=930).pack(anchor="w", pady=1)
        else:
            ttk.Label(
                safe,
                text="No automatically combined user/local state was detected.",
                foreground="gray",
            ).pack(anchor="w")

        conflicts = ttk.LabelFrame(body, text="User-owned conflicts", padding=10)
        conflicts.pack(fill="x", pady=(0, 10))
        if not self.review.field_conflicts:
            ttk.Label(conflicts, text="No conflicting user-owned values require a choice.").pack(anchor="w")
        for conflict in self.review.field_conflicts:
            row = ttk.Frame(conflicts)
            row.pack(fill="x", pady=(0, 10))
            ttk.Label(row, text=conflict.label, font=("Segoe UI", 10, "bold")).pack(anchor="w")
            var = tk.StringVar(value="")
            self._field_vars[conflict.field] = var
            source_text = _format_value(conflict.source_value)
            target_text = _format_value(conflict.target_value)
            ttk.Radiobutton(
                row,
                text=f"Keep source (SMWC {source.smwc_submission_id}): {source_text}",
                value=MergeValueOrigin.SOURCE.value,
                variable=var,
            ).pack(anchor="w", padx=(12, 0), pady=(3, 1))
            ttk.Radiobutton(
                row,
                text=f"Keep target (SMWC {target.smwc_submission_id}): {target_text}",
                value=MergeValueOrigin.TARGET.value,
                variable=var,
            ).pack(anchor="w", padx=(12, 0), pady=1)

        roms = ttk.LabelFrame(body, text="Primary ROM after merge", padding=10)
        roms.pack(fill="x", pady=(0, 10))
        self._primary_var = tk.StringVar(value="")
        if not self.review.primary_rom_choices:
            ttk.Label(roms, text="Neither record currently has a primary ROM path.").pack(anchor="w")
        elif self.review.primary_rom_required:
            ttk.Label(
                roms,
                text="Both records have different primary ROMs. Choose which one remains primary; both paths are retained.",
                wraplength=930,
            ).pack(anchor="w", pady=(0, 5))
        else:
            self._primary_var.set(self.review.primary_rom_choices[0].path)
            ttk.Label(
                roms,
                text="Only one primary ROM choice is present; it will remain primary if this merge proceeds later.",
                wraplength=930,
            ).pack(anchor="w", pady=(0, 5))
        for item in self.review.primary_rom_choices:
            label = "source" if item.origin is MergeValueOrigin.SOURCE else "target"
            ttk.Radiobutton(
                roms,
                text=f"{label.title()} primary: {item.path}",
                value=item.path,
                variable=self._primary_var,
            ).pack(anchor="w", padx=(12, 0), pady=1)

        footer = ttk.Frame(outer)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(
            footer,
            text=(
                "Saving these choices only retains a detached merge decision for the next bounded "
                "planning step. Nothing is applied."
            ),
            foreground="gray",
            wraplength=720,
        ).pack(side="left", anchor="w")
        ttk.Button(footer, text="Keep Separate / Close", command=self.close).pack(side="right")
        save = ttk.Button(footer, text="Save Merge Review", command=self._save)
        save.pack(side="right", padx=(0, 8))
        if self.review.unsupported_conflicts:
            save.state(["disabled"])

        try:
            self.win.grab_set()
        except tk.TclError:
            pass
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
        self.win = None
        if self.on_close:
            self.on_close()

    def _save(self):
        origins = {field: var.get().strip() for field, var in self._field_vars.items()}
        primary = self._primary_var.get().strip() if self._primary_var is not None else ""
        try:
            decision = finalize_collection_update_existing_target_merge_decision(
                self.review,
                field_origins=origins,
                primary_rom_path=primary,
            )
        except CollectionUpdateMergeReviewError as error:
            messagebox.showinfo("Complete Merge Review", str(error), parent=self.win)
            return
        accepted = True
        if self.on_save:
            accepted = self.on_save(self.review, decision) is not False
        if accepted:
            self.close()

    def _center(self):
        try:
            self.win.update_idletasks()
            width = self.win.winfo_width()
            height = self.win.winfo_height()
            x = self.parent.winfo_rootx() + max(0, (self.parent.winfo_width() - width) // 2)
            y = self.parent.winfo_rooty() + max(0, (self.parent.winfo_height() - height) // 2)
            self.win.geometry(f"+{x}+{y}")
        except (tk.TclError, AttributeError):
            pass


def _format_value(value):
    if value in (None, ""):
        return "(empty)"
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


__all__ = ["CollectionUpdateMergeReviewDialog"]
