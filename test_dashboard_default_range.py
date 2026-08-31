"""Source contracts for the Dashboard initial time range."""
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parent


class DashboardDefaultRangeContractTest(unittest.TestCase):
    def test_dashboard_initial_view_defaults_to_all_time(self):
        dashboard = (ROOT / "ui" / "dashboard" / "main_dashboard.py").read_text(encoding="utf-8")
        widgets = (ROOT / "ui" / "dashboard" / "widgets.py").read_text(encoding="utf-8")
        self.assertIn('self.date_filter = "all_time"', dashboard)
        self.assertIn('self.current_filter = "all_time"', widgets)
        self.assertIn('("All Time", "all_time")', widgets)


if __name__ == "__main__":
    unittest.main(verbosity=2)
