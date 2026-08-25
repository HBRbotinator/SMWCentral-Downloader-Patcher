"""Read-only preview for a finalized explicit SMWC replacement plan."""
from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import ttk

from collection_ingestion_plan_preview import CollectionIngestionPlanPreviewModel
from collection_update_plan import FinalizedCollectionUpdatePlan


class CollectionUpdatePlanPreviewDialog:
    """Show the exact replacement plan while deliberately withholding Apply."""

    def __init__(self, parent, finalized, *, on_close=None):
        if not isinstance(finalized, FinalizedCollectionUpdatePlan):
            raise TypeError("finalized must be FinalizedCollectionUpdatePlan")
        self.parent = parent
        self.finalized = finalized
        self.model = CollectionIngestionPlanPreviewModel(finalized.plan)
        self.on_close = on_close
        self.win = None
        self.tree = None
        self.details = None
        self.summary_label = None
        self._rows = ()
        self._closed = False

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

        selection = self.finalized.selection
        source = selection.source_entry
        target = selection.target_entry
        self.win = tk.Toplevel(self.parent)
        self.win.title("SMWC Replacement Plan Preview")
        self.win.geometry("1200x720")
        self.win.minsize(940, 580)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(
            root,
            text="SMWC Replacement Plan Preview",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                f"Explicit relationship: SMWC {source.smwc_submission_id} — {source.title} "
                f"→ SMWC {target.smwc_submission_id} — {target.title}. The application still "
                "does not claim that the target submission is newer; this relationship came "
                "from your explicit confirmation."
            ),
            wraplength=1090,
        ).pack(anchor="w", pady=(3, 5))
        ttk.Label(
            root,
            text=(
                "This immutable plan refreshes the selected target's durable KaizOFF/SMWC "
                "metadata, migrates Collection identity, and repoints participating dependent "
                "references. It does not download or patch the target ROM. Existing ROMs remain "
                "attached; no ROM/save files are moved, renamed, or deleted."
            ),
            foreground="#C47F00",
            wraplength=1090,
        ).pack(anchor="w", pady=(0, 4))
        merge_text = (
            " The target already existed in Collection, so the explicit merge-review choices "
            "are also encoded in this plan."
            if self.finalized.merge_decision is not None
            else ""
        )
        ttk.Label(
            root,
            text=(
                "Commit 016 remains preview-only. This replacement plan cannot be applied from "
                "this dialog yet." + merge_text
            ),
            foreground="gray",
            wraplength=1090,
        ).pack(anchor="w", pady=(0, 7))

        provider_text = _provider_freshness(self.finalized)
        ttk.Label(root, text=provider_text).pack(anchor="w", pady=(0, 8))

        self.summary_label = ttk.Label(root, font=("Segoe UI", 10, "bold"))
        self.summary_label.pack(anchor="w", pady=(0, 8))

        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True)
        columns = ("category", "target", "change", "details")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "category": "Category",
            "target": "Target",
            "change": "Planned change",
            "details": "Details",
        }
        widths = {
            "category": 115,
            "target": 230,
            "change": 245,
            "details": 520,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=80, anchor="w")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)

        details_frame = ttk.LabelFrame(root, text="Selected change", padding=8)
        details_frame.pack(fill="x", pady=(10, 0))
        self.details = tk.Text(details_frame, height=4, wrap="word")
        self.details.pack(fill="x")
        self.details.configure(state="disabled")

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(
            footer,
            text=(
                "No Collection, Planner, Save Sync, identity-hint, ROM, or save data is changed "
                "by this preview."
            ),
            foreground="gray",
            wraplength=880,
        ).pack(side="left", anchor="w")
        ttk.Button(footer, text="Close Preview", command=self.close).pack(side="right")

        self._populate()
        self._center()
        return self.win

    def lift(self):
        if self.is_open:
            self.win.lift()
            self.win.focus_force()

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

    def _populate(self):
        summary = self.model.summary()
        stores = ", ".join(summary.dependent_stores) or "none"
        self.summary_label.configure(
            text=(
                f"{summary.creates} create(s) · {summary.updates} update(s) · "
                f"{summary.identity_migrations} identity migration(s) · "
                f"{summary.rom_assets} ROM asset operation(s) · "
                f"{summary.primary_rom_selections} primary-ROM selection(s) · "
                f"dependent stores: {stores}"
            )
        )
        self._rows = self.model.rows()
        for index, row in enumerate(self._rows):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(row.category, row.target, row.change, row.details),
            )
        if self._rows:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._render_details(0)

    def _selection_changed(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            return
        try:
            index = int(selected[0])
        except (TypeError, ValueError):
            return
        self._render_details(index)

    def _render_details(self, index):
        if index < 0 or index >= len(self._rows):
            return
        row = self._rows[index]
        text = "\n".join(
            value
            for value in (row.category, row.target, row.change, row.details)
            if value
        )
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _center(self):
        try:
            self.win.update_idletasks()
            width = self.win.winfo_width()
            height = self.win.winfo_height()
            x = self.parent.winfo_rootx() + max(
                0,
                (self.parent.winfo_width() - width) // 2,
            )
            y = self.parent.winfo_rooty() + max(
                0,
                (self.parent.winfo_height() - height) // 2,
            )
            self.win.geometry(f"+{x}+{y}")
        except (tk.TclError, AttributeError):
            pass


class CollectionUpdatePlanProgressDialog:
    """Modal progress while the explicitly selected target detail is hydrated."""

    def __init__(self, parent):
        self.parent = parent
        self.win = None

    def show(self):
        if self.win:
            return self.win
        self.win = tk.Toplevel(self.parent)
        self.win.title("Preparing SMWC Replacement Preview")
        self.win.resizable(False, False)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        body = ttk.Frame(self.win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Hydrating the selected SMWC submission...",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "Fetching only the rich metadata for the SMWC ID you explicitly selected, then "
                "building an immutable read-only replacement plan. Nothing is applied."
            ),
            wraplength=480,
        ).pack(anchor="w", pady=(5, 10))
        progress = ttk.Progressbar(body, mode="indeterminate", length=480)
        progress.pack(fill="x")
        progress.start(12)
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        self._center()
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

    def _center(self):
        try:
            self.win.update_idletasks()
            x = self.parent.winfo_rootx() + max(
                0,
                (self.parent.winfo_width() - self.win.winfo_width()) // 2,
            )
            y = self.parent.winfo_rooty() + max(
                0,
                (self.parent.winfo_height() - self.win.winfo_height()) // 2,
            )
            self.win.geometry(f"+{x}+{y}")
        except (tk.TclError, AttributeError):
            pass


def _provider_freshness(finalized):
    try:
        timestamp = datetime.fromtimestamp(finalized.detail_fetched_at).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (OSError, OverflowError, ValueError):
        timestamp = str(finalized.detail_fetched_at)
    stale = " · STALE CACHE FALLBACK" if finalized.detail_stale else ""
    return f"Rich KaizOFF target detail: {finalized.detail_source} · {timestamp}{stale}"


__all__ = [
    "CollectionUpdatePlanPreviewDialog",
    "CollectionUpdatePlanProgressDialog",
]
