"""Planner page for filtering and staging lifecycle planning edits."""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from planner_page_model import PlannerPageModel
from planner_store import LIFECYCLE_STATUSES, PLANNING_HORIZONS, PlannerStore
from ui_constants import get_page_padding, get_section_padding


class PlannerPage:
    """Display and edit Planner state without touching core collection data."""

    COLUMNS = (
        ("next", "Next", 55, "center"),
        ("title", "Title", 260, "w"),
        ("status", "Status", 95, "center"),
        ("horizon", "Planning", 90, "center"),
        ("lists", "Lists", 190, "w"),
        ("difficulty", "Difficulty", 105, "center"),
        ("type", "Type(s)", 120, "center"),
    )

    SORT_LABELS = {
        "Planning order": "planning",
        "Title": "title",
        "Collection order": "collection",
    }
    NO_STATUS_CHANGE = "No status change"
    NO_HORIZON_CHANGE = "No planning change"

    def __init__(self, parent, data_manager, logger=None, planner_store=None):
        self.parent = parent
        self.data_manager = data_manager
        self.logger = logger
        self.planner_store = planner_store or PlannerStore(logger=logger)
        self.model = PlannerPageModel(data_manager, self.planner_store)

        self.frame = None
        self.tree = None
        self.status_label = None
        self.search_var = tk.StringVar()
        self.lifecycle_var = tk.StringVar(value="All statuses")
        self.horizon_var = tk.StringVar(value="All planning")
        self.list_var = tk.StringVar(value="All lists")
        self.downloaded_var = tk.StringVar(value="Any download state")
        self.sort_var = tk.StringVar(value="Planning order")
        self.edit_lifecycle_var = tk.StringVar(value=self.NO_STATUS_CHANGE)
        self.edit_horizon_var = tk.StringVar(value=self.NO_HORIZON_CHANGE)
        self.lifecycle_combo = None
        self.horizon_combo = None
        self.list_combo = None
        self.apply_button = None
        self.move_up_button = None
        self.move_down_button = None
        self.save_button = None
        self.discard_button = None
        self._list_name_to_id = {}
        self._filter_after_id = None
        self._last_action = ""

    def create(self):
        """Create and return the Planner page frame."""
        self.frame = ttk.Frame(self.parent, padding=get_page_padding())
        self._create_header()
        self._create_filters()
        self._create_editor()
        self._create_table()
        self.refresh()
        return self.frame

    def refresh(self, reload_planner=False):
        """Refresh current collection and Planner data."""
        try:
            if reload_planner:
                self.model.reload_planner()
            else:
                self.model.refresh()
            self._refresh_filter_choices()
            self._refresh_table()
        except Exception as error:
            self._log(f"Could not refresh Planner: {error}", "Error")
            messagebox.showerror("Planner", f"Could not refresh Planner:\n{error}")

    def _create_header(self):
        _, section_padding_y = get_section_padding()
        header = ttk.Frame(self.frame)
        header.pack(fill="x", pady=(0, section_padding_y))

        text_frame = ttk.Frame(header)
        text_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(
            text_frame,
            text="Planner",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            text_frame,
            text=(
                "Choose what to play using lifecycle status, "
                "Someday/Soon/Next, and custom lists."
            ),
        ).pack(anchor="w", pady=(3, 0))

        self.save_button = ttk.Button(
            header,
            text="Save Changes",
            style="Accent.TButton",
            command=self._save_changes,
        )
        self.save_button.pack(side="right")
        self.discard_button = ttk.Button(
            header,
            text="Discard Changes",
            command=self._discard_changes,
        )
        self.discard_button.pack(side="right", padx=(0, 8))
        ttk.Button(
            header,
            text="Refresh",
            command=self.refresh,
        ).pack(side="right", padx=(0, 8))

    def _create_filters(self):
        _, section_padding_y = get_section_padding()
        filters = ttk.LabelFrame(self.frame, text="Filters", padding=10)
        filters.pack(fill="x", pady=(0, section_padding_y))

        ttk.Label(filters, text="Search").grid(row=0, column=0, sticky="w")
        search_entry = ttk.Entry(filters, textvariable=self.search_var)
        search_entry.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        search_entry.bind("<KeyRelease>", self._schedule_filter_refresh)

        self.lifecycle_combo = self._filter_combo(
            filters, "Status", self.lifecycle_var, 1
        )
        self.horizon_combo = self._filter_combo(
            filters, "Planning", self.horizon_var, 2
        )
        self.list_combo = self._filter_combo(
            filters, "List", self.list_var, 3
        )
        self._filter_combo(
            filters,
            "Download",
            self.downloaded_var,
            4,
            values=(
                "Any download state",
                "Downloaded",
                "Not downloaded",
            ),
        )
        self._filter_combo(
            filters,
            "Sort",
            self.sort_var,
            5,
            values=tuple(self.SORT_LABELS),
        )

        filters.grid_columnconfigure(0, weight=2)
        for column in range(1, 6):
            filters.grid_columnconfigure(column, weight=1)

    def _create_editor(self):
        _, section_padding_y = get_section_padding()
        editor = ttk.LabelFrame(
            self.frame,
            text="Edit selected entries",
            padding=10,
        )
        editor.pack(fill="x", pady=(0, section_padding_y))

        ttk.Label(editor, text="Status").pack(side="left")
        ttk.Combobox(
            editor,
            textvariable=self.edit_lifecycle_var,
            values=(self.NO_STATUS_CHANGE, *LIFECYCLE_STATUSES),
            state="readonly",
            width=18,
        ).pack(side="left", padx=(6, 14))

        ttk.Label(editor, text="Planning").pack(side="left")
        ttk.Combobox(
            editor,
            textvariable=self.edit_horizon_var,
            values=(self.NO_HORIZON_CHANGE, *PLANNING_HORIZONS),
            state="readonly",
            width=18,
        ).pack(side="left", padx=(6, 14))

        self.apply_button = ttk.Button(
            editor,
            text="Apply to Selected",
            command=self._apply_selected,
        )
        self.apply_button.pack(side="left")

        self.move_down_button = ttk.Button(
            editor,
            text="Move Next Down",
            command=lambda: self._move_selected_next(1),
        )
        self.move_down_button.pack(side="right")
        self.move_up_button = ttk.Button(
            editor,
            text="Move Next Up",
            command=lambda: self._move_selected_next(-1),
        )
        self.move_up_button.pack(side="right", padx=(0, 8))

    def _filter_combo(self, parent, label, variable, column, values=()):
        ttk.Label(parent, text=label).grid(row=0, column=column, sticky="w")
        combo = ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly",
        )
        combo.grid(row=1, column=column, sticky="ew", padx=(0, 8))
        combo.bind("<<ComboboxSelected>>", self._schedule_filter_refresh)
        return combo

    def _create_table(self):
        table_frame = ttk.Frame(self.frame)
        table_frame.pack(fill="both", expand=True)

        column_ids = [column[0] for column in self.COLUMNS]
        self.tree = ttk.Treeview(
            table_frame,
            columns=column_ids,
            show="headings",
            selectmode="extended",
        )
        for column_id, header, width, anchor in self.COLUMNS:
            self.tree.heading(column_id, text=header)
            self.tree.column(
                column_id,
                width=width,
                minwidth=45,
                anchor=anchor,
            )
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)

        vertical = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self.tree.yview,
        )
        horizontal = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self.tree.xview,
        )
        self.tree.configure(
            yscrollcommand=vertical.set,
            xscrollcommand=horizontal.set,
        )

        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table_frame.grid_rowconfigure(0, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ttk.Label(self.frame, text="")
        self.status_label.pack(anchor="w", pady=(6, 0))

    def _refresh_filter_choices(self):
        choices = self.model.available_filters()
        statuses = ["All statuses", *choices["lifecycle_statuses"]]
        horizons = ["All planning", *choices["planning_horizons"]]

        self._list_name_to_id = {
            item["name"]: item["id"] for item in choices["lists"]
        }
        list_names = ["All lists", *self._list_name_to_id]

        self.lifecycle_combo.configure(values=statuses)
        self.horizon_combo.configure(values=horizons)
        self.list_combo.configure(values=list_names)
        self._keep_valid(self.lifecycle_var, statuses)
        self._keep_valid(self.horizon_var, horizons)
        self._keep_valid(self.list_var, list_names)

    def _schedule_filter_refresh(self, _event=None):
        if self._filter_after_id is not None:
            self.frame.after_cancel(self._filter_after_id)
        self._filter_after_id = self.frame.after(120, self._refresh_table)

    def _refresh_table(self):
        self._filter_after_id = None
        selected_ids = set(self.tree.selection()) if self.tree else set()
        try:
            records = self.model.visible_hacks(
                text=self.search_var.get(),
                lifecycle_status=self._selected_value(
                    self.lifecycle_var,
                    "All statuses",
                ),
                planning_horizon=self._selected_value(
                    self.horizon_var,
                    "All planning",
                ),
                list_id=self._selected_list_id(),
                downloaded=self._downloaded_filter(),
                sort_mode=self.SORT_LABELS[self.sort_var.get()],
            )
        except Exception as error:
            self._log(f"Could not filter Planner: {error}", "Error")
            return

        self.tree.delete(*self.tree.get_children())
        visible_ids = []
        for record in records:
            hack_id = str(record["id"])
            visible_ids.append(hack_id)
            self.tree.insert(
                "",
                "end",
                iid=hack_id,
                values=self.model.table_values(record),
            )

        retained = [item for item in visible_ids if item in selected_ids]
        if retained:
            self.tree.selection_set(retained)
        self._update_status(len(records))
        self._update_edit_controls()

    def _apply_selected(self):
        selected = list(self.tree.selection())
        if not selected:
            messagebox.showwarning(
                "Planner",
                "Select at least one collection entry.",
                parent=self.frame,
            )
            return

        lifecycle_status = self.edit_lifecycle_var.get()
        if lifecycle_status == self.NO_STATUS_CHANGE:
            lifecycle_status = ""
        planning_horizon = self.edit_horizon_var.get()
        if planning_horizon == self.NO_HORIZON_CHANGE:
            planning_horizon = ""

        try:
            self.model.apply_updates(
                selected,
                lifecycle_status=lifecycle_status,
                planning_horizon=planning_horizon,
            )
        except Exception as error:
            messagebox.showerror(
                "Planner",
                f"Could not apply Planner changes:\n{error}",
                parent=self.frame,
            )
            return

        self._last_action = f"Updated {len(selected)} selected entry(s)"
        self.edit_lifecycle_var.set(self.NO_STATUS_CHANGE)
        self.edit_horizon_var.set(self.NO_HORIZON_CHANGE)
        self._refresh_filter_choices()
        self._refresh_table()

    def _move_selected_next(self, offset):
        selected = list(self.tree.selection())
        if len(selected) != 1:
            messagebox.showwarning(
                "Planner",
                "Select exactly one Next entry to reorder.",
                parent=self.frame,
            )
            return
        try:
            position = self.model.move_next(selected[0], offset)
        except Exception as error:
            messagebox.showerror(
                "Planner",
                f"Could not reorder the Next queue:\n{error}",
                parent=self.frame,
            )
            return
        self._last_action = f"Moved selected entry to Next position {position}"
        self._refresh_table()

    def _save_changes(self):
        if not self.model.has_unsaved_changes:
            return
        if not self.model.save():
            messagebox.showerror(
                "Planner",
                "Could not save Planner changes. Check the application log.",
                parent=self.frame,
            )
            return
        self._last_action = "Planner changes saved"
        self._refresh_filter_choices()
        self._refresh_table()

    def _discard_changes(self):
        if not self.model.has_unsaved_changes:
            return
        confirmed = messagebox.askyesno(
            "Planner",
            "Discard all unsaved Planner changes?",
            parent=self.frame,
        )
        if not confirmed:
            return
        self.model.reload_planner()
        self._last_action = "Unsaved Planner changes discarded"
        self._refresh_filter_choices()
        self._refresh_table()

    def _selection_changed(self, _event=None):
        self._update_status()
        self._update_edit_controls()

    def _update_edit_controls(self):
        if not self.tree:
            return
        selected = list(self.tree.selection())
        self.apply_button.configure(state="normal" if selected else "disabled")
        move_up_state = "disabled"
        move_down_state = "disabled"
        if len(selected) == 1:
            values = self.tree.item(selected[0], "values")
            if len(values) > 3 and values[3] == "Next" and values[0]:
                position = int(values[0])
                queue_length = len(self.planner_store.get_next_queue())
                if position > 1:
                    move_up_state = "normal"
                if position < queue_length:
                    move_down_state = "normal"
        self.move_up_button.configure(state=move_up_state)
        self.move_down_button.configure(state=move_down_state)
        save_state = "normal" if self.model.has_unsaved_changes else "disabled"
        self.save_button.configure(state=save_state)
        self.discard_button.configure(state=save_state)

    def _update_status(self, visible_count=None):
        if not self.status_label or not self.tree:
            return
        if visible_count is None:
            visible_count = len(self.tree.get_children())
        total = len(self.model.projected_hacks)
        selected = len(self.tree.selection())
        parts = [f"Showing {visible_count} of {total} collection entries"]
        if selected:
            parts.append(f"{selected} selected")
        if self.model.has_unsaved_changes:
            parts.append("Unsaved Planner changes")
        if self._last_action:
            parts.append(self._last_action)
        self.status_label.configure(text=" · ".join(parts))

    def _selected_list_id(self):
        selected = self.list_var.get()
        if selected == "All lists":
            return ""
        return self._list_name_to_id.get(selected, "")

    def _downloaded_filter(self):
        selected = self.downloaded_var.get()
        return {
            "Any download state": "any",
            "Downloaded": "downloaded",
            "Not downloaded": "not downloaded",
        }[selected]

    @staticmethod
    def _selected_value(variable, all_label):
        value = variable.get()
        return "" if value == all_label else value

    @staticmethod
    def _keep_valid(variable, values):
        if variable.get() not in values:
            variable.set(values[0])

    def _log(self, message, level="Information"):
        if self.logger:
            self.logger.log(message, level)
