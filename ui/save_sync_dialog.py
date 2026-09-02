"""
Save Data Sync - preview & confirm dialog.

Two tabs:
  * Completion  - saves that matched a collection hack; toggle which to mark done.
  * Import from SMWC - saves that matched no hack; look each up on SMWC by name
    and import the confident matches as canonical ID-keyed entries (so a later
    download/update merges into the same entry instead of duplicating).

Nothing is written to the collection until "Apply Selected" is pressed.

Copyright (c) 2025 iamtheratio
Licensed under the MIT License - see LICENSE file for details
"""

import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import save_sync
import save_sync_sources
from local_collection_metadata import (
    LOCAL_DIFFICULTY_CHOICES,
    LOCAL_HACK_TYPE_CHOICES,
    format_local_hack_types,
    validate_local_collection_metadata,
)

CHECKED = "☑"
UNCHECKED = "☐"
LOCKED = "✓"

_STATUS_LABEL = {
    save_sync.STATUS_COMPLETED: "Complete",
    save_sync.STATUS_IN_PROGRESS: "In progress",
    save_sync.STATUS_UNCERTAIN: "Uncertain",
    save_sync.STATUS_ALREADY_COMPLETED: "Already synced",
}
_STATUS_ORDER = {
    save_sync.STATUS_COMPLETED: 0,
    save_sync.STATUS_IN_PROGRESS: 1,
    save_sync.STATUS_UNCERTAIN: 2,
    save_sync.STATUS_ALREADY_COMPLETED: 3,
}
_CHECKABLE = {
    save_sync.STATUS_COMPLETED,
    save_sync.STATUS_IN_PROGRESS,
    save_sync.STATUS_UNCERTAIN,
}

_RESOLUTION_LABEL = {
    save_sync.RESOLUTION_NONE: "—",
    save_sync.RESOLUTION_RESOLVED: "Import (new)",
    save_sync.RESOLUTION_EXISTS: "In collection",
    save_sync.RESOLUTION_NO_MATCH: "No match",
    save_sync.RESOLUTION_AMBIGUOUS: "Ambiguous",
    save_sync.RESOLUTION_REVIEW: "Review suggested",
    save_sync.RESOLUTION_ERROR: "Lookup error",
    save_sync.RESOLUTION_LOCAL: "Create local",
}
# Orphan resolutions the user can actually act on.
_ORPHAN_ACTIONABLE = {
    save_sync.RESOLUTION_RESOLVED,
    save_sync.RESOLUTION_EXISTS,
    save_sync.RESOLUTION_LOCAL,
}

_CONFIDENCE_LABEL = {
    "medium": "Medium",
    "low": "Low",
    "none": "None",
}


def _candidate_evidence(candidate):
    """Return analysis evidence without assuming a concrete analysis class."""

    try:
        evidence = candidate.evidence()
    except (AttributeError, TypeError, ValueError):
        evidence = {}
    return evidence if isinstance(evidence, dict) else {}


def _confidence_key(candidate):
    evidence = _candidate_evidence(candidate)
    confidence = evidence.get(
        "confidence", getattr(candidate, "confidence", "none")
    )
    key = str(confidence or "none").strip().lower()
    return key if key in _CONFIDENCE_LABEL else "none"


def _confidence_label(candidate):
    return _CONFIDENCE_LABEL[_confidence_key(candidate)]


def _accepted_copy_kinds(evidence, slot):
    copies = set()
    for attempt in evidence.get("attempts", []) or []:
        if not isinstance(attempt, dict):
            continue
        if not attempt.get("accepted") or attempt.get("slot") != slot:
            continue
        copy_kind = attempt.get("copy_kind")
        if copy_kind:
            copies.add(str(copy_kind))
    return copies


def _analysis_summary(candidate):
    """Return a concise explanation suitable for the review interface."""

    evidence = _candidate_evidence(candidate)
    profile = str(evidence.get("profile") or getattr(
        candidate, "profile", "unknown"
    ))
    slot = evidence.get("selected_slot")
    value = evidence.get("selected_value")

    if profile == "relocated_standard_smw_slots":
        explanation = f"Relocated standard slot {slot or '?'} + backup"
    elif profile == "standard_smw_slots":
        copies = _accepted_copy_kinds(evidence, slot)
        if {"primary", "backup"}.issubset(copies):
            explanation = f"Standard slot {slot or '?'} + backup"
        elif copies:
            copy_name = sorted(copies)[0].title()
            explanation = f"Standard slot {slot or '?'} ({copy_name} only)"
        else:
            explanation = f"Checksum-valid standard slot {slot or '?'}"
    elif profile == "legacy_raw_counter":
        explanation = "Unvalidated legacy raw counter"
    elif profile == "expanded_sram_unknown":
        explanation = "Unknown expanded SRAM layout"
    elif value is None:
        explanation = "No trusted progress value"
    else:
        explanation = profile.replace("_", " ").strip().title()

    if isinstance(value, int):
        explanation += f" · {value} detected event(s)"
    return explanation


def _analysis_detail(candidate):
    if candidate is None:
        return "Select a row to see its save-analysis evidence."
    confidence = _confidence_label(candidate)
    prefix = "No confidence" if confidence == "None" else f"{confidence} confidence"
    return f"{prefix} · {_analysis_summary(candidate)}"


