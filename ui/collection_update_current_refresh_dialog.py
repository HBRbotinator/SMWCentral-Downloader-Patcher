"""Tk preview/progress UI for refreshing the current SMWC submission in place."""
from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from collection_ingestion_plan_preview import CollectionIngestionPlanPreviewModel
from collection_update_current_refresh import FinalizedCurrentSubmissionRefreshPlan
from collection_update_current_refresh_acquisition import (
    finalized_current_refresh_has_acquired_rom,
    finalized_current_refresh_rom_checked,
)
from ui.window_positioning import center_window_on_parent


class CollectionCurrentRefreshProgressDialog:
    def __init__(self, parent, *, title="Refresh Current SMWC Submission", message="Working..."):
        self.parent = parent
        self.title = title
        self.message = message
        self.win = None

    def show(self):
        if self.win:
            return self.win
        self.win = tk.Toplevel(self.parent)
        self.win.title(self.title)
        self.win.resizable(False, False)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)
        body = ttk.Frame(self.win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=self.title, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(body, text=self.message, wraplength=500).pack(anchor="w", pady=(5, 10))
        progress = ttk.Progressbar(body, mode="indeterminate", length=500)
        progress.pack(fill="x")
        progress.start(12)
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        center_window_on_parent(self.win, self.parent)
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


class CollectionCurrentRefreshPreviewDialog:
    """Read-only same-ID refresh preview with explicit acquisition and Apply actions."""

    def __init__(self, parent, finalized, *, on_acquire=None, on_apply=None, on_close=None):
        if not isinstance(finalized, FinalizedCurrentSubmissionRefreshPlan):
            raise TypeError("finalized must be FinalizedCurrentSubmissionRefreshPlan")
        self.parent = parent
        self.finalized = finalized
        self.model = CollectionIngestionPlanPreviewModel(finalized.plan)
        self.on_acquire = on_acquire
        self.on_apply = on_apply
        self.on_close = on_close
        self.win = None
        self.tree = None
        self.details = None
        self.acquire_button = None
        self.apply_button = None
        self.close_button = None
        self._closed = False
        self._busy = False

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
        source = self.finalized.source_entry
        self.win = tk.Toplevel(self.parent)
        self.win.title("Current SMWC Submission Refresh")
        self.win.geometry("1160x700")
        self.win.minsize(900, 560)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(
            root,
            text="Refresh Current SMWC Submission",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                f"Current Collection identity stays SMWC {source.smwc_submission_id} — {source.title}. "
                "This checks current provider data for that exact submission ID; it is not a replacement "
                "or version-lineage decision."
            ),
            wraplength=1060,
        ).pack(anchor="w", pady=(4, 4))
        acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
        checked = finalized_current_refresh_rom_checked(self.finalized)
        ttk.Label(
            root,
            text=(
                "KaizOFF-owned catalogue metadata is frozen below. "
                + (
                    "A newly patched ROM is also frozen into the plan and will become primary if Apply succeeds; existing ROM assets are retained."
                    if acquired
                    else (
                        "The current download was checked and matches verified ROM bytes already in Collection, so no duplicate ROM was retained."
                        if checked and self.finalized.rom_matches_existing
                        else "You may apply the metadata refresh alone or acquire the current SMWC download first. Existing ROMs are not overwritten."
                    )
                )
            ),
            foreground="#C47F00",
            wraplength=1060,
        ).pack(anchor="w", pady=(0, 4))
        ttk.Label(
            root,
            text=(
                "Apply is network-free and keeps the same Collection key. A same-ID re-download may "
                "produce different ROM bytes if SMWCentral revised the active submission; those bytes "
                "are retained as a new modern ROM asset instead of replacing an existing file on disk."
            ),
            foreground="gray",
            wraplength=1060,
        ).pack(anchor="w", pady=(0, 8))
        ttk.Label(root, text=_provider_freshness(self.finalized)).pack(anchor="w", pady=(0, 8))

        frame = ttk.Frame(root)
        frame.pack(fill="both", expand=True)
        columns = ("category", "target", "change", "details")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        widths = {"category": 115, "target": 220, "change": 245, "details": 500}
        headings = {
            "category": "Category",
            "target": "Target",
            "change": "Planned change",
            "details": "Details",
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=80, anchor="w")
        vbar = ttk.Scrollbar(frame, orient="vertical", command=self.tree.yview)
        hbar = ttk.Scrollbar(frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)

        detail_frame = ttk.LabelFrame(root, text="Selected change", padding=8)
        detail_frame.pack(fill="x", pady=(10, 0))
        self.details = tk.Text(detail_frame, height=4, wrap="word")
        self.details.pack(fill="x")
        self.details.configure(state="disabled")

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(
            footer,
            text="Nothing has been applied yet. Newly acquired files are created before Apply but never overwrite existing ROMs.",
            foreground="gray",
            wraplength=620,
        ).pack(side="left", anchor="w")
        self.close_button = ttk.Button(footer, text="Close Preview", command=self.close)
        self.close_button.pack(side="right")
        self.apply_button = ttk.Button(footer, text="Apply Current Refresh...", command=self._request_apply)
        self.apply_button.pack(side="right", padx=(0, 8))
        if self.on_apply is None:
            self.apply_button.configure(state="disabled")

        available = bool(self.finalized.download_url)
        acquire_text = (
            "Current ROM Acquired"
            if acquired
            else (
                "Current ROM Already Matches"
                if checked and self.finalized.rom_matches_existing
                else ("Acquire Current ROM..." if available else "Current ROM Unavailable")
            )
        )
        self.acquire_button = ttk.Button(footer, text=acquire_text, command=self._request_acquire)
        self.acquire_button.pack(side="right", padx=(0, 8))
        if checked or acquired or not available or self.on_acquire is None:
            self.acquire_button.configure(state="disabled")

        self._populate()
        center_window_on_parent(self.win, self.parent)
        return self.win

    def _populate(self):
        rows = self.model.rows()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, row in enumerate(rows):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(row.category, row.target, row.change, row.details),
            )
        if rows:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._render_detail(0)

    def _selection_changed(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            self._render_detail(None)
            return
        try:
            self._render_detail(int(selected[0]))
        except (TypeError, ValueError):
            self._render_detail(None)

    def _render_detail(self, index):
        text = ""
        rows = self.model.rows()
        if index is not None and 0 <= index < len(rows):
            row = rows[index]
            text = f"{row.category} · {row.target}\n{row.change}\n{row.details}"
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _request_acquire(self):
        if self._busy or self.on_acquire is None:
            return False
        confirmed = messagebox.askyesno(
            "Acquire Current SMWC ROM",
            (
                f"Download and patch the current archive for SMWC {self.finalized.source_collection_key}?\n\n"
                "Existing ROM files are never overwritten. If the normal filename is occupied, "
                "a numbered filename is used. If the downloaded bytes already match a verified "
                "existing ROM, the duplicate copy is discarded.\n\n"
                "Collection state is still unchanged until you review the resulting plan and Apply."
            ),
            parent=self.win,
        )
        if not confirmed:
            return False
        self.set_busy(True)
        accepted = self.on_acquire()
        if accepted is False:
            self.set_busy(False)
        return accepted

    def _request_apply(self):
        if self._busy or self.on_apply is None:
            return False
        acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
        confirmed = messagebox.askyesno(
            "Apply Current SMWC Refresh",
            (
                f"Apply the frozen refresh for SMWC {self.finalized.source_collection_key}?\n\n"
                + (
                    "The newly acquired reviewed ROM will become primary while existing ROM assets are retained. "
                    if acquired else "No new ROM will be downloaded or patched during Apply. "
                )
                + "Collection identity remains unchanged. Apply performs no provider/network work."
            ),
            icon="warning",
            parent=self.win,
        )
        if not confirmed:
            return False
        self.set_busy(True)
        accepted = self.on_apply()
        if accepted is False:
            self.set_busy(False)
        return accepted

    def set_busy(self, busy):
        self._busy = bool(busy)
        state = "disabled" if self._busy else "normal"
        if self.close_button:
            self.close_button.configure(state=state)
        if self.apply_button:
            self.apply_button.configure(state=state if self.on_apply is not None else "disabled")
        if self.acquire_button:
            acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
            checked = finalized_current_refresh_rom_checked(self.finalized)
            if self._busy or checked or acquired or not self.finalized.download_url or self.on_acquire is None:
                self.acquire_button.configure(state="disabled")
            else:
                self.acquire_button.configure(state="normal")

    def lift(self):
        if self.is_open:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()

    def close(self):
        if self._closed or self._busy:
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


def _provider_freshness(finalized):
    try:
        timestamp = datetime.fromtimestamp(finalized.detail_fetched_at).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, TypeError, ValueError):
        timestamp = "unknown time"
    stale = " · stale cached fallback" if finalized.detail_stale else ""
    return f"KaizOFF detail: {finalized.detail_source} · {timestamp}{stale}"


__all__ = [
    "CollectionCurrentRefreshPreviewDialog",
    "CollectionCurrentRefreshProgressDialog",
]
