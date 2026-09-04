"""Exit-normalized trends, legend controls and read-only Dashboard view state."""
from copy import deepcopy
from datetime import date
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

from dashboard_time_progression import (
    TimeChartViewState, build_time_progression, excluded_exit_count,
    known_exit_count, progression_average, progression_series,
)

ROOT = Path(__file__).parent
TODAY = date(2026, 9, 4)


def load(relative):
    spec = importlib.util.spec_from_file_location("_" + relative.replace("/", "_"), ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CHART = load("ui/dashboard/time_chart.py")
ANALYTICS = load("ui/dashboard/analytics.py")


def record(day="2026-09-04", hours=1, exits=1, **extra):
    return {"completed": True, "completed_date": day, "time_to_beat": hours * 3600,
            "exits": exits, "current_difficulty": "Master", "hack_types": ["kaizo"], **extra}


class TimePerExitTest(unittest.TestCase):
    def test_per_exit_is_total_time_over_total_known_exits_not_mean_of_hack_rates(self):
        records = {"one": record(hours=2, exits=2), "two": record(hours=3, exits=18),
                   "unknown": record(hours=4, exits=0)}
        data = build_time_progression(records, "last_week", TODAY)
        bucket = data["2026-09-04"]
        self.assertEqual(0.25, progression_average(bucket, "Master", metric="per_exit"))
        self.assertEqual(3, progression_average(bucket, "Master", metric="per_hack"))
        self.assertEqual(1, excluded_exit_count(data))

    def test_type_filter_and_multi_type_hack_use_their_own_exit_denominators(self):
        records = {"one": record(hours=1, exits=2),
                   "two": record(hours=9, exits=3, hack_types=["standard"]),
                   "both": record(hours=2, exits=4, hack_types=["kaizo", "standard", "kaizo"])}
        bucket = build_time_progression(records, "all_time", TODAY)["2026-09"]
        self.assertAlmostEqual(12 / 9, progression_average(bucket, "Master", metric="per_exit"))
        self.assertEqual(0.5, progression_average(bucket, "Master", "kaizo", "per_exit"))
        self.assertAlmostEqual(11 / 7, progression_average(bucket, "Master", "standard", "per_exit"))
        self.assertIsNone(progression_average(bucket, "Master", "puzzle", "per_exit"))

    def test_unknown_invalid_and_zero_exits_never_gain_an_assumed_count(self):
        for exits in (None, "", "Unknown", "bad", 0, -1, True, False, 1.5, "2.5", float("nan"), float("inf")):
            with self.subTest(exits=exits):
                row = record(exits=exits)
                self.assertIsNone(known_exit_count(row))
                data = build_time_progression({"one": row}, "last_week", TODAY)
                bucket = data["2026-09-04"]
                self.assertIsNone(progression_average(bucket, "Master", metric="per_exit"))
                self.assertEqual(1, progression_average(bucket, "Master", metric="per_hack"))
                self.assertEqual(1, excluded_exit_count(data))
        for exits in (5, 5.0, "5", "5.0"):
            self.assertEqual(5, known_exit_count(record(exits=exits)))

    def test_actual_analytics_summary_matches_chart_and_tolerates_missing_exits(self):
        records = {"known": record(hours=2, exits=4), "unknown": record(hours=8, exits=None)}
        manager = SimpleNamespace(data=records, get_all_hacks=lambda **_kwargs: [{"id": key} for key in records])
        engine = ANALYTICS.DashboardAnalytics(manager)
        with patch.object(ANALYTICS, "datetime") as clock:
            clock.now.return_value.date.return_value = TODAY
            # Other analytics use real strptime and subtraction.
            from datetime import datetime
            clock.strptime.side_effect = datetime.strptime
            clock.now.return_value = datetime(2026, 9, 4, 18)
            analytics = engine.load_analytics_data("all_time")
        self.assertEqual(0.5, analytics["avg_time_per_exit"])
        self.assertEqual(5, analytics["avg_time_per_hack"])
        self.assertEqual(4, analytics["completed_exits"])
        self.assertEqual(4, analytics["total_exits"])
        self.assertEqual(analytics["avg_time_per_exit"], progression_average(
            analytics["time_progression"]["2026-09"], "Master", metric="per_exit"))

    def test_summary_excludes_exits_without_time_but_keeps_completed_exit_inventory(self):
        engine = ANALYTICS.DashboardAnalytics(None)
        engine.all_data = {"timed": record(hours=2, exits=4), "untimed": record(hours=0, exits=100)}
        engine._should_include_hack = lambda _record: True
        engine._calculate_time_metrics()
        self.assertEqual(104, engine.analytics_data["completed_exits"])
        self.assertEqual(0.5, engine.analytics_data["avg_time_per_exit"])
        engine.all_data = {"unknown": record(exits=0)}
        engine._calculate_time_metrics()
        self.assertEqual(0, engine.analytics_data["avg_time_per_exit"])

    def test_first_clear_projection_is_used_not_every_imported_playthrough(self):
        row = record(hours=2, exits=4, playthroughs=[{"time_to_beat": 900000}])
        data = build_time_progression({"one": row}, "last_week", TODAY)
        self.assertEqual(0.5, progression_average(data["2026-09-04"], "Master", metric="per_exit"))


class SmoothingTest(unittest.TestCase):
    def test_trailing_window_uses_calendar_periods_weights_and_preserves_gaps(self):
        records = {"one": record("2026-09-01", 1, 1), "two": record("2026-09-02", 3, 9),
                   "four": record("2026-09-04", 4, 2)}
        data = build_time_progression(records, "last_week", TODAY)
        result = dict(zip(sorted(data), progression_series(data, "Master", smoothing=3)))
        self.assertEqual(1, result["2026-09-01"])
        self.assertEqual(0.4, result["2026-09-02"])
        self.assertIsNone(result["2026-09-03"])
        self.assertAlmostEqual(7 / 11, result["2026-09-04"])

    def test_per_hack_smoothing_is_weighted_by_completed_hacks_not_average_of_averages(self):
        records = {"one": record("2026-09-01")}
        records.update({str(i): record("2026-09-02", 3) for i in range(3)})
        data = build_time_progression(records, "last_week", TODAY)
        result = dict(zip(sorted(data), progression_series(data, "Master", metric="per_hack", smoothing=3)))
        self.assertEqual(2.5, result["2026-09-02"])

    def test_smoothing_respects_type_difficulty_and_the_selected_period(self):
        records = {"before": record("2026-08-28", 1000), "inside": record("2026-08-29", 1),
                   "other_type": record("2026-08-29", 100, hack_types=["standard"]),
                   "other_difficulty": record("2026-08-29", 100, current_difficulty="Expert")}
        data = build_time_progression(records, "last_week", TODAY)
        result = progression_series(data, "Master", "kaizo", smoothing=5)
        self.assertEqual(1, result[0])
        self.assertTrue(all(value is None for value in result[1:]))

    def test_five_month_window_and_future_values_do_not_change_earlier_points(self):
        records = {str(month): record(f"2026-{month:02d}-01", month) for month in range(1, 9)}
        data = build_time_progression(records, "all_time", TODAY)
        series = progression_series(data, "Master", smoothing=5)
        self.assertEqual(1, series[0])
        self.assertEqual(6, series[7])  # Apr-Aug, each with one exit.
        records["8"]["time_to_beat"] *= 100
        changed = progression_series(build_time_progression(records, "all_time", TODAY), "Master", smoothing=5)
        self.assertEqual(series[:7], changed[:7])

    def test_per_exit_gap_stays_missing_even_when_a_timed_hack_lacks_exits(self):
        records = {"one": record("2026-09-01"), "missing": record("2026-09-02", 9, None)}
        data = build_time_progression(records, "last_week", TODAY)
        values = dict(zip(sorted(data), progression_series(data, "Master", smoothing=3)))
        self.assertIsNone(values["2026-09-02"])

    def test_chart_calculations_do_not_mutate_completion_or_bucket_data(self):
        records = {"one": record(), "unknown": record(exits=0)}
        original = deepcopy(records)
        data = build_time_progression(records, "last_week", TODAY)
        before = deepcopy(data)
        for metric in ("per_exit", "per_hack"):
            for smoothing in (0, 3, 5):
                progression_series(data, "Master", metric=metric, smoothing=smoothing)
        self.assertEqual(original, records)
        self.assertEqual(before, data)

    def test_unknown_metric_or_smoothing_is_rejected(self):
        data = build_time_progression({"one": record()}, "last_week", TODAY)
        with self.assertRaises(ValueError):
            progression_series(data, "Master", metric="unrecognized")
        with self.assertRaises(ValueError):
            progression_series(data, "Master", smoothing=7)


class Value:
    def __init__(self, value=False, **_kwargs): self.value = value
    def get(self): return self.value
    def set(self, value): self.value = value


class Canvas:
    def __init__(self): self.items = []
    def delete(self, *_args): self.items.clear()
    def winfo_width(self): return 800
    def winfo_height(self): return 400
    def create_text(self, *args, **kwargs): self.items.append(("text", args, kwargs))
    def create_line(self, *args, **kwargs): self.items.append(("line", args, kwargs))
    def create_oval(self, *args, **kwargs): self.items.append(("oval", args, kwargs))


class TimeChartUiTest(unittest.TestCase):
    def chart(self, records, state=None):
        data = {"time_progression": build_time_progression(records, "last_week", TODAY), "time_progression_bucket": "Day"}
        return CHART.TimeProgressionChart(data, state or TimeChartViewState(), {})

    def test_default_is_per_exit_with_smoothing_off_and_no_hidden_difficulties(self):
        state = TimeChartViewState()
        self.assertEqual(("per_exit", 0, "All Types", set()),
                         (state.metric, state.smoothing, state.filter_type, state.hidden_difficulties))
        state.hidden_difficulties.add("Master")
        self.assertEqual(set(), TimeChartViewState().hidden_difficulties)

    def test_dashboard_guide_is_copied_into_candidate_documentation(self):
        from build_support.build_candidate import _copy_support_files
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            identity = root / "identity.json"
            identity.write_text("{}", encoding="utf-8")
            destination = root / "Documentation"
            _copy_support_files(destination, identity)
            self.assertEqual((ROOT / "DASHBOARD.md").read_bytes(), (destination / "DASHBOARD.md").read_bytes())
            self.assertIn("[DASHBOARD.md](DASHBOARD.md)", (destination / "README.md").read_text(encoding="utf-8"))

    def test_metric_switch_changes_units_without_changing_recorded_time(self):
        row = record(hours=2, exits=4)
        chart = self.chart({"one": row})
        canvas = Canvas()
        chart.draw(canvas)
        labels = [item[2].get("text") for item in canvas.items]
        self.assertIn("Avg Minutes per Exit per Day", labels)
        self.assertIn("30m", labels)
        chart.state.metric = "per_hack"
        chart.draw(canvas)
        self.assertIn("2h", [item[2].get("text") for item in canvas.items])
        self.assertEqual(7200, row["time_to_beat"])

    def test_hiding_series_rescales_and_all_hidden_keeps_a_recovery_message(self):
        chart = self.chart({"one": record(), "large": record(hours=100, current_difficulty="Expert")})
        canvas = Canvas()
        chart.state.hidden_difficulties.add("Expert")
        chart.draw(canvas)
        self.assertIn("60m", [item[2].get("text") for item in canvas.items])
        self.assertFalse(any("Expert" in item[2].get("tags", ()) for item in canvas.items))
        chart.state.hidden_difficulties.add("Master")
        chart.draw(canvas)
        self.assertTrue(any("All difficulties are hidden" in item[2].get("text", "") for item in canvas.items))
        chart._redraw = Mock()
        chart.legend_vars = {"Master": Value(False), "Expert": Value(False)}
        chart._show_all()
        self.assertEqual(set(), chart.state.hidden_difficulties)
        self.assertTrue(all(variable.get() for variable in chart.legend_vars.values()))

    def test_legend_checkbox_and_swatch_both_toggle_the_same_view_state(self):
        chart = self.chart({"one": record()})
        chart._redraw = Mock()
        chart.legend_vars = {"Master": Value(False)}
        chart._legend_changed("Master")
        self.assertIn("Master", chart.state.hidden_difficulties)
        chart._toggle_swatch("Master")
        self.assertTrue(chart.legend_vars["Master"].get())
        self.assertNotIn("Master", chart.state.hidden_difficulties)
        self.assertEqual(2, chart._redraw.call_count)

    def test_raw_and_smoothed_lines_do_not_bridge_missing_periods(self):
        rows = {"one": record("2026-09-01"), "two": record("2026-09-02", 2), "four": record("2026-09-04", 4)}
        chart = self.chart(rows)
        canvas = Canvas()
        for smoothing in (0, 3, 5):
            chart.state.smoothing = smoothing
            chart.draw(canvas)
            lines = [item for item in canvas.items if "time_line" in item[2].get("tags", ())]
            self.assertEqual(1, len(lines))
            raw = [item for item in canvas.items if "time_raw" in item[2].get("tags", ())]
            self.assertEqual(3 if smoothing else 0, len(raw))

    def test_no_known_exits_explains_empty_chart_but_per_hack_still_shows_data(self):
        chart = self.chart({"one": record(exits=0)})
        canvas = Canvas()
        chart.draw(canvas)
        self.assertTrue(any("known positive exits" in item[2].get("text", "") for item in canvas.items))
        self.assertIn("Excluded: 1", chart._help_text())
        chart.state.metric = "per_hack"
        chart.draw(canvas)
        self.assertTrue(any("time_point" in item[2].get("tags", ()) for item in canvas.items))

    def test_controls_update_shared_state_and_use_the_existing_buckets(self):
        chart = self.chart({"one": record()})
        data = chart.progression
        chart.type_var, chart.metric_var, chart.smoothing_var = Value("Kaizo"), Value("Time per hack"), Value("3-day average")
        chart._type_values = {"Kaizo": "kaizo"}
        chart._smoothing_values = {"3-day average": 3}
        chart._build_legend = Mock()
        chart._redraw = Mock()
        chart._controls_changed()
        self.assertEqual(("kaizo", "per_hack", 3), (chart.state.filter_type, chart.state.metric, chart.state.smoothing))
        self.assertIs(data, chart.progression)
        chart._build_legend.assert_called_once()
        chart._redraw.assert_called_once()

    def test_legend_wraps_at_narrow_widths_and_includes_unknown_difficulties(self):
        chart = self.chart({"one": record(current_difficulty="Custom difficulty")})
        self.assertEqual(["Custom difficulty"], chart._difficulties("All Types"))
        chart.legend_items = [Mock() for _ in range(8)]
        chart._layout_legend(400)
        self.assertEqual(2, chart._legend_columns)
        chart.legend_items[-1].grid.assert_called_with(row=3, column=1, sticky="w", padx=(0, 12), pady=3)
        chart._layout_legend(800)
        self.assertEqual(4, chart._legend_columns)

    def test_dashboard_refresh_reuses_the_same_chart_state(self):
        import ui.dashboard.main_dashboard as module
        page = module.DashboardPage.__new__(module.DashboardPage)
        page.logger = None
        page.date_filter = "last_week"
        state = TimeChartViewState(metric="per_hack", smoothing=5, filter_type="kaizo", hidden_difficulties={"Master"})
        page.time_chart_view_state = state
        page.analytics_data = {}
        page.scrollable_frame = Mock()
        page.scrollable_frame.winfo_children.return_value = []
        page.canvas = Mock()
        page._load_analytics_data = Mock()
        page._bind_mousewheel_to_children = Mock()
        with patch.multiple(module, HackDataManager=Mock(), DashboardAnalytics=Mock(), DashboardMetrics=Mock()), \
             patch.object(module, "DashboardCharts") as charts, patch.object(module.tk, "Frame", Mock()):
            page._refresh_dashboard()
            charts.assert_called_once_with(page.scrollable_frame, page.analytics_data, state)
        self.assertIs(state, page.time_chart_view_state)
        self.assertEqual({"Master"}, state.hidden_difficulties)

    def test_created_controls_and_legend_are_wired_for_daily_and_monthly_views(self):
        class Widget(Canvas):
            def __init__(self, parent=None, **kwargs):
                super().__init__()
                self.parent, self.kwargs = parent, kwargs
                self.children, self.bindings = [], {}
                if isinstance(parent, Widget): parent.children.append(self)
            def pack(self, **_kwargs): pass
            def grid(self, **_kwargs): pass
            def bind(self, event, callback): self.bindings[event] = callback
            def configure(self, **kwargs): self.kwargs.update(kwargs)
            def winfo_children(self): return list(self.children)
            def destroy(self): self.parent.children.remove(self)

        for bucket in ("Day", "Month"):
            with self.subTest(bucket=bucket):
                chart = self.chart({"one": record()})
                chart.data["time_progression_bucket"] = bucket
                with patch.multiple(CHART.tk, StringVar=Value, BooleanVar=Value, Canvas=Widget), \
                     patch.multiple(CHART.ttk, Frame=Widget, LabelFrame=Widget, Label=Widget,
                                    Combobox=Widget, Button=Widget, Checkbutton=Widget):
                    frame = chart.create(None)
                    controls, trend_controls = frame.children[:2]
                    metric = next(widget for widget in controls.children if widget.kwargs.get("values") == ["Time per exit", "Time per hack"])
                    self.assertEqual("Time per exit", metric.kwargs["textvariable"].get())
                    metric.kwargs["textvariable"].set("Time per hack")
                    metric.bindings["<<ComboboxSelected>>"](None)
                    self.assertEqual("per_hack", chart.state.metric)
                    smoothing = next(widget for widget in trend_controls.children if "values" in widget.kwargs)
                    self.assertEqual(["Off", f"3-{bucket.lower()} average", f"5-{bucket.lower()} average"], smoothing.kwargs["values"])
                    smoothing.kwargs["textvariable"].set(f"3-{bucket.lower()} average")
                    smoothing.bindings["<<ComboboxSelected>>"](None)
                    self.assertEqual(3, chart.state.smoothing)
                    legend = chart.legend_items[0]
                    swatch, checkbox = legend.children
                    swatch.bindings["<Button-1>"](None)
                    self.assertEqual({"Master"}, chart.state.hidden_difficulties)
                    checkbox.kwargs["variable"].set(True)
                    checkbox.kwargs["command"]()
                    self.assertEqual(set(), chart.state.hidden_difficulties)


if __name__ == "__main__":
    unittest.main(verbosity=2)
