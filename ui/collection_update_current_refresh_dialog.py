"""Tk preview/progress UI for updating the current SMWC Collection entry."""
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


def _friendly_progress_title(title):
    aliases = {
        "Refresh Current SMWC Submission": "Update Current Entry",
        "Acquire Current SMWC ROM": "Download Current ROM",
        "Apply Current SMWC Refresh": "Apply Update",
    }
    return aliases.get(str(title or ""), str(title or "Updating Collection Entry"))


class CollectionCurrentRefreshProgressDialog:
    def __init__(self, parent, *, title="Update Current Entry", message="Working..."):
        self.parent = parent
        self.title = _friendly_progress_title(title)
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
    """User-facing same-ID update preview with optional ROM download."""

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
        self.win.title(f"Update {source.title}")
        self.win.geometry("1060x680")
        self.win.minsize(840, 540)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text=f"Update {source.title}",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")

        ttk.Label(
            root,
            text=(
                f"SMWC {source.smwc_submission_id} — {source.title}. "
                "This updates the existing Collection entry for this same SMWC ID. "
                "It does not replace the entry with another submission."
            ),
            wraplength=960,
        ).pack(anchor="w", pady=(4, 8))

        acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
        checked = finalized_current_refresh_rom_checked(self.finalized)

        choice = ttk.LabelFrame(root, text="Choose what to update", padding=10)
        choice.pack(fill="x", pady=(0, 10))

        if acquired:
            choice_text = (
                "The current ROM has been downloaded and patched successfully. "
                "Applying the update will refresh the SMWC information and add the downloaded ROM "
                "alongside the ROMs already in Collection; the downloaded ROM will be selected as primary."
            )
        elif checked and self.finalized.rom_matches_existing:
            choice_text = (
                "The current SMWC download matches verified ROM bytes already in Collection, "
                "so no duplicate ROM was kept. You can apply the refreshed SMWC information."
            )
        elif self.finalized.download_url:
            choice_text = (
                "You can apply the refreshed SMWC information only, or download and patch the current ROM "
                "before applying. Downloading prepares the ROM first; it does not change Collection by itself."
            )
        else:
            choice_text = (
                "The refreshed SMWC information is ready to apply. "
                "No current ROM download is available for this entry."
            )

        ttk.Label(choice, text=choice_text, wraplength=920).pack(anchor="w", fill="x")

        actions = ttk.Frame(choice)
        actions.pack(fill="x", pady=(10, 0))

        available = bool(self.finalized.download_url)
        acquire_text = (
            "ROM Downloaded"
            if acquired
            else (
                "ROM Already Matches"
                if checked and self.finalized.rom_matches_existing
                else ("Download Current ROM..." if available else "ROM Download Unavailable")
            )
        )
        self.acquire_button = ttk.Button(actions, text=acquire_text, command=self._request_acquire)
        self.acquire_button.pack(side="left")
        if checked or acquired or not available or self.on_acquire is None:
            self.acquire_button.configure(state="disabled")

        self.apply_button = ttk.Button(actions, text="Apply Update...", command=self._request_apply)
        self.apply_button.pack(side="right")
        if self.on_apply is None:
            self.apply_button.configure(state="disabled")

        ttk.Label(
            root,
            text=_provider_freshness(self.finalized),
            foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        plan_frame = ttk.LabelFrame(root, text="Prepared changes", padding=8)
        plan_frame.pack(fill="both", expand=True)

        frame = ttk.Frame(plan_frame)
        frame.pack(fill="both", expand=True)
        columns = ("category", "target", "change", "details")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        widths = {"category": 110, "target": 210, "change": 230, "details": 430}
        headings = {
            "category": "Area",
            "target": "Collection entry",
            "change": "Change",
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
            text=(
                "Nothing changes until you apply the prepared update. "
                "Your Collection ID and personal Collection data are preserved."
            ),
            foreground="gray",
            wraplength=760,
        ).pack(side="left", anchor="w")

        self.close_button = ttk.Button(footer, text="Close", command=self.close)
        self.close_button.pack(side="right")

        self._populate()
        center_window_on_parent(self.win, self.parent)
        return self.win

    def _populate(self):
        rows = self.model.rows()
        for item in self.tree.get_children():
            self.tree.delete(item)
        for index, row in enumerate(rows):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
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
        source = self.finalized.source_entry
        confirmed = messagebox.askyesno(
            "Download Current ROM",
            (
                f"Download and patch the current ROM for {source.title} "
                f"(SMWC {self.finalized.source_collection_key})?\n\n"
                "The ROM is prepared before anything is applied to Collection. "
                "If the downloaded bytes already match a verified ROM you already have, "
                "the duplicate copy is discarded.\n\n"
                "After the download completes, review the prepared update before applying it."
            ),
            parent=self.win,
        )
        if not confirmed:
            return False

        self.set_busy(True)
        try:
            accepted = self.on_acquire()
        except Exception:
            self.set_busy(False)
            raise
        if accepted is False:
            self.set_busy(False)
        return accepted

    def _request_apply(self):
        if self._busy or self.on_apply is None:
            return False

        source = self.finalized.source_entry
        acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
        if acquired:
            action_text = (
                "The refreshed SMWC information and the downloaded ROM will be added to this "
                "Collection entry. The downloaded ROM will be selected as primary, while existing "
                "ROM entries remain available."
            )
        else:
            action_text = (
                "The refreshed SMWC information will be applied to this Collection entry. "
                "No ROM will be downloaded or changed by this action."
            )

        confirmed = messagebox.askyesno(
            "Apply Update",
            (
                f"Apply the prepared update for {source.title} "
                f"(SMWC {self.finalized.source_collection_key})?\n\n"
                f"{action_text}\n\n"
                "The Collection ID stays the same and personal Collection data is preserved."
            ),
            icon="warning",
            parent=self.win,
        )
        if not confirmed:
            return False

        self.set_busy(True)
        try:
            accepted = self.on_apply()
        except Exception:
            self.set_busy(False)
            raise
        if accepted is False:
            self.set_busy(False)
        return accepted

    def set_busy(self, busy):
        self._busy = bool(busy)
        state = "disabled" if self._busy else "normal"

        if self.close_button:
            self.close_button.configure(state=state)

        if self.apply_button:
            self.apply_button.configure(
                state=state if self.on_apply is not None else "disabled"
            )

        if self.acquire_button:
            acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
            checked = finalized_current_refresh_rom_checked(self.finalized)
            if (
                self._busy
                or checked
                or acquired
                or not self.finalized.download_url
                or self.on_acquire is None
            ):
                self.acquire_button.configure(state="disabled")
            else:
                self.acquire_button.configure(state="normal")

    def lift(self):
        if self.is_open:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()

    def close(self):
        # Programmatic close must always be able to retire the old preview after an
        # async Download/Apply finishes.  The previous `_busy` guard left that
        # preview alive while the caller opened its refreshed replacement.
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


def _provider_freshness(finalized):
    try:
        timestamp = datetime.fromtimestamp(finalized.detail_fetched_at).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (OSError, OverflowError, TypeError, ValueError):
        timestamp = "unknown time"
    stale = " · stale cached fallback" if finalized.detail_stale else ""
    return f"SMWC information via KaizOFF: {finalized.detail_source} · {timestamp}{stale}"


__all__ = [
    "CollectionCurrentRefreshPreviewDialog",
    "CollectionCurrentRefreshProgressDialog",
]
