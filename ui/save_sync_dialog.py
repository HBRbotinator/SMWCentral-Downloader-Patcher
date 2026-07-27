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
    save_sync.RESOLUTION_ERROR: "Lookup error",
}
# Orphan resolutions the user can actually act on.
_ORPHAN_ACTIONABLE = {save_sync.RESOLUTION_RESOLVED, save_sync.RESOLUTION_EXISTS}


class ManualSmwcSearchDialog:
    """Modal free-text SMWC search for one unresolved save."""

    def __init__(self, parent, candidate, existing_ids, fetch_fn=None,
                 logger=None, on_selected=None):
        self.parent = parent
        self.candidate = candidate
        self.existing_ids = set(existing_ids)
        self.fetch_fn = fetch_fn
        self.logger = logger
        self.on_selected = on_selected

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
            text="Search SMWCentral manually, select the correct hack, then "
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
        self.status_label.config(text="Searching SMWCentral...")
        self.options.clear()
        for iid in self.result_tree.get_children():
            self.result_tree.delete(iid)

        threading.Thread(
            target=self._search_worker, args=(query,), daemon=True
        ).start()

    def _search_worker(self, query):
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
        for option in options:
            release = "Obsolete" if option["obsolete"] else "Current"
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

        if result.get("status") == save_sync.RESOLUTION_ERROR:
            message = "SMWCentral search failed. Check the log and try again."
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
        if len(selected) != 1:
            return
        option = self.options.get(selected[0])
        if not option:
            return

        resolution = save_sync.resolution_for_selected_hack(
            option["hack"], self.existing_ids
        )
        if resolution["status"] not in _ORPHAN_ACTIONABLE:
            self.status_label.config(text="The selected result cannot be used.")
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


