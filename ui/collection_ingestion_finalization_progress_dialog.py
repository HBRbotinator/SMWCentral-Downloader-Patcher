"""User-facing progress dialog while Collection import review is finalized."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ui.window_positioning import reveal_window_on_parent


class CollectionIngestionFinalizationProgressDialog:
    """Non-cancellable progress while reviewed choices become the final preview."""

    def __init__(self, parent):
        self.parent = parent
        self.win = None

    def show(self):
        if self.win:
            return self.win

        self.win = tk.Toplevel(self.parent)
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

        reveal_window_on_parent(self.win, self.parent, grab=True)
        return self.win

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
