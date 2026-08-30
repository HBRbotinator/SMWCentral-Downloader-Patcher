"""Shared Tk window placement helpers for Collection workflows."""
from __future__ import annotations

import tkinter as tk


def center_window_on_parent(win, parent, *, lift=True) -> None:
    """Center *win* on *parent* and clamp it to the visible virtual desktop."""

    if win is None or parent is None:
        return
    try:
        win.update_idletasks()
        width = max(1, int(win.winfo_width()))
        height = max(1, int(win.winfo_height()))
        parent_x = int(parent.winfo_rootx())
        parent_y = int(parent.winfo_rooty())
        parent_w = max(1, int(parent.winfo_width()))
        parent_h = max(1, int(parent.winfo_height()))

        x = parent_x + (parent_w - width) // 2
        y = parent_y + (parent_h - height) // 2

        try:
            vx = int(win.winfo_vrootx())
            vy = int(win.winfo_vrooty())
            vw = max(1, int(win.winfo_vrootwidth()))
            vh = max(1, int(win.winfo_vrootheight()))
        except (tk.TclError, AttributeError):
            vx = 0
            vy = 0
            vw = max(1, int(win.winfo_screenwidth()))
            vh = max(1, int(win.winfo_screenheight()))

        max_x = vx + max(0, vw - width)
        max_y = vy + max(0, vh - height)
        x = min(max(x, vx), max_x)
        y = min(max(y, vy), max_y)
        win.geometry(f"+{x}+{y}")
        if lift:
            win.lift()
            win.after_idle(win.lift)
    except (tk.TclError, AttributeError, ValueError):
        pass


__all__ = ["center_window_on_parent"]
