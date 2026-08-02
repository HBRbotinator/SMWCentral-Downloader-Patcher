"""Collection-owned Wheel dialog."""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk

from collection_wheel import EmptyWheelPoolError, ExhaustedWheelPoolError


class CollectionWheelDialog:
    """Spin from the full Collection with optional Planner refinements."""

    ALL_VALUE = "All"
    ANY_VALUE = "Any"
    ANY_RATING = "Any rating"
    UNRATED = "Unrated"
    MIN_WIDTH = 780
    MIN_HEIGHT = 650

    COMPLETION_OPTIONS = (
        ALL_VALUE,
        "Not completed",
        "Completed",
    )
    DOWNLOAD_OPTIONS = (
        ALL_VALUE,
        "Downloaded",
        "Not downloaded",
    )
    RATING_OPTIONS = (
        ANY_RATING,
        UNRATED,
        "1.0+",
        "2.0+",
        "3.0+",
        "4.0+",
        "4.5+",
        "5.0",
    )

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
        self.model.reload_planner_state()
        self.collection_records = copy.deepcopy(list(collection_records))
        self.result_callback = result_callback
        self.on_close = on_close
        self.window = None

        self.search_var = tk.StringVar()
        self.completion_var = tk.StringVar(value=self.ALL_VALUE)
        self.type_var = tk.StringVar(value=self.ALL_VALUE)
        self.difficulty_var = tk.StringVar(value=self.ALL_VALUE)
        self.rating_var = tk.StringVar(value=self.ANY_RATING)
        self.year_from_var = tk.StringVar(value=self.ANY_VALUE)
        self.year_to_var = tk.StringVar(value=self.ANY_VALUE)
        self.download_var = tk.StringVar(value=self.ALL_VALUE)

        self.lifecycle_var = tk.StringVar(value=self.ALL_VALUE)
        self.horizon_var = tk.StringVar(value=self.ALL_VALUE)
        self.list_var = tk.StringVar(value=self.ALL_VALUE)

        self.pool_count_var = tk.StringVar(value="0 candidates")
        self.result_var = tk.StringVar(value="No result yet")
        self.detail_var = tk.StringVar(
            value="Spin from your Collection using the filters above."
        )

        self.spin_button = None
        self.reroll_button = None
        self.clear_button = None
        self._current_result_id = ""
        self._list_name_to_id = {}
        self._planner_refinements_visible = False

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
                "The Wheel starts from your Collection and applies its own "
                "filters. Planner refinements appear only when Planner data "
                "is configured."
            ),
            wraplength=740,
        ).pack(anchor="w", pady=(4, 14))

        collection_frame = ttk.LabelFrame(
            content,
            text="Collection filters",
            padding=10,
        )
        collection_frame.pack(fill="x")
        ttk.Label(collection_frame, text="Search:").grid(
            row=0,
            column=0,
            columnspan=4,
            sticky="w",
        )
        self.search_entry = ttk.Entry(
            collection_frame,
            textvariable=self.search_var,
        )
        self.search_entry.grid(
            row=1,
            column=0,
            columnspan=4,
            sticky="ew",
            pady=(3, 10),
        )

        first_row = (
            ("Completion:", self.completion_var),
            ("Type:", self.type_var),
            ("Difficulty:", self.difficulty_var),
            ("Download status:", self.download_var),
        )
        second_row = (
            ("SMWC rating:", self.rating_var),
            ("Released from:", self.year_from_var),
            ("Released through:", self.year_to_var),
        )

        self.collection_combos = []
        for column, (label, variable) in enumerate(first_row):
            ttk.Label(collection_frame, text=label).grid(
                row=2,
                column=column,
                sticky="w",
            )
            combo = ttk.Combobox(
                collection_frame,
                textvariable=variable,
                state="readonly",
            )
            combo.grid(
                row=3,
                column=column,
                sticky="ew",
                padx=(0, 8) if column < 3 else 0,
                pady=(3, 10),
            )
            self.collection_combos.append(combo)

        for column, (label, variable) in enumerate(second_row):
            ttk.Label(collection_frame, text=label).grid(
                row=4,
                column=column,
                sticky="w",
            )
            combo = ttk.Combobox(
                collection_frame,
                textvariable=variable,
                state="readonly",
            )
            combo.grid(
                row=5,
                column=column,
                sticky="ew",
                padx=(0, 8),
                pady=(3, 0),
            )
            self.collection_combos.append(combo)

        ttk.Button(
            collection_frame,
            text="Reset Filters",
            command=self._reset_collection_filters,
        ).grid(
            row=5,
            column=3,
            sticky="e",
            pady=(3, 0),
        )
        for column in range(4):
            collection_frame.grid_columnconfigure(column, weight=1)

        self.planner_frame = ttk.LabelFrame(
            content,
            text="Planner refinements",
            padding=10,
        )
        self.planner_frame.pack(fill="x", pady=(12, 0))
        planner_fields = (
            ("Lifecycle:", self.lifecycle_var),
            ("Planning horizon:", self.horizon_var),
            ("Custom list:", self.list_var),
        )
        self.planner_combos = []
        for column, (label, variable) in enumerate(planner_fields):
            ttk.Label(self.planner_frame, text=label).grid(
                row=0,
                column=column,
                sticky="w",
            )
            combo = ttk.Combobox(
                self.planner_frame,
                textvariable=variable,
                state="readonly",
            )
            combo.grid(
                row=1,
                column=column,
                sticky="ew",
                padx=(0, 8) if column < 2 else 0,
                pady=(3, 0),
            )
            self.planner_combos.append(combo)
            self.planner_frame.grid_columnconfigure(column, weight=1)

        buttons = ttk.Frame(content)
        buttons.pack(side="bottom", fill="x", pady=(14, 0))
        ttk.Button(buttons, text="Close", command=self.close).pack(
            side="right"
        )
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
        result_frame.pack(fill="both", expand=True, pady=(12, 0))
        ttk.Label(
            result_frame,
            textvariable=self.pool_count_var,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            result_frame,
            textvariable=self.result_var,
            font=("Segoe UI", 14, "bold"),
            wraplength=700,
        ).pack(anchor="center", pady=(24, 8))
        ttk.Label(
            result_frame,
            textvariable=self.detail_var,
            wraplength=700,
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
        self.collection_combos[0].configure(
            values=self.COMPLETION_OPTIONS
        )
        self.collection_combos[1].configure(
            values=[self.ALL_VALUE, *choices["hack_types"]]
        )
        self.collection_combos[2].configure(
            values=[self.ALL_VALUE, *choices["difficulties"]]
        )
        self.collection_combos[3].configure(
            values=self.DOWNLOAD_OPTIONS
        )
        self.collection_combos[4].configure(values=self.RATING_OPTIONS)

        year_values = [
            self.ANY_VALUE,
            *(str(year) for year in choices["release_years"]),
        ]
        self.collection_combos[5].configure(values=year_values)
        self.collection_combos[6].configure(values=year_values)

        self.planner_combos[0].configure(
            values=[self.ALL_VALUE, *choices["lifecycle_statuses"]]
        )
        self.planner_combos[1].configure(
            values=[self.ALL_VALUE, *choices["planning_horizons"]]
        )
        self._list_name_to_id = {
            item["name"]: item["id"]
            for item in choices["lists"]
        }
        self.planner_combos[2].configure(
            values=[self.ALL_VALUE, *self._list_name_to_id]
        )

        self._planner_refinements_visible = (
            self.model.planner_refinements_available
        )
        if not self._planner_refinements_visible:
            self.planner_frame.pack_forget()

    def _bind_filters(self):
        self.search_var.trace_add(
            "write",
            lambda *_: self._refresh_pool_state(),
        )
        for combo in (*self.collection_combos, *self.planner_combos):
            combo.bind(
                "<<ComboboxSelected>>",
                lambda _event: self._refresh_pool_state(),
            )

    def _current_filters(self):
        lifecycle = self._optional_choice(self.lifecycle_var.get())
        horizon = self._optional_choice(self.horizon_var.get())
        list_name = self._optional_choice(self.list_var.get())
        list_id = self._list_name_to_id.get(list_name, "")

        rating_value = self.rating_var.get()
        rating_min = None
        rating_unrated = rating_value == self.UNRATED
        if rating_value not in (self.ANY_RATING, self.UNRATED):
            rating_min = float(rating_value.rstrip("+"))

        return {
            "text": self.search_var.get(),
            "completed": self._completion_choice(
                self.completion_var.get()
            ),
            "hack_types": self._single_filter(self.type_var.get()),
            "difficulties": self._single_filter(
                self.difficulty_var.get()
            ),
            "downloaded": self._download_choice(self.download_var.get()),
            "smwc_rating_min": rating_min,
            "smwc_rating_unrated": rating_unrated,
            "release_year_from": self._optional_year_choice(
                self.year_from_var.get()
            ),
            "release_year_to": self._optional_year_choice(
                self.year_to_var.get()
            ),
            "lifecycle_statuses": (
                [lifecycle]
                if self._planner_refinements_visible and lifecycle
                else None
            ),
            "planning_horizons": (
                [horizon]
                if self._planner_refinements_visible and horizon
                else None
            ),
            "list_ids": (
                [list_id]
                if self._planner_refinements_visible and list_id
                else None
            ),
            "include_obsolete": False,
        }

    def _reset_collection_filters(self):
        self.search_var.set("")
        self.completion_var.set(self.ALL_VALUE)
        self.type_var.set(self.ALL_VALUE)
        self.difficulty_var.set(self.ALL_VALUE)
        self.rating_var.set(self.ANY_RATING)
        self.year_from_var.set(self.ANY_VALUE)
        self.year_to_var.set(self.ANY_VALUE)
        self.download_var.set(self.ALL_VALUE)
        self._refresh_pool_state()

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
            f"{count} {suffix} after Wheel filters"
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
                "No hacks match the current Wheel filters.",
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
        difficulty = str(candidate.get("difficulty", "")).strip()
        if difficulty:
            details.append(difficulty)
        hack_types = candidate.get("hack_types", [])
        if not isinstance(hack_types, (list, tuple)) or not hack_types:
            hack_types = [candidate.get("hack_type", "")]
        type_display = ", ".join(
            str(value).strip()
            for value in hack_types
            if str(value).strip()
        )
        if type_display:
            details.append(type_display)

        rating = self.model._smwc_rating(candidate)
        if rating is not None:
            details.append(f"SMWC {rating:g}")
        release_year = self.model._release_year(candidate)
        if release_year is not None:
            details.append(f"Released {release_year}")

        if self._planner_refinements_visible:
            status = str(
                candidate.get("planner_lifecycle_status", "")
            ).strip()
            horizon = str(candidate.get("planner_horizon", "")).strip()
            if status:
                details.append(status)
            if horizon:
                details.append(horizon)

        self.result_var.set(title)
        self.detail_var.set(
            " · ".join(details)
            if details
            else "Selected from your Collection."
        )

    def _clear_result(self, refresh=True):
        self._current_result_id = ""
        self.result_var.set("No result yet")
        self.detail_var.set(
            "Spin from your Collection using the filters above."
        )
        if refresh:
            self._refresh_pool_state()

    @classmethod
    def _optional_choice(cls, value):
        value = str(value).strip()
        return "" if not value or value == cls.ALL_VALUE else value

    @classmethod
    def _single_filter(cls, value):
        value = cls._optional_choice(value)
        return [value] if value else None

    @classmethod
    def _completion_choice(cls, value):
        if value == "Completed":
            return True
        if value == "Not completed":
            return False
        return None

    @classmethod
    def _download_choice(cls, value):
        if value == "Downloaded":
            return True
        if value == "Not downloaded":
            return False
        return None

    @classmethod
    def _optional_year_choice(cls, value):
        value = str(value).strip()
        return None if not value or value == cls.ANY_VALUE else int(value)


__all__ = ["CollectionWheelDialog"]
