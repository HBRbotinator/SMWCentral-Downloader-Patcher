"""Read-only Tk UI for checking one Collection entry against the SMWC catalogue."""
from __future__ import annotations

from datetime import datetime
import tkinter as tk
from tkinter import messagebox, ttk

from collection_update_discovery import (
    CollectionUpdateDiscovery,
    search_collection_update_catalogue,
    select_possible_collection_replacement,
)
from ui.window_positioning import center_window_on_parent


class CollectionUpdateDiscoveryProgressDialog:
    """Modal busy window while the current SMWC catalogue snapshot is loaded."""

    def __init__(self, parent):
        self.parent = parent
        self.win = None

    def show(self):
        if self.win:
            return self.win
        self.win = tk.Toplevel(self.parent)
        self.win.title("Checking SMWC Entry")
        self.win.resizable(False, False)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", lambda: None)
        body = ttk.Frame(self.win, padding=18)
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text="Checking this Collection entry...",
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            body,
            text=(
                "Checking the SMWC catalogue for this entry and looking for possibly related "
                "submissions. Nothing in your Collection is changed."
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


class CollectionUpdateDiscoveryDialog:
    """Keep the same-ID update path prominent and replacements clearly secondary."""

    def __init__(
        self,
        parent,
        discovery,
        *,
        on_select=None,
        on_refresh_current=None,
        on_close=None,
    ):
        if not isinstance(discovery, CollectionUpdateDiscovery):
            raise TypeError("discovery must be CollectionUpdateDiscovery")
        self.parent = parent
        self.discovery = discovery
        self.on_select = on_select
        self.on_refresh_current = on_refresh_current
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
        self.win.title(f"Update {source.title}")
        self.win.geometry("1180x760")
        self.win.minsize(900, 600)
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
                f"SMWC {source.smwc_submission_id}. Choose the normal update action below when "
                "you want to refresh this same Collection entry."
            ),
            wraplength=1100,
        ).pack(anchor="w", pady=(4, 10))

        current_frame = ttk.LabelFrame(root, text="Update this Collection entry", padding=12)
        current_frame.pack(fill="x", pady=(0, 12))
        current_text = ttk.Frame(current_frame)
        current_text.pack(side="left", fill="both", expand=True)
        ttk.Label(
            current_text,
            text=f"{source.title}  ·  SMWC {source.smwc_submission_id}",
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            current_text,
            text=(
                "Refresh its SMWC information and optionally download the ROM currently offered "
                "for this same SMWC entry. Your Collection identity does not change."
            ),
            wraplength=790,
        ).pack(anchor="w", pady=(3, 0))
        current_button = ttk.Button(
            current_frame,
            text="Update This Entry...",
            command=self._refresh_current,
            width=24,
        )
        current_button.pack(side="right", padx=(18, 0), pady=2)
        if self.on_refresh_current is None:
            current_button.configure(state="disabled")

        related = ttk.LabelFrame(root, text="Other SMWC submissions", padding=10)
        related.pack(fill="both", expand=True)
        ttk.Label(
            related,
            text=(
                "These are separate submissions that may be related. "
                "the application cannot prove that another submission is newer. "
                "Only continue when you recognize the relationship."
            ),
            foreground="#C47F00",
            wraplength=1080,
        ).pack(anchor="w", pady=(0, 5))

        self.status_label = ttk.Label(related, text=_freshness_text(self.discovery), foreground="gray")
        self.status_label.pack(anchor="w", pady=(0, 8))

        search = ttk.Frame(related)
        search.pack(fill="x", pady=(0, 8))
        ttk.Label(search, text="Search other submissions:").pack(side="left")
        self.search_var = tk.StringVar(value=source.title)
        entry = ttk.Entry(search, textvariable=self.search_var)
        entry.pack(side="left", fill="x", expand=True, padx=(8, 6))
        entry.bind("<Return>", self._search)
        ttk.Button(search, text="Search", command=self._search).pack(side="left")
        ttk.Button(search, text="Suggested", command=self._show_suggestions).pack(
            side="left", padx=(6, 0)
        )

        table_frame = ttk.Frame(related)
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

        details_frame = ttk.LabelFrame(related, text="Why this submission is shown", padding=8)
        details_frame.pack(fill="x", pady=(8, 0))
        self.details = tk.Text(details_frame, height=4, wrap="word")
        self.details.pack(fill="x")
        self.details.configure(state="disabled")

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Label(
            footer,
            text=(
                "Possible replacements are review-only here. Nothing is downloaded or changed "
                "until you continue through the later reviewed update flow."
            ),
            foreground="gray",
            wraplength=760,
        ).pack(side="left", anchor="w")
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")
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
        center_window_on_parent(self.win, self.parent)
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
        self.search_var.set(self.discovery.source_entry.title)
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
            text=_freshness_text(self.discovery) + f" · {len(results)} result(s)"
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
                    "This submission came from your manual catalogue search; no update relationship is inferred."
                )
            if entry.smwc_submission_id in self.discovery.existing_numeric_collection_ids:
                lines.append(
                    "This SMWC ID is already in Collection; continuing would require an explicit merge review."
                )
            lines.append("This list is not proof of version order or recency.")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(lines))
        self.details.configure(state="disabled")

    def _refresh_current(self):
        if self.on_refresh_current is None:
            return False
        source = self.discovery.source_entry
        confirmed = messagebox.askyesno(
            "Update This Collection Entry",
            (
                f"Update {source.title} (SMWC {source.smwc_submission_id})?\n\n"
                "Next you can update the SMWC information only, or also download the ROM currently "
                "offered for this same SMWC entry. This is not a replacement with another submission.\n\n"
                "Nothing changes until you review and apply the update."
            ),
            parent=self.win,
        )
        if not confirmed:
            return False
        accepted = self.on_refresh_current(self.discovery) is not False
        if accepted:
            self.close()
        return accepted

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
                "will reconcile the two records explicitly."
            )
        confirmed = messagebox.askyesno(
            "Confirm Possible Relationship",
            (
                f"Treat SMWC {entry.smwc_submission_id} — {entry.title} as a possible related "
                f"submission for SMWC {self.discovery.source_collection_key} — "
                f"{self.discovery.source_entry.title}?\n\n"
                "The application cannot prove that this submission is newer. You are only confirming "
                "that you recognize a relationship worth reviewing."
                f"{merge_note}\n\n"
                "Nothing is downloaded or changed at this step."
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
    stale = " · cached fallback" if discovery.catalogue_stale else ""
    return f"SMWC catalogue checked {timestamp}{stale}"


__all__ = [
    "CollectionUpdateDiscoveryDialog",
    "CollectionUpdateDiscoveryProgressDialog",
]
