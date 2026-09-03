"""Plain-language scan scope for a newly selected Save Data Sync folder."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ui.window_positioning import reveal_window_on_parent


def ask_include_save_subfolders(parent, directory):
    """Return True/False for the folder scope, or None when cancelled."""
    win = tk.Toplevel(parent)
    win.withdraw()
    win.title("Add Save Folder")
    win.transient(parent)
    win.resizable(False, False)
    result = None
    previous_grab = parent.grab_current()

    def finish(value):
        nonlocal result
        result = value
        win.destroy()

    win.protocol("WM_DELETE_WINDOW", lambda: finish(None))
    win.bind("<Escape>", lambda _event: finish(None))
    body = ttk.Frame(win, padding=18)
    body.pack(fill="both", expand=True)
    wrap = max(240, min(480, parent.winfo_screenwidth() - 100))
    ttk.Label(
        body, text="Include folders inside this folder?",
        font=("Segoe UI", 12, "bold"), wraplength=wrap,
    ).pack(anchor="w")
    ttk.Label(body, text=str(directory), wraplength=wrap).pack(
        anchor="w", pady=(8, 12)
    )
    ttk.Label(
        body,
        text="Choose where Save Data Sync should look for save files. "
             "You can change this later with Include subfolders.",
        wraplength=wrap,
    ).pack(anchor="w", pady=(0, 10))
    include = tk.BooleanVar(master=win, value=False)
    first = ttk.Radiobutton(
        body, text="Only this folder", variable=include, value=False,
    )
    first.pack(anchor="w")
    ttk.Radiobutton(
        body, text="This folder and all folders inside it", variable=include, value=True,
    ).pack(anchor="w", pady=(6, 0))
    buttons = ttk.Frame(body)
    buttons.pack(fill="x", pady=(16, 0))
    ttk.Button(buttons, text="Cancel", command=lambda: finish(None)).pack(side="left")
    ttk.Button(
        buttons, text="Add Folder", style="Accent.TButton",
        command=lambda: finish(bool(include.get())),
    ).pack(side="right")
    reveal_window_on_parent(win, parent, grab=True)
    first.focus_set()
    try:
        parent.wait_window(win)
    finally:
        if previous_grab is not None:
            try:
                if previous_grab.winfo_exists():
                    previous_grab.grab_set()
            except tk.TclError:
                pass
    return result
