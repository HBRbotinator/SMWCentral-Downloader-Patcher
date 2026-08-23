"""Collection UI wiring tests for read-only bulk import preview."""

from __future__ import annotations

import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


COLLECTION_PAGE_PATH = Path("ui/pages/collection_page.py")
FILTERS_PATH = Path("ui/components/table_filters.py")


def _collection_page_source():
    return COLLECTION_PAGE_PATH.read_text(encoding="utf-8")


def _load_collection_methods():
    """Compile only bulk-import methods, avoiding unrelated GUI imports."""

    tree = ast.parse(_collection_page_source())
    collection_class = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "CollectionPage"
    )
    wanted = {
        "_open_bulk_collection_import_preview",
        "_resolve_bulk_collection_import_review",
        "_build_bulk_collection_import_application_preview",
        "_apply_bulk_collection_import",
        "_on_bulk_collection_import_closed",
    }
    methods = [
        node
        for node in collection_class.body
        if isinstance(node, ast.FunctionDef)
        and node.name in wanted
    ]
    if {node.name for node in methods} != wanted:
        raise AssertionError("Bulk import Collection methods are missing.")

    module = ast.Module(body=methods, type_ignores=[])
    ast.fix_missing_locations(module)

    fake_messagebox = types.SimpleNamespace(showerror=Mock())
    namespace = {"messagebox": fake_messagebox}
    exec(
        compile(
            module,
            str(COLLECTION_PAGE_PATH),
            "exec",
        ),
        namespace,
    )
    return namespace, fake_messagebox


class _FakeTopLevel:
    pass


class _FakeFrame:
    def __init__(self):
        self.top = _FakeTopLevel()

    def winfo_toplevel(self):
        return self.top


class _FakeDialog:
    instances = []

    def __init__(
        self,
        parent,
        preview,
        logger=None,
        on_close=None,
        on_review_ready=None,
        on_application_preview=None,
        on_apply=None,
    ):
        self.parent = parent
        self.preview = preview
        self.logger = logger
        self.on_close = on_close
        self.on_review_ready = on_review_ready
        self.on_application_preview = on_application_preview
        self.on_apply = on_apply
        self.show_count = 0
        self.close_count = 0
        self.__class__.instances.append(self)

    def show(self):
        self.show_count += 1

    def close(self):
        self.close_count += 1
        if self.on_close is not None:
            self.on_close()


class _PageHarness:
    pass


