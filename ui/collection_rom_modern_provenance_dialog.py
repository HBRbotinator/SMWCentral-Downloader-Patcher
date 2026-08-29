"""Explicit read-only provenance choices for modern ROM assets missing SMWC ownership."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from collection_rom_modern_provenance_review import (
    ModernRomProvenanceReview,
    ModernRomProvenanceReviewError,
    build_modern_rom_provenance_decision,
)


class CollectionRomModernProvenanceDialog:
    def __init__(self, parent, review: ModernRomProvenanceReview, on_close=None, on_saved=None, on_apply=None):
        self.review = review
        self._on_close = on_close
        self._on_saved = on_saved
        self._on_apply = on_apply
        self._saved_decision = None
        self._closed = False
        self._vars: dict[tuple[str, str], tk.StringVar] = {}
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Modern ROM Provenance Review")
        self.dialog.geometry("940x650")
        self.dialog.minsize(740, 500)
        self.dialog.transient(parent)
        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Modern ROM Provenance Review", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Choose which already-recorded SMWC submission owns each modern ROM whose files[] row "
                "is missing per-ROM provenance. No provider lookup, hashing, Collection write, or file "
                "operation occurs in this review."
            ),
            wraplength=880,
            justify="left",
        ).pack(anchor="w", pady=(4, 12))

        canvas = tk.Canvas(outer, highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        body = ttk.Frame(canvas)
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=body, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        for index, row in enumerate(self.review.rows):
            frame = ttk.LabelFrame(body, text=row.title, padding=10)
            frame.grid(row=index, column=0, sticky="ew", pady=(0, 10))
            body.grid_columnconfigure(0, weight=1)
            ttk.Label(frame, text=f"ROM: {row.asset_name}", wraplength=800, justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
            ttk.Label(frame, text=row.current_path, wraplength=800, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(2, 0))
            ttk.Label(frame, text="ROM belongs to:").grid(row=2, column=0, sticky="w", pady=(8, 0))
            var = tk.StringVar(value="")
            self._vars[row.decision_key] = var
            values = [f"SMWC {value}" for value in row.candidate_smwc_submission_ids]
            ttk.Combobox(frame, textvariable=var, values=values, state="readonly", width=24).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
            ttk.Label(
                frame,
                text=(
                    f"Current Collection ID: SMWC {row.current_smwc_submission_id}. "
                    "Choices come only from the current ID and recorded prior/migration history."
                ),
                wraplength=800,
                justify="left",
            ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        self._apply_button = ttk.Button(buttons, text="Apply Provenance Repair...", command=self._apply, state="disabled")
        self._apply_button.pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Save Provenance Decisions", command=self._save).pack(side="right", padx=(0, 8))

    def _save(self):
        selections = {}
        for row in self.review.rows:
            text = self._vars[row.decision_key].get().strip()
            if text.startswith("SMWC "):
                selections[row.decision_key] = int(text[5:])
        try:
            decision = build_modern_rom_provenance_decision(self.review, selections)
        except ModernRomProvenanceReviewError as error:
            messagebox.showerror("Modern ROM Provenance", str(error), parent=self.dialog)
            return
        self._saved_decision = decision
        if self._on_saved is not None:
            self._on_saved(self.review, decision)
        if self._on_apply is not None:
            self._apply_button.configure(state="normal")
        messagebox.showinfo(
            "Provenance Decisions Saved",
            (
                "The decisions are retained only for this active review. Collection metadata and ROM files "
                "have not changed. Use Apply Provenance Repair only when you are ready to write the reviewed "
                "smwc_submission_id values."
            ),
            parent=self.dialog,
        )

    def _apply(self):
        if self._on_apply is not None and self._saved_decision is not None:
            self._on_apply(self.review, self._saved_decision, self.dialog)

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