class ManualSmwcSearchDialog:
    """Modal free-text SMWC search for one unresolved save."""

    def __init__(self, parent, candidate, existing_ids, fetch_fn=None,
                 logger=None, on_selected=None, lookup_service=None):
        self.parent = parent
        self.candidate = candidate
        self.existing_ids = set(existing_ids)
        self.fetch_fn = fetch_fn
        self.logger = logger
        self.on_selected = on_selected
        self.lookup_service = lookup_service

        self.win = None
        self.query_var = None
        self.result_tree = None
        self.search_button = None
        self.use_button = None
        self.status_label = None
        self.options = {}
        self._search_running = False

    def show(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title(f"Search SMWCentral - {self.candidate.save_name}")
        self.win.geometry("760x470")
        self.win.transient(self.parent)
        self.win.grab_set()
        self.win.protocol("WM_DELETE_WINDOW", self._close)

        container = ttk.Frame(self.win, padding=15)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="The initial search runs automatically using this save name. "
                 "Change the search text if needed, select the correct hack, then "
                 "confirm the selection. No result is chosen automatically.",
            wraplength=720,
        ).pack(anchor="w", pady=(0, 10))

        query_row = ttk.Frame(container)
        query_row.pack(fill="x", pady=(0, 10))
        ttk.Label(query_row, text="Search:").pack(side="left")
        self.query_var = tk.StringVar(
            value=save_sync.make_search_query(self.candidate.save_name)
        )
        entry = ttk.Entry(query_row, textvariable=self.query_var)
        entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        entry.bind("<Return>", lambda _event: self._start_search())
        self.search_button = ttk.Button(
            query_row, text="Search", command=self._start_search
        )
        self.search_button.pack(side="right")

        columns = ("name", "difficulty", "release", "collection")
        frame = ttk.Frame(container)
        frame.pack(fill="both", expand=True)
        self.result_tree = ttk.Treeview(
            frame, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "name": ("Hack", 330, "w", True),
            "difficulty": ("Difficulty", 120, "w", False),
            "release": ("Release", 100, "w", False),
            "collection": ("Collection", 120, "w", False),
        }
        for column, (label, width, anchor, stretch) in headings.items():
            self.result_tree.heading(column, text=label)
            self.result_tree.column(
                column, width=width, anchor=anchor, stretch=stretch
            )
        scrollbar = ttk.Scrollbar(
            frame, orient="vertical", command=self.result_tree.yview
        )
        self.result_tree.configure(yscrollcommand=scrollbar.set)
        self.result_tree.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.result_tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.result_tree.bind("<Double-1>", self._use_selected)

        footer = ttk.Frame(container)
        footer.pack(fill="x", pady=(10, 0))
        self.status_label = ttk.Label(footer, text="", foreground="gray")
        self.status_label.pack(side="left")
        self.use_button = ttk.Button(
            footer, text="Use Selected", state="disabled",
            command=self._use_selected,
        )
        self.use_button.pack(side="right")
        ttk.Button(footer, text="Cancel", command=self._close).pack(
            side="right", padx=(0, 8)
        )

        self._center()
        entry.focus_set()
        entry.selection_range(0, "end")
        self.win.after_idle(self._start_search)
        return self.win

    def _start_search(self):
        if self._search_running:
            return
        query = self.query_var.get().strip()
        if not query:
            self.status_label.config(text="Enter a search term.")
            return

        self._search_running = True
        self.search_button.config(state="disabled")
        self.use_button.config(state="disabled")
        self.status_label.config(text="Searching SMWC catalogue...")
        self.options.clear()
        for iid in self.result_tree.get_children():
            self.result_tree.delete(iid)

        threading.Thread(
            target=self._search_worker, args=(query,), daemon=True
        ).start()

    def _search_worker(self, query):
        if self.lookup_service is not None:
            result = self.lookup_service.search_manual(query, self.existing_ids)
        else:
            result = save_sync.search_orphan_options(
                query,
                self.existing_ids,
                fetch_fn=self.fetch_fn,
                log=self.logger.log if self.logger else None,
            )
        self._ui(self._show_results, result)

    def _show_results(self, result):
        self._search_running = False
        try:
            self.search_button.config(state="normal")
        except tk.TclError:
            return

        options = result.get("options", [])
        suggested_iid = None
        suggested_hack_id = str(
            getattr(self.candidate, "suggested_hack_id", "") or ""
        )
        for option in options:
            obsolete = option.get("obsolete")
            if obsolete is True:
                release = "Obsolete"
            elif obsolete is False:
                release = "Current"
            else:
                release = "Catalogue"
            collection = "Already added" if option["in_collection"] else "New"
            iid = self.result_tree.insert(
                "",
                "end",
                values=(
                    option["name"],
                    option["difficulty"] or "-",
                    release,
                    collection,
                ),
            )
            self.options[iid] = option
            if str(option.get("hack_id", "")) == suggested_hack_id:
                suggested_iid = iid

        if suggested_iid is not None:
            self.result_tree.selection_set(suggested_iid)
            self.result_tree.focus(suggested_iid)
            self.result_tree.see(suggested_iid)

        if result.get("status") == save_sync.RESOLUTION_ERROR:
            message = "SMWC catalogue search failed. Check the log and try again."
        elif options:
            message = f"Found {len(options)} result(s). Select the correct hack."
        else:
            message = "No results found. Try a different search term."
        self.status_label.config(text=message)
        self._selection_changed()

    def _selection_changed(self, _event=None):
        selected = self.result_tree.selection() if self.result_tree else ()
        state = (
            "normal"
            if len(selected) == 1 and not self._search_running
            else "disabled"
        )
        try:
            self.use_button.config(state=state)
        except (tk.TclError, AttributeError):
            pass

    def _use_selected(self, _event=None):
        selected = self.result_tree.selection()
        if len(selected) != 1 or self._search_running:
            return
        option = self.options.get(selected[0])
        if not option:
            return

        if self.lookup_service is not None and option.get("lookup_source") == "kaizoff":
            self._search_running = True
            self.search_button.config(state="disabled")
            self.use_button.config(state="disabled")
            self.status_label.config(text="Loading selected SMWC details...")
            threading.Thread(
                target=self._resolve_selected_worker, args=(option,), daemon=True
            ).start()
            return

        resolution = save_sync.resolution_for_selected_hack(
            option.get("hack"), self.existing_ids
        )
        self._finish_selected_resolution(resolution)

    def _resolve_selected_worker(self, option):
        resolution = self.lookup_service.resolve_selected_option(
            option, self.existing_ids
        )
        self._ui(self._finish_selected_resolution, resolution)

    def _finish_selected_resolution(self, resolution):
        self._search_running = False
        try:
            self.search_button.config(state="normal")
        except tk.TclError:
            return
        if resolution.get("status") not in _ORPHAN_ACTIONABLE:
            self.status_label.config(
                text="The selected SMWC result could not be loaded. Check the log."
            )
            self._selection_changed()
            return
        if self.on_selected:
            self.on_selected(resolution)
        self._close()

    def _ui(self, func, *args):
        try:
            if self.win and self.win.winfo_exists():
                self.win.after(0, lambda: func(*args))
        except tk.TclError:
            pass

    def _close(self):
        try:
            if self.win and self.win.winfo_exists():
                self.win.destroy()
            if self.parent and self.parent.winfo_exists():
                self.parent.grab_set()
        except tk.TclError:
            pass

    def _center(self):
        self.win.update_idletasks()
        try:
            x = self.parent.winfo_x() + (
                self.parent.winfo_width() - self.win.winfo_width()
            ) // 2
            y = self.parent.winfo_y() + (
                self.parent.winfo_height() - self.win.winfo_height()
            ) // 2
            self.win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass


