"""Contracts for Collection Wheel browser-runtime dialog wiring."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace


def _load_dialog_class():
    path = Path("ui/collection_wheel_dialog.py").resolve()
    spec = importlib.util.spec_from_file_location(
        "collection_wheel_runtime_dialog_under_test",
        path,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.CollectionWheelDialog


CollectionWheelDialog = _load_dialog_class()


class FakeVar:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeButton:
    def __init__(self):
        self.state = None

    def configure(self, **options):
        self.state = options.get("state", self.state)


class FakeWindow:
    def __init__(self):
        self.clipboard = ""

    def clipboard_clear(self):
        self.clipboard = ""

    def clipboard_append(self, value):
        self.clipboard += value

    def update_idletasks(self):
        return None


class FakeBridge:
    def __init__(self):
        self.running = False
        self.calls = []

    def start(self, pool):
        self.calls.append(("start", pool))
        self.running = True
        return "http://127.0.0.1:8765/wheel/"

    def stop(self):
        self.calls.append(("stop",))
        self.running = False

    def refresh_pool(self, pool):
        self.calls.append(("refresh", pool))
        return {"candidates": pool}

    def publish_selection(self, pool, winner_id, **options):
        self.calls.append(
            ("publish", pool, winner_id, options)
        )
        return {"winner_id": winner_id}


def fake_dialog(bridge=None):
    dialog = CollectionWheelDialog.__new__(CollectionWheelDialog)
    dialog.runtime_bridge = bridge or FakeBridge()
    dialog.browser_landing_offset_supplier = lambda: 0.23
    dialog.runtime_status_var = FakeVar("Browser Wheel stopped")
    dialog.runtime_url_var = FakeVar()
    dialog.runtime_start_button = FakeButton()
    dialog.runtime_copy_button = FakeButton()
    dialog.runtime_stop_button = FakeButton()
    dialog.window = FakeWindow()
    dialog._active_pool = [{"id": "one", "title": "One"}]
    dialog._pool_available = True
    dialog._spinning = False
    return dialog


class CollectionWheelRuntimeDialogTest(unittest.TestCase):
    def test_dialog_exposes_managed_obs_controls(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        for required in (
            "Browser / OBS Wheel",
            "Start Browser Wheel",
            "Copy OBS URL",
            "Stop",
            "runtime_bridge_factory=CollectionWheelRuntimeBridge",
            "browser_landing_offset_supplier=build_browser_landing_offset",
            "self.runtime_bridge =",
            "stays hidden while",
            "idle",
        ):
            self.assertIn(required, source)

    def test_obs_url_adds_overlay_mode_without_losing_query(self):
        self.assertEqual(
            CollectionWheelDialog._obs_browser_url(
                "http://127.0.0.1:8765/wheel/"
            ),
            "http://127.0.0.1:8765/wheel/?mode=overlay",
        )
        self.assertEqual(
            CollectionWheelDialog._obs_browser_url(
                "http://127.0.0.1:8765/wheel/?quality=high"
            ),
            (
                "http://127.0.0.1:8765/wheel/"
                "?quality=high&mode=overlay"
            ),
        )
        self.assertEqual(
            CollectionWheelDialog._obs_browser_url(
                "http://127.0.0.1:8765/wheel/?mode=preview"
            ),
            "http://127.0.0.1:8765/wheel/?mode=overlay",
        )

    def test_browser_has_dedicated_show_oriented_schedule(self):
        native_duration = (
            CollectionWheelDialog.SPIN_FRAME_DELAY_MS
            * (CollectionWheelDialog.SPIN_FRAME_COUNT - 1)
        )

        self.assertEqual(
            CollectionWheelDialog._browser_spin_duration_ms(),
            12500,
        )
        self.assertEqual(
            CollectionWheelDialog.BROWSER_SPIN_DURATION_MS,
            12500,
        )
        self.assertEqual(
            CollectionWheelDialog.BROWSER_SPIN_TURNS,
            9,
        )
        self.assertGreater(
            CollectionWheelDialog.BROWSER_SPIN_DURATION_MS,
            native_duration,
        )
        self.assertGreater(
            CollectionWheelDialog.BROWSER_SPIN_TURNS,
            CollectionWheelDialog.SPIN_TURNS,
        )

    def test_start_uses_active_pool_and_copies_overlay_url(self):
        dialog = fake_dialog()

        dialog._start_browser_runtime()

        self.assertEqual(
            dialog.runtime_bridge.calls[0],
            ("start", dialog._active_pool),
        )
        expected_url = (
            "http://127.0.0.1:8765/wheel/?mode=overlay"
        )
        self.assertEqual(
            dialog.runtime_url_var.get(),
            expected_url,
        )
        self.assertEqual(dialog.window.clipboard, expected_url)
        self.assertIn("OBS URL copied", dialog.runtime_status_var.get())
        self.assertEqual(dialog.runtime_start_button.state, "disabled")
        self.assertEqual(dialog.runtime_copy_button.state, "normal")
        self.assertEqual(dialog.runtime_stop_button.state, "normal")

    def test_filter_refresh_syncs_only_when_runtime_is_running(self):
        dialog = fake_dialog()
        pool = [{"id": "two", "title": "Two"}]

        self.assertTrue(dialog._sync_browser_pool(pool))
        self.assertEqual(dialog.runtime_bridge.calls, [])

        dialog.runtime_bridge.running = True
        self.assertTrue(dialog._sync_browser_pool(pool))
        self.assertEqual(
            dialog.runtime_bridge.calls[-1],
            ("refresh", pool),
        )
        self.assertIn("1 candidate", dialog.runtime_status_var.get())

    def test_spin_publication_uses_exact_pool_and_native_timing(self):
        dialog = fake_dialog()
        dialog.runtime_bridge.running = True
        pool = [
            {"id": "two", "title": "Two"},
            {"id": "three", "title": "Three"},
        ]
        result = SimpleNamespace(
            candidate_id="three",
            candidate={"id": "three", "title": "Three"},
        )

        self.assertTrue(
            dialog._publish_browser_selection(pool, result)
        )
        call = dialog.runtime_bridge.calls[-1]
        self.assertEqual(call[0], "publish")
        self.assertEqual(call[1], pool)
        self.assertEqual(call[2], "three")
        self.assertEqual(
            call[3],
            {
                "duration_ms": (
                    CollectionWheelDialog._browser_spin_duration_ms()
                ),
                "turns": CollectionWheelDialog.BROWSER_SPIN_TURNS,
                "landing_offset": 0.23,
            },
        )

    def test_each_publication_uses_one_python_supplied_offset(self):
        dialog = fake_dialog()
        dialog.runtime_bridge.running = True
        offsets = iter((0.21, 0.79))
        dialog.browser_landing_offset_supplier = lambda: next(offsets)
        pool = [{"id": "one", "title": "One"}]
        result = SimpleNamespace(
            candidate_id="one",
            candidate={"id": "one", "title": "One"},
        )

        self.assertTrue(
            dialog._publish_browser_selection(pool, result)
        )
        self.assertTrue(
            dialog._publish_browser_selection(pool, result)
        )

        publish_calls = [
            call
            for call in dialog.runtime_bridge.calls
            if call[0] == "publish"
        ]
        self.assertEqual(
            [call[3]["landing_offset"] for call in publish_calls],
            [0.21, 0.79],
        )

    def test_dialog_publishes_after_selection_and_before_native_animation(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        spin_method = source.split(
            "    def _spin(self, exclude_current=False):",
            1,
        )[1].split(
            "    def _begin_spin_animation",
            1,
        )[0]

        select_index = spin_method.index("self.model.select_from_pool(")
        pool_index = spin_method.index("animation_pool = [")
        publish_index = spin_method.index(
            "self._publish_browser_selection(animation_pool, result)"
        )
        animate_index = spin_method.index(
            "self._begin_spin_animation(layout, frames, result)"
        )
        self.assertLess(select_index, pool_index)
        self.assertLess(pool_index, publish_index)
        self.assertLess(publish_index, animate_index)

    def test_filter_changes_refresh_the_runtime_with_current_pool(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        refresh_method = source.split(
            "    def _refresh_pool_state(self):",
            1,
        )[1].split(
            "    def _spin(self, exclude_current=False):",
            1,
        )[0]

        self.assertIn(
            "self._active_pool = copy.deepcopy(pool)",
            refresh_method,
        )
        self.assertIn(
            "self._sync_browser_pool(self._active_pool)",
            refresh_method,
        )

    def test_close_stops_runtime_before_destroying_dialog(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )
        close_method = source.split(
            "    def close(self):",
            1,
        )[1].split("    def _create_window", 1)[0]

        stop_index = close_method.index(
            "self._stop_browser_runtime(show_error=False)"
        )
        destroy_index = close_method.index("window.destroy()")
        self.assertLess(stop_index, destroy_index)

    def test_runtime_controls_lock_during_native_animation(self):
        dialog = fake_dialog()
        dialog.runtime_bridge.running = True
        dialog._spinning = True

        dialog._update_runtime_controls()

        self.assertEqual(dialog.runtime_start_button.state, "disabled")
        self.assertEqual(dialog.runtime_copy_button.state, "normal")
        self.assertEqual(dialog.runtime_stop_button.state, "disabled")

    def test_constructor_rejects_non_callable_landing_supplier(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "if not callable(browser_landing_offset_supplier):",
            source,
        )
        self.assertIn(
            "browser_landing_offset_supplier must be callable",
            source,
        )

    def test_dialog_never_selects_in_browser_or_opens_external_apps(self):
        source = Path("ui/collection_wheel_dialog.py").read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "random.choice",
            "webbrowser.open",
            "os.startfile",
            "subprocess",
            'method: "POST"',
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
