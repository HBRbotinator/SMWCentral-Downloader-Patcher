"""Collection-owned graphical Wheel dialog."""

from __future__ import annotations

import copy
import math
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from collection_wheel import EmptyWheelPoolError, ExhaustedWheelPoolError
from collection_wheel_animation import build_spin_frames, build_wheel_layout
from wheel_runtime_bridge import CollectionWheelRuntimeBridge


class CollectionWheelDialog:
    """Filter the full Collection and animate an honest random selection."""

    ALL_VALUE = "All"
    ANY_VALUE = "Any"
    ANY_RATING = "Any rating"
    UNRATED = "Unrated"
    MIN_WIDTH = 980
    MIN_HEIGHT = 850
    MAX_WHEEL_LABELS = 18
    SPIN_TURNS = 5
    SPIN_FRAME_COUNT = 61
    SPIN_FRAME_DELAY_MS = 28
    POINTER_ANGLE = 90.0
    RESULT_DETAILS_WIDTH = 320
    RESULT_DETAILS_WRAP = 300
    BROWSER_LANDING_OFFSET = 0.5

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
    WHEEL_COLORS = (
        "#5B8FF9",
        "#61DDAA",
        "#65789B",
        "#F6BD16",
        "#7262FD",
        "#78D3F8",
        "#9661BC",
        "#F6903D",
        "#008685",
        "#F08BB4",
        "#2E8B57",
        "#D96C6C",
    )

    def __init__(
        self,
        parent,
        model,
        collection_records,
        *,
        result_callback=None,
        on_close=None,
        runtime_bridge=None,
        runtime_bridge_factory=CollectionWheelRuntimeBridge,
    ):
        self.parent = parent
        self.model = model
        self.model.reload_planner_state()
        self.collection_records = copy.deepcopy(list(collection_records))
        self.result_callback = result_callback
        self.on_close = on_close
        self.runtime_bridge = (
            runtime_bridge
            if runtime_bridge is not None
            else runtime_bridge_factory(self.model)
        )
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
        self.runtime_status_var = tk.StringVar(
            value="Browser Wheel stopped"
        )
        self.runtime_url_var = tk.StringVar()

        self.spin_button = None
        self.reroll_button = None
        self.clear_button = None
        self.reset_filters_button = None
        self.runtime_start_button = None
        self.runtime_copy_button = None
        self.runtime_stop_button = None
        self.wheel_canvas = None
        self._current_result_id = ""
        self._active_pool = []
        self._pool_available = False
        self._list_name_to_id = {}
        self._planner_refinements_visible = False

        self._spinning = False
        self._animation_after_id = None
        self._spin_frames = ()
        self._spin_frame_index = 0
        self._wheel_layout = build_wheel_layout([])
        self._wheel_rotation = 0.0
        self._pending_result = None

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
        self._cancel_spin_animation()
        self._stop_browser_runtime(show_error=False)
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
            wraplength=940,
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

        self.reset_filters_button = ttk.Button(
            collection_frame,
            text="Reset Filters",
            command=self._reset_collection_filters,
        )
        self.reset_filters_button.grid(
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

        runtime_frame = ttk.LabelFrame(
            content,
            text="Browser / OBS Wheel",
            padding=10,
        )
        runtime_frame.pack(fill="x", pady=(12, 0))
        runtime_frame.grid_columnconfigure(1, weight=1)
        ttk.Label(
            runtime_frame,
            text=(
                "Start the local browser Wheel, then paste its URL into an "
                "OBS Browser Source. The transparent overlay follows "
                "this dialog's filters and results, and stays hidden while "
                "idle."
            ),
            wraplength=930,
        ).grid(
            row=0,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(0, 8),
        )
        self.runtime_start_button = ttk.Button(
            runtime_frame,
            text="Start Browser Wheel",
            command=self._start_browser_runtime,
        )
        self.runtime_start_button.grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 8),
        )
        runtime_url_entry = ttk.Entry(
            runtime_frame,
            textvariable=self.runtime_url_var,
            state="readonly",
        )
        runtime_url_entry.grid(
            row=1,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        self.runtime_copy_button = ttk.Button(
            runtime_frame,
            text="Copy OBS URL",
            command=self._copy_browser_url,
        )
        self.runtime_copy_button.grid(
            row=1,
            column=2,
            sticky="e",
            padx=(0, 8),
        )
        self.runtime_stop_button = ttk.Button(
            runtime_frame,
            text="Stop",
            command=self._stop_browser_runtime,
        )
        self.runtime_stop_button.grid(
            row=1,
            column=3,
            sticky="e",
        )
        ttk.Label(
            runtime_frame,
            textvariable=self.runtime_status_var,
        ).grid(
            row=2,
            column=0,
            columnspan=4,
            sticky="w",
            pady=(7, 0),
        )

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

        result_frame = ttk.LabelFrame(content, text="Wheel", padding=12)
        result_frame.pack(fill="both", expand=True, pady=(12, 0))
        result_frame.grid_columnconfigure(0, weight=1)
        result_frame.grid_columnconfigure(
            1,
            weight=0,
            minsize=self.RESULT_DETAILS_WIDTH,
        )
        result_frame.grid_rowconfigure(0, weight=1)

        canvas_background = self.window.cget("background")
        self.wheel_canvas = tk.Canvas(
            result_frame,
            width=440,
            height=440,
            background=canvas_background,
            highlightthickness=0,
        )
        self.wheel_canvas.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 16),
        )
        self.wheel_canvas.bind("<Configure>", self._on_canvas_resize)

        result_details = ttk.Frame(
            result_frame,
            width=self.RESULT_DETAILS_WIDTH,
            padding=(8, 8),
        )
        result_details.grid(row=0, column=1, sticky="nsew")
        result_details.grid_propagate(False)
        ttk.Label(
            result_details,
            textvariable=self.pool_count_var,
            font=("Segoe UI", 9, "bold"),
            wraplength=self.RESULT_DETAILS_WRAP,
        ).pack(anchor="w")
        ttk.Separator(result_details).pack(fill="x", pady=(12, 18))
        ttk.Label(
            result_details,
            textvariable=self.result_var,
            font=("Segoe UI", 16, "bold"),
            wraplength=self.RESULT_DETAILS_WRAP,
            justify="center",
        ).pack(fill="x", expand=True, anchor="center")
        ttk.Label(
            result_details,
            textvariable=self.detail_var,
            wraplength=self.RESULT_DETAILS_WRAP,
            justify="center",
        ).pack(fill="x", pady=(12, 0))

    @staticmethod
    def _obs_browser_url(browser_url):
        parts = urlsplit(str(browser_url).strip())
        query = dict(parse_qsl(parts.query, keep_blank_values=True))
        query["mode"] = "overlay"
        return urlunsplit(
            (
                parts.scheme,
                parts.netloc,
                parts.path,
                urlencode(query),
                parts.fragment,
            )
        )

    @classmethod
    def _browser_spin_duration_ms(cls):
        return max(
            1000,
            cls.SPIN_FRAME_DELAY_MS * (cls.SPIN_FRAME_COUNT - 1),
        )

    def _start_browser_runtime(self):
        if self._spinning or not self._pool_available:
            return
        try:
            preview_url = self.runtime_bridge.start(self._active_pool)
            browser_url = self._obs_browser_url(preview_url)
            self.runtime_url_var.set(browser_url)
            copied = self._copy_browser_url(show_error=False)
            count = len(self._active_pool)
            suffix = "candidate" if count == 1 else "candidates"
            status = f"Running with {count} {suffix}"
            if copied:
                status += " · OBS URL copied"
            self.runtime_status_var.set(status)
        except Exception as error:
            self.runtime_status_var.set(
                f"Browser Wheel could not start: {error}"
            )
            messagebox.showerror(
                "Browser Wheel",
                f"Could not start the browser Wheel:\n{error}",
                parent=self.window,
            )
        finally:
            self._update_runtime_controls()

    def _copy_browser_url(self, show_error=True):
        browser_url = self.runtime_url_var.get().strip()
        if not browser_url:
            return False
        try:
            self.window.clipboard_clear()
            self.window.clipboard_append(browser_url)
            self.window.update_idletasks()
            return True
        except tk.TclError as error:
            if show_error:
                messagebox.showerror(
                    "Browser Wheel",
                    f"Could not copy the OBS URL:\n{error}",
                    parent=self.window,
                )
            return False

    def _stop_browser_runtime(self, show_error=True):
        try:
            self.runtime_bridge.stop()
        except Exception as error:
            if show_error and self.window:
                messagebox.showerror(
                    "Browser Wheel",
                    f"Could not stop the browser Wheel:\n{error}",
                    parent=self.window,
                )
            return False

        self.runtime_url_var.set("")
        self.runtime_status_var.set("Browser Wheel stopped")
        self._update_runtime_controls()
        return True

    def _sync_browser_pool(self, pool):
        if not self.runtime_bridge.running:
            return True
        try:
            self.runtime_bridge.refresh_pool(pool)
        except Exception as error:
            self.runtime_status_var.set(
                f"Browser Wheel kept its previous pool: {error}"
            )
            return False

        count = len(pool)
        suffix = "candidate" if count == 1 else "candidates"
        self.runtime_status_var.set(
            f"Running with {count} {suffix}"
        )
        return True

    def _publish_browser_selection(self, pool, result):
        if not self.runtime_bridge.running:
            return True
        try:
            self.runtime_bridge.publish_selection(
                pool,
                result.candidate_id,
                duration_ms=self._browser_spin_duration_ms(),
                turns=self.SPIN_TURNS,
                landing_offset=self.BROWSER_LANDING_OFFSET,
            )
        except Exception as error:
            self.runtime_status_var.set(
                f"Browser Wheel did not receive the spin: {error}"
            )
            messagebox.showwarning(
                "Browser Wheel",
                (
                    "The native Wheel will continue, but the browser Wheel "
                    f"could not receive this spin:\n{error}"
                ),
                parent=self.window,
            )
            return False

        self.runtime_status_var.set(
            f"Spinning to {result.candidate.get('title', result.candidate_id)}"
        )
        return True

    def _update_runtime_controls(self):
        if not self.runtime_start_button:
            return

        running = bool(self.runtime_bridge.running)
        locked = self._spinning
        self.runtime_start_button.configure(
            state=(
                "normal"
                if self._pool_available and not running and not locked
                else "disabled"
            )
        )
        self.runtime_copy_button.configure(
            state="normal" if running else "disabled"
        )
        self.runtime_stop_button.configure(
            state="normal" if running and not locked else "disabled"
        )

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
        if self._spinning:
            return
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
        if self._spinning:
            return
        try:
            pool = self.model.build_pool(
                self.collection_records,
                **self._current_filters(),
            )
        except Exception as error:
            self._pool_available = False
            self._active_pool = []
            self.pool_count_var.set("Pool unavailable")
            self.spin_button.configure(state="disabled")
            self.reroll_button.configure(state="disabled")
            self.detail_var.set(str(error))
            self._wheel_layout = build_wheel_layout([])
            self._wheel_rotation = 0.0
            self._render_wheel()
            self._update_runtime_controls()
            return

        self._pool_available = True
        self._active_pool = copy.deepcopy(pool)
        self._sync_browser_pool(self._active_pool)
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

        selected_id = self._current_result_id if current is not None else None
        self._wheel_layout = build_wheel_layout(
            pool,
            selected_id=selected_id,
            max_labels=self.MAX_WHEEL_LABELS,
        )
        self._wheel_rotation = 0.0
        self._render_wheel(reveal_selected=bool(selected_id))

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
        self._update_runtime_controls()

    def _spin(self, exclude_current=False):
        if self._spinning:
            return
        excluded_ids = None
        if exclude_current and self._current_result_id:
            excluded_ids = [self._current_result_id]
        try:
            pool = self.model.build_pool(
                self.collection_records,
                **self._current_filters(),
            )
            result = self.model.select_from_pool(
                pool,
                excluded_ids=excluded_ids,
            )
            excluded = set(result.excluded_ids)
            animation_pool = [
                record
                for record in pool
                if str(record.get("id", "")).strip() not in excluded
            ]
            layout = build_wheel_layout(
                animation_pool,
                selected_id=result.candidate_id,
                max_labels=self.MAX_WHEEL_LABELS,
            )
            frames = build_spin_frames(
                layout,
                turns=self.SPIN_TURNS,
                frame_count=self.SPIN_FRAME_COUNT,
                pointer_angle=self.POINTER_ANGLE,
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
                f"Could not select a Wheel result:\n{error}",
                parent=self.window,
            )
            return

        self._publish_browser_selection(animation_pool, result)
        self._begin_spin_animation(layout, frames, result)

    def _begin_spin_animation(self, layout, frames, result):
        self._cancel_spin_animation()
        self._wheel_layout = layout
        self._spin_frames = tuple(frames)
        self._spin_frame_index = 0
        self._wheel_rotation = self._spin_frames[0]
        self._pending_result = result
        self.result_var.set("Spinning...")
        self.detail_var.set(
            f"Selecting from {result.eligible_size} eligible candidates."
        )
        self._set_spinning_state(True)
        self._render_wheel(reveal_selected=False)
        self._animation_after_id = self.window.after(
            self.SPIN_FRAME_DELAY_MS,
            self._advance_spin_animation,
        )

    def _advance_spin_animation(self):
        self._animation_after_id = None
        if not self._spinning or not self.window:
            return
        self._spin_frame_index += 1
        self._wheel_rotation = self._spin_frames[self._spin_frame_index]
        self._render_wheel(reveal_selected=False)
        if self._spin_frame_index >= len(self._spin_frames) - 1:
            self._finish_spin_animation()
            return
        self._animation_after_id = self.window.after(
            self.SPIN_FRAME_DELAY_MS,
            self._advance_spin_animation,
        )

    def _finish_spin_animation(self):
        result = self._pending_result
        self._pending_result = None
        self._animation_after_id = None
        if result is None:
            self._set_spinning_state(False)
            return

        self._current_result_id = result.candidate_id
        self._show_result(result.candidate)
        self._render_wheel(reveal_selected=True)
        self._set_spinning_state(False)
        self.spin_button.configure(state="normal")
        self.reroll_button.configure(
            state="normal" if result.pool_size > 1 else "disabled"
        )
        self.clear_button.configure(state="normal")
        if self.result_callback:
            self.result_callback(result.candidate_id)

    def _cancel_spin_animation(self):
        after_id = self._animation_after_id
        self._animation_after_id = None
        if after_id is not None and self.window:
            try:
                if self.window.winfo_exists():
                    self.window.after_cancel(after_id)
            except tk.TclError:
                pass
        self._pending_result = None
        self._spinning = False

    def _set_spinning_state(self, spinning):
        self._spinning = bool(spinning)
        entry_state = "disabled" if spinning else "normal"
        combo_state = "disabled" if spinning else "readonly"
        button_state = "disabled" if spinning else "normal"

        self.search_entry.configure(state=entry_state)
        self.reset_filters_button.configure(state=button_state)
        for combo in (*self.collection_combos, *self.planner_combos):
            combo.configure(state=combo_state)

        if spinning:
            self.spin_button.configure(state="disabled")
            self.reroll_button.configure(state="disabled")
            self.clear_button.configure(state="disabled")
        self._update_runtime_controls()

    def _on_canvas_resize(self, _event=None):
        self._render_wheel(reveal_selected=not self._spinning)

    def _render_wheel(self, *, reveal_selected=False):
        if not self.wheel_canvas:
            return
        canvas = self.wheel_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), int(canvas.cget("width")))
        height = max(canvas.winfo_height(), int(canvas.cget("height")))
        center_x, center_y, radius, bounds = self._wheel_geometry(
            width,
            height,
        )

        if not self._wheel_layout.segments:
            canvas.create_oval(
                *bounds,
                outline="#8A8A8A",
                width=2,
            )
            self.wheel_canvas.create_text(
                center_x,
                center_y,
                text="No candidates",
                fill="#666666",
                font=("Segoe UI", 12, "bold"),
            )
            self._draw_pointer(center_x, center_y, radius)
            return

        selected_index = self._wheel_layout.selected_index
        for index, segment in enumerate(self._wheel_layout.segments):
            start = (segment.start_angle + self._wheel_rotation) % 360.0
            is_selected = reveal_selected and index == selected_index
            outline = "#202020" if not is_selected else "#FFFFFF"
            width_value = 1 if not is_selected else 4
            extent = min(segment.extent, 359.999)
            self.wheel_canvas.create_arc(
                *bounds,
                start=start,
                extent=extent,
                style="pieslice",
                fill=self.WHEEL_COLORS[index % len(self.WHEEL_COLORS)],
                outline=outline,
                width=width_value,
            )

        for segment in self._wheel_layout.segments:
            if not segment.show_label:
                continue
            angle = (
                segment.center_angle + self._wheel_rotation
            ) % 360.0
            radians = math.radians(angle)
            label_radius = radius * 0.67
            x = center_x + label_radius * math.cos(radians)
            y = center_y - label_radius * math.sin(radians)
            label = self._short_label(segment.title)
            self.wheel_canvas.create_text(
                x + 1,
                y + 1,
                text=label,
                fill="#202020",
                font=("Segoe UI", 8, "bold"),
                width=max(60, int(radius * 0.42)),
                justify="center",
            )
            self.wheel_canvas.create_text(
                x,
                y,
                text=label,
                fill="#FFFFFF",
                font=("Segoe UI", 8, "bold"),
                width=max(60, int(radius * 0.42)),
                justify="center",
            )

        hub_radius = max(12.0, radius * 0.08)
        canvas.create_oval(
            center_x - hub_radius,
            center_y - hub_radius,
            center_x + hub_radius,
            center_y + hub_radius,
            fill="#F4F4F4",
            outline="#303030",
            width=2,
        )
        self._draw_pointer(center_x, center_y, radius)

    @staticmethod
    def _wheel_geometry(width, height):
        width = max(1.0, float(width))
        height = max(1.0, float(height))
        size = min(width, height)
        radius = max(40.0, size / 2 - 28.0)
        center_x = width / 2
        center_y = height / 2 + 6
        bounds = (
            center_x - radius,
            center_y - radius,
            center_x + radius,
            center_y + radius,
        )
        return center_x, center_y, radius, bounds

    def _draw_pointer(self, center_x, center_y, radius):
        tip_y = center_y - radius + 14
        base_y = center_y - radius - 16
        self.wheel_canvas.create_polygon(
            center_x,
            tip_y,
            center_x - 15,
            base_y,
            center_x + 15,
            base_y,
            fill="#E5484D",
            outline="#6E1F22",
            width=2,
        )

    @staticmethod
    def _short_label(title, limit=22):
        title = " ".join(str(title).split())
        if len(title) <= limit:
            return title
        return title[: max(1, limit - 1)].rstrip() + "…"

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
        if self._spinning:
            return
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
