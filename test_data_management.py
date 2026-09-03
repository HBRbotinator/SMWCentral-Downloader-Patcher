"""Data navigation, isolated import sources and persistent Save Sync scheduling."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from collection_ingestion_entrypoint import CollectionIngestionEntrypointError
from ui import layout
from ui.collection_ingestion_source_dialog import CollectionIngestionSourceDialog
from ui.navigation import NavigationBar
from ui.pages import data_page
from ui.pages.collection_page import CollectionPage
from ui.save_sync_panel import SaveSyncPanel


class Value:
    def __init__(self, value=False, **_kwargs):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ImportSourceModeTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.export = self.root / "history.json"
        self.export.write_text("{}", encoding="utf-8")

    def dialog(self, mode):
        dialog = CollectionIngestionSourceDialog(None, source_kind=mode)
        dialog.rom_path = Value(str(self.root))
        dialog.bucket_path = Value(str(self.export))
        dialog.rom_enabled = Value(True)
        dialog.bucket_enabled = Value(True)
        return dialog

    def test_rom_import_ignores_bucket_state_even_when_enabled(self):
        dialog = self.dialog("rom")
        dialog.bucket_path.set("missing-export.json")
        selection = dialog._selection()
        self.assertEqual(str(self.root), selection.rom_root)
        self.assertEqual("", selection.giganticbucket_path)

    def test_bucket_import_ignores_output_folder_and_rom_state(self):
        dialog = self.dialog("giganticbucket")
        dialog.rom_path.set("missing-rom-folder")
        selection = dialog._selection()
        self.assertEqual("", selection.rom_root)
        self.assertEqual(str(self.export), selection.giganticbucket_path)

    def test_single_source_requires_its_path_with_specific_feedback(self):
        for mode, field, message in (
            ("rom", "rom_path", "Choose a ROM folder"),
            ("giganticbucket", "bucket_path", "Choose a GiganticBucket JSON export"),
        ):
            with self.subTest(mode=mode):
                dialog = self.dialog(mode)
                getattr(dialog, field).set("")
                with self.assertRaisesRegex(CollectionIngestionEntrypointError, message):
                    dialog._selection()

    def test_combined_import_respects_explicit_source_choices(self):
        dialog = self.dialog("combined")
        selection = dialog._selection()
        self.assertTrue(selection.has_rom_source)
        self.assertTrue(selection.has_giganticbucket_source)
        dialog.rom_enabled.set(False)
        self.assertFalse(dialog._selection().has_rom_source)
        dialog.bucket_enabled.set(False)
        with self.assertRaises(CollectionIngestionEntrypointError):
            dialog._selection()

    def test_unknown_source_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            self.dialog("other")

    def test_source_windows_show_only_relevant_fields_and_reveal_after_withdraw(self):
        import ui.collection_ingestion_source_dialog as module
        for mode, rows in (("rom", ["ROM folder (.sfc / .smc)"]),
                           ("giganticbucket", ["GiganticBucket JSON export"]),
                           ("combined", ["ROM folder (.sfc / .smc)", "GiganticBucket JSON export"])):
            with self.subTest(mode=mode):
                events = []
                window = Mock()
                window.withdraw.side_effect = lambda: events.append("withdraw")
                owner = object()
                dialog = CollectionIngestionSourceDialog(owner, source_kind=mode)
                dialog._source_row = Mock()
                with patch.object(module.tk, "Toplevel", return_value=window), \
                     patch.object(module.tk, "BooleanVar", Value), \
                     patch.object(module.tk, "StringVar", Value), \
                     patch.multiple(module.ttk, Frame=Mock(), Label=Mock(), LabelFrame=Mock(), Button=Mock()), \
                     patch.object(module, "reveal_window_on_parent", side_effect=lambda *_args: events.append("reveal")):
                    dialog.show()
                self.assertEqual(rows, [call.kwargs["label"] for call in dialog._source_row.call_args_list])
                self.assertEqual(["withdraw", "reveal"], events)
                window.transient.assert_called_once_with(owner)


class DataNavigationTest(unittest.TestCase):
    def test_collection_shortcut_opens_data_without_starting_import(self):
        page = CollectionPage.__new__(CollectionPage)
        page.open_data_callback = Mock()
        page._start_collection_ingestion_review = Mock()
        page._open_collection_import()
        page.open_data_callback.assert_called_once_with()
        page._start_collection_ingestion_review.assert_not_called()

    def test_each_data_action_uses_the_existing_collection_import_controller(self):
        collection = Mock()
        page = data_page.DataPage(None, None, collection)
        for kind in ("rom", "giganticbucket", "combined"):
            page._start_import(kind)
            collection._open_collection_import.assert_called_with(source_kind=kind)

    def test_pending_review_is_resumed_before_opening_another_source(self):
        page = CollectionPage.__new__(CollectionPage)
        page._collection_ingestion_busy = False
        page.collection_ingestion_plan_preview_dialog = None
        page.collection_ingestion_review_dialog = Mock(is_open=True)
        page._collection_ingestion_state_is_saved = Mock()
        page._open_collection_import(source_kind="giganticbucket")
        page.collection_ingestion_review_dialog.lift.assert_called_once_with()
        page._collection_ingestion_state_is_saved.assert_not_called()

    def test_data_page_is_created_once_and_combined_import_is_collapsed(self):
        collection = Mock()
        setup = object()
        logger = object()
        page = data_page.DataPage(None, setup, collection, logger)
        page._bind_scrolling = Mock()
        page._update_theme = Mock()
        with patch.object(data_page.tk, "Canvas", Mock()), \
             patch.object(data_page.tk, "BooleanVar", Value), \
             patch.multiple(data_page.ttk, Frame=Mock(side_effect=lambda *_args, **_kwargs: Mock()), Scrollbar=Mock(), Label=Mock(),
                            LabelFrame=Mock(), Button=Mock(), Checkbutton=Mock()), \
             patch.object(data_page, "SaveSyncPanel") as controller:
            frame = page.create()
            self.assertIs(frame, page.create())
            controller.assert_called_once_with(
                unittest.mock.ANY, setup, collection.data_manager, logger=logger,
                on_applied=collection._refresh_data_and_table,
            )
            controller.return_value.create.assert_called_once_with()
            self.assertFalse(page.advanced_var.get())
            page.advanced_frame.pack.assert_not_called()
            page.advanced_var.set(True)
            page._toggle_advanced()
            page.advanced_frame.pack.assert_called_once()
            page.advanced_var.set(False)
            page._toggle_advanced()
            page.advanced_frame.pack_forget.assert_called_once()

    def test_layout_eagerly_registers_data_and_shares_collection_manager(self):
        manager = Mock()
        app = layout.MainLayout(Mock(), Mock(), Mock(), Mock(), Mock(), Mock(), Mock())
        app.content_frame = object()
        app.page_manager = Mock()
        app.navigation = Mock()
        with patch.multiple(layout, DashboardPage=Mock(), DownloadPage=Mock(), SettingsPage=Mock(),
                            CollectionPage=Mock(), PlannerPage=Mock(), DataPage=Mock()):
            layout.CollectionPage.return_value.data_manager = manager
            app._create_pages()
            layout.DataPage.assert_called_once_with(
                app.content_frame, app.setup_section, app.collection_page, app.logger,
            )
            app.page_manager.add_page.assert_any_call("Data", app.data_page.create.return_value)
            app.collection_page.open_data_callback()
            app.navigation.show_page.assert_called_once_with("Data")

    def test_tab_spacing_resizes_even_without_a_theme_toggle(self):
        nav = NavigationBar(Mock(), Mock())
        nav._draw_tabs = Mock()
        with patch("ui.navigation.get_colors", return_value={"nav_bg": "white"}), \
             patch("ui.navigation.tk.Canvas", Mock()):
            nav.create()
        nav.nav_bar.bind.assert_called_once_with("<Configure>", nav._update_toggle_position)

    def test_data_stays_visible_when_planner_is_hidden_and_tabs_fit_minimum_width(self):
        nav = NavigationBar.__new__(NavigationBar)
        nav.nav_bar = Mock()
        nav.nav_bar.winfo_width.return_value = 800
        nav.current_page = "Data"
        nav.hover_cursor = "hand2"
        for visible in (True, False):
            with self.subTest(planner=visible):
                nav.planner_visible = visible
                self.assertIn("Data", nav._visible_tabs())
                self.assertEqual(visible, "Planner" in nav._visible_tabs())
                with patch("ui.navigation.get_colors", return_value={"nav_text": "white"}):
                    nav._draw_tabs()
                last = nav.tab_refs[-1]
                self.assertLess(last["x"] + last["width"], 800 - 128)


class Scheduler:
    """Tk callback clock that does not depend on widget visibility."""
    def __init__(self):
        self.jobs = {}
        self.counter = 0

    def after(self, delay, callback):
        self.counter += 1
        key = f"job-{self.counter}"
        self.jobs[key] = (delay, callback)
        return key

    def after_cancel(self, key):
        self.jobs.pop(key, None)

    def fire(self, key):
        self.jobs.pop(key)[1]()


class SaveSyncSchedulingTest(unittest.TestCase):
    def setUp(self):
        self.panel = SaveSyncPanel(None, Mock(), Mock())
        self.panel.frame = Scheduler()
        self.panel.save_sync_auto_scan_var = Value(False)
        self.panel.save_sync_periodic_scan_var = Value(False)
        self.panel.save_sync_scan_interval_var = Value("15")

    def test_existing_disabled_choices_do_not_start_a_timer_or_scan(self):
        self.panel._scan_saves = Mock()
        self.panel.start_save_sync_auto_scan()
        self.panel.start_save_sync_periodic_scan()
        self.assertEqual({}, self.panel.frame.jobs)
        self.panel._scan_saves.assert_not_called()

    def test_startup_runs_once_without_consulting_page_visibility(self):
        self.panel.save_sync_auto_scan_var.set(True)
        self.panel._scan_saves = Mock()
        self.panel.start_save_sync_auto_scan()
        self.panel.start_save_sync_auto_scan()
        self.panel._scan_saves.assert_called_once_with(auto=True)

    def test_periodic_check_keeps_running_without_visiting_data(self):
        self.panel.save_sync_periodic_scan_var.set(True)
        self.panel._scan_saves = Mock()
        self.panel.start_save_sync_periodic_scan()
        key = self.panel._periodic_scan_job
        self.assertEqual(900000, self.panel.frame.jobs[key][0])
        self.panel.frame.fire(key)
        self.panel._scan_saves.assert_called_once_with(auto=True)
        self.assertEqual(1, len(self.panel.frame.jobs))
        self.assertNotEqual(key, self.panel._periodic_scan_job)

    def test_periodic_check_defers_running_scans_and_pending_reviews(self):
        self.panel.save_sync_periodic_scan_var.set(True)
        self.panel._scan_saves = Mock()
        for busy, pending in ((True, []), (False, [object()])):
            with self.subTest(busy=busy, pending=bool(pending)):
                self.panel._scan_running = busy
                self.panel._pending_auto_scan_candidates = pending
                self.panel.start_save_sync_periodic_scan()
                self.panel.frame.fire(self.panel._periodic_scan_job)
                self.panel._scan_saves.assert_not_called()
                self.assertEqual(1, len(self.panel.frame.jobs))

    def test_manual_and_automatic_requests_cannot_overlap_scan_or_review(self):
        self.panel._available_save_directories = Mock()
        for busy, review in ((True, None), (False, Mock())):
            with self.subTest(busy=busy):
                self.panel._scan_running = busy
                self.panel._review_dialog = review
                if review is not None:
                    review.win.winfo_exists.return_value = True
                self.panel._scan_saves(auto=False)
                self.panel._scan_saves(auto=True)
                self.panel._available_save_directories.assert_not_called()

    def test_interval_change_replaces_timer_and_disabling_cancels_it(self):
        self.panel.save_sync_periodic_scan_var.set(True)
        self.panel.start_save_sync_periodic_scan()
        old = self.panel._periodic_scan_job
        self.panel.save_sync_scan_interval_var.set("30")
        self.panel._restart_periodic_save_sync_scan()
        self.assertNotIn(old, self.panel.frame.jobs)
        self.assertEqual(1, len(self.panel.frame.jobs))
        self.assertEqual(1800000, self.panel.frame.jobs[self.panel._periodic_scan_job][0])
        self.panel.save_sync_periodic_scan_var.set(False)
        self.panel._restart_periodic_save_sync_scan()
        self.assertEqual({}, self.panel.frame.jobs)

    def test_destroy_cancels_owned_jobs_and_late_results_do_not_touch_widgets(self):
        self.panel._startup_jobs = [self.panel.frame.after(2000, self.panel.start_save_sync_auto_scan)]
        self.panel.save_sync_periodic_scan_var.set(True)
        self.panel.start_save_sync_periodic_scan()
        self.panel._on_destroy(SimpleNamespace(widget=object()))
        self.assertFalse(self.panel._closed)
        self.panel._on_destroy(SimpleNamespace(widget=self.panel.frame))
        self.panel.cleanup()
        self.assertEqual({}, self.panel.frame.jobs)
        self.panel._on_scan_complete([], None, auto=True)
        self.panel.start_save_sync_periodic_scan()
        self.assertEqual({}, self.panel.frame.jobs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
