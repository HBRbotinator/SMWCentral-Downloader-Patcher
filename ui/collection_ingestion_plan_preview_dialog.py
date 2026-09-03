"""Final Tk preview and explicit Apply confirmation for Collection ingestion."""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from collection_ingestion_plan_preview import CollectionIngestionPlanPreviewModel
from ui.window_positioning import center_window_on_parent, reveal_window_on_parent


class CollectionIngestionPlanPreviewDialog:
    """Show the finalized plan and require explicit confirmation before Apply."""

    def __init__(self, parent, plan, *, on_apply=None, on_close=None):
        self.parent = parent
        self.model = CollectionIngestionPlanPreviewModel(plan)
        self.on_apply = on_apply
        self.on_close = on_close
        self.win = None
        self.tree = None
        self.summary_label = None
        self.details = None
        self._rows = ()
        self.apply_button = None
        self.close_button = None
        self._closed = False
        self._applying = False

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

        self.win = tk.Toplevel(self.parent)
        self.win.title("Final Collection Import Preview")
        self.win.geometry("1200x720")
        self.win.minsize(940, 580)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(
            root,
            text="Final Collection Import Preview",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "This preview is generated directly from the finalized immutable "
                "Collection change plan. Rich KaizOFF details have already been "
                "hydrated where required. Review it before explicitly applying "
                "these exact planned changes."
            ),
            wraplength=1080,
        ).pack(anchor="w", pady=(3, 8))

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
        horizontal = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.tree.xview,
        )
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
                "Nothing has been applied yet. Apply updates Collection and any "
                "planned dependent references transactionally; ROM/save files are "
                "not moved, renamed, or deleted by ingestion."
            ),
            foreground="gray",
            wraplength=900,
        ).pack(side="left", anchor="w")
        self.close_button = ttk.Button(
            footer,
            text="Close Preview",
            command=self.close,
        )
        self.close_button.pack(side="right")
        self.apply_button = ttk.Button(
            footer,
            text="Apply Import...",
            command=self._request_apply,
        )
        self.apply_button.pack(side="right", padx=(0, 8))
        if self.on_apply is None:
            self.apply_button.configure(state="disabled")

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

    def _request_apply(self):
        if self._applying or self.on_apply is None:
            return False
        summary = self.model.summary()
        confirmed = messagebox.askyesno(
            "Apply Collection Import",
            (
                "Apply exactly the finalized changes shown in this preview?\n\n"
                f"{summary.creates} create(s), {summary.updates} update(s), "
                f"{summary.identity_migrations} identity migration(s), and "
                f"{summary.rom_assets} ROM asset change(s) are planned.\n\n"
                "Collection metadata and planned dependent references will be "
                "written transactionally. Ingestion will not move, rename, or "
                "delete ROM/save files."
            ),
            icon="warning",
            parent=self.win or self.parent,
        )
        if not confirmed:
            return False
        accepted = bool(self.on_apply())
        if accepted:
            self.set_applying(True)
        return accepted

    def set_applying(self, applying=True):
        self._applying = bool(applying)
        state = "disabled" if self._applying else "normal"
        if self.apply_button is not None:
            self.apply_button.configure(state=state)
        if self.close_button is not None:
            self.close_button.configure(state=state)

    def _populate(self):
        summary = self.model.summary()
        stores = ", ".join(summary.dependent_stores) or "none"
        self.summary_label.configure(
            text=(
                f"{summary.creates} create(s) · {summary.updates} update(s) · "
                f"{summary.identity_migrations} identity migration(s) · "
                f"{summary.rom_assets} ROM asset(s) · "
                f"{summary.imported_playthroughs} playthrough(s) · "
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
            for value in (
                row.category,
                row.target,
                row.change,
                row.details,
            )
            if value
        )
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _center(self):
        center_window_on_parent(self.win, self.parent)
class CollectionIngestionApplyProgressDialog:
    """Modal progress while the finalized plan crosses the transactional boundary."""

    def __init__(self, parent, *, recovery=False):
        self.parent = parent
        self.recovery = bool(recovery)
        self.win = None

    def show(self):
        if self.win:
            return self.win
        self.win = tk.Toplevel(self.parent)
        self.win.withdraw()
        self.win.title(
            "Recovering Collection Import"
            if self.recovery
            else "Applying Collection Import"
        )
        self.win.resizable(False, False)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        body = ttk.Frame(self.win, padding=18)
        body.pack(fill="both", expand=True)
        heading = (
            "Recovering interrupted Collection transaction..."
            if self.recovery
            else "Applying finalized Collection changes..."
        )
        detail = (
            "Restoring or cleaning the existing coordinated transaction journal. "
            "The current import plan will be discarded after recovery."
            if self.recovery
            else
            "Writing Collection and planned dependent reference stores as one "
            "coordinated transaction. Do not close another application instance "
            "over these files while this operation is active."
        )
        ttk.Label(body, text=heading, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(body, text=detail, wraplength=470).pack(
            anchor="w",
            pady=(5, 10),
        )
        progress = ttk.Progressbar(body, mode="indeterminate", length=470)
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

class CollectionIngestionFinalizationProgressDialog:
    """Non-cancellable progress while required detail hydration finalizes a plan."""

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
            text="Finalizing reviewed Collection changes...",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "Fetching only required rich KaizOFF records, rechecking reviewed "
                "store state, and building the immutable change plan. User-owned "
                "Collection and dependent state are not changed."
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


__all__ = [
    "CollectionIngestionFinalizationProgressDialog",
    "CollectionIngestionPlanPreviewDialog",
]
