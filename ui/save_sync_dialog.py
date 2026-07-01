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
from tkinter import ttk, messagebox

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


class SaveSyncDialog:
    """Modal preview dialog for applying save-sync results."""

    def __init__(self, parent, candidates, data_manager, logger=None,
                 on_applied=None, fetch_fn=None, mark_all=False):
        self.parent = parent
        self.data_manager = data_manager
        self.logger = logger
        self.on_applied = on_applied
        self.fetch_fn = fetch_fn
        self.mark_all = mark_all

        self.matched = sorted(
            (c for c in candidates if c.hack_id),
            key=lambda c: (_STATUS_ORDER.get(c.status, 9), c.title.lower()),
        )
        self.unmatched = sorted(
            (c for c in candidates if not c.hack_id),
            key=lambda c: c.save_name.lower(),
        )

        self.win = None
        # Completion tab state
        self.comp_tree = None
        self.comp_checked = {}
        self.comp_cand = {}
        # Orphan tab state
        self.orph_tree = None
        self.orph_checked = {}
        self.orph_cand = {}
        self.orph_iid = {}  # candidate id() -> iid, for background updates

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

        columns = ("check", "title", "file", "decision", "date", "exits")
        self.comp_tree = self._make_tree(
            tab, columns,
            {
                "check": ("", 34, "center", False),
                "title": ("Hack", 220, "w", True),
                "file": ("Save File", 190, "w", True),
                "decision": ("Decision", 90, "w", False),
                "date": ("Play Date", 90, "center", False),
                "exits": ("Exits", 70, "center", False),
            },
        )
        self.comp_tree.bind("<Button-1>", self._on_comp_click)
        # Clicking the check-column header toggles all rows.
        self.comp_tree.heading("check", text=UNCHECKED, command=self._comp_toggle_all)

        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Select All", command=lambda: self._comp_set_all(True)).pack(side="left")
        ttk.Button(btns, text="Select None", command=lambda: self._comp_set_all(False)).pack(side="left", padx=(8, 0))
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
                values=(glyph, cand.title, cand.save_name,
                        _STATUS_LABEL.get(cand.status, cand.status),
                        cand.completed_date or "-", cand.exits_display),
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

    # -- orphan tab -----------------------------------------------------------

    def _build_orphan_tab(self, notebook):
        tab = ttk.Frame(notebook, padding=10)

        ttk.Label(
            tab,
            text="These saves matched no hack in your collection. Check the ones you "
                 "recognize, look them up on SMWCentral, then import the confident "
                 "matches. Each lookup is a network request, so only check what you need.",
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
        )
        self.orph_tree.bind("<Button-1>", self._on_orph_click)
        # Clicking the check-column header toggles all selectable rows.
        self.orph_tree.heading("check", text=UNCHECKED, command=self._orph_toggle_all)

        controls = ttk.Frame(tab)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Button(controls, text="Select All", command=lambda: self._orph_set_all(True)).pack(side="left")
        ttk.Button(controls, text="Select None", command=lambda: self._orph_set_all(False)).pack(side="left", padx=(8, 0))

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
        cand = self.orph_cand.get(iid)
        if cand is None:
            return
        save_sync.attach_resolution(cand, resolution, self.data_manager, self.mark_all)

        label = _RESOLUTION_LABEL.get(cand.resolution, cand.resolution)
        hack_name = cand.title if cand.resolution in _ORPHAN_ACTIONABLE else ""
        difficulty = ""
        if cand.resolution == save_sync.RESOLUTION_RESOLVED and cand.resolved_hack:
            difficulty = save_sync._smwc_entry_fields(cand.resolved_hack)["current_difficulty"]
        elif cand.resolution == save_sync.RESOLUTION_EXISTS:
            existing = self.data_manager.data.get(cand.resolved_hack_id, {})
            difficulty = existing.get("current_difficulty", "")
            if cand.already_completed:
                label = _STATUS_LABEL[save_sync.STATUS_ALREADY_COMPLETED]  # "Already synced"

        # Auto-check actionable results; new imports always, existing only when
        # the save actually meets the completion rule.
        if cand.resolution == save_sync.RESOLUTION_RESOLVED:
            checked = True
        elif cand.resolution == save_sync.RESOLUTION_EXISTS:
            checked = cand.status == save_sync.STATUS_COMPLETED
        else:
            checked = False
        self.orph_checked[iid] = checked

        values = (CHECKED if checked else UNCHECKED, cand.save_name, label, hack_name, difficulty)
        try:
            self.orph_tree.item(iid, values=values,
                                tags=("locked",) if self._orph_locked(cand) else ())
        except tk.TclError:
            return
        self.lookup_status.config(text=f"Looked up {index}/{total}...")
        self._update_orph_header()

    def _lookup_done(self):
        self._lookup_running = False
        self._cancel_lookup = False
        try:
            self.lookup_button.config(text="Look up checked on SMWC", state="normal")
            self.lookup_status.config(text="")
        except tk.TclError:
            pass
        self._update_apply_state()

    # -- shared tree helpers --------------------------------------------------

    def _make_tree(self, parent, columns, headings):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="none")
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
        new_imports = [c for c in orphans if c.resolution == save_sync.RESOLUTION_RESOLVED]
        existing_updates = [c for c in orphans if c.resolution == save_sync.RESOLUTION_EXISTS]

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
        except Exception as exc:  # pragma: no cover - defensive
            if self.logger:
                self.logger.log(f"Save sync apply failed: {exc}", "Error")
            messagebox.showerror("Save Data Sync", f"Failed to apply changes:\n{exc}", parent=self.win)
            return

        if self.logger:
            self.logger.log(
                f"Save Data Sync: {marked} completion update(s), {imported} hack(s) imported",
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
            f"Marked {marked} hack(s) completed and imported {imported} new hack(s).",
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
