from pathlib import Path
import importlib.util
import unittest


def _load_add_hack_dialog():
    module_path = Path("ui/components/table_filters.py")
    spec = importlib.util.spec_from_file_location("collection_table_filters_direct", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.AddHackDialog


AddHackDialog = _load_add_hack_dialog()


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value


class _Manager:
    def __init__(self, record):
        self.data = {"41022": record}
        self.calls = []

    def update_hack(self, hack_id, field, value):
        self.calls.append((str(hack_id), field, value))
        self.data[str(hack_id)][field] = value
        return True


class CollectionRomAssetUiTests(unittest.TestCase):
    def _dialog(self, record, selected_path="B.sfc", *, dirty=True):
        dialog = object.__new__(AddHackDialog)
        dialog.data_manager = _Manager(record)
        dialog.hack_id = "41022"
        dialog._has_multi_files = True
        dialog._primary_selection_dirty = dirty
        dialog.primary_path_var = _Var(selected_path)
        return dialog

    def test_primary_selection_updates_files_and_compatibility_path(self):
        record = {
            "file_path": "A.sfc",
            "files": [
                {"path": "A.sfc", "primary": True, "future": "keep-a"},
                {"path": "B.sfc", "primary": False, "future": "keep-b"},
            ],
        }
        dialog = self._dialog(record)

        success = dialog._save_primary_rom_selection(True)

        self.assertTrue(success)
        self.assertEqual(record["file_path"], "B.sfc")
        self.assertFalse(record["files"][0]["primary"])
        self.assertTrue(record["files"][1]["primary"])
        self.assertEqual(record["files"][0]["future"], "keep-a")
        self.assertEqual(
            [field for _, field, _ in dialog.data_manager.calls],
            ["files", "file_path"],
        )
        self.assertFalse(dialog._primary_selection_dirty)

    def test_unchanged_primary_selector_does_not_write(self):
        record = {
            "file_path": "A.sfc",
            "files": [
                {"path": "A.sfc", "primary": True},
                {"path": "B.sfc", "primary": False},
            ],
        }
        dialog = self._dialog(record, selected_path="A.sfc", dirty=False)

        self.assertTrue(dialog._save_primary_rom_selection(True))
        self.assertEqual(dialog.data_manager.calls, [])

    def test_edit_dialog_contract_exposes_modern_local_assets_without_editing_file_path_separately(self):
        source = Path("ui/components/table_filters.py").read_text(encoding="utf-8")
        self.assertIn("if files:\n            self._build_files_section(files)", source)
        self.assertIn("if self._has_modern_files", source)
        self.assertIn("self.file_path_frame.grid_remove()", source)
        self.assertIn('updates["file_path"] = self.file_path_var.get().strip()', source)
        self.assertIn("if not self._has_modern_files:", source)
        self.assertIn("it never moves, renames, deletes, or re-hashes ROM files", source)


if __name__ == "__main__":
    unittest.main()
