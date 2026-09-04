"""Interactive, read-only completion-time chart for the Dashboard."""
import tkinter as tk
from tkinter import ttk

from dashboard_time_progression import (
    excluded_exit_count, progression_series, progression_values, timeline_label_indices,
)


DIFFICULTY_ORDER = (
    "Newcomer", "Casual", "Skilled", "Intermediate", "Advanced", "Expert", "Master", "Grandmaster",
)
DIFFICULTY_COLORS = {
    "Newcomer": "diff_newcomer", "Casual": "diff_casual", "Skilled": "diff_skilled",
    "Intermediate": "diff_skilled", "Advanced": "diff_advanced", "Expert": "diff_expert",
    "Master": "diff_master", "Grandmaster": "diff_grandmaster",
}
METRIC_LABELS = {"Time per exit": "per_exit", "Time per hack": "per_hack"}


class TimeProgressionChart:
    def __init__(self, analytics_data, view_state, colors):
        self.data = analytics_data
        self.state = view_state
        self.colors = colors
        self.canvas = None
        self.legend_items = []
        self.legend_vars = {}
        self._legend_columns = None

    @property
    def progression(self):
        return self.data.get("time_progression", {})

    def _color(self, difficulty):
        return self.colors.get(DIFFICULTY_COLORS.get(difficulty)) or self.colors.get("accent") or "#3b82f6"

    def _difficulties(self, filter_type):
        present = {
            difficulty for bucket in self.progression.values()
            for difficulty in bucket.get("difficulties", {})
            if progression_values(bucket, difficulty, filter_type)
        }
        return [name for name in DIFFICULTY_ORDER if name in present] + sorted(present.difference(DIFFICULTY_ORDER))

    def create(self, parent):
        period = self.data.get("time_progression_period", "All Time")
        frame = ttk.LabelFrame(parent, text=f"Average Clear Time by Difficulty ({period})", padding=12)
        frame.pack(fill="both", expand=True, pady=5)

        controls = ttk.Frame(frame)
        controls.pack(fill="x", pady=(0, 8))
        all_types = {kind for bucket in self.progression.values()
                     for values in bucket.get("difficulties", {}).values() for kind in values.get("types", [])}
        if self.state.filter_type != "All Types":
            all_types.add(self.state.filter_type)  # Retain a selection through an empty date range.
        self._type_values = {kind.capitalize(): kind for kind in sorted(all_types)}
        self._type_values = {"All Types": "All Types", **self._type_values}
        type_label = next(label for label, value in self._type_values.items() if value == self.state.filter_type)
        ttk.Label(controls, text="Type:").grid(row=0, column=0, sticky="w", padx=(0, 5))
        self.type_var = tk.StringVar(master=frame, value=type_label)
        type_combo = ttk.Combobox(controls, textvariable=self.type_var, values=list(self._type_values), state="readonly", width=16)
        type_combo.grid(row=0, column=1, sticky="w", padx=(0, 18))
        ttk.Label(controls, text="Measure:").grid(row=0, column=2, sticky="w", padx=(0, 5))
        metric_label = next(label for label, value in METRIC_LABELS.items() if value == self.state.metric)
        self.metric_var = tk.StringVar(master=frame, value=metric_label)
        metric_combo = ttk.Combobox(controls, textvariable=self.metric_var, values=list(METRIC_LABELS), state="readonly", width=16)
        metric_combo.grid(row=0, column=3, sticky="w")

        trend_controls = ttk.Frame(frame)
        trend_controls.pack(fill="x", pady=(0, 8))
        bucket = self.data.get("time_progression_bucket", "Month").lower()
        self._smoothing_values = {"Off": 0, f"3-{bucket} average": 3, f"5-{bucket} average": 5}
        trend_label = next(label for label, value in self._smoothing_values.items() if value == self.state.smoothing)
        ttk.Label(trend_controls, text="Smoothing:").pack(side="left", padx=(0, 5))
        self.smoothing_var = tk.StringVar(master=frame, value=trend_label)
        smoothing_combo = ttk.Combobox(trend_controls, textvariable=self.smoothing_var, values=list(self._smoothing_values), state="readonly", width=19)
        smoothing_combo.pack(side="left")
        ttk.Button(trend_controls, text="Show all difficulties", command=self._show_all).pack(side="left", padx=(12, 0))

        self.help_var = tk.StringVar(master=frame)
        help_label = ttk.Label(frame, textvariable=self.help_var, wraplength=680, justify="left")
        help_label.pack(anchor="w", fill="x", pady=(0, 8))
        frame.bind("<Configure>", lambda event: help_label.configure(wraplength=max(200, event.width - 32)))
        self.canvas = tk.Canvas(frame, height=400, highlightthickness=0, bg=self.colors.get("chart_bg"))
        self.canvas.pack(fill="both", expand=True)
        ttk.Label(frame, text="Click a difficulty to hide or show it:").pack(anchor="w", pady=(6, 4))
        self.legend_frame = ttk.Frame(frame)
        self.legend_frame.pack(fill="x")
        self.legend_frame.bind("<Configure>", lambda event: self._layout_legend(event.width))
        for combo in (type_combo, metric_combo, smoothing_combo):
            combo.bind("<<ComboboxSelected>>", self._controls_changed)
        self.canvas.bind("<Configure>", self._redraw)
        self._build_legend()
        self._redraw()
        return frame

    def _controls_changed(self, _event=None):
        self.state.filter_type = self._type_values[self.type_var.get()]
        self.state.metric = METRIC_LABELS[self.metric_var.get()]
        self.state.smoothing = self._smoothing_values[self.smoothing_var.get()]
        self._build_legend()
        self._redraw()

    def _build_legend(self):
        for child in self.legend_frame.winfo_children():
            child.destroy()
        self.legend_items = []
        self.legend_vars = {}
        self._legend_columns = None
        for difficulty in self._difficulties(self.state.filter_type):
            item = ttk.Frame(self.legend_frame)
            variable = tk.BooleanVar(master=item, value=difficulty not in self.state.hidden_difficulties)
            self.legend_vars[difficulty] = variable
            swatch = ttk.Label(item, text="●", foreground=self._color(difficulty))
            swatch.pack(side="left")
            ttk.Checkbutton(
                item, text=difficulty, variable=variable,
                command=lambda name=difficulty: self._legend_changed(name),
            ).pack(side="left")
            swatch.bind("<Button-1>", lambda _event, name=difficulty: self._toggle_swatch(name))
            self.legend_items.append(item)
        self._layout_legend(self.legend_frame.winfo_width())

    def _layout_legend(self, width):
        columns = max(1, min(4, int(width) // 180))
        if columns == self._legend_columns:
            return
        self._legend_columns = columns
        for index, item in enumerate(self.legend_items):
            item.grid(row=index // columns, column=index % columns, sticky="w", padx=(0, 12), pady=3)

    def _toggle_swatch(self, difficulty):
        variable = self.legend_vars[difficulty]
        variable.set(not variable.get())
        self._legend_changed(difficulty)

    def _legend_changed(self, difficulty):
        if self.legend_vars[difficulty].get():
            self.state.hidden_difficulties.discard(difficulty)
        else:
            self.state.hidden_difficulties.add(difficulty)
        self._redraw()

    def _show_all(self):
        self.state.hidden_difficulties.clear()
        for variable in self.legend_vars.values():
            variable.set(True)
        self._redraw()

    def _help_text(self):
        if self.state.metric == "per_exit":
            excluded = excluded_exit_count(self.progression, self.state.filter_type)
            text = "Minutes per exit = recorded time ÷ known exits (exit-weighted). "
            text += f"Excluded: {excluded} timed completion(s) with missing/invalid exit counts. "
        else:
            text = "Hours per hack = total recorded time ÷ number of timed completions. "
        if self.state.smoothing:
            unit = self.data.get("time_progression_bucket", "Month").lower()
            text += (f"Line: trailing {self.state.smoothing}-{unit} average; early windows use available data. "
                     "Faint dots: actual period averages. ")
        text += "Dated completions only; missing periods stay gaps."
        return text

    def _redraw(self, _event=None):
        self.help_var.set(self._help_text())
        self.draw(self.canvas)

    def draw(self, canvas, filter_type=None):
        """Render only the selected view; hidden series do not affect scaling."""
        canvas.delete("all")
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width < 160 or height < 120:
            return  # Mapping/resizing triggers Configure; no orphan retry timers.
        filter_type = self.state.filter_type if filter_type is None else filter_type
        metric, smoothing = self.state.metric, self.state.smoothing
        colors = self.colors
        names = self._difficulties(filter_type)
        visible = [name for name in names if name not in self.state.hidden_difficulties]
        unit, factor = ("m", 60) if metric == "per_exit" else ("h", 1)
        raw, lines = {}, {}
        for name in visible:
            raw[name] = progression_series(self.progression, name, filter_type, metric=metric)
            lines[name] = progression_series(self.progression, name, filter_type, metric=metric, smoothing=smoothing)
        max_time = max((value * factor for series in [*raw.values(), *lines.values()]
                        for value in series if value is not None), default=0)
        bucket_label = self.data.get("time_progression_bucket", "Month")
        title = f"Avg Minutes per Exit per {bucket_label}" if metric == "per_exit" else f"Avg Hours per Hack per {bucket_label}"
        canvas.create_text(width // 2, 15, text=title, font=("Segoe UI", 11, "bold"), fill=colors.get("text"))
        if not max_time:
            if names and not visible:
                message = "All difficulties are hidden. Click a legend entry or Show all difficulties."
            elif metric == "per_exit":
                message = "No dated completions with both Time to Beat and known positive exits match this period and type."
            else:
                message = "No dated completions with Time to Beat match this period and type."
            canvas.create_text(width // 2, height // 2, text=message, width=max(100, width - 80),
                               font=("Segoe UI", 11), fill=colors.get("text_secondary"))
            return

        left, top, chart_width, chart_height = 85, 38, width - 115, height - 100
        for index in range(6):
            value = max_time * index / 5
            y = top + chart_height * (1 - index / 5)
            canvas.create_line(left, y, left + chart_width, y, fill=colors.get("border"), dash=(2, 2))
            canvas.create_text(left - 10, y, text=f"{value:.2g}{unit}", anchor="e", font=("Segoe UI", 9), fill=colors.get("text_secondary"))
        keys = sorted(self.progression)
        step = chart_width / max(1, len(keys) - 1)

        def point(index, value):
            x = left + index * step if len(keys) > 1 else left + chart_width / 2
            return x, top + chart_height * (1 - value * factor / max_time)

        for index in timeline_label_indices(len(keys), chart_width):
            x, _ = point(index, 0)
            canvas.create_line(x, top, x, top + chart_height, fill=colors.get("border"), dash=(2, 2))
            canvas.create_text(x, top + chart_height + 16, text=self.progression[keys[index]]["month_name"],
                               anchor="n", font=("Segoe UI", 9), fill=colors.get("text_secondary"))
        for name, values in lines.items():
            color = self._color(name)
            if smoothing:
                for index, value in enumerate(raw[name]):
                    if value is not None:
                        x, y = point(index, value)
                        canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline="", stipple="gray50", tags=("time_raw", name))
            previous = None
            for index, value in enumerate(values):
                if value is None:
                    previous = None  # Never bridge an unobserved day/month.
                    continue
                x, y = point(index, value)
                if previous is not None:
                    canvas.create_line(*previous, x, y, fill=color, width=3, tags=("time_line", name))
                radius = 3 if smoothing else 4
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius,
                                   fill=color, outline=colors.get("chart_bg"), width=1, tags=("time_point", name))
                previous = (x, y)
        axis_title = "Minutes per exit" if metric == "per_exit" else "Hours per hack"
        canvas.create_text(15, height // 2, text=axis_title, angle=90, font=("Segoe UI", 10), fill=colors.get("text_secondary"))