class LocalSaveEntryDialog:
    """Choose an existing local Collection record or create a separate one."""

    def __init__(self, parent, candidate, existing_records, on_selected=None):
        self.parent = parent
        self.candidate = candidate
        self.existing_records = dict(existing_records or {})
        self.on_selected = on_selected
        self.win = None
        self.title_var = None
        self.type_var = None
        self.difficulty_var = None
        self.exits_var = None
        self.mode_var = None
        self.local_tree = None
        self.local_targets = {}
        self.local_labels = {}
        self.local_selection_label = None
        self.continue_button = None
        self.local_matches = save_sync.local_collection_matches(
            self.existing_records,
            save_sync.make_search_query(self.candidate.save_name),
        )

    def show(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title(f"Local Collection Entry - {self.candidate.save_name}")
        self.win.geometry("700x520" if self.local_matches else "580x380")
        self.win.transient(self.parent)
        self.win.grab_set()

        container = ttk.Frame(self.win, padding=15)
        container.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text=(
                "This save is not being linked to SMWCentral. Attach it to an "
                "existing local Collection entry when it is the same hack, or "
                "create a separate local record. Title similarity is never an "
                "automatic identity decision."
            ),
            wraplength=640,
        ).pack(anchor="w", pady=(0, 10))

        self.mode_var = tk.StringVar(value="" if self.local_matches else "create")
        if self.local_matches:
            ttk.Radiobutton(
                container,
                text="Attach this save to the selected existing local entry",
                variable=self.mode_var,
                value="attach",
                command=self._local_mode_changed,
            ).pack(anchor="w", pady=(0, 2))
            ttk.Label(
                container,
                text=(
                    "Choose the exact local Collection row below. Even a single "
                    "suggestion is not selected automatically."
                ),
                foreground="gray",
                wraplength=640,
            ).pack(anchor="w", padx=(22, 0), pady=(0, 4))
            holder = ttk.Frame(container)
            holder.pack(fill="x", pady=(0, 10))
            columns = ("title", "id", "difficulty", "type", "exits", "score")
            self.local_tree = ttk.Treeview(
                holder,
                columns=columns,
                show="headings",
                height=min(4, len(self.local_matches)),
                selectmode="browse",
            )
            specs = {
                "title": ("Local hack", 220),
                "id": ("Collection ID", 145),
                "difficulty": ("Difficulty", 90),
                "type": ("Type", 75),
                "exits": ("Exits", 45),
                "score": ("Match", 55),
            }
            for column, (label, width) in specs.items():
                self.local_tree.heading(column, text=label)
                self.local_tree.column(column, width=width, minwidth=40, anchor="w")
            hscroll = ttk.Scrollbar(holder, orient="horizontal", command=self.local_tree.xview)
            self.local_tree.configure(xscrollcommand=hscroll.set)
            self.local_tree.tag_configure(
                "chosen", font=("Segoe UI", 9, "bold")
            )
            self.local_tree.grid(row=0, column=0, sticky="ew")
            hscroll.grid(row=1, column=0, sticky="ew")
            holder.columnconfigure(0, weight=1)
            for index, match in enumerate(self.local_matches):
                iid = f"local:{index}:{match.target_key}"
                self.local_tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=(
                        match.title,
                        match.target_key,
                        match.difficulty or "-",
                        ", ".join(match.hack_types) or "-",
                        "-" if match.exits is None else match.exits,
                        f"{match.confidence:.0%}",
                    ),
                )
                self.local_targets[iid] = match.target_key
                self.local_labels[iid] = (match.title, match.target_key)
            self.local_tree.bind("<<TreeviewSelect>>", self._local_selected)
            self.local_selection_label = ttk.Label(
                container,
                text="No existing local entry selected yet.",
                font=("Segoe UI", 9, "bold"),
            )
            self.local_selection_label.pack(anchor="w", pady=(0, 8))

        ttk.Radiobutton(
            container,
            text="Create a separate local Collection entry",
            variable=self.mode_var,
            value="create",
            command=self._local_mode_changed,
        ).pack(anchor="w", pady=(2, 4))

        form = ttk.Frame(container)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Title:").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.title_var = tk.StringVar(
            value=save_sync.make_search_query(self.candidate.save_name)
        )
        title_entry = ttk.Entry(form, textvariable=self.title_var)
        title_entry.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Type(s):").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.type_var = tk.StringVar(value="Unknown")
        ttk.Combobox(
            form,
            textvariable=self.type_var,
            values=LOCAL_HACK_TYPE_CHOICES,
        ).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Difficulty:").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.difficulty_var = tk.StringVar(value="Unknown")
        ttk.Combobox(
            form,
            textvariable=self.difficulty_var,
            values=LOCAL_DIFFICULTY_CHOICES,
            state="readonly",
        ).grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Total exits:").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.exits_var = tk.StringVar(value="0")
        exits_entry = ttk.Entry(form, textvariable=self.exits_var, width=10)
        exits_entry.grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(
            container,
            text=(
                "Creation fields are used only when creating a separate record. "
                "Type accepts one or more comma-separated values. Use Unknown when "
                "type/difficulty are not known and 0 exits when the total is unknown."
            ),
            foreground="gray",
            wraplength=640,
        ).pack(anchor="w", pady=(6, 0))

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(12, 0))
        self.continue_button = ttk.Button(
            buttons, text="Continue", command=self._confirm
        )
        self.continue_button.pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.win.destroy).pack(
            side="right", padx=(0, 8)
        )
        self._local_mode_changed()

        self.win.update_idletasks()
        try:
            x = self.parent.winfo_x() + (
                self.parent.winfo_width() - self.win.winfo_width()
            ) // 2
            y = self.parent.winfo_y() + (
                self.parent.winfo_height() - self.win.winfo_height()
            ) // 2
            self.win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass
        title_entry.focus_set()
        title_entry.selection_range(0, "end")
        return self.win

    def _local_selected(self, _event=None):
        if self.mode_var is not None:
            self.mode_var.set("attach")
        selected = self.local_tree.selection() if self.local_tree is not None else ()
        if self.local_tree is not None:
            for iid in self.local_tree.get_children():
                self.local_tree.item(
                    iid, tags=("chosen",) if iid in selected else ()
                )
            if len(selected) == 1:
                self.local_tree.focus(selected[0])
                self.local_tree.see(selected[0])
        self._local_mode_changed()

    def _local_mode_changed(self):
        """Make the explicit existing-local selection state unmistakable."""

        mode = self.mode_var.get().strip() if self.mode_var is not None else ""
        selected = self.local_tree.selection() if self.local_tree is not None else ()
        target = self._selected_local_target()

        if self.local_selection_label is not None:
            if len(selected) == 1 and target:
                title, collection_id = self.local_labels.get(
                    selected[0], ("Selected local entry", target)
                )
                if mode == "create":
                    message = (
                        f"Existing local row selected but not in use: {title}  •  "
                        f"{collection_id}"
                    )
                else:
                    message = (
                        f"Selected existing local entry: {title}  •  "
                        f"{collection_id}"
                    )
                self.local_selection_label.configure(text=message)
            elif mode == "attach":
                self.local_selection_label.configure(
                    text="Select a row above before continuing with Attach."
                )
            else:
                self.local_selection_label.configure(
                    text="No existing local entry selected yet."
                )

        if self.continue_button is not None:
            enabled = mode == "create" or (mode == "attach" and bool(target))
            self.continue_button.configure(
                state="normal" if enabled else "disabled"
            )

    def _selected_local_target(self):
        if self.local_tree is None:
            return ""
        selected = self.local_tree.selection()
        if len(selected) != 1:
            return ""
        return self.local_targets.get(selected[0], "")

    def _confirm(self):
        mode = self.mode_var.get().strip() if self.mode_var is not None else ""
        if mode == "attach":
            target = self._selected_local_target()
            if not target:
                messagebox.showerror(
                    "Save Data Sync",
                    "Select the existing local Collection entry to attach this save to.",
                    parent=self.win,
                )
                return
            resolution = save_sync.resolution_for_existing_local_entry(
                target, self.existing_records
            )
        elif mode == "create":
            try:
                resolution = save_sync.resolution_for_local_entry(
                    self.candidate.save_name,
                    self.title_var.get(),
                    self.exits_var.get(),
                    self.existing_records.keys(),
                    difficulty=self.difficulty_var.get(),
                    hack_types=self.type_var.get(),
                )
            except ValueError as exc:
                messagebox.showerror(
                    "Save Data Sync", str(exc), parent=self.win
                )
                return
        else:
            messagebox.showerror(
                "Save Data Sync",
                "Choose whether to attach to an existing local entry or create a separate one.",
                parent=self.win,
            )
            return

        if self.on_selected:
            self.on_selected(resolution)
        self.win.destroy()


