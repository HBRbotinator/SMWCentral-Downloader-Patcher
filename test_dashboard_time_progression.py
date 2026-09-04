"""Dashboard periods, type averages, and dense timeline rendering regressions."""
from datetime import date, datetime, timedelta
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dashboard_time_progression import (
    DATE_FILTER_DAYS, build_time_progression, completion_in_period,
    period_start, progression_average, timeline_label_indices,
    TimeChartViewState,
)

ROOT = Path(__file__).parent
TODAY = date(2026, 9, 3)


def load(relative):
    spec = importlib.util.spec_from_file_location(relative.replace('/', '_'), ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(completed="2026-09-01", hours=1, types=("kaizo",), **extra):
    return dict(completed=True, completed_date=completed, time_to_beat=hours * 3600,
                current_difficulty="Master", hack_types=list(types), exits=10, **extra)


class DashboardTimeProgressionTest(unittest.TestCase):
    def test_selected_period_filters_before_averaging_and_all_time_includes_older_history(self):
        records = {"recent": record(), "older": record("2025-01-01", 9)}
        week = build_time_progression(records, "last_week", TODAY)
        self.assertEqual(7, len(week))
        self.assertEqual(1, progression_average(week["2026-09-01"], "Master"))
        all_time = build_time_progression(records, "all_time", TODAY)
        self.assertEqual(9, progression_average(all_time["2025-01"], "Master"))
        self.assertEqual(1, progression_average(all_time["2026-09"], "Master"))

    def test_all_rolling_periods_share_inclusive_whole_day_boundaries(self):
        for selection, days in DATE_FILTER_DAYS.items():
            with self.subTest(selection=selection):
                start = TODAY - timedelta(days=days - 1)
                self.assertEqual(start, period_start(selection, TODAY))
                rows = {"start": record(start.isoformat(), 2), "today": record(TODAY.isoformat(), 4),
                        "before": record((start - timedelta(days=1)).isoformat(), 100),
                        "future": record((TODAY + timedelta(days=1)).isoformat(), 100)}
                chart = build_time_progression(rows, selection, TODAY)
                self.assertEqual([True, True, False, False],
                                 [completion_in_period(row, selection, TODAY) for row in rows.values()])
                self.assertEqual(2, sum(d['count'] for b in chart.values() for d in b['difficulties'].values()))

    def test_monthly_buckets_do_not_include_out_of_period_start_of_month(self):
        rows = {"outside": record("2026-06-01", 100), "inside": record("2026-06-30", 2)}
        chart = build_time_progression(rows, "3_months", TODAY)
        self.assertEqual(2, progression_average(chart["2026-06"], "Master"))
        self.assertEqual({}, chart["2026-07"]["difficulties"])

    def test_type_average_and_multi_type_hack_are_counted_correctly(self):
        rows = {"one": record(hours=1), "nine": record(hours=9, types=("standard",)),
                "two": record(hours=2, types=("kaizo", "standard", "kaizo"))}
        bucket = build_time_progression(rows, "all_time", TODAY)["2026-09"]
        self.assertEqual(4, progression_average(bucket, "Master"))
        self.assertEqual(3, bucket["difficulties"]["Master"]["count"])
        self.assertEqual(1.5, progression_average(bucket, "Master", "kaizo"))
        self.assertEqual(5.5, progression_average(bucket, "Master", "standard"))
        self.assertIsNone(progression_average(bucket, "Master", "puzzle"))

    def test_undated_invalid_and_nonpositive_times_do_not_invent_timeline_points(self):
        rows = {"undated": record(None), "invalid_date": record("1/5/2026"),
                "future": record("2027-01-01")}
        for i, value in enumerate([None, "invalid", float('inf'), float('nan'), True, -1, 0]):
            row = record()
            row["time_to_beat"] = value
            rows[str(i)] = row
        self.assertEqual({}, build_time_progression(rows, "all_time", TODAY))
        self.assertTrue(completion_in_period(rows["undated"], "all_time", TODAY))
        row = record()
        row["time_to_beat"] = "7200"
        self.assertEqual(2, progression_average(build_time_progression({"1": row}, "all_time", TODAY)["2026-09"], "Master"))

    def test_daily_period_crosses_year_boundary_and_empty_days_are_gaps(self):
        chart = build_time_progression({"1": record("2025-12-31")}, "last_week", date(2026, 1, 2))
        self.assertEqual("2025-12-27", min(chart))
        self.assertEqual("2026-01-02", max(chart))
        self.assertIsNone(progression_average(chart["2026-01-01"], "Master"))
        self.assertEqual(1, progression_average(chart["2025-12-31"], "Master"))

    def test_analytics_summary_and_timeline_use_the_same_period_and_keep_obsolete_history(self):
        module = load('ui/dashboard/analytics.py')
        rows = {"1": record(), "2": record("2025-01-01", 9), "3": record(None, 2)}
        class Manager:
            data = rows
            def get_all_hacks(self, include_obsolete=False):
                return [{"id": k} for k in rows if include_obsolete or k != "2"]
        class Clock(datetime):
            @classmethod
            def now(cls): return cls(2026, 9, 3, 22, 10)
        engine = module.DashboardAnalytics(Manager())
        with patch.object(module, 'datetime', Clock):
            week = engine.load_analytics_data('last_week')
            all_time = engine.load_analytics_data('all_time')
        self.assertEqual(1, week['completed_hacks'])
        self.assertEqual(1, week['avg_time_per_hack'])
        self.assertEqual('Last Week', week['time_progression_period'])
        self.assertEqual('Day', week['time_progression_bucket'])
        self.assertEqual(3, all_time['completed_hacks'])
        self.assertEqual(4, all_time['avg_time_per_hack'])
        self.assertEqual(9, progression_average(all_time['time_progression']['2025-01'], 'Master'))

    def test_dense_chart_thins_labels_without_removing_points_and_renders_selected_type(self):
        module = load('ui/dashboard/charts.py')
        rows = {str(i): record((TODAY - timedelta(days=i)).isoformat(), 1) for i in range(30)}
        rows['standard'] = record(TODAY.isoformat(), 9, types=('standard',))
        chart = build_time_progression(rows, 'last_month', TODAY)
        class Canvas:
            def __init__(self): self.labels = []; self.points = []
            def delete(self, *_args): self.labels.clear(); self.points.clear()
            def update_idletasks(self): pass
            def winfo_width(self): return 500
            def winfo_height(self): return 520
            def create_text(self, *args, **kwargs): self.labels.append(kwargs['text'])
            def create_line(self, *args, **kwargs): pass
            def create_oval(self, *args, **kwargs): self.points.append(args)
        canvas = Canvas()
        instance = module.DashboardCharts(None, {'time_progression': chart, 'time_progression_bucket': 'Day'}, TimeChartViewState(metric='per_hack'))
        with patch.object(module, 'get_colors', return_value={}):
            instance._draw_time_progression_lines(canvas, 'kaizo')
        self.assertEqual(30, len(canvas.points))
        self.assertEqual(1, len({point[1] for point in canvas.points}))
        day_labels = [text for text in canvas.labels if text in {b['month_name'] for b in chart.values()}]
        self.assertLess(len(day_labels), 10)
        self.assertIn('05 Aug', day_labels)
        self.assertIn('03 Sep', day_labels)
        self.assertIn('Avg Hours per Hack per Day', canvas.labels)

    def test_label_spacing_keeps_endpoints_at_narrow_and_wide_sizes(self):
        for count in (1, 2, 7, 30, 120, 600):
            for width in (200, 700, 1500):
                with self.subTest(count=count, width=width):
                    indices = timeline_label_indices(count, width)
                    self.assertEqual((0, count - 1), (indices[0], indices[-1]))
                    self.assertEqual(tuple(sorted(set(indices))), indices)
                    if count > 1:
                        self.assertTrue(all((b-a)*width/(count-1) >= 90 for a,b in zip(indices,indices[1:])))


if __name__ == '__main__':
    unittest.main(verbosity=2)
