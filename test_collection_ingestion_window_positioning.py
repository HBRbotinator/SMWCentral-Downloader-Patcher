"""Source contract for consistent Collection-dialog centering."""
from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).parent


class CollectionIngestionWindowPositioningContractTest(unittest.TestCase):
    def test_shared_helper_centers_from_parent_center_then_clamps_to_virtual_root(self):
        source = (ROOT / "ui" / "window_positioning.py").read_text(encoding="utf-8")
        self.assertIn("parent_x + (parent_w - width) // 2", source)
        self.assertIn("winfo_vrootwidth", source)
        self.assertIn("min(max(x, vx), max_x)", source)
        self.assertIn("win.after_idle(win.lift)", source)

    def test_ingestion_review_and_progress_windows_use_shared_helper(self):
        for relative in (
            "ui/collection_ingestion_review_dialog.py",
            "ui/collection_ingestion_source_dialog.py",
            "ui/collection_ingestion_plan_preview_dialog.py",
            "ui/collection_ingestion_convergence_review_dialog.py",
        ):
            with self.subTest(relative=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("center_window_on_parent", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
