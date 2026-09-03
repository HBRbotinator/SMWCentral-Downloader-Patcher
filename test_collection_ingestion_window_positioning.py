"""Source contract for consistent Collection-dialog centering."""
from __future__ import annotations

from pathlib import Path
import ast
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

    def test_all_audited_progress_dialogs_withdraw_immediately_and_use_shared_reveal(self):
        audited = {
            "collection_ingestion_source_dialog.py": ("CollectionIngestionProgressDialog",),
            "collection_ingestion_finalization_progress_dialog.py": ("CollectionIngestionFinalizationProgressDialog",),
            "collection_ingestion_plan_preview_dialog.py": ("CollectionIngestionApplyProgressDialog", "CollectionIngestionFinalizationProgressDialog"),
            "collection_update_current_refresh_dialog.py": ("CollectionCurrentRefreshProgressDialog",),
            "collection_update_discovery_dialog.py": ("CollectionUpdateDiscoveryProgressDialog",),
            "collection_update_plan_preview_dialog.py": ("CollectionUpdatePlanProgressDialog", "CollectionUpdateRomAcquisitionProgressDialog", "CollectionUpdateApplyProgressDialog"),
            "collection_rom_historical_provenance_dialog.py": ("HistoricalRomProvenanceProgressDialog",),
        }
        found = set()
        for filename, names in audited.items():
            source = (ROOT / "ui" / filename).read_text(encoding="utf-8")
            tree = ast.parse(source)
            for cls in tree.body:
                if not isinstance(cls, ast.ClassDef) or cls.name not in names:
                    continue
                found.add((filename, cls.name))
                with self.subTest(filename=filename, dialog=cls.name):
                    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                                  and n.name == ("__init__" if cls.name == "HistoricalRomProvenanceProgressDialog" else "show"))
                    text = ast.get_source_segment(source, method)
                    lines = text.splitlines()
                    creation = next(i for i, line in enumerate(lines) if "= tk.Toplevel(" in line)
                    self.assertIn(".withdraw()", lines[creation + 1])
                    self.assertIn("reveal_window_on_parent(", text)
                    self.assertLess(text.index("progress.start("), text.index("reveal_window_on_parent("))
                    self.assertNotIn(".grab_set()", text)
                    self.assertNotIn(".deiconify()", text)
        self.assertEqual({(f, n) for f, names in audited.items() for n in names}, found)

    def test_reveal_sizes_centers_before_mapping_and_recenters_safely_after_idle(self):
        class Parent:
            def winfo_rootx(self): return 100
            def winfo_rooty(self): return 50
            def winfo_width(self): return 800
            def winfo_height(self): return 600

        class Window:
            def __init__(self):
                self.events = []
                self.callbacks = []
                self.mapped = False
                self.exists = True
            def update_idletasks(self): self.events.append("size")
            def winfo_width(self): return 420 if self.mapped else 1
            def winfo_height(self): return 220 if self.mapped else 1
            def winfo_reqwidth(self): return 400
            def winfo_reqheight(self): return 200
            def winfo_vrootx(self): return 0
            def winfo_vrooty(self): return 0
            def winfo_vrootwidth(self): return 1920
            def winfo_vrootheight(self): return 1080
            def geometry(self, value): self.events.append(value)
            def deiconify(self): self.events.append("map"); self.mapped = True
            def after_idle(self, callback): self.callbacks.append(callback)
            def grab_set(self): self.events.append("grab")
            def lift(self): self.events.append("lift")
            def winfo_exists(self): return self.exists

        win = Window()
        _WINDOW_POSITIONING.reveal_window_on_parent(win, Parent(), grab=True)
        self.assertLess(win.events.index("400x200"), win.events.index("map"))
        self.assertLess(win.events.index("+300+250"), win.events.index("map"))
        self.assertLess(win.events.index("map"), win.events.index("grab"))
        win.callbacks.pop(0)()
        self.assertIn("+290+240", win.events)
        closed = Window()
        _WINDOW_POSITIONING.reveal_window_on_parent(closed, Parent())
        closed.exists = False
        before = tuple(closed.events)
        closed.callbacks.pop(0)()
        self.assertEqual(before, tuple(closed.events))

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
