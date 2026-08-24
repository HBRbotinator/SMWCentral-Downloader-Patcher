"""Read-only Tk UI for explicit Collection update/replacement discovery."""
from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from collection_update_discovery import (
    CollectionUpdateDiscovery,
    CollectionUpdateSelection,
    RelatedSubmissionCandidate,
    search_collection_update_catalogue,
    select_possible_collection_replacement,
)


class CollectionUpdateDiscoveryProgressDialog:
    """Modal busy window while a current KaizOFF Index snapshot is loaded."""

    def __init__(self, parent):
        self.parent = parent
        self.win = None

    def show(self):
        if self.win:
            return self.win
        self.win = tk.Toplevel(self.parent)
        self.win.title("Finding Possible SMWC Update")
        self.win.resizable(False, False)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)

        body = ttk.Frame(self.win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Checking the KaizOFF catalogue...",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "Loading a current lightweight Index and ranking possible related "
                "SMWC submissions. No Collection, ROM, save, or Planner data is changed."
            ),
            wraplength=460,
        ).pack(anchor="w", pady=(5, 10))
        progress = ttk.Progressbar(body, mode="indeterminate", length=460)
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


class CollectionUpdateDiscoveryDialog:
    """Browse one frozen Index and explicitly choose a possible replacement target."""

    def __init__(self, parent, discovery, *, on_select=None, on_close=None):
        if not isinstance(discovery, CollectionUpdateDiscovery):
            raise TypeError("discovery must be CollectionUpdateDiscovery")
        self.parent = parent
        self.discovery = discovery
        self.on_select = on_select
        self.on_close = on_close
        self.win = None
        self.tree = None
        self.search_var = None
        self.details = None
        self.status_label = None
        self._displayed_entries = ()
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

        source = self.discovery.source_entry
        self.win = tk.Toplevel(self.parent)
        self.win.title("Find Possible SMWC Update / Replacement")
        self.win.geometry("1180x720")
        self.win.minsize(900, 560)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=14)
        root.pack(fill="both", expand=True)
        ttk.Label(
            root,
            text="Find Possible SMWC Update / Replacement",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                f"Current Collection entry: {source.title} (SMWC {source.smwc_submission_id}). "
                "SMWC submission IDs are not permanent logical-version identities, and the "
                "application cannot prove that another submission is newer."
            ),
            wraplength=1100,
        ).pack(anchor="w", pady=(4, 3))
        ttk.Label(
            root,
            text=(
                "Suggestions below are only possibly related catalogue rows. Search the frozen "
                "Index yourself and confirm a relationship only when you recognize it externally."
            ),
            foreground="#C47F00",
            wraplength=1100,
        ).pack(anchor="w", pady=(0, 8))

        freshness = _freshness_text(self.discovery)
        self.status_label = ttk.Label(root, text=freshness)
        self.status_label.pack(anchor="w", pady=(0, 10))

        search = ttk.Frame(root)
        search.pack(fill="x", pady=(0, 8))
        ttk.Label(search, text="Search frozen KaizOFF Index:").pack(side="left")
        self.search_var = tk.StringVar(value="")
        entry = ttk.Entry(search, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True, padx=(8, 6))
        entry.bind("<Return>", self._search)
        ttk.Button(search, text="Search", command=self._search).pack(side="left")
        ttk.Button(search, text="Suggestions", command=self._show_suggestions).pack(
            side="left", padx=(6, 0)
        )

        table_frame = ttk.Frame(root)
        table_frame.pack(fill="both", expand=True)
        columns = ("id", "title", "difficulty", "type", "exits", "collection")
        self.tree = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "id": "SMWC ID",
            "title": "Title",
            "difficulty": "Difficulty",
            "type": "Type",
            "exits": "Exits",
            "collection": "Collection",
        }
        widths = {
            "id": 90,
            "title": 470,
            "difficulty": 120,
            "type": 160,
            "exits": 65,
            "collection": 110,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=55, anchor="w")
        vertical = ttk.Scrollbar(table_frame, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(table_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)

        details_frame = ttk.LabelFrame(root, text="Why this row is shown", padding=8)
        details_frame.pack(fill="x", pady=(8, 0))
        self.details = tk.Text(details_frame, height=5, wrap="word")
        self.details.pack(fill="x")
        self.details.configure(state="disabled")

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(
            footer,
            text=(
                "This step is read-only. Choosing a possible replacement does not download a ROM, "
                "change Collection identity, or modify dependent references."
            ),
            foreground="gray",
            wraplength=760,
        ).pack(side="left", anchor="w")
        ttk.Button(footer, text="Keep Separate / Close", command=self.close).pack(side="right")
        ttk.Button(
            footer,
            text="Use as Possible Replacement...",
            command=self._choose_selected,
        ).pack(side="right", padx=(0, 8))

        self._show_suggestions()
        try:
            self.win.grab_set()
        except tk.TclError:
            pass
        self._center()
        return self.win

    def lift(self):
        if not self.is_open:
            return
        try:
            self.win.deiconify()
            self.win.lift()
            self.win.focus_force()
        except tk.TclError:
            pass

    def close(self):
        if self._closed:
            return
        self._closed = True
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
        if self.on_close:
            self.on_close()

    def _show_suggestions(self):
        self.search_var.set("")
        self._populate(tuple(item.entry for item in self.discovery.suggestions))
        self.status_label.configure(
            text=(
                _freshness_text(self.discovery)
                + f" · {len(self.discovery.suggestions)} possible related suggestion(s)"
            )
        )

    def _search(self, _event=None):
        query = self.search_var.get().strip()
        results = search_collection_update_catalogue(self.discovery, query)
        self._populate(results)
        self.status_label.configure(
            text=(
                _freshness_text(self.discovery)
                + f" · {len(results)} result(s) for {query!r}"
            )
        )

    def _populate(self, entries):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._displayed_entries = tuple(entries)
        existing = self.discovery.existing_numeric_collection_ids
        for index, entry in enumerate(self._displayed_entries):
            self.tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    entry.smwc_submission_id,
                    entry.title,
                    entry.difficulty,
                    entry.hack_type,
                    "" if entry.exits is None else entry.exits,
                    "Already present" if entry.smwc_submission_id in existing else "",
                ),
            )
        self._render_details(None)
        if self._displayed_entries:
            self.tree.selection_set("0")
            self.tree.focus("0")
            self._render_details(0)

    def _selection_changed(self, _event=None):
        selected = self.tree.selection()
        if not selected:
            self._render_details(None)
            return
        try:
            index = int(selected[0])
        except (TypeError, ValueError):
            self._render_details(None)
            return
        self._render_details(index)

    def _render_details(self, index):
        lines = []
        if index is not None and 0 <= index < len(self._displayed_entries):
            entry = self._displayed_entries[index]
            suggestion = _suggestion_for(self.discovery, entry.smwc_submission_id)
            if suggestion is not None:
                lines.extend(suggestion.reasons)
                lines.extend(f"Caution: {item}" for item in suggestion.cautions)
            else:
                lines.append(
                    "This row came from your manual frozen-Index search; no update relationship is inferred."
                )
            if entry.smwc_submission_id in self.discovery.existing_numeric_collection_ids:
                lines.append(
                    "Target already exists in Collection; a later confirmed replacement would need explicit merge reconciliation."
                )
            lines.append("No catalogue result shown here is proof of version lineage or recency.")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(lines))
        self.details.configure(state="disabled")

    def _choose_selected(self):
        selected = self.tree.selection()
        if not selected:
            messagebox.showinfo(
                "Possible SMWC Replacement",
                "Select a catalogue row first.",
                parent=self.win,
            )
            return
        try:
            entry = self._displayed_entries[int(selected[0])]
        except (IndexError, TypeError, ValueError):
            return

        merge_note = ""
        if entry.smwc_submission_id in self.discovery.existing_numeric_collection_ids:
            merge_note = (
                "\n\nThat SMWC ID already exists in your Collection. A later replacement flow "
                "would have to reconcile/merge the two records explicitly."
            )
        confirmed = messagebox.askyesno(
            "Confirm Possible Relationship",
            (
                f"Treat SMWC {entry.smwc_submission_id} — {entry.title} as a possible "
                f"replacement/update candidate for SMWC {self.discovery.source_collection_key} — "
                f"{self.discovery.source_entry.title}?\n\n"
                "The application cannot prove that this submission is newer. You are only "
                "confirming that you recognize a relationship worth continuing with."
                f"{merge_note}\n\n"
                "Nothing is downloaded or changed in Collection at this step."
            ),
            icon="warning",
            parent=self.win,
        )
        if not confirmed:
            return
        selection = select_possible_collection_replacement(
            self.discovery,
            entry.smwc_submission_id,
        )
        accepted = True
        if self.on_select:
            accepted = self.on_select(selection) is not False
        if accepted:
            self.close()

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


def _suggestion_for(discovery, submission_id):
    return next(
        (
            item
            for item in discovery.suggestions
            if item.entry.smwc_submission_id == submission_id
        ),
        None,
    )


def _freshness_text(discovery):
    try:
        timestamp = datetime.fromtimestamp(discovery.catalogue_fetched_at).strftime(
            "%Y-%m-%d %H:%M"
        )
    except (OSError, OverflowError, TypeError, ValueError):
        timestamp = "unknown time"
    stale = " · STALE fallback" if discovery.catalogue_stale else ""
    return f"KaizOFF Index: {discovery.catalogue_source} · fetched {timestamp}{stale}"


__all__ = [
    "CollectionUpdateDiscoveryDialog",
    "CollectionUpdateDiscoveryProgressDialog",
]
