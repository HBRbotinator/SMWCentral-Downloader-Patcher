"""Guided Tk UI for updating the current SMWC Collection entry."""
from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from collection_update_current_refresh import (
    CurrentRomDisposition,
    FinalizedCurrentSubmissionRefreshPlan,
)
from collection_update_current_refresh_acquisition import (
    finalized_current_refresh_has_acquired_rom,
    finalized_current_refresh_rom_checked,
)
from ui.window_positioning import center_window_on_parent


def _friendly_progress_title(title):
    aliases = {
        "Refresh Current SMWC Submission": "Preparing Update",
        "Acquire Current SMWC ROM": "Downloading ROM",
        "Apply Current SMWC Refresh": "Applying Update",
    }
    return aliases.get(str(title or ""), str(title or "Updating Collection Entry"))


class CollectionCurrentRefreshProgressDialog:
    def __init__(self, parent, *, title="Preparing Update", message="Working..."):
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
    """User-facing guided same-ID update flow."""

    def __init__(
        self,
        parent,
        finalized,
        *,
        on_acquire=None,
        on_review_rom=None,
        on_apply=None,
        on_close=None,
    ):
        if not isinstance(finalized, FinalizedCurrentSubmissionRefreshPlan):
            raise TypeError("finalized must be FinalizedCurrentSubmissionRefreshPlan")
        self.parent = parent
        self.finalized = finalized
        self.on_acquire = on_acquire
        self.on_review_rom = on_review_rom
        self.on_apply = on_apply
        self.on_close = on_close
        self.win = None
        self.update_choice_var = None
        self.continue_button = None
        self.review_rom_button = None
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
        acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
        checked = finalized_current_refresh_rom_checked(self.finalized)
        unresolved_rom_choice = (
            acquired
            and not self.finalized.rom_matches_existing
            and self.finalized.rom_disposition is None
        )

        self.win = tk.Toplevel(self.parent)
        self.win.title(f"Update {source.title}")
        self.win.geometry("820x560")
        self.win.minsize(700, 480)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=16)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text=f"Update {source.title}",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                f"SMWC {source.smwc_submission_id}. This updates the existing Collection entry for "
                "this same SMWC ID; it does not replace it with another submission."
            ),
            wraplength=760,
        ).pack(anchor="w", pady=(4, 10))

        if not checked and not acquired:
            self._build_initial_choice(root)
        elif unresolved_rom_choice:
            self._build_rom_choice_required(root)
        else:
            self._build_ready_summary(root)

        ttk.Label(
            root,
            text=_provider_freshness(self.finalized),
            foreground="gray",
        ).pack(anchor="w", pady=(10, 0))

        footer = ttk.Frame(root)
        footer.pack(side="bottom", fill="x", pady=(14, 0))
        ttk.Label(
            footer,
            text=(
                "Nothing changes in Collection until you apply the update. Your Collection ID, "
                "completion, notes, ratings and other personal Collection data are preserved."
            ),
            foreground="gray",
            wraplength=600,
        ).pack(side="left", anchor="w")
        self.close_button = ttk.Button(footer, text="Cancel", command=self.close)
        self.close_button.pack(side="right")

        center_window_on_parent(self.win, self.parent)
        return self.win

    def _build_initial_choice(self, root):
        available = bool(self.finalized.download_url)
        choice = ttk.LabelFrame(root, text="What would you like to update?", padding=12)
        choice.pack(fill="x")

        self.update_choice_var = tk.StringVar(value="metadata")
        ttk.Radiobutton(
            choice,
            text="Update SMWC information only",
            variable=self.update_choice_var,
            value="metadata",
        ).pack(anchor="w")

        rom_option = ttk.Radiobutton(
            choice,
            text="Update SMWC information and download the ROM offered for this SMWC entry",
            variable=self.update_choice_var,
            value="metadata_rom",
        )
        rom_option.pack(anchor="w", pady=(8, 0))
        if not available or self.on_acquire is None:
            rom_option.configure(state="disabled")
            ttk.Label(
                choice,
                text="A downloadable ROM is not available for this SMWC entry.",
                foreground="gray",
            ).pack(anchor="w", padx=(22, 0), pady=(2, 0))
        else:
            ttk.Label(
                choice,
                text=(
                    "The new ROM is prepared in your Default ROM Output Folder. Existing Collection "
                    "ROMs can live elsewhere and are not moved just because that folder is different."
                ),
                foreground="gray",
                wraplength=720,
            ).pack(anchor="w", padx=(22, 0), pady=(2, 0))

        actions = ttk.Frame(choice)
        actions.pack(fill="x", pady=(14, 0))
        self.continue_button = ttk.Button(
            actions,
            text="Continue",
            command=self._continue_initial_choice,
        )
        self.continue_button.pack(side="right")
        if self.on_apply is None:
            self.continue_button.configure(state="disabled")

    def _build_rom_choice_required(self, root):
        frame = ttk.LabelFrame(root, text="Downloaded ROM", padding=12)
        frame.pack(fill="x")
        ttk.Label(
            frame,
            text=(
                "The downloaded ROM is different from the ROMs already recorded for this Collection "
                "entry. Choose whether to replace your current primary ROM or keep both before applying."
            ),
            wraplength=720,
        ).pack(anchor="w")
        if self.finalized.acquired_default_primary_path:
            ttk.Label(
                frame,
                text=f"Downloaded file: {self.finalized.acquired_default_primary_path}",
                foreground="gray",
                wraplength=720,
            ).pack(anchor="w", pady=(6, 0))
        self.review_rom_button = ttk.Button(
            frame,
            text="Choose What Happens to the ROM...",
            command=self._request_rom_review,
        )
        self.review_rom_button.pack(anchor="e", pady=(12, 0))
        if self.on_review_rom is None:
            self.review_rom_button.configure(state="disabled")

    def _build_ready_summary(self, root):
        frame = ttk.LabelFrame(root, text="Ready to apply", padding=12)
        frame.pack(fill="both", expand=True)

        lines = ["✓ Update the SMWC information for this Collection entry"]
        acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
        checked = finalized_current_refresh_rom_checked(self.finalized)

        if checked and self.finalized.rom_matches_existing:
            lines.append("✓ Download checked: you already have the same ROM bytes, so no duplicate was kept")
        elif acquired and self.finalized.rom_disposition is CurrentRomDisposition.REPLACE_CURRENT:
            replacement = self.finalized.rom_replacement
            if replacement is not None:
                lines.append("✓ Replace your current primary ROM while keeping its existing filename and location")
                lines.append(f"  {replacement.target_path}")
            else:
                lines.append("✓ Replace your current primary ROM at its existing filename and location")
        elif acquired and self.finalized.rom_disposition is CurrentRomDisposition.KEEP_BOTH:
            lines.append("✓ Keep the existing ROMs and the downloaded ROM")
            if self.finalized.reviewed_primary_path:
                lines.append(f"✓ Use this ROM as primary: {self.finalized.reviewed_primary_path}")

        ttk.Label(
            frame,
            text="\n".join(lines),
            wraplength=720,
            justify="left",
        ).pack(anchor="w", fill="x")

        if acquired and not self.finalized.rom_matches_existing and self.on_review_rom is not None:
            self.review_rom_button = ttk.Button(
                frame,
                text="Change ROM Choice...",
                command=self._request_rom_review,
            )
            self.review_rom_button.pack(anchor="w", pady=(12, 0))

        self.apply_button = ttk.Button(frame, text="Apply Update", command=self._request_apply)
        self.apply_button.pack(anchor="e", pady=(14, 0))
        if self.on_apply is None:
            self.apply_button.configure(state="disabled")

    def _continue_initial_choice(self):
        if self._busy:
            return False
        choice = self.update_choice_var.get() if self.update_choice_var else "metadata"
        if choice == "metadata_rom":
            return self._request_acquire()
        return self._request_apply()

    def _request_acquire(self):
        if self._busy or self.on_acquire is None:
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

    def _request_rom_review(self):
        if self._busy or self.on_review_rom is None:
            return False
        return self.on_review_rom()

    def _request_apply(self):
        if self._busy or self.on_apply is None:
            return False

        source = self.finalized.source_entry
        acquired = finalized_current_refresh_has_acquired_rom(self.finalized)
        if acquired and self.finalized.rom_disposition is CurrentRomDisposition.REPLACE_CURRENT:
            action_text = (
                "The SMWC information will be updated and the reviewed downloaded ROM will replace "
                "your current primary ROM at the same filename and location."
            )
        elif acquired and self.finalized.rom_disposition is CurrentRomDisposition.KEEP_BOTH:
            action_text = (
                "The SMWC information will be updated, both ROMs will be kept, and your reviewed "
                "primary ROM choice will be used."
            )
        elif finalized_current_refresh_rom_checked(self.finalized) and self.finalized.rom_matches_existing:
            action_text = (
                "The SMWC information will be updated. The downloaded check matched ROM bytes you "
                "already have, so no ROM file will be added or replaced."
            )
        else:
            action_text = "The SMWC information will be updated. No ROM file will be downloaded or changed."

        confirmed = messagebox.askyesno(
            "Apply Update",
            (
                f"Update {source.title} (SMWC {self.finalized.source_collection_key})?\n\n"
                f"{action_text}\n\n"
                "Your Collection ID and personal Collection data are preserved."
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
        if self.continue_button:
            self.continue_button.configure(state=state if self.on_apply is not None else "disabled")
        if self.apply_button:
            unresolved_rom_choice = (
                finalized_current_refresh_has_acquired_rom(self.finalized)
                and not self.finalized.rom_matches_existing
                and self.finalized.rom_disposition is None
            )
            self.apply_button.configure(
                state=(state if self.on_apply is not None and not unresolved_rom_choice else "disabled")
            )
        if self.review_rom_button:
            if self._busy or self.on_review_rom is None:
                self.review_rom_button.configure(state="disabled")
            else:
                self.review_rom_button.configure(state="normal")

    def lift(self):
        if self.is_open:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()

    def close(self):
        # Programmatic close must always be able to retire the old preview after an
        # asynchronous Download/Apply finishes. Do not block this on `_busy`.
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
    stale = " · cached fallback" if finalized.detail_stale else ""
    return f"SMWC information checked {timestamp}{stale}"


__all__ = [
    "CollectionCurrentRefreshPreviewDialog",
    "CollectionCurrentRefreshProgressDialog",
]