class EditLocalSaveEntryDialog:
    """Modal editor for metadata on an existing local save entry."""

    def __init__(self, parent, candidate, entry, on_saved=None):
        self.parent = parent
        self.candidate = candidate
        self.entry = entry
        self.on_saved = on_saved
        self.win = None
        self.title_var = None
        self.type_var = None
        self.difficulty_var = None
        self.exits_var = None

    def show(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title(f"Edit Local Entry - {self.candidate.save_name}")
        self.win.geometry("560x330")
        self.win.transient(self.parent)
        self.win.grab_set()

        container = ttk.Frame(self.win, padding=15)
        container.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text="Edit the local collection metadata. The saved association "
                 "and save file remain unchanged.",
            wraplength=480,
        ).pack(anchor="w", pady=(0, 12))

        form = ttk.Frame(container)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="Title:").grid(
            row=0, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.title_var = tk.StringVar(value=self.entry.get("title", ""))
        title_entry = ttk.Entry(form, textvariable=self.title_var)
        title_entry.grid(row=0, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Type(s):").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.type_var = tk.StringVar(
            value=format_local_hack_types(
                self.entry.get("hack_types")
                or ([self.entry.get("hack_type")] if self.entry.get("hack_type") else ())
            )
        )
        ttk.Combobox(
            form,
            textvariable=self.type_var,
            values=LOCAL_HACK_TYPE_CHOICES,
        ).grid(row=1, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Difficulty:").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.difficulty_var = tk.StringVar(
            value=self.entry.get("current_difficulty", "Unknown") or "Unknown"
        )
        ttk.Combobox(
            form,
            textvariable=self.difficulty_var,
            values=LOCAL_DIFFICULTY_CHOICES,
            state="readonly",
        ).grid(row=2, column=1, sticky="ew", pady=4)

        ttk.Label(form, text="Total exits:").grid(
            row=3, column=0, sticky="w", padx=(0, 8), pady=4
        )
        self.exits_var = tk.StringVar(value=str(self.entry.get("exits", 0)))
        ttk.Entry(form, textvariable=self.exits_var, width=10).grid(
            row=3, column=1, sticky="w", pady=4
        )

        buttons = ttk.Frame(container)
        buttons.pack(fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Save", command=self._confirm).pack(
            side="right"
        )
        ttk.Button(buttons, text="Cancel", command=self.win.destroy).pack(
            side="right", padx=(0, 8)
        )

        self.win.update_idletasks()
        try:
            x = self.parent.winfo_x() + (
                self.parent.winfo_width() - self.win.winfo_width()
            ) // 2
            y = self.parent.winfo_y() + (
                self.parent.winfo_height() - self.win.winfo_height()
            ) // 2
            self.win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass
        title_entry.focus_set()
        title_entry.selection_range(0, "end")
        return self.win

    def _confirm(self):
        try:
            metadata = validate_local_collection_metadata(
                self.title_var.get(),
                self.difficulty_var.get(),
                self.type_var.get(),
                self.exits_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("Save Data Sync", str(exc), parent=self.win)
            return

        if self.on_saved:
            self.on_saved(metadata)
        self.win.destroy()


class SaveSyncDialog:
    """Modal preview dialog for applying save-sync results."""

    def __init__(self, parent, candidates, data_manager, logger=None,
                 on_applied=None, fetch_fn=None, mark_all=False,
                 config_manager=None, lookup_service=None):
        self.parent = parent
        self.data_manager = data_manager
        self.logger = logger
        self.on_applied = on_applied
        self.fetch_fn = fetch_fn
        self.lookup_service = lookup_service
        self.mark_all = mark_all
        self.config_manager = config_manager
        self.candidates = list(candidates)

        self.matched = sorted(
            (c for c in self.candidates if c.hack_id),
            key=lambda c: (_STATUS_ORDER.get(c.status, 9), c.title.lower()),
        )
        self.unmatched = sorted(
            (c for c in self.candidates if not c.hack_id),
            key=lambda c: c.save_name.lower(),
        )

        self.win = None
        # Completion tab state
        self.comp_tree = None
        self.comp_checked = {}
        self.comp_cand = {}
        self.forget_match_button = None
        self.edit_local_button = None
        self.remove_local_button = None
        # Orphan tab state
        self.orph_tree = None
        self.orph_checked = {}
        self.orph_cand = {}
        self.orph_iid = {}  # candidate id() -> iid, for background updates
        self.manual_search_button = None
        self.local_entry_button = None
        self.comp_analysis_label = None
        self.orph_analysis_label = None

        self._cancel_lookup = False
        self._lookup_running = False

    def _catalogue_lookup(self):
        """Return one shared KaizOFF-first lookup session for this review."""

        if self.lookup_service is None:
            from save_sync_catalogue import SaveSyncCatalogueLookup

            self.lookup_service = SaveSyncCatalogueLookup(
                processed_json_path=getattr(self.data_manager, "json_path", None),
                log=self.logger.log if self.logger else None,
            )
        return self.lookup_service

    # -- construction ---------------------------------------------------------

    def show(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title("Save Data Sync - Review Changes")
        self.win.geometry("980x650")
        self.win.transient(self.parent.winfo_toplevel())
        self.win.grab_set()
        self.win.bind("<Destroy>", self._on_destroy)

        container = ttk.Frame(self.win, padding=15)
        container.pack(fill="both", expand=True)

        self._build_header(container)

        notebook = ttk.Notebook(container)
        notebook.pack(fill="both", expand=True)
        notebook.add(self._build_completion_tab(notebook),
                     text=f"Completion ({len(self.matched)})")
        notebook.add(self._build_orphan_tab(notebook),
                     text=f"Import from SMWC ({len(self.unmatched)})")

        self._build_buttons(container)

        self._populate_completion()
        self._populate_orphans()
        self._update_apply_state()
        self._center()
        return self.win

    def _build_header(self, parent):
        ttk.Label(
            parent,
            text="Review the changes below, then apply only what you check. "
                 "Completion updates and newly imported hacks are both optional.",
            wraplength=780,
        ).pack(anchor="w", pady=(0, 10))

    # -- completion tab -------------------------------------------------------

    def _build_completion_tab(self, notebook):
        tab = ttk.Frame(notebook, padding=10)

        counts = {}
        for c in self.matched:
            counts[c.status] = counts.get(c.status, 0) + 1
        summary = "  ·  ".join(
            f"{counts[s]} {_STATUS_LABEL[s].lower()}"
            for s in (save_sync.STATUS_COMPLETED, save_sync.STATUS_IN_PROGRESS,
                      save_sync.STATUS_UNCERTAIN, save_sync.STATUS_ALREADY_COMPLETED)
            if counts.get(s)
        ) or "No matching saves"
        ttk.Label(tab, text=summary, foreground="gray").pack(
            anchor="w", pady=(0, 3)
        )
        ttk.Label(
            tab,
            text="Medium = checksum-validated structure; Low = unvalidated "
                 "fallback; None = no trusted progress. Low-confidence "
                 "completions require manual selection.",
            foreground="gray",
            wraplength=920,
        ).pack(anchor="w", pady=(0, 8))

        columns = (
            "check", "title", "file", "decision", "confidence", "source",
            "date", "exits"
        )
        self.comp_tree = self._make_tree(
            tab, columns,
            {
                "check": ("", 34, "center", False),
                "title": ("Hack", 195, "w", True),
                "file": ("Save File", 165, "w", True),
                "decision": ("Decision", 85, "w", False),
                "confidence": ("Confidence", 92, "center", False),
                "source": ("Match", 80, "w", False),
                "date": ("Play Date", 90, "center", False),
                "exits": ("Exits", 70, "center", False),
            },
            selectmode="browse",
        )
        self.comp_tree.bind("<Button-1>", self._on_comp_click)
        self.comp_tree.bind(
            "<<TreeviewSelect>>", self._completion_selection_changed
        )
        # Clicking the check-column header toggles all rows.
        self.comp_tree.heading(
            "check", text=UNCHECKED, command=self._comp_toggle_all
        )
        self.comp_analysis_label = ttk.Label(
            tab,
            text=_analysis_detail(None),
            foreground="gray",
            wraplength=920,
        )
        self.comp_analysis_label.pack(anchor="w", pady=(7, 0))

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Select All", command=lambda: self._comp_set_all(True)).pack(side="left")
        ttk.Button(btns, text="Select None", command=lambda: self._comp_set_all(False)).pack(side="left", padx=(8, 0))
        self.remove_local_button = ttk.Button(
            btns,
            text="Remove Local Entry...",
            state="disabled",
            command=self._remove_selected_local_entry,
        )
        self.remove_local_button.pack(side="right")
        self.edit_local_button = ttk.Button(
            btns,
            text="Edit Local Entry...",
            state="disabled",
            command=self._edit_selected_local_entry,
        )
        self.edit_local_button.pack(side="right", padx=(0, 8))
        self.forget_match_button = ttk.Button(
            btns,
            text="Forget Saved Match",
            state="disabled",
            command=self._forget_selected_match,
        )
        self.forget_match_button.pack(side="right", padx=(0, 8))
        return tab

    def _populate_completion(self):
        for cand in self.matched:
            checkable = cand.status in _CHECKABLE
            default_checked = (
                cand.status == save_sync.STATUS_COMPLETED
                and _confidence_key(cand) == "medium"
            )
            if cand.status == save_sync.STATUS_ALREADY_COMPLETED:
                glyph = LOCKED
            else:
                glyph = CHECKED if default_checked else UNCHECKED

            tags = ()
            if cand.status == save_sync.STATUS_ALREADY_COMPLETED:
                tags = ("locked",)
            elif cand.status == save_sync.STATUS_UNCERTAIN:
                tags = ("uncertain",)

            iid = self.comp_tree.insert(
                "", "end",
                values=(
                    glyph,
                    cand.title,
                    cand.save_name,
                    _STATUS_LABEL.get(cand.status, cand.status),
                    _confidence_label(cand),
                    (
                        "Saved"
                        if cand.match_source == save_sync.MATCH_SOURCE_SAVED_ALIAS
                        else "Automatic"
                    ),
                    cand.completed_date or "-",
                    cand.exits_display,
                ),
                tags=tags,
            )
            self.comp_cand[iid] = cand
            self.comp_checked[iid] = bool(checkable and default_checked)
        self._update_comp_header()

    def _on_comp_click(self, event):
        iid = self._hit_check(self.comp_tree, event)
        if not iid or iid not in self.comp_cand:
            return
        if self.comp_cand[iid].status not in _CHECKABLE:
            return
        self._set_row(self.comp_tree, self.comp_checked, iid, not self.comp_checked[iid])
        self._update_comp_header()
        self._update_apply_state()

    def _comp_set_all(self, value):
        for iid, cand in self.comp_cand.items():
            if cand.status in _CHECKABLE:
                self._set_row(self.comp_tree, self.comp_checked, iid, value)
        self._update_comp_header()
        self._update_apply_state()

    def _comp_toggle_all(self):
        checkable = [iid for iid, c in self.comp_cand.items() if c.status in _CHECKABLE]
        all_on = bool(checkable) and all(self.comp_checked[i] for i in checkable)
        self._comp_set_all(not all_on)

    def _update_comp_header(self):
        checkable = [iid for iid, c in self.comp_cand.items() if c.status in _CHECKABLE]
        all_on = bool(checkable) and all(self.comp_checked[i] for i in checkable)
        try:
            self.comp_tree.heading("check", text=CHECKED if all_on else UNCHECKED)
        except tk.TclError:
            pass

    def _selected_local_completion(self):
        if self.comp_tree is None:
            return None, None, None
        selected = self.comp_tree.selection()
        if len(selected) != 1:
            return None, None, None
        iid = selected[0]
        candidate = self.comp_cand.get(iid)
        entry = (
            self.data_manager.data.get(candidate.hack_id)
            if candidate is not None
            else None
        )
        if not isinstance(entry, dict) or not entry.get("local_save_entry"):
            return iid, candidate, None
        return iid, candidate, entry

    def _completion_selection_changed(self, _event=None):
        iid, candidate, local_entry = self._selected_local_completion()
        self._set_analysis_detail(self.comp_analysis_label, candidate)
        forget_enabled = bool(
            candidate
            and candidate.match_source == save_sync.MATCH_SOURCE_SAVED_ALIAS
            and self.config_manager is not None
        )
        local_enabled = bool(iid and candidate and local_entry)
        try:
            self.forget_match_button.config(
                state="normal" if forget_enabled else "disabled"
            )
            self.edit_local_button.config(
                state="normal" if local_enabled else "disabled"
            )
            self.remove_local_button.config(
                state="normal" if local_enabled else "disabled"
            )
        except (tk.TclError, AttributeError):
            pass

    def _edit_selected_local_entry(self):
        iid, candidate, entry = self._selected_local_completion()
        if not iid or candidate is None or entry is None:
            return
        EditLocalSaveEntryDialog(
            self.win,
            candidate,
            entry,
            on_saved=lambda metadata: self._apply_local_entry_edit(
                iid, candidate, metadata
            ),
        ).show()

    def _apply_local_entry_edit(self, iid, candidate, metadata):
        if not save_sync.update_local_entry(
            self.data_manager,
            candidate.hack_id,
            metadata.title,
            metadata.exits,
            difficulty=metadata.difficulty,
            hack_types=metadata.hack_types,
        ):
            messagebox.showerror(
                "Save Data Sync",
                "The local collection entry could not be updated.",
                parent=self.win,
            )
            return

        candidate.title = metadata.title
        candidate.total_exits = metadata.exits
        candidate.status = save_sync.classify(
            candidate.collected_exits,
            metadata.exits,
            candidate.already_completed,
            self.mark_all,
        )
        values = list(self.comp_tree.item(iid, "values"))
        values[1] = candidate.title
        values[3] = _STATUS_LABEL.get(candidate.status, candidate.status)
        values[7] = candidate.exits_display
        self.comp_tree.item(iid, values=values)
        self._update_apply_state()
        if self.on_applied:
            self.on_applied()
        messagebox.showinfo(
            "Save Data Sync",
            "Local collection metadata updated. Completion state was not "
            "changed automatically.",
            parent=self.win,
        )

    def _remove_selected_local_entry(self):
        _iid, candidate, entry = self._selected_local_completion()
        if candidate is None or entry is None:
            return
        if not messagebox.askyesno(
            "Remove Local Entry",
            f"Remove '{entry.get('title', candidate.title)}' from the "
            "collection?\n\nThe save file will not be deleted. Any saved "
            "save-file associations to this local entry will also be removed.",
            parent=self.win,
        ):
            return

        removed, _legacy_count = save_sync.remove_local_entry(
            self.data_manager, None, candidate.hack_id
        )
        if not removed:
            messagebox.showerror(
                "Save Data Sync",
                "The local collection entry could not be removed.",
                parent=self.win,
            )
            return
        association_count = save_sync_sources.remove_associations_for_hack(
            self.config_manager, candidate.hack_id
        )
        if self.on_applied:
            self.on_applied()
        self.win.destroy()
        messagebox.showinfo(
            "Save Data Sync",
            "Local collection entry removed. The save file was left "
            f"untouched. Removed {association_count} saved match(es).",
            parent=self.parent.winfo_toplevel(),
        )

    def _forget_selected_match(self):
        selected = self.comp_tree.selection() if self.comp_tree else ()
        if len(selected) != 1:
            return
        candidate = self.comp_cand.get(selected[0])
        if not candidate or (
            candidate.match_source != save_sync.MATCH_SOURCE_SAVED_ALIAS
        ):
            return

        if not messagebox.askyesno(
            "Save Data Sync",
            f"Forget the saved match for {candidate.save_name}?\n\n"
            "The review window will close. Scan again to choose another match.",
            parent=self.win,
        ):
            return

        if save_sync_sources.forget_candidate_association(
            self.config_manager, candidate
        ):
            if self.logger:
                self.logger.log(
                    f"Forgot saved match for {candidate.save_name}",
                    "Information",
                )
            self.win.destroy()
            messagebox.showinfo(
                "Save Data Sync",
                "Saved match forgotten. Scan the save directory again to "
                "review or replace it.",
                parent=self.parent.winfo_toplevel(),
            )

    # -- orphan tab -----------------------------------------------------------

    def _build_orphan_tab(self, notebook):
        tab = ttk.Frame(notebook, padding=10)

        ttk.Label(
            tab,
            text="These saves matched no hack in your collection. An initial KaizOFF "
                 "catalogue match runs automatically during the scan: safe matches "
                 "resolve automatically, while abbreviations and other plausible "
                 "matches are suggested for review. Select a row to refine the search "
                 "or create a local entry.",
            wraplength=780, foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        columns = (
            "check", "file", "confidence", "result", "hack", "difficulty"
        )
        self.orph_tree = self._make_tree(
            tab, columns,
            {
                "check": ("", 34, "center", False),
                "file": ("Save File", 220, "w", True),
                "confidence": ("Confidence", 92, "center", False),
                "result": ("Result", 145, "w", False),
                "hack": ("Resolved Hack", 215, "w", True),
                "difficulty": ("Difficulty", 105, "w", False),
            },
            selectmode="browse",
        )
        self.orph_tree.bind("<Button-1>", self._on_orph_click)
        self.orph_tree.bind(
            "<<TreeviewSelect>>", self._orphan_selection_changed
        )
        # Clicking the check-column header toggles all selectable rows.
        self.orph_tree.heading(
            "check", text=UNCHECKED, command=self._orph_toggle_all
        )
        self.orph_analysis_label = ttk.Label(
            tab,
            text=_analysis_detail(None),
            foreground="gray",
            wraplength=920,
        )
        self.orph_analysis_label.pack(anchor="w", pady=(7, 0))

        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Button(controls, text="Select All", command=lambda: self._orph_set_all(True)).pack(side="left")
        ttk.Button(controls, text="Select None", command=lambda: self._orph_set_all(False)).pack(side="left", padx=(8, 0))
        self.manual_search_button = ttk.Button(
            controls, text="Search Selected...",
            command=self._manual_search_selected,
        )
        self.manual_search_button.pack(side="left", padx=(12, 0))
        self.local_entry_button = ttk.Button(
            controls, text="Local Entry...",
            command=self._create_local_entry_selected,
        )
        self.local_entry_button.pack(side="left", padx=(8, 0))

        self.lookup_button = ttk.Button(
            controls, text="Retry checked lookup", command=self._toggle_lookup
        )
        self.lookup_button.pack(side="right")
        self.lookup_status = ttk.Label(controls, text="", foreground="gray")
        self.lookup_status.pack(side="right", padx=(0, 10))
        return tab

    def _populate_orphans(self):
        for cand in self.unmatched:
            iid = self.orph_tree.insert(
                "", "end",
                values=(
                    UNCHECKED, cand.save_name, _confidence_label(cand),
                    _RESOLUTION_LABEL[save_sync.RESOLUTION_NONE], "", ""
                ),
            )
            self.orph_cand[iid] = cand
            self.orph_checked[iid] = False
            self.orph_iid[id(cand)] = iid
            if cand.resolution != save_sync.RESOLUTION_NONE:
                self._render_orphan_candidate(iid, cand)
        self._update_orph_header()

    def _orph_locked(self, cand):
        """A row can't be toggled once it resolves to a non-actionable result.

        Also locks saves that resolve to a hack already marked completed, so an
        existing completion date can never be overwritten by the sync.
        """
        if cand.resolution == save_sync.RESOLUTION_EXISTS and cand.already_completed:
            return True
        return bool(cand.resolution) and cand.resolution not in _ORPHAN_ACTIONABLE

    def _on_orph_click(self, event):
        if self._lookup_running:
            return
        iid = self._hit_check(self.orph_tree, event)
        if not iid or iid not in self.orph_cand:
            return
        if self._orph_locked(self.orph_cand[iid]):
            return
        self._set_row(self.orph_tree, self.orph_checked, iid, not self.orph_checked[iid])
        self._update_orph_header()
        self._update_apply_state()

    def _orph_set_all(self, value):
        if self._lookup_running:
            return
        for iid, cand in self.orph_cand.items():
            if self._orph_locked(cand):
                continue
            self._set_row(self.orph_tree, self.orph_checked, iid, value)
        self._update_orph_header()
        self._update_apply_state()

    def _orph_toggle_all(self):
        if self._lookup_running:
            return
        toggleable = [iid for iid, c in self.orph_cand.items() if not self._orph_locked(c)]
        all_on = bool(toggleable) and all(self.orph_checked[i] for i in toggleable)
        self._orph_set_all(not all_on)

    def _update_orph_header(self):
        toggleable = [iid for iid, c in self.orph_cand.items() if not self._orph_locked(c)]
        all_on = bool(toggleable) and all(self.orph_checked[i] for i in toggleable)
        try:
            self.orph_tree.heading("check", text=CHECKED if all_on else UNCHECKED)
        except tk.TclError:
            pass

    def _orphan_selection_changed(self, _event=None):
        selected = self.orph_tree.selection() if self.orph_tree else ()
        candidate = (
            self.orph_cand.get(selected[0]) if len(selected) == 1 else None
        )
        self._set_analysis_detail(self.orph_analysis_label, candidate)

    def _create_local_entry_selected(self):
        if self._lookup_running:
            return
        selected = self.orph_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo(
                "Save Data Sync",
                "Select one unmatched save row first.",
                parent=self.win,
            )
            return

        iid = selected[0]
        candidate = self.orph_cand.get(iid)
        if candidate is None:
            return
        dialog = LocalSaveEntryDialog(
            self.win,
            candidate,
            self.data_manager.data,
            on_selected=lambda resolution: self._set_orphan_resolution(
                iid, resolution, manual=True
            ),
        )
        dialog.show()

    def _manual_search_selected(self):
        if self._lookup_running:
            return
        selected = self.orph_tree.selection()
        if len(selected) != 1:
            messagebox.showinfo(
                "Save Data Sync",
                "Select one unmatched save row to search manually.",
                parent=self.win,
            )
            return

        iid = selected[0]
        cand = self.orph_cand.get(iid)
        if cand is None:
            return
        if cand.resolution in _ORPHAN_ACTIONABLE:
            messagebox.showinfo(
                "Save Data Sync",
                "This save already has a usable SMWCentral match.",
                parent=self.win,
            )
            return

        existing_ids = set(self.data_manager.data.keys())
        ManualSmwcSearchDialog(
            self.win,
            cand,
            existing_ids,
            fetch_fn=self.fetch_fn,
            logger=self.logger,
            on_selected=lambda resolution: self._apply_manual_resolution(
                iid, resolution
            ),
            lookup_service=(
                None if self.fetch_fn is not None else self._catalogue_lookup()
            ),
        ).show()

    def _apply_manual_resolution(self, iid, resolution):
        if self._set_orphan_resolution(iid, resolution, manual=True):
            try:
                self.lookup_status.config(text="Manual match selected")
            except tk.TclError:
                pass
            self._update_apply_state()

    # -- SMWC catalogue lookup (threaded) ------------------------------------

    def _toggle_lookup(self):
        if self._lookup_running:
            self._cancel_lookup = True
            self.lookup_button.config(text="Cancelling...", state="disabled")
            return

        targets = [
            iid for iid, on in self.orph_checked.items()
            if on and self.orph_cand[iid].resolution in (save_sync.RESOLUTION_NONE,
                                                         save_sync.RESOLUTION_ERROR)
        ]
        if not targets:
            messagebox.showinfo(
                "Save Data Sync",
                "Check one or more lookup-error saves to retry.",
                parent=self.win,
            )
            return

        self._cancel_lookup = False
        self._lookup_running = True
        self.lookup_button.config(text="Cancel Lookup")
        self.manual_search_button.config(state="disabled")
        self.local_entry_button.config(state="disabled")
        self._update_apply_state()

        existing_ids = set(self.data_manager.data.keys())
        threading.Thread(
            target=self._lookup_worker, args=(targets, existing_ids), daemon=True
        ).start()

    def _lookup_worker(self, targets, existing_ids):
        total = len(targets)
        lookup = None if self.fetch_fn is not None else self._catalogue_lookup()
        for index, iid in enumerate(targets, start=1):
            if self._cancel_lookup:
                break
            cand = self.orph_cand[iid]
            if lookup is not None:
                resolution = lookup.resolve_automatic(cand.save_name, existing_ids)
            else:
                resolution = save_sync.resolve_orphan(
                    cand.save_name, existing_ids, fetch_fn=self.fetch_fn,
                    log=self.logger.log if self.logger else None,
                )
            self._ui(self._apply_lookup_result, iid, resolution, index, total)
            if resolution.get("catalogue_unavailable"):
                self._ui(self._lookup_done, True)
                return
        self._ui(self._lookup_done, False)

    def _apply_lookup_result(self, iid, resolution, index, total):
        if self._set_orphan_resolution(iid, resolution):
            self.lookup_status.config(text=f"Looked up {index}/{total}...")

    def _set_orphan_resolution(self, iid, resolution, manual=False):
        cand = self.orph_cand.get(iid)
        if cand is None:
            return False
        cand.manual_selection = bool(manual)
        save_sync.attach_resolution(
            cand, resolution, self.data_manager, self.mark_all
        )
        return self._render_orphan_candidate(iid, cand, manual=manual)

    def _render_orphan_candidate(self, iid, cand, manual=False):
        label = _RESOLUTION_LABEL.get(cand.resolution, cand.resolution)
        hack_name = cand.title if cand.resolution in _ORPHAN_ACTIONABLE else ""
        difficulty = ""
        if cand.resolution == save_sync.RESOLUTION_REVIEW:
            score = float(getattr(cand, "suggested_confidence", 0.0) or 0.0)
            classification = str(
                getattr(cand, "suggested_classification", "") or "Review"
            )
            label = f"{classification} {score:.0%}"
            hack_name = str(getattr(cand, "suggested_title", "") or "")
            difficulty = str(getattr(cand, "suggested_difficulty", "") or "")
        elif cand.resolution == save_sync.RESOLUTION_RESOLVED and cand.resolved_hack:
            difficulty = save_sync._smwc_entry_fields(
                cand.resolved_hack
            )["current_difficulty"]
        elif cand.resolution == save_sync.RESOLUTION_LOCAL:
            difficulty = "Local"
        elif cand.resolution == save_sync.RESOLUTION_EXISTS:
            existing = self.data_manager.data.get(cand.resolved_hack_id, {})
            difficulty = existing.get("current_difficulty", "")
            if cand.already_completed:
                label = _STATUS_LABEL[save_sync.STATUS_ALREADY_COMPLETED]

        if manual and cand.resolution in _ORPHAN_ACTIONABLE:
            checked = True
        elif cand.resolution == save_sync.RESOLUTION_RESOLVED:
            checked = True
        elif cand.resolution == save_sync.RESOLUTION_EXISTS:
            checked = cand.status == save_sync.STATUS_COMPLETED
        else:
            checked = False
        self.orph_checked[iid] = checked

        values = (
            CHECKED if checked else UNCHECKED,
            cand.save_name,
            _confidence_label(cand),
            label,
            hack_name,
            difficulty,
        )
        try:
            self.orph_tree.item(
                iid,
                values=values,
                tags=("locked",) if self._orph_locked(cand) else (),
            )
        except tk.TclError:
            return False
        self._update_orph_header()
        self._update_apply_state()
        return True

    def _lookup_done(self, catalogue_unavailable=False):
        self._lookup_running = False
        self._cancel_lookup = False
        try:
            self.lookup_button.config(text="Retry checked lookup", state="normal")
            self.manual_search_button.config(state="normal")
            self.local_entry_button.config(state="normal")
            self.lookup_status.config(
                text=(
                    "KaizOFF unavailable - manual search can use SMWC fallback"
                    if catalogue_unavailable
                    else ""
                )
            )
        except tk.TclError:
            pass
        self._update_apply_state()

    # -- shared tree helpers --------------------------------------------------

    def _make_tree(self, parent, columns, headings, selectmode="none"):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(
            frame, columns=columns, show="headings", selectmode=selectmode
        )
        for col, (text, width, anchor, stretch) in headings.items():
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor=anchor, stretch=stretch)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.tag_configure("locked", foreground="gray")
        tree.tag_configure("uncertain", foreground="#b8860b")
        return tree

    def _set_analysis_detail(self, label, candidate):
        if label is None:
            return
        try:
            label.config(text=_analysis_detail(candidate))
        except tk.TclError:
            pass

    def _hit_check(self, tree, event):
        """Return the row iid if the click landed in the check column, else None."""
        if tree.identify_region(event.x, event.y) != "cell":
            return None
        if tree.identify_column(event.x) != "#1":
            return None
        return tree.identify_row(event.y)

    def _set_row(self, tree, state, iid, value):
        state[iid] = value
        values = list(tree.item(iid, "values"))
        values[0] = CHECKED if value else UNCHECKED
        tree.item(iid, values=values)

    def _ui(self, func, *args):
        """Run a UI update on the Tk main thread if the window still exists."""
        try:
            if self.win and self.win.winfo_exists():
                self.win.after(0, lambda: func(*args))
        except tk.TclError:
            pass

    def _on_destroy(self, event):
        if event.widget is self.win:
            self._cancel_lookup = True

    # -- apply ----------------------------------------------------------------

    def _selected_completions(self):
        return [self.comp_cand[iid] for iid, on in self.comp_checked.items() if on]

    def _selected_orphans(self):
        out = []
        for iid, on in self.orph_checked.items():
            if not on:
                continue
            cand = self.orph_cand[iid]
            if cand.resolution in _ORPHAN_ACTIONABLE:
                out.append(cand)
        return out

    def _build_buttons(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(12, 0))
        self.apply_button = ttk.Button(
            bar, text="Apply Selected", style="Accent.TButton", command=self._apply
        )
        self.apply_button.pack(side="right")
        ttk.Button(bar, text="Cancel", command=self.win.destroy).pack(side="right", padx=(0, 8))
        ttk.Button(
            bar,
            text="Export Diagnostics...",
            command=self._export_diagnostics,
        ).pack(side="left")

    def _export_diagnostics(self):
        destination = filedialog.asksaveasfilename(
            parent=self.win,
            title="Export Save Data Sync Diagnostics",
            defaultextension=".json",
            initialfile=save_sync.diagnostic_filename(),
            filetypes=(("JSON diagnostic report", "*.json"), ("All files", "*.*")),
        )
        if not destination:
            return

        try:
            written = save_sync.write_diagnostic_report(destination, self.candidates)
        except Exception as exc:  # pragma: no cover - defensive UI boundary
            if self.logger:
                self.logger.log(f"Save diagnostic export failed: {exc}", "Error")
            messagebox.showerror(
                "Save Data Sync",
                f"Failed to export diagnostics:\n{exc}",
                parent=self.win,
            )
            return

        if self.logger:
            self.logger.log(
                f"Save Data Sync diagnostics exported: {os.path.basename(written)}",
                "Information",
            )
        messagebox.showinfo(
            "Save Data Sync",
            "Diagnostic report exported.\n\n"
            "The report contains no absolute paths or raw save bytes.",
            parent=self.win,
        )

    def _update_apply_state(self):
        count = len(self._selected_completions()) + len(self._selected_orphans())
        text = f"Apply Selected ({count})" if count else "Apply Selected"
        state = "normal" if count and not self._lookup_running else "disabled"
        try:
            self.apply_button.config(text=text, state=state)
        except (tk.TclError, AttributeError):
            pass

    def _apply(self):
        if self._lookup_running:
            return
        completions = self._selected_completions()
        orphans = self._selected_orphans()
        new_imports = [
            c for c in orphans
            if c.resolution == save_sync.RESOLUTION_RESOLVED
        ]
        local_imports = [
            c for c in orphans
            if c.resolution == save_sync.RESOLUTION_LOCAL
        ]
        existing_updates = [
            c for c in orphans
            if c.resolution == save_sync.RESOLUTION_EXISTS
            and c.status == save_sync.STATUS_COMPLETED
        ]
        manual_matches = [c for c in orphans if c.manual_selection]

        if not completions and not orphans:
            return

        try:
            # 'exists' orphans behave like a normal completion update.
            marked = save_sync.apply_candidates(completions + existing_updates, self.data_manager)
            imported = 0
            for cand in new_imports:
                if save_sync.import_orphan(cand, self.data_manager, self.mark_all):
                    imported += 1
            local_created = 0
            for cand in local_imports:
                if save_sync.import_local_orphan(
                    cand, self.data_manager, self.mark_all
                ):
                    local_created += 1
            if imported or new_imports or local_created or local_imports:
                self.data_manager.force_save()

            remembered = 0
            for cand in manual_matches:
                target_id = str(cand.resolved_hack_id or "")
                if target_id not in self.data_manager.data:
                    continue
                if save_sync_sources.remember_candidate_association(
                    self.config_manager, cand, target_id
                ):
                    remembered += 1
        except Exception as exc:  # pragma: no cover - defensive
            if self.logger:
                self.logger.log(f"Save sync apply failed: {exc}", "Error")
            messagebox.showerror("Save Data Sync", f"Failed to apply changes:\n{exc}", parent=self.win)
            return

        if self.logger:
            self.logger.log(
                f"Save Data Sync: {marked} completion update(s), "
                f"{imported} SMWC hack(s) imported, "
                f"{local_created} local hack(s) created, "
                f"{remembered} saved match(es)",
                "Information",
            )

        if self.on_applied:
            try:
                self.on_applied()
            except Exception as exc:  # pragma: no cover - defensive
                if self.logger:
                    self.logger.log(f"Collection refresh after sync failed: {exc}", "Error")

        self.win.destroy()
        messagebox.showinfo(
            "Save Data Sync",
            f"Marked {marked} hack(s) completed, imported {imported} "
            f"SMWC hack(s), created {local_created} local hack(s), and "
            f"remembered {remembered} manual match(es).",
            parent=self.parent.winfo_toplevel(),
        )

    def _center(self):
        self.win.update_idletasks()
        try:
            root = self.parent.winfo_toplevel()
            x = root.winfo_x() + (root.winfo_width() - self.win.winfo_width()) // 2
            y = root.winfo_y() + (root.winfo_height() - self.win.winfo_height()) // 2
            self.win.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        except Exception:
            pass
