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
    ):
        self.parent = parent
        self.preview = preview
        self.logger = logger
        self.on_close = on_close
        self.on_review_ready = on_review_ready
        self.on_application_preview = on_application_preview
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

        dialog = types.ModuleType("ui.bulk_collection_import_dialog")
        dialog.BulkCollectionImportDialog = _FakeDialog

        return {
            "platform_utils": platform,
            "bulk_collection_import_workflow_preview": workflow,
            "bulk_collection_import_workflow_resolution": resolution,
            "bulk_collection_import_application_preview": application,
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

    def test_collection_ui_preview_wiring_has_no_apply_or_persistence_path(self):
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
