"""Explicit read-only provenance choices for ambiguous legacy ROM paths."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from collection_rom_legacy_provenance_review import (
    LegacyRomProvenanceReview,
    LegacyRomProvenanceReviewError,
    build_legacy_rom_provenance_decision,
)


class CollectionRomLegacyProvenanceDialog:
    def __init__(self, parent, review: LegacyRomProvenanceReview, on_close=None, on_saved=None, on_preview_plan=None):
        self.review = review
        self._on_close = on_close
        self._on_saved = on_saved
        self._on_preview_plan = on_preview_plan
        self._saved_decision = None
        self._closed = False
        self._vars: dict[str, tk.StringVar] = {}
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("Legacy ROM Provenance Review")
        self.dialog.geometry("900x620")
        self.dialog.minsize(720, 480)
        self.dialog.transient(parent)
        self._build()
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.grab_set()

    def _build(self):
        outer = ttk.Frame(self.dialog, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Legacy ROM Provenance Review", font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text=(
                "Choose which already-recorded SMWC submission owns each legacy ROM. "
                "The app does not infer the answer, contact KaizOFF, hash ROMs, or write Collection data here."
            ),
            wraplength=850,
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
            ttk.Label(frame, text=row.current_path, wraplength=760, justify="left").grid(row=0, column=0, columnspan=2, sticky="w")
            ttk.Label(frame, text="ROM belongs to:").grid(row=1, column=0, sticky="w", pady=(8, 0))
            var = tk.StringVar(value="")
            self._vars[row.collection_id] = var
            values = [f"SMWC {value}" for value in row.candidate_smwc_submission_ids]
            combo = ttk.Combobox(frame, textvariable=var, values=values, state="readonly", width=24)
            combo.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
            ttk.Label(
                frame,
                text=(
                    f"Current Collection ID: SMWC {row.current_smwc_submission_id}. "
                    "Alternatives come only from recorded prior/migration history."
                ),
                wraplength=760,
                justify="left",
            ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        self._preview_button = ttk.Button(
            buttons,
            text="Preview Modernization Plan...",
            command=self._preview_plan,
            state="disabled",
        )
        if self._on_preview_plan is not None:
            self._preview_button.pack(side="right", padx=(0, 8))
        ttk.Button(buttons, text="Save Provenance Decisions", command=self._save).pack(side="right", padx=(0, 8))

    def _save(self):
        selections = {}
        for row in self.review.rows:
            text = self._vars[row.collection_id].get().strip()
            if text.startswith("SMWC "):
                selections[row.collection_id] = int(text[5:])
        try:
            decision = build_legacy_rom_provenance_decision(self.review, selections)
        except LegacyRomProvenanceReviewError as error:
            messagebox.showerror("Legacy ROM Provenance", str(error), parent=self.dialog)
            return
        self._saved_decision = decision
        if self._on_preview_plan is not None:
            self._preview_button.configure(state="normal")
        if self._on_saved is not None:
            self._on_saved(self.review, decision)
        messagebox.showinfo(
            "Provenance Decisions Saved",
            (
                "The decisions are retained only for this active review. Collection metadata and ROM files "
                "have not changed. A later explicit modernization-plan boundary will consume them."
            ),
            parent=self.dialog,
        )


    def _preview_plan(self):
        if self._on_preview_plan is not None and self._saved_decision is not None:
            self._on_preview_plan(self.review, self._saved_decision)

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