class BulkCollectionImportCollectionUiContractTest(unittest.TestCase):
    def setUp(self):
        _FakeDialog.instances.clear()
        namespace, self.messagebox = _load_collection_methods()
        _PageHarness._open_bulk_collection_import_preview = namespace[
            "_open_bulk_collection_import_preview"
        ]
        _PageHarness._resolve_bulk_collection_import_review = namespace[
            "_resolve_bulk_collection_import_review"
        ]
        _PageHarness._build_bulk_collection_import_application_preview = (
            namespace[
                "_build_bulk_collection_import_application_preview"
            ]
        )
        _PageHarness._apply_bulk_collection_import = namespace[
            "_apply_bulk_collection_import"
        ]
        _PageHarness._on_bulk_collection_import_closed = namespace[
            "_on_bulk_collection_import_closed"
        ]

    def _page(self):
        page = _PageHarness()
        page.frame = _FakeFrame()
        page.logger = object()
        page.data_manager = object()
        page.bulk_collection_import_dialog = None
        page._log = Mock()
        page.filters = types.SimpleNamespace(
            refresh_dropdown_values=Mock()
        )
        page._refresh_table = Mock()
        return page

    def _install_modules(self, *, selected, preview=None, error=None):
        platform = types.ModuleType("platform_utils")
        platform.pick_file = Mock(return_value=selected)

        workflow = types.ModuleType(
            "bulk_collection_import_workflow_preview"
        )
        planner = Mock(
            return_value=preview
            if error is None
            else None,
            side_effect=error,
        )
        workflow.plan_v5_1_bulk_collection_import_workflow_preview = planner

        resolution = types.ModuleType(
            "bulk_collection_import_workflow_resolution"
        )
        resolution.resolve_v5_1_bulk_collection_import_review = Mock(
            return_value="resolution-plan"
        )

        application = types.ModuleType(
            "bulk_collection_import_application_preview"
        )
        application.build_v5_1_bulk_collection_import_application_preview = (
            Mock(return_value="application-plan")
        )

        apply_module = types.ModuleType(
            "bulk_collection_import_apply"
        )

        class _FakeApplySession:
            def __init__(self, state="awaiting_confirmation"):
                self.state = state

        apply_module.BulkCollectionImportApplySession = _FakeApplySession
        apply_module.execute_bulk_collection_import_apply_session = Mock(
            return_value="persistence-result"
        )

        store_module = types.ModuleType(
            "bulk_collection_import_hack_data_store"
        )
        store_module.BulkCollectionImportHackDataStore = Mock(
            return_value="hack-data-store"
        )

        dialog = types.ModuleType("ui.bulk_collection_import_dialog")
        dialog.BulkCollectionImportDialog = _FakeDialog

        return {
            "platform_utils": platform,
            "bulk_collection_import_workflow_preview": workflow,
            "bulk_collection_import_workflow_resolution": resolution,
            "bulk_collection_import_application_preview": application,
            "bulk_collection_import_apply": apply_module,
            "bulk_collection_import_hack_data_store": store_module,
            "ui.bulk_collection_import_dialog": dialog,
        }

    def test_collection_filter_actions_expose_bulk_import_preview(self):
        source = FILTERS_PATH.read_text(encoding="utf-8")

        self.assertIn("bulk_import_callback=None", source)
        self.assertIn('text="Bulk Import Preview"', source)
        self.assertIn("command=self.bulk_import_callback", source)

    def test_collection_page_passes_preview_callback_to_filters(self):
        source = _collection_page_source()

        self.assertIn(
            "bulk_import_callback="
            "self._open_bulk_collection_import_preview",
            source,
        )

    def test_cancelled_picker_does_not_plan_or_open_dialog(self):
        page = self._page()
        modules = self._install_modules(
            selected="",
            preview=object(),
        )

        with patch.dict(sys.modules, modules):
            page._open_bulk_collection_import_preview()

        modules["platform_utils"].pick_file.assert_called_once()
        modules[
            "bulk_collection_import_workflow_preview"
        ].plan_v5_1_bulk_collection_import_workflow_preview.assert_not_called()
        self.assertEqual(_FakeDialog.instances, [])
        self.assertIsNone(page.bulk_collection_import_dialog)

    def test_selected_json_is_planned_against_live_manager(self):
        page = self._page()
        preview = object()
        modules = self._install_modules(
            selected="C:/imports/list.json",
            preview=preview,
        )

        with patch.dict(sys.modules, modules):
            page._open_bulk_collection_import_preview()

            review_document = {"review": "document"}
            self.assertEqual(
                page.bulk_collection_import_dialog.on_review_ready(
                    review_document
                ),
                "resolution-plan",
            )

        modules["platform_utils"].pick_file.assert_called_once_with(
            title="Select Bulk Collection Import JSON",
            filetypes=[
                ("JSON files", "*.json"),
                ("All files", "*.*"),
            ],
        )
        modules[
            "bulk_collection_import_workflow_preview"
        ].plan_v5_1_bulk_collection_import_workflow_preview.assert_called_once_with(
            "C:/imports/list.json",
            page.data_manager,
        )
        self.messagebox.showerror.assert_not_called()

        self.assertEqual(len(_FakeDialog.instances), 1)
        dialog = _FakeDialog.instances[0]
        self.assertIs(dialog.parent, page.frame.top)
        self.assertIs(dialog.preview, preview)
        self.assertIs(dialog.logger, page.logger)
        self.assertTrue(callable(dialog.on_review_ready))
        self.assertTrue(callable(dialog.on_application_preview))
        self.assertTrue(callable(dialog.on_apply))
        self.assertEqual(dialog.show_count, 1)
        self.assertIs(page.bulk_collection_import_dialog, dialog)

        modules[
            "bulk_collection_import_workflow_resolution"
        ].resolve_v5_1_bulk_collection_import_review.assert_called_once_with(
            "C:/imports/list.json",
            page.data_manager,
            review_document,
        )

        resolution_plan = object()
        with patch.dict(sys.modules, modules):
            self.assertEqual(
                dialog.on_application_preview(resolution_plan),
                "application-plan",
            )
        modules[
            "bulk_collection_import_application_preview"
        ].build_v5_1_bulk_collection_import_application_preview.assert_called_once_with(
            resolution_plan,
            page.data_manager,
        )

    def test_collection_page_wires_final_application_preview_callback(self):
        source = _collection_page_source()

        self.assertIn(
            "on_application_preview=(",
            source,
        )
        self.assertIn(
            "self._build_bulk_collection_import_application_preview",
            source,
        )
        self.assertIn(
            "build_v5_1_bulk_collection_import_application_preview(",
            source,
        )

    def test_collection_page_wires_explicit_apply_callback(self):
        source = _collection_page_source()

        self.assertIn(
            "on_apply=self._apply_bulk_collection_import",
            source,
        )
        self.assertIn(
            "BulkCollectionImportHackDataStore(self.data_manager)",
            source,
        )
        self.assertIn(
            "execute_bulk_collection_import_apply_session(",
            source,
        )

    def test_unconfirmed_session_is_rejected_before_store_construction(self):
        page = self._page()
        modules = self._install_modules(
            selected="",
            preview=object(),
        )
        session_type = modules[
            "bulk_collection_import_apply"
        ].BulkCollectionImportApplySession
        session = session_type("awaiting_confirmation")

        with patch.dict(sys.modules, modules):
            with self.assertRaises(RuntimeError):
                page._apply_bulk_collection_import(session)

        modules[
            "bulk_collection_import_hack_data_store"
        ].BulkCollectionImportHackDataStore.assert_not_called()
        modules[
            "bulk_collection_import_apply"
        ].execute_bulk_collection_import_apply_session.assert_not_called()
        page._refresh_table.assert_not_called()

    def test_confirmed_apply_constructs_store_executes_once_and_refreshes_ui(self):
        page = self._page()
        modules = self._install_modules(
            selected="",
            preview=object(),
        )
        session_type = modules[
            "bulk_collection_import_apply"
        ].BulkCollectionImportApplySession
        session = session_type("confirmed")

        with patch.dict(sys.modules, modules):
            result = page._apply_bulk_collection_import(session)

        self.assertEqual(result, "persistence-result")
        modules[
            "bulk_collection_import_hack_data_store"
        ].BulkCollectionImportHackDataStore.assert_called_once_with(
            page.data_manager
        )
        modules[
            "bulk_collection_import_apply"
        ].execute_bulk_collection_import_apply_session.assert_called_once_with(
            session,
            "hack-data-store",
        )
        page.filters.refresh_dropdown_values.assert_called_once_with(
            page.data_manager
        )
        page._refresh_table.assert_called_once()

    def test_apply_ui_refresh_failure_does_not_turn_committed_result_into_failure(self):
        page = self._page()
        modules = self._install_modules(
            selected="",
            preview=object(),
        )
        session_type = modules[
            "bulk_collection_import_apply"
        ].BulkCollectionImportApplySession
        session = session_type("confirmed")
        page._refresh_table.side_effect = RuntimeError(
            "render failure"
        )

        with patch.dict(sys.modules, modules):
            result = page._apply_bulk_collection_import(session)

        self.assertEqual(result, "persistence-result")
        page._log.assert_called_once()
        self.assertEqual(page._log.call_args.args[1], "Warning")

    def test_invalid_import_shows_error_without_opening_dialog(self):
        page = self._page()
        modules = self._install_modules(
            selected="C:/imports/bad.json",
            error=ValueError("invalid import"),
        )

        with patch.dict(sys.modules, modules):
            page._open_bulk_collection_import_preview()

        self.messagebox.showerror.assert_called_once()
        args, kwargs = self.messagebox.showerror.call_args
        self.assertEqual(args[0], "Bulk Collection Import")
        self.assertIn("invalid import", args[1])
        self.assertIs(kwargs["parent"], page.frame.top)
        self.assertEqual(_FakeDialog.instances, [])
        self.assertIsNone(page.bulk_collection_import_dialog)
        page._log.assert_called_once()
        self.assertEqual(page._log.call_args.args[1], "Error")

    def test_dialog_close_callback_releases_page_reference(self):
        page = self._page()
        modules = self._install_modules(
            selected="C:/imports/list.json",
            preview=object(),
        )

        with patch.dict(sys.modules, modules):
            page._open_bulk_collection_import_preview()

        dialog = page.bulk_collection_import_dialog
        self.assertIsNotNone(dialog)

        dialog.close()

        self.assertEqual(dialog.close_count, 1)
        self.assertIsNone(page.bulk_collection_import_dialog)

    def test_cleanup_closes_open_bulk_preview(self):
        source = _collection_page_source()

        self.assertIn(
            "if self.bulk_collection_import_dialog:",
            source,
        )
        self.assertIn(
            "self.bulk_collection_import_dialog.close()",
            source,
        )

    def test_collection_preview_method_has_no_direct_persistence_path(self):
        tree = ast.parse(_collection_page_source())
        collection_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "CollectionPage"
        )
        method = next(
            node
            for node in collection_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_open_bulk_collection_import_preview"
        )
        method_source = ast.unparse(method)

        for forbidden in (
            "execute_bulk_collection_import_application_plan",
            "build_v5_1_bulk_collection_import_application_plan",
            "BulkCollectionImportHackDataStore",
            "allocate_bulk_collection_import_keys",
            ".save_data(",
            ".force_save(",
            ".update_hack(",
            ".add_user_hack(",
        ):
            self.assertNotIn(forbidden, method_source)

    def test_concrete_store_exists_only_in_explicit_apply_method(self):
        tree = ast.parse(_collection_page_source())
        collection_class = next(
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == "CollectionPage"
        )
        apply_method = next(
            node
            for node in collection_class.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "_apply_bulk_collection_import"
        )
        source = ast.unparse(apply_method)

        self.assertIn(
            "session.state != 'confirmed'",
            source,
        )
        self.assertIn(
            "BulkCollectionImportHackDataStore(self.data_manager)",
            source,
        )
        self.assertIn(
            "execute_bulk_collection_import_apply_session",
            source,
        )
        self.assertNotIn("force_save", source)
        self.assertNotIn("reload_data", source)

    def test_collection_ui_uses_cross_platform_picker_not_filedialog(self):
        source = _collection_page_source()
        start = source.index(
            "    def _open_bulk_collection_import_preview(self):"
        )
        end = source.index(
            "    def _open_collection_wheel(self):",
            start,
        )
        method = source[start:end]

        self.assertIn("from platform_utils import pick_file", method)
        self.assertNotIn("filedialog", method)


if __name__ == "__main__":
    unittest.main(verbosity=2)
