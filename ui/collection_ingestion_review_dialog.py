"""Tk review dialog for frozen Collection ingestion sessions.

The dialog only captures explicit ReviewDecision objects. It does not fetch
network data, allocate local Collection identities, finalize plans, or persist
Collection/configuration state.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk

from collection_ingestion import IngestionSource
from collection_ingestion_review_model import (
    CollectionIngestionReviewError,
    CollectionIngestionReviewModel,
)
from collection_reconciliation import (
    FirstClearDecision,
    IgnoredRomDecision,
    RememberedAssociationDecision,
    ReviewAction,
    ReviewDecision,
    ReviewState,
    RomSelectionDecision,
    UserFieldResolution,
)


_IDENTITY_REVIEW_STATES = {
    ReviewState.NEEDS_CONFIRMATION,
    ReviewState.AMBIGUOUS,
    ReviewState.IDENTITY_CONFLICT,
    ReviewState.UNMATCHED,
}


class CollectionIngestionReviewDialog:
    """Review all ingestion matches and collect explicit unresolved decisions."""

    def __init__(
        self,
        parent,
        session,
        *,
        decisions=None,
        on_complete=None,
        on_close=None,
    ):
        self.parent = parent
        self.model = CollectionIngestionReviewModel(session, decisions)
        self.on_complete = on_complete
        self.on_close = on_close

        self.win = None
        self.tree = None
        self.summary_label = None
        self.catalogue_label = None
        self.details = None
        self.done_button = None
        self.attention_var = None
        self.search_var = None
        self.search_status = None
        self.suggestion_tree = None
        self._suggestion_targets = {}
        self._current_group_id = None
        self._action_var = None
        self._rom_action_vars = {}
        self._rom_primary_var = None
        self._rom_initial = {}
        self._user_field_vars = {}
        self._first_clear_var = None
        self._first_clear_values = {}
        self._remember_vars = []
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

        self.win = tk.Toplevel(self.parent)
        self.win.title("Review Collection Import")
        self.win.geometry("1180x760")
        self.win.minsize(940, 620)
        self.win.transient(self.parent)
        self.win.protocol("WM_DELETE_WINDOW", self.close)

        root = ttk.Frame(self.win, padding=14)
        root.pack(fill="both", expand=True)

        heading = ttk.Frame(root)
        heading.pack(fill="x", pady=(0, 10))
        ttk.Label(
            heading,
            text="Review Collection Import",
            font=("Segoe UI", 15, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            heading,
            text=(
                "Matches are based on the frozen KaizOFF catalogue snapshot for this "
                "session. Resolve highlighted items before continuing. Nothing is "
                "written from this dialog."
            ),
            wraplength=1050,
        ).pack(anchor="w", pady=(3, 0))

        status = ttk.Frame(root)
        status.pack(fill="x", pady=(0, 10))
        self.summary_label = ttk.Label(status, font=("Segoe UI", 10, "bold"))
        self.summary_label.pack(side="left")
        self.catalogue_label = ttk.Label(status, foreground="gray")
        self.catalogue_label.pack(side="right")

        toolbar = ttk.Frame(root)
        toolbar.pack(fill="x", pady=(0, 8))
        self.attention_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            toolbar,
            text="Show items needing attention",
            variable=self.attention_var,
            command=self._refresh_rows,
        ).pack(side="left")
        ttk.Button(
            toolbar,
            text="Review Remaining",
            command=self._select_next_unresolved,
        ).pack(side="right")

        pane = ttk.Panedwindow(root, orient="horizontal")
        pane.pack(fill="both", expand=True)

        left = ttk.Frame(pane, padding=(0, 0, 8, 0))
        right = ttk.Frame(pane, padding=(8, 0, 0, 0))
        pane.add(left, weight=3)
        pane.add(right, weight=4)

        columns = ("status", "item", "source", "target", "details")
        self.tree = ttk.Treeview(left, columns=columns, show="headings", selectmode="browse")
        headings = {
            "status": ("Status", 120, False),
            "item": ("Item", 220, True),
            "source": ("Source", 120, False),
            "target": ("Match / target", 210, True),
            "details": ("Evidence", 100, False),
        }
        for column, (label, width, stretch) in headings.items():
            self.tree.heading(column, text=label)
            self.tree.column(column, width=width, minwidth=70, stretch=stretch, anchor="w")
        scroll = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)

        detail_canvas = tk.Canvas(right, highlightthickness=0)
        detail_scroll = ttk.Scrollbar(right, orient="vertical", command=detail_canvas.yview)
        self.details = ttk.Frame(detail_canvas)
        detail_window = detail_canvas.create_window((0, 0), window=self.details, anchor="nw")
        detail_canvas.configure(yscrollcommand=detail_scroll.set)
        detail_canvas.grid(row=0, column=0, sticky="nsew")
        detail_scroll.grid(row=0, column=1, sticky="ns")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.details.bind(
            "<Configure>",
            lambda _event: detail_canvas.configure(scrollregion=detail_canvas.bbox("all")),
        )
        detail_canvas.bind(
            "<Configure>",
            lambda event: detail_canvas.itemconfigure(detail_window, width=event.width),
        )

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(footer, text="Close", command=self.close).pack(side="right")
        self.done_button = ttk.Button(
            footer,
            text="Continue",
            command=self._complete,
        )
        self.done_button.pack(side="right", padx=(0, 8))

        self._refresh_rows()
        self._update_summary()
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
                self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()

    def _center(self):
        try:
            self.win.update_idletasks()
            width = self.win.winfo_width()
            height = self.win.winfo_height()
            x = self.parent.winfo_rootx() + max(0, (self.parent.winfo_width() - width) // 2)
            y = self.parent.winfo_rooty() + max(0, (self.parent.winfo_height() - height) // 2)
            self.win.geometry(f"+{x}+{y}")
        except (tk.TclError, AttributeError):
            pass

    def _refresh_rows(self):
        if not self.tree:
            return
        selected = self._current_group_id
        for item in self.tree.get_children():
            self.tree.delete(item)
        rows = self.model.rows(attention_only=bool(self.attention_var.get()))
        for row in rows:
            target = row.target_title
            if row.target_key and row.target_key.isdecimal():
                target = f"{target} [{row.target_key}]" if target else f"SMWC {row.target_key}"
            details = []
            if row.rom_count:
                details.append(f"{row.rom_count} ROM")
            if row.history_count:
                details.append(f"{row.history_count} play")
            self.tree.insert(
                "",
                "end",
                iid=row.group_id,
                values=(
                    row.status,
                    row.title,
                    ", ".join(row.sources),
                    target,
                    ", ".join(details) or "-",
                ),
            )
        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.see(selected)
        elif rows:
            self.tree.selection_set(rows[0].group_id)
            self.tree.see(rows[0].group_id)
        else:
            self._clear_details("No review items match the current filter.")
        self._update_summary()

    def _update_summary(self):
        summary = self.model.summary()
        summary_text = (
            f"{summary.total_groups} groups  •  "
            f"{summary.ready_groups} ready  •  "
            f"{summary.resolved_blocking_groups} reviewed  •  "
            f"{summary.unresolved_blocking_groups} remaining"
        )
        if summary.suppressed_roms:
            summary_text += f"  •  {summary.suppressed_roms} ROMs suppressed"
        self.summary_label.configure(text=summary_text)
        stale = " • cached/stale" if self.model.session.catalogue_stale else ""
        self.catalogue_label.configure(
            text=f"KaizOFF Index: {self.model.session.catalogue_source}{stale}"
        )
        self.done_button.configure(state="normal" if summary.can_complete else "disabled")

    def _select_next_unresolved(self):
        unresolved = self.model.unresolved_group_ids()
        if not unresolved:
            messagebox.showinfo("Collection Import", "All required review decisions are resolved.", parent=self.win)
            return
        if self.attention_var and not self.attention_var.get():
            self.attention_var.set(True)
            self._refresh_rows()
        for group_id in unresolved:
            if self.tree.exists(group_id):
                self.tree.selection_set(group_id)
                self.tree.focus(group_id)
                self.tree.see(group_id)
                self._render_group(group_id)
                return

    def _on_row_selected(self, _event=None):
        selected = self.tree.selection()
        if len(selected) != 1:
            return
        self._render_group(selected[0])

    def _clear_details(self, message="Select an item to review."):
        for child in self.details.winfo_children():
            child.destroy()
        ttk.Label(self.details, text=message, wraplength=500).pack(anchor="w", padx=4, pady=4)
        self._current_group_id = None

    def _render_group(self, group_id):
        self._current_group_id = group_id
        self.search_var = None
        self.search_status = None
        self.suggestion_tree = None
        self._suggestion_targets = {}
        self._action_var = None
        self._rom_action_vars = {}
        self._rom_primary_var = None
        self._rom_initial = {}
        self._user_field_vars = {}
        self._first_clear_var = None
        self._first_clear_values = {}
        self._remember_vars = []
        for child in self.details.winfo_children():
            child.destroy()
        context = self.model.context(group_id)
        group = context.group
        previous = self.model.decision_for(group_id)

        ttk.Label(
            self.details,
            text=context.row.title,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            self.details,
            text=f"Source: {', '.join(context.row.sources)}   •   {context.row.status}",
            foreground="gray",
        ).pack(anchor="w", pady=(2, 8))

        if group.issues:
            issue_box = ttk.LabelFrame(self.details, text="Review status", padding=8)
            issue_box.pack(fill="x", pady=(0, 8))
            for issue in group.issues:
                ttk.Label(issue_box, text=f"• {issue.reason}", wraplength=520).pack(anchor="w")

        if context.candidate_reasons:
            evidence = ttk.LabelFrame(self.details, text="Matching evidence", padding=8)
            evidence.pack(fill="x", pady=(0, 8))
            for reason in context.candidate_reasons:
                ttk.Label(evidence, text=reason, wraplength=520).pack(anchor="w", pady=1)

        self._action_var = tk.StringVar(value=self._default_action(group, previous))
        self._render_identity(group, context, previous)
        self._render_roms(group, previous)
        self._render_user_conflicts(group, previous)
        self._render_first_clear(group, previous)
        self._render_remember_aliases(context, previous)

        actions = ttk.Frame(self.details)
        actions.pack(fill="x", pady=(10, 4))
        if previous is not None:
            ttk.Button(actions, text="Reset Decision", command=self._reset_current).pack(side="left")
        ttk.Button(actions, text="Save Decision", command=self._save_current).pack(side="right")

    def _default_action(self, group, previous):
        if previous is not None:
            return previous.action.value
        states = set(group.review_states)
        if ReviewState.IDENTITY_MIGRATION in states:
            return ""
        if states.intersection(_IDENTITY_REVIEW_STATES):
            return ""
        return ReviewAction.ACCEPT.value

    def _render_identity(self, group, context, previous):
        frame = ttk.LabelFrame(self.details, text="Identity", padding=8)
        frame.pack(fill="x", pady=(0, 8))
        states = set(group.review_states)

        if group.migration is not None:
            migration = group.migration
            ttk.Label(
                frame,
                text=f"{migration.source_key}  →  {migration.target_key}",
                font=("Segoe UI", 10, "bold"),
            ).pack(anchor="w", pady=(0, 5))
            ttk.Radiobutton(
                frame,
                text="Confirm identity migration / replacement",
                variable=self._action_var,
                value=ReviewAction.CONFIRM_MIGRATION.value,
            ).pack(anchor="w")
            ttk.Radiobutton(
                frame,
                text="Keep both Collection records separate",
                variable=self._action_var,
                value=ReviewAction.KEEP_SEPARATE.value,
            ).pack(anchor="w")
            ttk.Radiobutton(
                frame,
                text="Skip this item",
                variable=self._action_var,
                value=ReviewAction.SKIP.value,
            ).pack(anchor="w")
            return

        needs_identity = bool(states.intersection(_IDENTITY_REVIEW_STATES))
        proposed = group.proposed_target_key
        if proposed:
            ttk.Label(frame, text=f"Proposed target: SMWC {proposed}").pack(anchor="w", pady=(0, 4))

        if context.suggestions or needs_identity:
            search = ttk.Frame(frame)
            search.pack(fill="x", pady=(2, 6))
            self.search_var = tk.StringVar(value=context.row.title)
            entry = ttk.Entry(search, textvariable=self.search_var)
            entry.pack(side="left", fill="x", expand=True)
            entry.bind("<Return>", lambda _event: self._search_catalogue())
            ttk.Button(search, text="Search KaizOFF", command=self._search_catalogue).pack(side="left", padx=(6, 0))
            self.search_status = ttk.Label(frame, text="Searches this review's frozen Index only.", foreground="gray")
            self.search_status.pack(anchor="w", pady=(0, 4))

            columns = ("title", "id", "difficulty", "type", "exits", "score")
            holder = ttk.Frame(frame)
            holder.pack(fill="x")
            self.suggestion_tree = ttk.Treeview(holder, columns=columns, show="headings", height=6, selectmode="browse")
            specs = {
                "title": ("Hack", 210),
                "id": ("SMWC ID", 75),
                "difficulty": ("Difficulty", 90),
                "type": ("Type", 75),
                "exits": ("Exits", 45),
                "score": ("Match", 55),
            }
            for column, (label, width) in specs.items():
                self.suggestion_tree.heading(column, text=label)
                self.suggestion_tree.column(column, width=width, minwidth=40, anchor="w")
            tree_scroll = ttk.Scrollbar(holder, orient="vertical", command=self.suggestion_tree.yview)
            self.suggestion_tree.configure(yscrollcommand=tree_scroll.set)
            self.suggestion_tree.grid(row=0, column=0, sticky="ew")
            tree_scroll.grid(row=0, column=1, sticky="ns")
            holder.columnconfigure(0, weight=1)
            self.suggestion_tree.bind("<<TreeviewSelect>>", self._suggestion_selected)
            self._populate_suggestions(context.suggestions)
            self._restore_target_selection(previous, proposed)

        if needs_identity:
            ttk.Radiobutton(
                frame,
                text="Use selected KaizOFF match",
                variable=self._action_var,
                value=ReviewAction.USE_TARGET.value,
            ).pack(anchor="w", pady=(6, 0))
            ttk.Radiobutton(
                frame,
                text="Import as a local/manual Collection entry",
                variable=self._action_var,
                value=ReviewAction.IMPORT_LOCAL.value,
            ).pack(anchor="w")
            ttk.Radiobutton(
                frame,
                text="Skip this item",
                variable=self._action_var,
                value=ReviewAction.SKIP.value,
            ).pack(anchor="w")
            if group.rom_files:
                ttk.Radiobutton(
                    frame,
                    text="Ignore these exact ROM discoveries (path + SHA-256)",
                    variable=self._action_var,
                    value=ReviewAction.IGNORE.value,
                ).pack(anchor="w")
        else:
            ttk.Radiobutton(
                frame,
                text="Keep proposed identity",
                variable=self._action_var,
                value=ReviewAction.ACCEPT.value,
            ).pack(anchor="w", pady=(6, 0))
            if self.suggestion_tree is not None:
                ttk.Radiobutton(
                    frame,
                    text="Use selected KaizOFF match instead",
                    variable=self._action_var,
                    value=ReviewAction.USE_TARGET.value,
                ).pack(anchor="w")
            ttk.Radiobutton(
                frame,
                text="Skip this item",
                variable=self._action_var,
                value=ReviewAction.SKIP.value,
            ).pack(anchor="w")
            if group.rom_files:
                ttk.Radiobutton(
                    frame,
                    text="Ignore these exact ROM discoveries",
                    variable=self._action_var,
                    value=ReviewAction.IGNORE.value,
                ).pack(anchor="w")

    def _populate_suggestions(self, suggestions):
        self._suggestion_targets = {}
        if not self.suggestion_tree:
            return
        for item in self.suggestion_tree.get_children():
            self.suggestion_tree.delete(item)
        for index, suggestion in enumerate(suggestions):
            iid = f"result:{index}:{suggestion.target_key}"
            self.suggestion_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    suggestion.title,
                    suggestion.target_key,
                    suggestion.difficulty or "-",
                    suggestion.hack_type or "-",
                    "-" if suggestion.exits is None else suggestion.exits,
                    f"{suggestion.confidence:.0%}" if suggestion.confidence else "-",
                ),
            )
            self._suggestion_targets[iid] = suggestion.target_key

    def _restore_target_selection(self, previous, proposed):
        target = ""
        if previous is not None and previous.action is ReviewAction.USE_TARGET:
            target = previous.target_key
        elif proposed:
            target = proposed
        if not target or not self.suggestion_tree:
            return
        for iid, value in self._suggestion_targets.items():
            if value == target:
                self.suggestion_tree.selection_set(iid)
                self.suggestion_tree.see(iid)
                return

    def _suggestion_selected(self, _event=None):
        if self._action_var is None:
            return
        if self._action_var.get() not in {
            ReviewAction.IMPORT_LOCAL.value,
            ReviewAction.SKIP.value,
            ReviewAction.IGNORE.value,
        }:
            self._action_var.set(ReviewAction.USE_TARGET.value)

    def _search_catalogue(self):
        query = self.search_var.get().strip() if self.search_var else ""
        if not query:
            self.search_status.configure(text="Enter a hack name or SMWC ID.")
            return
        try:
            results = self.model.search_catalogue(query, limit=20)
        except Exception as error:
            self.search_status.configure(text=str(error))
            return
        self._populate_suggestions(results)
        if results:
            self.search_status.configure(text=f"Found {len(results)} result(s) in the frozen KaizOFF Index.")
            first = self.suggestion_tree.get_children()[0]
            self.suggestion_tree.selection_set(first)
            self.suggestion_tree.see(first)
        else:
            self.search_status.configure(text="No results found. Try another search term or import locally.")

    def _render_roms(self, group, previous):
        if not group.rom_files:
            return
        frame = ttk.LabelFrame(self.details, text="ROM files", padding=8)
        frame.pack(fill="x", pady=(0, 8))
        if len(group.rom_hashes) > 1:
            ttk.Label(
                frame,
                text="Different hashes are distinct ROM variants. Choose what to keep and which retained file is primary.",
                wraplength=520,
            ).pack(anchor="w", pady=(0, 6))
        elif len(group.rom_files) > 1:
            ttk.Label(
                frame,
                text="These locations contain identical ROM bytes. Keeping both is the safe default.",
                wraplength=520,
            ).pack(anchor="w", pady=(0, 6))

        previous_selection = previous.rom_selection if previous is not None else None
        previous_kept = set(previous_selection.kept_paths) if previous_selection else set()
        previous_ignored = {item.path for item in previous_selection.ignored} if previous_selection else set()
        self._rom_action_vars = {}
        self._rom_initial = {}
        self._rom_primary_var = tk.StringVar(
            value=previous_selection.primary_path if previous_selection else ""
        )

        for rom in group.rom_files:
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=2)
            if previous_selection:
                if rom.path in previous_ignored:
                    initial = "Ignore"
                elif rom.path in previous_kept:
                    initial = "Keep"
                else:
                    initial = "Leave out"
            else:
                initial = "Keep"
            var = tk.StringVar(value=initial)
            self._rom_action_vars[rom.path] = var
            self._rom_initial[rom.path] = initial
            ttk.Combobox(
                row,
                textvariable=var,
                values=("Keep", "Ignore", "Leave out"),
                state="readonly",
                width=10,
            ).pack(side="left")
            ttk.Radiobutton(
                row,
                text="Primary",
                variable=self._rom_primary_var,
                value=rom.path,
            ).pack(side="left", padx=(6, 8))
            ttk.Label(
                row,
                text=f"{os.path.basename(rom.path)}  •  {rom.sha256[:12]}…",
            ).pack(side="left", fill="x", expand=True)
            ttk.Label(frame, text=rom.path, foreground="gray", wraplength=500).pack(anchor="w", padx=(24, 0))

    def _render_user_conflicts(self, group, previous):
        conflicts = {}
        for proposal in group.user_field_proposals:
            if proposal.conflict:
                conflicts.setdefault(proposal.field, proposal)
        if not conflicts:
            self._user_field_vars = {}
            return
        frame = ttk.LabelFrame(self.details, text="Personal data conflicts", padding=8)
        frame.pack(fill="x", pady=(0, 8))
        previous_values = {
            item.field: item.use_proposed
            for item in (previous.user_field_resolutions if previous else ())
        }
        self._user_field_vars = {}
        for field, proposal in sorted(conflicts.items()):
            row = ttk.Frame(frame)
            row.pack(fill="x", pady=(1, 5))
            ttk.Label(row, text=field.replace("_", " ").title(), width=18).pack(side="left")
            selected = "imported" if previous_values.get(field, False) else "existing"
            var = tk.StringVar(value=selected)
            self._user_field_vars[field] = var
            ttk.Radiobutton(
                row,
                text=f"Keep existing: {proposal.current_value!s}",
                variable=var,
                value="existing",
            ).pack(side="left", padx=(0, 8))
            ttk.Radiobutton(
                row,
                text=f"Use imported: {proposal.proposed_value!s}",
                variable=var,
                value="imported",
            ).pack(side="left")

    def _render_first_clear(self, group, previous):
        if ReviewState.FIRST_CLEAR_VERIFICATION not in set(group.review_states):
            self._first_clear_var = None
            self._first_clear_values = {}
            return
        frame = ttk.LabelFrame(self.details, text="First clear for statistics", padding=8)
        frame.pack(fill="x", pady=(0, 8))
        ttk.Label(
            frame,
            text="Choose the playthrough that represents the first clear, or choose None if it cannot be established safely.",
            wraplength=520,
        ).pack(anchor="w", pady=(0, 5))
        self._first_clear_var = tk.StringVar(value="")
        self._first_clear_values = {"none": (None, None)}
        ttk.Radiobutton(
            frame,
            text="None / unknown",
            variable=self._first_clear_var,
            value="none",
        ).pack(anchor="w")
        for index, history in enumerate(group.user_history):
            token = f"history:{index}"
            self._first_clear_values[token] = (history.source, history.source_record_id)
            pieces = [history.completed_date_iso or history.completed_date_text or "No date"]
            pieces.append(history.elapsed_text or "No time")
            if history.play_kind:
                pieces.append(history.play_kind)
            if history.category:
                pieces.append(history.category)
            ttk.Radiobutton(
                frame,
                text=" • ".join(pieces),
                variable=self._first_clear_var,
                value=token,
            ).pack(anchor="w")
        if previous is not None and previous.first_clear is not None:
            if previous.first_clear.source_record_id is None:
                self._first_clear_var.set("none")
            else:
                wanted = (previous.first_clear.source, previous.first_clear.source_record_id)
                for token, value in self._first_clear_values.items():
                    if value == wanted:
                        self._first_clear_var.set(token)
                        break

    def _render_remember_aliases(self, context, previous):
        self._remember_vars = []
        if not context.rememberable_aliases:
            return
        frame = ttk.LabelFrame(self.details, text="Remember match", padding=8)
        frame.pack(fill="x", pady=(0, 8))
        ttk.Label(
            frame,
            text="Only save aliases you explicitly want the ROM scanner to reuse later.",
            wraplength=520,
        ).pack(anchor="w", pady=(0, 4))
        previous_values = {
            (item.source, item.value)
            for item in (previous.remembered_associations if previous else ())
        }
        for source, value in context.rememberable_aliases:
            var = tk.BooleanVar(value=(source, value) in previous_values)
            self._remember_vars.append((source, value, var))
            ttk.Checkbutton(
                frame,
                text=f'Remember ROM filename/title alias "{value}"',
                variable=var,
            ).pack(anchor="w")

    def _selected_target(self):
        if not self.suggestion_tree:
            return ""
        selected = self.suggestion_tree.selection()
        if len(selected) != 1:
            return ""
        return self._suggestion_targets.get(selected[0], "")

    def _build_rom_selection(self, group):
        if not self._rom_action_vars:
            return None
        changed = any(
            var.get() != self._rom_initial.get(path)
            for path, var in self._rom_action_vars.items()
        )
        required = ReviewState.ROM_SELECTION_REQUIRED in set(group.review_states)
        primary = self._rom_primary_var.get().strip() if self._rom_primary_var else ""
        if not changed and not required and not primary:
            return None

        by_path = {rom.path: rom for rom in group.rom_files}
        kept = tuple(path for path, var in self._rom_action_vars.items() if var.get() == "Keep")
        ignored = tuple(
            IgnoredRomDecision(path=path, sha256=by_path[path].sha256)
            for path, var in self._rom_action_vars.items()
            if var.get() == "Ignore"
        )
        if len(kept) == 1 and not primary:
            primary = kept[0]
        return RomSelectionDecision(
            kept_paths=kept,
            primary_path=primary,
            ignored=ignored,
        )

    def _build_decision(self, group):
        value = self._action_var.get().strip() if self._action_var else ""
        if not value:
            raise CollectionIngestionReviewError("Choose an action for this review item.")
        try:
            action = ReviewAction(value)
        except ValueError as error:
            raise CollectionIngestionReviewError("Unknown review action.") from error

        if action in {ReviewAction.SKIP, ReviewAction.IGNORE}:
            return ReviewDecision(group_id=group.group_id, action=action)

        target = ""
        if action is ReviewAction.USE_TARGET:
            target = self._selected_target()
            if not target:
                raise CollectionIngestionReviewError("Select a KaizOFF result first.")

        rom_selection = self._build_rom_selection(group)
        user_fields = tuple(
            UserFieldResolution(field=field, use_proposed=(var.get() == "imported"))
            for field, var in sorted(self._user_field_vars.items())
        )

        first_clear = None
        if ReviewState.FIRST_CLEAR_VERIFICATION in set(group.review_states):
            token = self._first_clear_var.get().strip() if self._first_clear_var else ""
            if not token:
                raise CollectionIngestionReviewError(
                    "Choose a first-clear playthrough or None / unknown."
                )
            source, record_id = self._first_clear_values[token]
            first_clear = FirstClearDecision(
                decided=True,
                source=source,
                source_record_id=record_id,
            )

        remembered = ()
        if action is ReviewAction.USE_TARGET:
            remembered = tuple(
                RememberedAssociationDecision(source=source, value=value)
                for source, value, var in self._remember_vars
                if var.get()
            )

        return ReviewDecision(
            group_id=group.group_id,
            action=action,
            target_key=target,
            rom_selection=rom_selection,
            user_field_resolutions=user_fields,
            first_clear=first_clear,
            remembered_associations=remembered,
        )

    def _save_current(self):
        if not self._current_group_id:
            return
        group = self.model.get_group(self._current_group_id)
        try:
            decision = self._build_decision(group)
            self.model.set_decision(group.group_id, decision)
        except (CollectionIngestionReviewError, ValueError) as error:
            messagebox.showerror("Review Incomplete", str(error), parent=self.win)
            return
        current = group.group_id
        self._refresh_rows()
        if self.tree.exists(current):
            self.tree.selection_set(current)
            self._render_group(current)
        else:
            self._select_next_unresolved()

    def _reset_current(self):
        if not self._current_group_id:
            return
        group_id = self._current_group_id
        self.model.clear_decision(group_id)
        self._refresh_rows()
        if self.tree.exists(group_id):
            self.tree.selection_set(group_id)
            self._render_group(group_id)

    def _complete(self):
        unresolved = self.model.unresolved_group_ids()
        if unresolved:
            messagebox.showwarning(
                "Review Incomplete",
                f"Resolve the remaining {len(unresolved)} review item(s) before continuing.",
                parent=self.win,
            )
            self._select_next_unresolved()
            return
        decisions = self.model.decisions
        if self.on_complete:
            result = self.on_complete(decisions)
            if result is False:
                return
        self.close()


__all__ = ["CollectionIngestionReviewDialog"]
