"""Collection-owned Wheel dialog."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk

from collection_wheel import EmptyWheelPoolError, ExhaustedWheelPoolError


class CollectionWheelDialog:
    """Spin from the current Collection view with optional Planner refinements."""

    ALL_VALUE = "All"
    MIN_WIDTH = 560
    MIN_HEIGHT = 460

    def __init__(
        self,
        parent,
        model,
        collection_records,
        *,
        result_callback=None,
        on_close=None,
    ):
        self.parent = parent
        self.model = model
        self.collection_records = copy.deepcopy(list(collection_records))
        self.result_callback = result_callback
        self.on_close = on_close
        self.window = None
        self.search_var = tk.StringVar()
        self.lifecycle_var = tk.StringVar(value=self.ALL_VALUE)
        self.horizon_var = tk.StringVar(value=self.ALL_VALUE)
        self.list_var = tk.StringVar(value=self.ALL_VALUE)
        self.pool_count_var = tk.StringVar(value="0 candidates")
        self.result_var = tk.StringVar(value="No result yet")
        self.detail_var = tk.StringVar(
            value="Spin from the hacks currently shown by Collection filters."
        )
        self.spin_button = None
        self.reroll_button = None
        self.clear_button = None
        self._current_result_id = ""
        self._list_name_to_id = {}
        self._create_window()
        self._populate_filter_choices()
        self._bind_filters()
        self._refresh_pool_state()
        self._finalize_window()

    @property
    def is_open(self):
        return bool(self.window and self.window.winfo_exists())

    def lift(self):
        if self.is_open:
            self.window.deiconify()
            self.window.lift()
            self.window.focus_force()

    def close(self):
        if not self.window:
            return
        window = self.window
        self.window = None
        try:
            if window.winfo_exists():
                window.grab_release()
                window.destroy()
        finally:
            if self.on_close:
                callback = self.on_close
                self.on_close = None
                callback()

    def _create_window(self):
        self.window = tk.Toplevel(self.parent)
        self.window.withdraw()
        self.window.title("Collection Wheel")
        self.window.transient(self.parent)
        self.window.minsize(self.MIN_WIDTH, self.MIN_HEIGHT)
        self.window.protocol("WM_DELETE_WINDOW", self.close)

        content = ttk.Frame(self.window, padding=16)
        content.pack(fill="both", expand=True)
        ttk.Label(
            content,
            text="Collection Wheel",
            font=("Segoe UI", 16, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            content,
            text=(
                "The current Collection view owns the candidate pool. "
                "Planner choices below are optional refinements."
            ),
            wraplength=520,
        ).pack(anchor="w", pady=(4, 14))

        filters = ttk.LabelFrame(
            content,
            text="Refine current Collection view",
            padding=10,
        )
        filters.pack(fill="x")
        ttk.Label(filters, text="Search:").grid(row=0, column=0, sticky="w")
        self.search_entry = ttk.Entry(filters, textvariable=self.search_var)
        self.search_entry.grid(
            row=1,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(3, 10),
        )

        labels = ("Lifecycle:", "Planning:", "Custom list:")
        combos = []
        for column, label in enumerate(labels):
            ttk.Label(filters, text=label).grid(
                row=2,
                column=column,
                sticky="w",
            )
        self.lifecycle_combo = ttk.Combobox(
            filters,
            textvariable=self.lifecycle_var,
            state="readonly",
        )
        self.horizon_combo = ttk.Combobox(
            filters,
            textvariable=self.horizon_var,
            state="readonly",
        )
        self.list_combo = ttk.Combobox(
            filters,
            textvariable=self.list_var,
            state="readonly",
        )
        combos = [self.lifecycle_combo, self.horizon_combo, self.list_combo]
        for column, combo in enumerate(combos):
            combo.grid(
                row=3,
                column=column,
                sticky="ew",
                padx=(0, 8) if column < 2 else 0,
                pady=(3, 0),
            )
            filters.grid_columnconfigure(column, weight=1)

        self.planner_note = ttk.Label(filters, wraplength=500)
        self.planner_note.grid(
            row=4,
            column=0,
            columnspan=3,
            sticky="w",
            pady=(10, 0),
        )

        buttons = ttk.Frame(content)
        buttons.pack(side="bottom", fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Close", command=self.close).pack(side="right")
        self.clear_button = ttk.Button(
            buttons,
            text="Clear Result",
            command=self._clear_result,
        )
        self.clear_button.pack(side="right", padx=(0, 8))
        self.reroll_button = ttk.Button(
            buttons,
            text="Spin Again",
            command=lambda: self._spin(exclude_current=True),
        )
        self.reroll_button.pack(side="right", padx=(0, 8))
        self.spin_button = ttk.Button(
            buttons,
            text="Spin Wheel",
            style="Accent.TButton",
            command=self._spin,
        )
        self.spin_button.pack(side="right", padx=(0, 8))

        result_frame = ttk.LabelFrame(content, text="Result", padding=14)
        result_frame.pack(fill="both", expand=True, pady=(14, 0))
        ttk.Label(
            result_frame,
            textvariable=self.pool_count_var,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            result_frame,
            textvariable=self.result_var,
            font=("Segoe UI", 14, "bold"),
            wraplength=500,
        ).pack(anchor="center", pady=(28, 8))
        ttk.Label(
            result_frame,
            textvariable=self.detail_var,
            wraplength=500,
            justify="center",
        ).pack(anchor="center")

    def _finalize_window(self):
        self.window.update_idletasks()
        self._center_window()
        self.window.deiconify()
        self.window.grab_set()
        self.search_entry.focus_set()

    @classmethod
    def _required_window_size(cls, requested_width, requested_height):
        return (
            max(int(requested_width), cls.MIN_WIDTH),
            max(int(requested_height), cls.MIN_HEIGHT),
        )

    def _center_window(self):
        self.parent.update_idletasks()
        self.window.update_idletasks()
        width, height = self._required_window_size(
            self.window.winfo_reqwidth(),
            self.window.winfo_reqheight(),
        )
        x = self.parent.winfo_rootx() + max(
            0,
            (self.parent.winfo_width() - width) // 2,
        )
        y = self.parent.winfo_rooty() + max(
            0,
            (self.parent.winfo_height() - height) // 2,
        )
        self.window.geometry(f"{width}x{height}+{x}+{y}")

    def _populate_filter_choices(self):
        choices = self.model.available_filters(self.collection_records)
        self.lifecycle_combo.configure(
            values=[self.ALL_VALUE, *choices["lifecycle_statuses"]]
        )
        self.horizon_combo.configure(
            values=[self.ALL_VALUE, *choices["planning_horizons"]]
        )
        self._list_name_to_id = {
            item["name"]: item["id"]
            for item in choices["lists"]
        }
        self.list_combo.configure(
            values=[self.ALL_VALUE, *self._list_name_to_id]
        )

        if self.model.planner_refinements_available:
            self.planner_note.configure(
                text=(
                    "Planner metadata is available. These choices only refine "
                    "the current Collection pool."
                )
            )
        else:
            self.horizon_combo.configure(state="disabled")
            self.list_combo.configure(state="disabled")
            self.planner_note.configure(
                text=(
                    "No Planner horizons or custom lists are configured. "
                    "Lifecycle remains available from Collection completion "
                    "state."
                )
            )

    def _bind_filters(self):
        self.search_var.trace_add(
            "write",
            lambda *_: self._refresh_pool_state(),
        )
        for combo in (
            self.lifecycle_combo,
            self.horizon_combo,
            self.list_combo,
        ):
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _event: self._refresh_pool_state(),
            )

    def _current_filters(self):
        lifecycle = self._optional_choice(self.lifecycle_var.get())
        horizon = self._optional_choice(self.horizon_var.get())
        list_name = self._optional_choice(self.list_var.get())
        list_id = self._list_name_to_id.get(list_name, "")
        return {
            "text": self.search_var.get(),
            "lifecycle_statuses": [lifecycle] if lifecycle else None,
            "planning_horizons": [horizon] if horizon else None,
            "list_ids": [list_id] if list_id else None,
        }

    def _refresh_pool_state(self):
        try:
            pool = self.model.build_pool(
                self.collection_records,
                **self._current_filters(),
            )
        except Exception as error:
            self.pool_count_var.set("Pool unavailable")
            self.spin_button.configure(state="disabled")
            self.reroll_button.configure(state="disabled")
            self.detail_var.set(str(error))
            return

        count = len(pool)
        suffix = "candidate" if count == 1 else "candidates"
        self.pool_count_var.set(
            f"{count} {suffix} from the current Collection view"
        )
        pool_by_id = {str(record["id"]): record for record in pool}
        current = pool_by_id.get(self._current_result_id)
        if self._current_result_id and current is None:
            self._clear_result(refresh=False)
        elif current is not None:
            self._show_result(current)

        self.spin_button.configure(state="normal" if count else "disabled")
        self.reroll_button.configure(
            state=(
                "normal"
                if count > 1 and self._current_result_id in pool_by_id
                else "disabled"
            )
        )
        self.clear_button.configure(
            state="normal" if self._current_result_id else "disabled"
        )

    def _spin(self, exclude_current=False):
        excluded_ids = None
        if exclude_current and self._current_result_id:
            excluded_ids = [self._current_result_id]
        try:
            result = self.model.spin(
                self.collection_records,
                excluded_ids=excluded_ids,
                **self._current_filters(),
            )
        except EmptyWheelPoolError:
            messagebox.showinfo(
                "Collection Wheel",
                "No hacks match the current Wheel refinements.",
                parent=self.window,
            )
            return
        except ExhaustedWheelPoolError:
            messagebox.showinfo(
                "Collection Wheel",
                "There is no other candidate in the current pool.",
                parent=self.window,
            )
            return
        except Exception as error:
            messagebox.showerror(
                "Collection Wheel",
                f"Could not select a Wheel result:\\n{error}",
                parent=self.window,
            )
            return

        candidate = result.candidate
        self._current_result_id = result.candidate_id
        self._show_result(candidate)
        if self.result_callback:
            self.result_callback(result.candidate_id)
        self._refresh_pool_state()

    def _show_result(self, candidate):
        title = str(candidate.get("title", "")).strip()
        if not title:
            title = str(candidate.get("id", "")).strip()
        details = []
        if candidate.get("completed", False):
            details.append("Completed")
        status = str(
            candidate.get("planner_lifecycle_status", "")
        ).strip()
        if status and status not in details:
            details.append(status)
        if self.model.planner_refinements_available:
            horizon = str(candidate.get("planner_horizon", "")).strip()
            if horizon:
                details.append(horizon)
        self.result_var.set(title)
        self.detail_var.set(
            " · ".join(details)
            if details
            else "Selected from the current Collection view."
        )

    def _clear_result(self, refresh=True):
        self._current_result_id = ""
        self.result_var.set("No result yet")
        self.detail_var.set(
            "Spin from the hacks currently shown by Collection filters."
        )
        if refresh:
            self._refresh_pool_state()

    @classmethod
    def _optional_choice(cls, value):
        value = str(value).strip()
        return "" if not value or value == cls.ALL_VALUE else value


__all__ = ["CollectionWheelDialog"]