class SaveSyncDialog:
    """Modal preview dialog for applying save-sync results."""

    def __init__(self, parent, candidates, data_manager, logger=None,
                 on_applied=None, fetch_fn=None, mark_all=False,
                 config_manager=None):
        self.parent = parent
        self.data_manager = data_manager
        self.logger = logger
        self.on_applied = on_applied
        self.fetch_fn = fetch_fn
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
        # Orphan tab state
        self.orph_tree = None
        self.orph_checked = {}
        self.orph_cand = {}
        self.orph_iid = {}  # candidate id() -> iid, for background updates
        self.manual_search_button = None

        self._cancel_lookup = False
        self._lookup_running = False

    # -- construction ---------------------------------------------------------

    def show(self):
        self.win = tk.Toplevel(self.parent)
        self.win.title("Save Data Sync - Review Changes")
        self.win.geometry("820x620")
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
        ttk.Label(tab, text=summary, foreground="gray").pack(anchor="w", pady=(0, 8))

        columns = (
            "check", "title", "file", "decision", "source", "date", "exits"
        )
        self.comp_tree = self._make_tree(
            tab, columns,
            {
                "check": ("", 34, "center", False),
                "title": ("Hack", 205, "w", True),
                "file": ("Save File", 175, "w", True),
                "decision": ("Decision", 90, "w", False),
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
        self.comp_tree.heading("check", text=UNCHECKED, command=self._comp_toggle_all)

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Select All", command=lambda: self._comp_set_all(True)).pack(side="left")
        ttk.Button(btns, text="Select None", command=lambda: self._comp_set_all(False)).pack(side="left", padx=(8, 0))
        self.forget_match_button = ttk.Button(
            btns,
            text="Forget Saved Match",
            state="disabled",
            command=self._forget_selected_match,
        )
        self.forget_match_button.pack(side="right")
        return tab

    def _populate_completion(self):
        for cand in self.matched:
            checkable = cand.status in _CHECKABLE
            default_checked = cand.status == save_sync.STATUS_COMPLETED
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

    def _completion_selection_changed(self, _event=None):
        enabled = False
        if self.comp_tree is not None:
            selected = self.comp_tree.selection()
            if len(selected) == 1:
                candidate = self.comp_cand.get(selected[0])
                enabled = bool(
                    candidate
                    and candidate.match_source
                    == save_sync.MATCH_SOURCE_SAVED_ALIAS
                    and self.config_manager is not None
                )
        try:
            self.forget_match_button.config(
                state="normal" if enabled else "disabled"
            )
        except (tk.TclError, AttributeError):
            pass

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

        if save_sync.forget_save_association(
            self.config_manager, candidate.save_name
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
            text="These saves matched no hack in your collection. Use the checked "
                 "lookup for strict exact-title matches, or select one row and search "
                 "SMWCentral manually for abbreviations and alternate names.",
            wraplength=780, foreground="gray",
        ).pack(anchor="w", pady=(0, 8))

        columns = ("check", "file", "result", "hack", "difficulty")
        self.orph_tree = self._make_tree(
            tab, columns,
            {
                "check": ("", 34, "center", False),
                "file": ("Save File", 240, "w", True),
                "result": ("Result", 110, "w", False),
                "hack": ("Resolved Hack", 230, "w", True),
                "difficulty": ("Difficulty", 110, "w", False),
            },
            selectmode="browse",
        )
        self.orph_tree.bind("<Button-1>", self._on_orph_click)
        # Clicking the check-column header toggles all selectable rows.
        self.orph_tree.heading("check", text=UNCHECKED, command=self._orph_toggle_all)

        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Button(controls, text="Select All", command=lambda: self._orph_set_all(True)).pack(side="left")
        ttk.Button(controls, text="Select None", command=lambda: self._orph_set_all(False)).pack(side="left", padx=(8, 0))
        self.manual_search_button = ttk.Button(
            controls, text="Search Selected...",
            command=self._manual_search_selected,
        )
        self.manual_search_button.pack(side="left", padx=(12, 0))

        self.lookup_button = ttk.Button(
            controls, text="Look up checked on SMWC", command=self._toggle_lookup
        )
        self.lookup_button.pack(side="right")
        self.lookup_status = ttk.Label(controls, text="", foreground="gray")
        self.lookup_status.pack(side="right", padx=(0, 10))
        return tab

    def _populate_orphans(self):
        for cand in self.unmatched:
            iid = self.orph_tree.insert(
                "", "end",
                values=(UNCHECKED, cand.save_name,
                        _RESOLUTION_LABEL[save_sync.RESOLUTION_NONE], "", ""),
            )
            self.orph_cand[iid] = cand
            self.orph_checked[iid] = False
            self.orph_iid[id(cand)] = iid
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
        ).show()

    def _apply_manual_resolution(self, iid, resolution):
        if self._set_orphan_resolution(iid, resolution, manual=True):
            try:
                self.lookup_status.config(text="Manual match selected")
            except tk.TclError:
                pass
            self._update_apply_state()

    # -- SMWC lookup (threaded) ----------------------------------------------

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
                "Check one or more unmatched saves to look up first.",
                parent=self.win,
            )
            return

        self._cancel_lookup = False
        self._lookup_running = True
        self.lookup_button.config(text="Cancel Lookup")
        self.manual_search_button.config(state="disabled")
        self._update_apply_state()

        existing_ids = set(self.data_manager.data.keys())
        threading.Thread(
            target=self._lookup_worker, args=(targets, existing_ids), daemon=True
        ).start()

    def _lookup_worker(self, targets, existing_ids):
        total = len(targets)
        for index, iid in enumerate(targets, start=1):
            if self._cancel_lookup:
                break
            cand = self.orph_cand[iid]
            resolution = save_sync.resolve_orphan(
                cand.save_name, existing_ids, fetch_fn=self.fetch_fn,
                log=self.logger.log if self.logger else None,
            )
            self._ui(self._apply_lookup_result, iid, resolution, index, total)
        self._ui(self._lookup_done)

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

        label = _RESOLUTION_LABEL.get(cand.resolution, cand.resolution)
        hack_name = cand.title if cand.resolution in _ORPHAN_ACTIONABLE else ""
        difficulty = ""
        if cand.resolution == save_sync.RESOLUTION_RESOLVED and cand.resolved_hack:
            difficulty = save_sync._smwc_entry_fields(
                cand.resolved_hack
            )["current_difficulty"]
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
        return True

    def _lookup_done(self):
        self._lookup_running = False
        self._cancel_lookup = False
        try:
            self.lookup_button.config(text="Look up checked on SMWC", state="normal")
            self.manual_search_button.config(state="normal")
            self.lookup_status.config(text="")
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
        tree.configure(yscrollcommand=vsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.tag_configure("locked", foreground="gray")
        tree.tag_configure("uncertain", foreground="#b8860b")
        return tree

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
            if imported or new_imports:
                self.data_manager.force_save()

            remembered = 0
            for cand in manual_matches:
                target_id = str(cand.resolved_hack_id or "")
                if target_id not in self.data_manager.data:
                    continue
                if save_sync.remember_save_association(
                    self.config_manager, cand.save_name, target_id
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
                f"{imported} hack(s) imported, "
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
            f"new hack(s), and remembered {remembered} manual match(es).",
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
