"""Source contract for consistent Collection-dialog centering."""
from __future__ import annotations

from pathlib import Path
import importlib.util
import unittest


ROOT = Path(__file__).parent
_SPEC = importlib.util.spec_from_file_location(
    "collection_window_positioning_under_test",
    ROOT / "ui" / "window_positioning.py",
)
_WINDOW_POSITIONING = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_WINDOW_POSITIONING)
center_window_on_parent = _WINDOW_POSITIONING.center_window_on_parent


class CollectionIngestionWindowPositioningContractTest(unittest.TestCase):
    def test_shared_helper_centers_from_parent_center_then_clamps_to_virtual_root(self):
        source = (ROOT / "ui" / "window_positioning.py").read_text(encoding="utf-8")
        self.assertIn("parent_x + (parent_w - width) // 2", source)
        self.assertIn("winfo_vrootwidth", source)
        self.assertIn("min(max(x, vx), max_x)", source)
        self.assertIn("win.after_idle(win.lift)", source)


    def test_helper_uses_requested_size_before_window_is_mapped(self):
        class Parent:
            def winfo_rootx(self): return 100
            def winfo_rooty(self): return 50
            def winfo_width(self): return 800
            def winfo_height(self): return 600

        class Window:
            geometry_value = ""
            def update_idletasks(self): pass
            def winfo_width(self): return 1
            def winfo_height(self): return 1
            def winfo_reqwidth(self): return 400
            def winfo_reqheight(self): return 200
            def winfo_vrootx(self): return 0
            def winfo_vrooty(self): return 0
            def winfo_vrootwidth(self): return 1920
            def winfo_vrootheight(self): return 1080
            def geometry(self, value): self.geometry_value = value

        win = Window()
        center_window_on_parent(win, Parent(), lift=False)
        self.assertEqual("+300+250", win.geometry_value)

    def test_progress_window_is_positioned_before_mapping_then_recentred_after_idle(self):
        source = (ROOT / "ui" / "collection_ingestion_source_dialog.py").read_text(encoding="utf-8")
        progress_source = source.split("class CollectionIngestionProgressDialog:", 1)[1]
        self.assertIn("self.win.withdraw()", progress_source)
        self.assertIn("center_window_on_parent(self.win, self.parent, lift=False)", progress_source)
        self.assertIn("self.win.deiconify()", progress_source)
        self.assertIn("self.win.after_idle(self._center_after_map)", progress_source)
        self.assertLess(
            progress_source.index("self.win.withdraw()"),
            progress_source.index("self.win.deiconify()"),
        )

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
