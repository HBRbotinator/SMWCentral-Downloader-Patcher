"""Explicit review UI for handling a newly downloaded same-ID current ROM."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from collection_update_current_refresh import CurrentRomDisposition
from collection_update_current_rom_disposition import CurrentRomDispositionReview
from ui.window_positioning import center_window_on_parent


class CollectionCurrentRomDispositionDialog:
    """Read-only ROM evidence + explicit Replace/Keep Both decision."""

    def __init__(self, parent, review, *, on_save=None, on_close=None):
        if not isinstance(review, CurrentRomDispositionReview):
            raise TypeError("review must be CurrentRomDispositionReview")
        self.parent = parent
        self.review = review
        self.on_save = on_save
        self.on_close = on_close
        self.win = None
        self.disposition_var = None
        self.primary_var = None
        self.primary_frame = None
        self.save_button = None
        self._closed = False

    @property
    def is_open(self):
        try:
            return bool(self.win and self.win.winfo_exists())
        except tk.TclError:
            return False

    def show(self):
        if self.is_open:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
            return self.win
        self.win = tk.Toplevel(self.parent)
        self.win.title("Choose How to Handle the Downloaded ROM")
        self.win.geometry("820x610")
        self.win.minsize(700, 500)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(
            root,
            text="Choose how to handle the downloaded ROM",
            font=("Segoe UI", 14, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "This is an explicit storage/primary-ROM choice only. The application does not infer "
                "which ROM is newer from SMWC IDs, filenames, or hashes."
            ),
            wraplength=760,
        ).pack(anchor="w", pady=(4, 10))

        options = ttk.LabelFrame(root, text="ROM handling", padding=10)
        options.pack(fill="x")
        self.disposition_var = tk.StringVar(value="")
        replace = ttk.Radiobutton(
            options,
            text="Replace current ROM — keep the existing primary filename/path",
            variable=self.disposition_var,
            value=CurrentRomDisposition.REPLACE_CURRENT.value,
            command=self._choice_changed,
        )
        replace.pack(anchor="w")
        if not self.review.can_replace_current:
            replace.configure(state="disabled")
            ttk.Label(
                options,
                text="Replace is unavailable because there is no verified current primary ROM to replace.",
                foreground="gray",
            ).pack(anchor="w", padx=(22, 0), pady=(0, 6))
        ttk.Radiobutton(
            options,
            text="Keep both — retain existing ROMs and add the downloaded ROM",
            variable=self.disposition_var,
            value=CurrentRomDisposition.KEEP_BOTH.value,
            command=self._choice_changed,
        ).pack(anchor="w", pady=(6, 0))

        self.primary_frame = ttk.LabelFrame(root, text="Primary ROM when keeping both", padding=8)
        self.primary_frame.pack(fill="both", expand=True, pady=(10, 0))
        ttk.Label(
            self.primary_frame,
            text=(
                "Keep Both requires a primary choice. The downloaded ROM is preselected as a convenience "
                "because you initiated this update; that is not a version-ordering inference."
            ),
            wraplength=740,
        ).pack(anchor="w", pady=(0, 6))
        self.primary_var = tk.StringVar(value=self.review.downloaded_default_primary_path)

        table_frame = ttk.Frame(self.primary_frame)
        table_frame.pack(fill="both", expand=True)
        canvas = tk.Canvas(table_frame, highlightthickness=0, height=240)
        scrollbar = ttk.Scrollbar(table_frame, orient="vertical", command=canvas.yview)
        rows = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=rows, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        rows.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))

        for choice in self.review.choices:
            flags = []
            if choice.downloaded:
                flags.append("Downloaded")
            if choice.current_primary:
                flags.append("Current primary")
            label = choice.filename
            if flags:
                label += "  [" + ", ".join(flags) + "]"
            row = ttk.Frame(rows)
            row.pack(fill="x", pady=2)
            radio = ttk.Radiobutton(
                row,
                text=label,
                variable=self.primary_var,
                value=choice.path,
                command=self._choice_changed,
            )
            radio.pack(anchor="w")
            ttk.Label(row, text=choice.path, foreground="gray", wraplength=690).pack(
                anchor="w", padx=(24, 0)
            )

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(12, 0))
        ttk.Button(footer, text="Cancel", command=self.close).pack(side="right")
        self.save_button = ttk.Button(footer, text="Save ROM Choice", command=self._save)
        self.save_button.pack(side="right", padx=(0, 8))
        self._choice_changed()
        center_window_on_parent(self.win, self.parent)
        return self.win

    def _choice_changed(self):
        if self.save_button is None:
            return
        disposition = self.disposition_var.get() if self.disposition_var else ""
        valid = disposition in {
            CurrentRomDisposition.REPLACE_CURRENT.value,
            CurrentRomDisposition.KEEP_BOTH.value,
        }
        if disposition == CurrentRomDisposition.REPLACE_CURRENT.value:
            valid = valid and self.review.can_replace_current
        elif disposition == CurrentRomDisposition.KEEP_BOTH.value:
            valid = valid and bool(self.primary_var and self.primary_var.get())
        self.save_button.configure(state="normal" if valid else "disabled")

    def _save(self):
        if self.on_save is None:
            return False
        raw = self.disposition_var.get() if self.disposition_var else ""
        try:
            disposition = CurrentRomDisposition(raw)
        except ValueError:
            messagebox.showerror(
                "Choose ROM Handling",
                "Choose Replace current ROM or Keep both before saving.",
                parent=self.win,
            )
            return False
        primary = ""
        if disposition is CurrentRomDisposition.KEEP_BOTH:
            primary = self.primary_var.get() if self.primary_var else ""
            if not primary:
                messagebox.showerror(
                    "Choose Primary ROM",
                    "Keep Both requires a primary ROM choice.",
                    parent=self.win,
                )
                return False
        accepted = self.on_save(disposition, primary)
        if accepted is False:
            return False
        self.close()
        return True

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            if self.win and self.win.winfo_exists():
                self.win.destroy()
        except tk.TclError:
            pass
        self.win = None
        if self.on_close:
            self.on_close()


__all__ = ["CollectionCurrentRomDispositionDialog"]
