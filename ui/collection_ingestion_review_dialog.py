"""Tk review dialog for frozen Collection ingestion sessions.

The dialog only captures explicit ReviewDecision objects. It does not fetch
network data, allocate local Collection identities, finalize plans, or persist
Collection/configuration state.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from collection_ingestion import IngestionSource
from local_collection_metadata import (
    LOCAL_DIFFICULTY_CHOICES,
    LOCAL_HACK_TYPE_CHOICES,
    format_local_hack_types,
    validate_local_collection_metadata,
)
from collection_ingestion_diagnostics import diagnostic_filename, write_diagnostic_report
from ui.window_positioning import center_window_on_parent
from collection_ingestion_review_model import (
    CollectionIngestionReviewError,
    CollectionIngestionReviewModel,
)
from collection_reconciliation import (
    FirstClearDecision,
    IgnoredRomDecision,
    LocalRecordMetadataDecision,
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


def _catalogue_author_text(suggestion):
    """Return frozen catalogue author text when the suggestion exposes it."""

    for source in (suggestion, getattr(suggestion, "entry", None)):
        if source is None:
            continue
        authors = getattr(source, "authors", None)
        if isinstance(authors, str) and authors.strip():
            return authors.strip()
        if authors:
            values = [str(value).strip() for value in authors if str(value).strip()]
            if values:
                return ", ".join(values)
        author = str(getattr(source, "author", "") or "").strip()
        if author:
            return author
    return "-"


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
        self.detail_actions = None
        self.review_win = None
        self.review_button = None
        self.selection_label = None
        self.done_button = None
        self.attention_var = None
        self.search_var = None
        self.search_status = None
        self.suggestion_tree = None
        self.suggestion_detail_label = None
        self._suggestion_targets = {}
        self._suggestion_rows = {}
        self.local_tree = None
        self._local_targets = {}
        self._current_group_id = None
        self._action_var = None
        self._rom_action_vars = {}
        self._rom_primary_var = None
        self._rom_initial = {}
        self._user_field_vars = {}
        self._local_title_var = None
        self._local_type_var = None
        self._local_difficulty_var = None
        self._local_exits_var = None
        self._local_metadata_frame = None
        self._decision_area = None
        self._support_area = None
        self._support_left = None
        self._support_right = None
        self._support_layout_mode = None
        self._rom_detail_label = None
        self._first_clear_var = None
        self._first_clear_values = {}
        self._remember_vars = []
        self._closed = False
        self._submitting = False
        self._diagnostic_error = ""
        self._converged_rom_decisions = {}

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
        self.win.geometry("1120x700")
        self.win.minsize(820, 520)
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
                "Catalogue matches are frozen for this review so results do not "
                "change while you decide. Resolve highlighted items before continuing. "
                "Nothing changes until you apply the final preview."
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
        self.review_button = ttk.Button(
            toolbar,
            text="Review Selected...",
            command=self._open_selected_review,
            state="disabled",
        )
        self.review_button.pack(side="right", padx=(0, 8))

        list_frame = ttk.Frame(root)
        list_frame.pack(fill="both", expand=True)
        columns = ("status", "item", "source", "target", "details")
        self.tree = ttk.Treeview(
            list_frame, columns=columns, show="headings", selectmode="browse"
        )
        headings = {
            "status": ("Status", 130, False),
            "item": ("Item", 300, True),
            "source": ("Source", 140, False),
            "target": ("Match / target", 300, True),
            "details": ("Evidence", 120, False),
        }
        for column, (label, width, stretch) in headings.items():
            self.tree.heading(column, text=label)
            self.tree.column(
                column, width=width, minwidth=70, stretch=stretch, anchor="w"
            )
        vscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        hscroll = ttk.Scrollbar(list_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(
            yscrollcommand=vscroll.set,
            xscrollcommand=hscroll.set,
        )
        self.tree.grid(row=0, column=0, sticky="nsew")
        vscroll.grid(row=0, column=1, sticky="ns")
        hscroll.grid(row=1, column=0, sticky="ew")
        list_frame.rowconfigure(0, weight=1)
        list_frame.columnconfigure(0, weight=1)
        self.tree.tag_configure("resolved", foreground="gray")
        self.tree.bind("<<TreeviewSelect>>", self._on_row_selected)
        self.tree.bind("<Double-1>", lambda _event: self._open_selected_review())

        selection = ttk.Frame(root, padding=(0, 8, 0, 0))
        selection.pack(fill="x")
        self.selection_label = ttk.Label(
            selection,
            text=(
                "Select an item and choose Review Selected, or double-click it, "
                "to open the full-width decision workspace."
            ),
            foreground="gray",
        )
        self.selection_label.pack(anchor="w")

        footer = ttk.Frame(root)
        footer.pack(fill="x", pady=(10, 0))
        ttk.Button(
            footer,
            text="Export Diagnostics...",
            command=self._export_diagnostics,
        ).pack(side="left")
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

    def set_submitting(self, submitting: bool):
        """Keep reviewed decisions alive while detached finalization runs."""

        self._submitting = bool(submitting)
        if self.done_button is not None:
            self.done_button.configure(
                state="disabled" if self._submitting else "normal"
            )
        self._apply_submitting_state()
        if self._submitting:
            try:
                self.win.configure(cursor="watch")
            except (tk.TclError, AttributeError):
                pass
        else:
            try:
                self.win.configure(cursor="")
            except (tk.TclError, AttributeError):
                pass
            self._update_summary()

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._close_item_review()
        try:
            if self.win and self.win.winfo_exists():
                self.win.destroy()
        except tk.TclError:
            pass
        if self.on_close:
            self.on_close()

    def _center(self):
        center_window_on_parent(self.win, self.parent)

    def _refresh_rows(self):
        if not self.tree:
            return
        selected = self._selected_group_id() or self._current_group_id
        for item in self.tree.get_children():
            self.tree.delete(item)

        rows = self.model.rows(attention_only=False)
        if self.attention_var and self.attention_var.get():
            # "Needs attention" is a work queue: once a blocking item has a valid
            # saved decision it leaves this view.  It remains available from All.
            rows = tuple(row for row in rows if row.blocking and not row.resolved)

        for row in rows:
            target = row.target_title
            if row.target_key and row.target_key.isdecimal():
                target = f"{target} [{row.target_key}]" if target else f"SMWC {row.target_key}"
            details = []
            if row.rom_count:
                details.append(f"{row.rom_count} ROM")
            if row.history_count:
                details.append(f"{row.history_count} play")
            tags = ("resolved",) if row.resolved else ()
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
                tags=tags,
            )

        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
            self.tree.focus(selected)
            self.tree.see(selected)
        elif rows:
            self.tree.selection_set(rows[0].group_id)
            self.tree.focus(rows[0].group_id)
            self.tree.see(rows[0].group_id)
        self._update_selected_row_state()
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
        catalogue_status = (
            "Catalogue snapshot: cached copy (may be out of date)"
            if self.model.session.catalogue_stale
            else "Catalogue snapshot: ready"
        )
        self.catalogue_label.configure(text=catalogue_status)
        self.done_button.configure(
            state=(
                "disabled"
                if self._submitting or not summary.can_complete
                else "normal"
            )
        )

    def _select_next_unresolved(self, *, quiet=False):
        unresolved = self.model.unresolved_group_ids()
        if not unresolved:
            if not quiet:
                messagebox.showinfo(
                    "Collection Import",
                    "All required review decisions are resolved.",
                    parent=self.review_win if self.review_win else self.win,
                )
            return False
        if self.attention_var and not self.attention_var.get():
            self.attention_var.set(True)
            self._refresh_rows()
        for group_id in unresolved:
            if self.tree.exists(group_id):
                self.tree.selection_set(group_id)
                self.tree.focus(group_id)
                self.tree.see(group_id)
                self._open_group_review(group_id)
                return True
        return False

    def _selected_group_id(self):
        if self.tree is None:
            return None
        selected = self.tree.selection()
        return selected[0] if len(selected) == 1 else None

    def _on_row_selected(self, _event=None):
        self._update_selected_row_state()

    def _update_selected_row_state(self):
        group_id = self._selected_group_id()
        state = "normal" if group_id else "disabled"
        if self.review_button is not None:
            self.review_button.configure(state=state)
        if self.selection_label is None:
            return
        if not group_id:
            text = "No item is selected."
        else:
            context = self.model.context(group_id)
            row = context.row
            target = row.target_title or row.target_key or "No target selected"
            text = f"{row.title}  •  {row.status}  •  {target}"
        self.selection_label.configure(text=text)

    def _open_selected_review(self):
        group_id = self._selected_group_id()
        if not group_id:
            return False
        self._open_group_review(group_id)
        return True

    def _open_group_review(self, group_id):
        self.model.get_group(group_id)
        if self.review_win is None or not self._item_review_is_open():
            self.review_win = tk.Toplevel(self.win)
            self.review_win.title("Review Collection Import Item")
            self._size_item_review_window()
            self.review_win.transient(self.win)
            self.review_win.protocol("WM_DELETE_WINDOW", self._close_item_review)

            workspace = ttk.Frame(self.review_win, padding=14)
            workspace.pack(fill="both", expand=True)
            ttk.Label(
                workspace,
                text="Review selected import item",
                font=("Segoe UI", 14, "bold"),
            ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

            item_canvas = tk.Canvas(workspace, highlightthickness=0)
            item_scroll = ttk.Scrollbar(
                workspace, orient="vertical", command=item_canvas.yview
            )
            self.details = ttk.Frame(item_canvas)
            item_window = item_canvas.create_window(
                (0, 0), window=self.details, anchor="nw"
            )
            item_canvas.configure(yscrollcommand=item_scroll.set)
            item_canvas.grid(row=1, column=0, sticky="nsew")
            item_scroll.grid(row=1, column=1, sticky="ns")
            self.detail_actions = ttk.Frame(workspace, padding=(0, 8, 0, 0))
            self.detail_actions.grid(row=2, column=0, columnspan=2, sticky="ew")
            workspace.rowconfigure(1, weight=1)
            workspace.columnconfigure(0, weight=1)
            self.details.bind(
                "<Configure>",
                lambda _event: item_canvas.configure(
                    scrollregion=item_canvas.bbox("all")
                ),
            )
            item_canvas.bind(
                "<Configure>",
                lambda event: item_canvas.itemconfigure(
                    item_window, width=event.width
                ),
            )
            center_window_on_parent(self.review_win, self.win)

        self._render_group(group_id)
        try:
            self.review_win.deiconify()
            self.review_win.lift()
            self.review_win.focus_force()
        except tk.TclError:
            pass

    def _size_item_review_window(self):
        # Use most of the available desktop on smaller displays instead of forcing
        # the previous desktop-sized geometry off-screen.
        try:
            screen_width = int(self.review_win.winfo_vrootwidth())
            screen_height = int(self.review_win.winfo_vrootheight())
        except (tk.TclError, TypeError, ValueError):
            screen_width = int(self.review_win.winfo_screenwidth())
            screen_height = int(self.review_win.winfo_screenheight())
        width = min(1180, max(760, screen_width - 80))
        height = min(820, max(540, screen_height - 120))
        self.review_win.geometry(f"{width}x{height}")
        self.review_win.minsize(min(760, width), min(540, height))

    def _item_review_is_open(self):
        try:
            return bool(self.review_win and self.review_win.winfo_exists())
        except tk.TclError:
            return False

    def _close_item_review(self):
        try:
            if self.review_win and self.review_win.winfo_exists():
                self.review_win.destroy()
        except tk.TclError:
            pass
        self.review_win = None
        self.details = None
        self.detail_actions = None
        self._current_group_id = None

    def _clear_details(self, message="Select an item to review."):
        if self.details is None:
            if self.selection_label is not None:
                self.selection_label.configure(text=message)
            self._current_group_id = None
            return
        for child in self.details.winfo_children():
            child.destroy()
        self._clear_detail_actions()
        self._wrapped_label(self.details, message).pack(anchor="w", padx=4, pady=4)
        self._current_group_id = None

    def _clear_detail_actions(self):
        if self.detail_actions is None:
            return
        for child in self.detail_actions.winfo_children():
            child.destroy()

    def _apply_submitting_state(self):
        if self.detail_actions is None:
            return
        state = "disabled" if self._submitting else "normal"
        for child in self.detail_actions.winfo_children():
            if isinstance(child, ttk.Button):
                try:
                    child.configure(state=state)
                except tk.TclError:
                    pass

    def _wrapped_label(self, parent, text, **kwargs):
        label = ttk.Label(parent, text=text, wraplength=480, **kwargs)
        def resize(event):
            try:
                label.configure(wraplength=max(180, int(event.width) - 24))
            except (tk.TclError, ValueError):
                pass
        parent.bind("<Configure>", resize, add="+")
        return label

    def _render_review_context(self, group, context):
        lines = []
        lines.extend(f"Review: {issue.reason}" for issue in group.issues)
        lines.extend(f"Evidence: {reason}" for reason in context.candidate_reasons)
        if not lines:
            return

        frame = ttk.LabelFrame(self.details, text="Why this needs review", padding=6)
        frame.pack(fill="x", pady=(0, 8))
        holder = ttk.Frame(frame)
        holder.pack(fill="x")
        text = tk.Text(
            holder,
            height=min(2, max(1, len(lines))),
            wrap="word",
            takefocus=False,
            relief="flat",
            borderwidth=0,
        )
        scroll = ttk.Scrollbar(holder, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        holder.columnconfigure(0, weight=1)
        text.insert("1.0", "\n".join(lines))
        text.configure(state="disabled")

    def _action_changed(self, *_args):
        self._update_conditional_sections()

    def _update_conditional_sections(self):
        frame = self._local_metadata_frame
        if frame is None or self._action_var is None:
            return
        show_local = self._action_var.get() == ReviewAction.IMPORT_LOCAL.value
        if show_local:
            if not frame.winfo_manager():
                frame.pack(fill="x", pady=(0, 8))
        elif frame.winfo_manager():
            frame.pack_forget()

    def _show_rom_detail(self, path):
        if self._rom_detail_label is not None:
            self._rom_detail_label.configure(text=f"ROM path: {path}")

    def _render_group(self, group_id):
        if self.details is None:
            self._open_group_review(group_id)
            return
        self._current_group_id = group_id
        if self.review_win is not None:
            try:
                context_for_title = self.model.context(group_id)
                self.review_win.title(f"Review {context_for_title.row.title}")
            except (tk.TclError, CollectionIngestionReviewError):
                pass
        self.search_var = None
        self.search_status = None
        self.suggestion_tree = None
        self.suggestion_detail_label = None
        self._suggestion_targets = {}
        self._suggestion_rows = {}
        self.local_tree = None
        self._local_targets = {}
        self._action_var = None
        self._rom_action_vars = {}
        self._rom_primary_var = None
        self._rom_initial = {}
        self._user_field_vars = {}
        self._local_title_var = None
        self._local_type_var = None
        self._local_difficulty_var = None
        self._local_exits_var = None
        self._local_metadata_frame = None
        self._decision_area = None
        self._support_area = None
        self._support_left = None
        self._support_right = None
        self._support_layout_mode = None
        self._rom_detail_label = None
        self._first_clear_var = None
        self._first_clear_values = {}
        self._remember_vars = []
        for child in self.details.winfo_children():
            child.destroy()
        self._clear_detail_actions()
        context = self.model.context(group_id)
        group = context.group
        previous = self.model.decision_for(group_id)

        self._wrapped_label(
            self.details,
            context.row.title,
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", fill="x")
        ttk.Label(
            self.details,
            text=f"Source: {', '.join(context.row.sources)}   •   {context.row.status}",
            foreground="gray",
        ).pack(anchor="w", pady=(2, 8))

        self._render_review_context(group, context)

        self._action_var = tk.StringVar(value=self._default_action(group, previous))
        self._decision_area = ttk.Frame(self.details)
        self._decision_area.pack(fill="x", pady=(0, 8))

        # Identity owns the full review width. The earlier side-by-side identity/ROM
        # layout made catalogue details unnecessarily cramped on ordinary desktops.
        self._render_identity(group, context, previous, parent=self._decision_area)

        # Local/manual metadata stays directly below the identity choice so those
        # user-owned fields remain obvious as soon as local creation is selected.
        self._render_local_metadata(
            group, context, previous, parent=self._decision_area
        )

        # Secondary decisions share the lower row instead: ROM handling benefits
        # from width, while remembered aliases are short and naturally compact.
        self._support_area = ttk.Frame(self._decision_area)
        self._support_area.pack(fill="x")
        self._support_left = ttk.Frame(self._support_area)
        self._support_right = ttk.Frame(self._support_area)
        self._render_roms(group, previous, parent=self._support_left)
        self._render_remember_aliases(
            context, previous, parent=self._support_right
        )
        self._support_area.bind("<Configure>", self._layout_support_sections)
        self._layout_support_sections()

        self._render_user_conflicts(group, previous)
        self._render_first_clear(group, previous)
        self._action_var.trace_add("write", self._action_changed)
        self._update_conditional_sections()

        actions = self.detail_actions
        if actions is not None:
            ttk.Button(actions, text="Reset", command=self._reset_current).pack(side="left")
            ttk.Button(
                actions,
                text="Save & Next",
                style="Accent.TButton",
                command=lambda: self._save_current(advance=True),
            ).pack(side="right")
            ttk.Button(
                actions,
                text="Save",
                command=self._save_current,
            ).pack(side="right", padx=(0, 8))
            self._apply_submitting_state()

    def _layout_support_sections(self, _event=None):
        """Place ROM variants and remembered aliases side by side when useful."""

        area = self._support_area
        left = self._support_left
        right = self._support_right
        if area is None or left is None or right is None:
            return
        try:
            width = max(1, int(area.winfo_width()))
            left_has_content = bool(left.winfo_children())
            right_has_content = bool(right.winfo_children())
        except (tk.TclError, TypeError, ValueError):
            return

        if left_has_content and right_has_content:
            mode = "wide" if width >= 760 else "stacked"
        elif left_has_content:
            mode = "left-only"
        elif right_has_content:
            mode = "right-only"
        else:
            mode = "empty"
        if mode == self._support_layout_mode:
            return
        self._support_layout_mode = mode

        left.grid_forget()
        right.grid_forget()
        area.columnconfigure(0, weight=1)
        area.columnconfigure(1, weight=0)
        if mode == "wide":
            left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
            right.grid(row=0, column=1, sticky="nsew")
            area.columnconfigure(0, weight=3)
            area.columnconfigure(1, weight=2)
        elif mode == "stacked":
            left.grid(row=0, column=0, sticky="nsew")
            right.grid(row=1, column=0, sticky="nsew")
        elif mode == "left-only":
            left.grid(row=0, column=0, sticky="nsew")
        elif mode == "right-only":
            right.grid(row=0, column=0, sticky="nsew")

    def _default_action(self, group, previous):
        if previous is not None:
            return previous.action.value
        states = set(group.review_states)
        if ReviewState.IDENTITY_MIGRATION in states:
            return ""
        if states.intersection(_IDENTITY_REVIEW_STATES):
            return ""
        return ReviewAction.ACCEPT.value

    def _render_identity(self, group, context, previous, *, parent=None):
        parent = parent or self.details
        frame = ttk.LabelFrame(parent, text="Identity", padding=8)
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
            ttk.Button(search, text="Search catalogue", command=self._search_catalogue).pack(side="left", padx=(6, 0))
            self.search_status = ttk.Label(frame, text="Searches this review's catalogue snapshot only.", foreground="gray")
            self.search_status.pack(anchor="w", pady=(0, 4))

            columns = (
                "title", "id", "author", "difficulty", "type", "exits", "score"
            )
            holder = ttk.Frame(frame)
            holder.pack(fill="x")
            self.suggestion_tree = ttk.Treeview(holder, columns=columns, show="headings", height=4, selectmode="browse")
            specs = {
                "title": ("Hack", 310),
                "id": ("SMWC ID", 82),
                "author": ("Author", 190),
                "difficulty": ("Difficulty", 105),
                "type": ("Type", 90),
                "exits": ("Exits", 55),
                "score": ("Match", 65),
            }
            for column, (label, width) in specs.items():
                self.suggestion_tree.heading(column, text=label)
                self.suggestion_tree.column(column, width=width, minwidth=40, anchor="w")
            tree_scroll = ttk.Scrollbar(holder, orient="vertical", command=self.suggestion_tree.yview)
            tree_hscroll = ttk.Scrollbar(holder, orient="horizontal", command=self.suggestion_tree.xview)
            self.suggestion_tree.configure(
                yscrollcommand=tree_scroll.set,
                xscrollcommand=tree_hscroll.set,
            )
            self.suggestion_tree.grid(row=0, column=0, sticky="nsew")
            tree_scroll.grid(row=0, column=1, sticky="ns")
            tree_hscroll.grid(row=1, column=0, sticky="ew")
            holder.columnconfigure(0, weight=1)
            self.suggestion_detail_label = self._wrapped_label(
                frame,
                "Select a catalogue result to see its full details.",
                foreground="gray",
            )
            self.suggestion_detail_label.pack(anchor="w", fill="x", pady=(4, 0))
            self.suggestion_tree.bind("<<TreeviewSelect>>", self._suggestion_selected)
            self._populate_suggestions(context.suggestions)
            self._restore_target_selection(previous, proposed)

        if needs_identity and context.local_suggestions:
            ttk.Label(
                frame,
                text="Existing local Collection matches (suggestions only)",
                font=("Segoe UI", 9, "bold"),
            ).pack(anchor="w", pady=(8, 3))
            local_holder = ttk.Frame(frame)
            local_holder.pack(fill="x")
            local_columns = ("title", "id", "difficulty", "type", "exits", "score")
            self.local_tree = ttk.Treeview(
                local_holder,
                columns=local_columns,
                show="headings",
                height=min(2, max(1, len(context.local_suggestions))),
                selectmode="browse",
            )
            local_specs = {
                "title": ("Local hack", 340),
                "id": ("Collection ID", 175),
                "difficulty": ("Difficulty", 120),
                "type": ("Type", 110),
                "exits": ("Exits", 60),
                "score": ("Match", 70),
            }
            for column, (label, width) in local_specs.items():
                self.local_tree.heading(column, text=label)
                self.local_tree.column(column, width=width, minwidth=40, anchor="w")
            local_vscroll = ttk.Scrollbar(
                local_holder, orient="vertical", command=self.local_tree.yview
            )
            local_hscroll = ttk.Scrollbar(
                local_holder, orient="horizontal", command=self.local_tree.xview
            )
            self.local_tree.configure(
                yscrollcommand=local_vscroll.set,
                xscrollcommand=local_hscroll.set,
            )
            self.local_tree.grid(row=0, column=0, sticky="ew")
            local_vscroll.grid(row=0, column=1, sticky="ns")
            local_hscroll.grid(row=1, column=0, sticky="ew")
            local_holder.columnconfigure(0, weight=1)
            self._populate_local_suggestions(context.local_suggestions)
            self.local_tree.bind("<<TreeviewSelect>>", self._local_suggestion_selected)
            self._restore_local_selection(previous)

        if needs_identity:
            ttk.Radiobutton(
                frame,
                text="Use selected SMWC match",
                variable=self._action_var,
                value=ReviewAction.USE_TARGET.value,
            ).pack(anchor="w", pady=(6, 0))
            if context.local_suggestions:
                ttk.Radiobutton(
                    frame,
                    text="Attach to selected existing local Collection entry",
                    variable=self._action_var,
                    value=ReviewAction.ATTACH_LOCAL.value,
                ).pack(anchor="w")
            ttk.Radiobutton(
                frame,
                text="Create a separate local/manual Collection entry",
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
                    text="Use selected SMWC match instead",
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

    def _render_local_metadata(self, group, context, previous, *, parent=None):
        states = set(group.review_states)
        if not states.intersection(_IDENTITY_REVIEW_STATES):
            return

        previous_metadata = (
            previous.local_metadata
            if previous is not None and previous.action is ReviewAction.IMPORT_LOCAL
            else None
        )
        title = previous_metadata.title if previous_metadata else context.row.title
        difficulty = previous_metadata.difficulty if previous_metadata else "Unknown"
        if previous_metadata is None:
            hints = [
                str(rom.difficulty_hint or "").strip()
                for rom in group.rom_files
                if str(rom.difficulty_hint or "").strip()
            ]
            if hints and len(set(hints)) == 1:
                difficulty = hints[0]
        type_text = (
            format_local_hack_types(previous_metadata.hack_types)
            if previous_metadata
            else "Unknown"
        )
        exits = previous_metadata.exits if previous_metadata else 0

        parent = parent or self.details
        slot = ttk.Frame(parent)
        slot.pack(fill="x")
        frame = ttk.LabelFrame(
            slot, text="New local/manual record details", padding=8
        )
        frame.pack(fill="x", pady=(0, 8))
        self._local_metadata_frame = frame
        ttk.Label(
            frame,
            text=(
                "Used only when 'Create a separate local/manual Collection entry' "
                "is selected. Existing local attachments keep their current metadata."
            ),
            foreground="gray",
            wraplength=520,
        ).grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Title:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=3)
        self._local_title_var = tk.StringVar(value=title)
        ttk.Entry(frame, textvariable=self._local_title_var).grid(
            row=1, column=1, sticky="ew", pady=3
        )

        ttk.Label(frame, text="Type(s):").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=3)
        self._local_type_var = tk.StringVar(value=type_text)
        ttk.Combobox(
            frame, textvariable=self._local_type_var, values=LOCAL_HACK_TYPE_CHOICES
        ).grid(row=2, column=1, sticky="ew", pady=3)

        ttk.Label(frame, text="Difficulty:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=3)
        self._local_difficulty_var = tk.StringVar(value=difficulty)
        ttk.Combobox(
            frame,
            textvariable=self._local_difficulty_var,
            values=LOCAL_DIFFICULTY_CHOICES,
            state="readonly",
        ).grid(row=3, column=1, sticky="ew", pady=3)

        ttk.Label(frame, text="Total exits:").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=3)
        self._local_exits_var = tk.StringVar(value=str(exits))
        ttk.Entry(frame, textvariable=self._local_exits_var, width=10).grid(
            row=4, column=1, sticky="w", pady=3
        )

    def _build_local_metadata(self):
        if not self._local_title_var:
            raise CollectionIngestionReviewError(
                "Local record details are unavailable for this review item."
            )
        try:
            metadata = validate_local_collection_metadata(
                self._local_title_var.get(),
                self._local_difficulty_var.get(),
                self._local_type_var.get(),
                self._local_exits_var.get(),
            )
        except ValueError as error:
            raise CollectionIngestionReviewError(str(error)) from error
        return LocalRecordMetadataDecision(
            title=metadata.title,
            difficulty=metadata.difficulty,
            hack_types=metadata.hack_types,
            exits=metadata.exits,
        )

    def _populate_local_suggestions(self, suggestions):
        self._local_targets = {}
        if not self.local_tree:
            return
        for item in self.local_tree.get_children():
            self.local_tree.delete(item)
        for index, suggestion in enumerate(suggestions):
            iid = f"local:{index}:{suggestion.target_key}"
            self.local_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    suggestion.title,
                    suggestion.target_key,
                    suggestion.difficulty or "-",
                    ", ".join(suggestion.hack_types) or "-",
                    "-" if suggestion.exits is None else suggestion.exits,
                    f"{suggestion.confidence:.0%}",
                ),
            )
            self._local_targets[iid] = suggestion.target_key

    def _restore_local_selection(self, previous):
        if (
            previous is None
            or previous.action is not ReviewAction.ATTACH_LOCAL
            or not self.local_tree
        ):
            return
        for iid, target in self._local_targets.items():
            if target == previous.target_key:
                self.local_tree.selection_set(iid)
                self.local_tree.see(iid)
                return

    def _local_suggestion_selected(self, _event=None):
        if self._action_var is not None:
            self._action_var.set(ReviewAction.ATTACH_LOCAL.value)

    def _populate_suggestions(self, suggestions):
        self._suggestion_targets = {}
        self._suggestion_rows = {}
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
                    _catalogue_author_text(suggestion),
                    suggestion.difficulty or "-",
                    suggestion.hack_type or "-",
                    "-" if suggestion.exits is None else suggestion.exits,
                    f"{suggestion.confidence:.0%}" if suggestion.confidence else "-",
                ),
            )
            self._suggestion_targets[iid] = suggestion.target_key
            self._suggestion_rows[iid] = suggestion

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
                self._update_selected_suggestion_text()
                return

    def _suggestion_selected(self, _event=None):
        self._update_selected_suggestion_text()
        if self._action_var is None:
            return
        if self._action_var.get() not in {
            ReviewAction.IMPORT_LOCAL.value,
            ReviewAction.SKIP.value,
            ReviewAction.IGNORE.value,
        }:
            self._action_var.set(ReviewAction.USE_TARGET.value)

    def _update_selected_suggestion_text(self):
        if self.suggestion_tree is None or self.suggestion_detail_label is None:
            return
        selected = self.suggestion_tree.selection()
        suggestion = self._suggestion_rows.get(selected[0]) if len(selected) == 1 else None
        if suggestion is None:
            self.suggestion_detail_label.configure(
                text="Select a catalogue result to see its full details."
            )
            return
        parts = [f"{suggestion.title} [SMWC {suggestion.target_key}]"]
        author = _catalogue_author_text(suggestion)
        if author != "-":
            parts.append(f"by {author}")
        if suggestion.difficulty:
            parts.append(suggestion.difficulty)
        if suggestion.hack_type:
            parts.append(suggestion.hack_type)
        if suggestion.exits is not None:
            parts.append(f"{suggestion.exits} exits")
        if suggestion.confidence:
            parts.append(f"{suggestion.confidence:.0%} match")
        self.suggestion_detail_label.configure(text="  •  ".join(parts))

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
            self.search_status.configure(text=f"Found {len(results)} result(s) in this review's catalogue snapshot.")
            first = self.suggestion_tree.get_children()[0]
            self.suggestion_tree.selection_set(first)
            self.suggestion_tree.see(first)
            self._update_selected_suggestion_text()
        else:
            self.search_status.configure(text="No results found. Try another search term or import locally.")

    def _render_roms(self, group, previous, *, parent=None):
        if not group.rom_files:
            return
        parent = parent or self.details
        frame = ttk.LabelFrame(parent, text="ROM variants", padding=8)
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
        default_primary = previous_selection.primary_path if previous_selection else ""
        if not default_primary and len(group.rom_files) == 1:
            default_primary = group.rom_files[0].path
        self._rom_primary_var = tk.StringVar(value=default_primary)

        holder = ttk.Frame(frame)
        holder.pack(fill="x")
        list_height = 30 * min(4, max(1, len(group.rom_files)))
        rom_canvas = tk.Canvas(holder, height=list_height, highlightthickness=0)
        rom_scroll = ttk.Scrollbar(holder, orient="vertical", command=rom_canvas.yview)
        rows = ttk.Frame(rom_canvas)
        row_window = rom_canvas.create_window((0, 0), window=rows, anchor="nw")
        rom_canvas.configure(yscrollcommand=rom_scroll.set)
        rom_canvas.grid(row=0, column=0, sticky="ew")
        rom_scroll.grid(row=0, column=1, sticky="ns")
        holder.columnconfigure(0, weight=1)
        rows.bind(
            "<Configure>",
            lambda _event: rom_canvas.configure(scrollregion=rom_canvas.bbox("all")),
        )
        rom_canvas.bind(
            "<Configure>",
            lambda event: rom_canvas.itemconfigure(row_window, width=event.width),
        )

        for rom in group.rom_files:
            row = ttk.Frame(rows)
            row.pack(fill="x", pady=1)
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
            action = ttk.Combobox(
                row,
                textvariable=var,
                values=("Keep", "Ignore", "Leave out"),
                state="readonly",
                width=10,
            )
            action.pack(side="left")
            action.bind(
                "<<ComboboxSelected>>",
                lambda _event, path=rom.path: self._show_rom_detail(path),
            )
            ttk.Radiobutton(
                row,
                text="Primary",
                variable=self._rom_primary_var,
                value=rom.path,
                command=lambda path=rom.path: self._show_rom_detail(path),
            ).pack(side="left", padx=(6, 8))
            label = ttk.Label(
                row,
                text=f"{os.path.basename(rom.path)}  •  {rom.sha256[:12]}…",
            )
            label.pack(side="left", fill="x", expand=True)
            label.bind(
                "<Button-1>",
                lambda _event, path=rom.path: self._show_rom_detail(path),
            )

        self._rom_detail_label = self._wrapped_label(
            frame,
            "",
            foreground="gray",
        )
        self._rom_detail_label.pack(anchor="w", fill="x", pady=(4, 0))
        self._show_rom_detail(default_primary or group.rom_files[0].path)

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

    def _render_remember_aliases(self, context, previous, *, parent=None):
        self._remember_vars = []
        if not context.rememberable_aliases:
            return
        parent = parent or self.details
        frame = ttk.LabelFrame(parent, text="Remember match", padding=8)
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

    def _selected_local_target(self):
        if not self.local_tree:
            return ""
        selected = self.local_tree.selection()
        if len(selected) != 1:
            return ""
        return self._local_targets.get(selected[0], "")

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
                raise CollectionIngestionReviewError("Select an SMWC catalogue result first.")
        elif action is ReviewAction.ATTACH_LOCAL:
            target = self._selected_local_target()
            if not target:
                raise CollectionIngestionReviewError(
                    "Select an existing local Collection entry first."
                )

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

        local_metadata = (
            self._build_local_metadata()
            if action is ReviewAction.IMPORT_LOCAL
            else None
        )

        remembered = ()
        if action in {ReviewAction.USE_TARGET, ReviewAction.ATTACH_LOCAL}:
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
            local_metadata=local_metadata,
        )

    def _save_current(self, *, advance=False):
        if not self._current_group_id:
            return
        group = self.model.get_group(self._current_group_id)
        try:
            decision = self._build_decision(group)
            self.model.set_decision(group.group_id, decision)
        except (CollectionIngestionReviewError, ValueError) as error:
            messagebox.showerror(
                "Review Incomplete",
                str(error),
                parent=self.review_win if self.review_win else self.win,
            )
            return
        current = group.group_id
        self._refresh_rows()
        if advance:
            if not self._select_next_unresolved(quiet=True):
                self._close_item_review()
            return
        if self.tree.exists(current):
            self.tree.selection_set(current)
            self.tree.focus(current)
        # A saved blocking row intentionally disappears from the attention queue,
        # but the full-width workspace stays open so the decision can be reviewed
        # or reset until the user closes it.
        if self._item_review_is_open():
            self._render_group(current)

    def _reset_current(self):
        if not self._current_group_id:
            return
        group_id = self._current_group_id
        self.model.clear_decision(group_id)
        self._refresh_rows()
        if self.tree.exists(group_id):
            self.tree.selection_set(group_id)
            self.tree.focus(group_id)
            self.tree.see(group_id)
        if self._item_review_is_open():
            self._render_group(group_id)

    def set_diagnostic_error(self, error):
        self._diagnostic_error = str(error or "")

    def set_converged_rom_decisions(self, decisions):
        self._converged_rom_decisions = dict(decisions or {})

    def _export_diagnostics(self):
        destination = filedialog.asksaveasfilename(
            parent=self.win,
            title="Export Collection Import Diagnostics",
            defaultextension=".json",
            initialfile=diagnostic_filename(),
            filetypes=(("JSON diagnostic report", "*.json"), ("All files", "*.*")),
        )
        if not destination:
            return
        try:
            written = write_diagnostic_report(
                destination,
                self.model.session,
                self.model.decisions,
                converged_rom_decisions=self._converged_rom_decisions,
                finalization_error=self._diagnostic_error,
            )
        except Exception as error:
            messagebox.showerror(
                "Collection Import",
                f"Failed to export diagnostics:\n{error}",
                parent=self.win,
            )
            return
        messagebox.showinfo(
            "Collection Import",
            "Diagnostic report exported.\n\n"
            "The report contains ROM filenames and SHA-256 hashes, but no absolute "
            "paths, raw ROM bytes, or imported history record IDs.",
            parent=self.win,
        )

    def _complete(self):
        if self._submitting:
            return
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


__all__ = ["CollectionIngestionReviewDialog"]
