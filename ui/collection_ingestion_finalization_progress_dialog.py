"""User-facing progress dialog while Collection import review is finalized."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ui.window_positioning import center_window_on_parent


class CollectionIngestionFinalizationProgressDialog:
    """Non-cancellable progress while reviewed choices become the final preview."""

    def __init__(self, parent):
        self.parent = parent
        self.win = None

    def show(self):
        if self.win:
            return self.win

        self.win = tk.Toplevel(self.parent)
        # Keep the window hidden until Tk knows its requested size. This avoids the
        # transient top-left placement seen on Windows for short-lived progress UI.
        self.win.withdraw()
        self.win.title("Preparing Final Collection Preview")
        self.win.resizable(False, False)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        body = ttk.Frame(self.win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Preparing your final Collection preview...",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "Checking your reviewed choices and loading any remaining hack "
                "information needed for the preview. Your Collection is not changed "
                "during this step."
            ),
            wraplength=460,
        ).pack(anchor="w", pady=(5, 10))
        progress = ttk.Progressbar(body, mode="indeterminate", length=460)
        progress.pack(fill="x")
        progress.start(12)

        self.win.update_idletasks()
        center_window_on_parent(self.win, self.parent, lift=False)
        self.win.deiconify()
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        self.win.after_idle(self._center_after_map)
        return self.win

    def _center_after_map(self):
        try:
            if self.win and self.win.winfo_exists():
                center_window_on_parent(self.win, self.parent)
        except tk.TclError:
            pass

    def close(self):
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


__all__ = ["CollectionIngestionFinalizationProgressDialog"]
