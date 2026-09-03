"""New-folder scope prompts and persisted per-folder Save Sync behavior."""
import ast
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import save_sync
import save_sync_sources

ROOT = Path(__file__).parent


def function(relative, name, namespace):
    path = ROOT / relative
    tree = ast.parse(path.read_text(encoding='utf-8'))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


class Config:
    def __init__(self): self.data = {}
    def get(self, key, default=None): return self.data.get(key, default)
    def set(self, key, value): self.data[key] = value


class SaveFolderSetupTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root / 'Saves'
        self.folder.mkdir()
        (self.folder / 'inside').mkdir()
        (self.folder / 'top.srm').write_bytes(b'save')
        (self.folder / 'inside' / 'nested.srm').write_bytes(b'save')
        self.config = Config()

    def add(self, selection, answer=False):
        paths = save_sync.get_save_directories(self.config)
        parent = object()
        dialog_module = ModuleType('ui.save_sync_folder_dialog')
        dialog_module.ask_include_save_subfolders = Mock(return_value=answer)
        picker = ModuleType('platform_utils')
        picker.pick_directory = Mock(return_value=selection)
        page = SimpleNamespace(setup_section=SimpleNamespace(config=self.config),
                               frame=SimpleNamespace(winfo_toplevel=lambda: parent),
                               _save_sync_directories_from_widget=lambda: paths,
                               _selected_save_sync_directory=lambda: '',
                               _populate_save_sync_directories=Mock())
        errors = Mock()
        call = function('ui/save_sync_panel.py', '_add_save_dir', {'os': os, 'messagebox': errors})
        with patch.dict(sys.modules, {'ui.save_sync_folder_dialog': dialog_module, 'platform_utils': picker}):
            call(page)
        errors.showerror.assert_not_called()
        return page, dialog_module.ask_include_save_subfolders, parent

    def test_adding_folder_persists_selected_scope_and_selects_it(self):
        for include in (False, True):
            with self.subTest(include=include):
                self.config = Config()
                page, prompt, parent = self.add(str(self.folder), include)
                prompt.assert_called_once_with(parent, str(self.folder))
                paths = save_sync.get_save_directories(self.config)
                self.assertEqual([str(self.folder)], paths)
                self.assertEqual(include, save_sync_sources.is_save_directory_recursive(self.config, str(self.folder)))
                page._populate_save_sync_directories.assert_called_once_with(paths, select_index=0)
                found = save_sync_sources.discover_save_files(paths, save_sync_sources.get_recursive_save_directories(self.config, paths))
                self.assertEqual(2 if include else 1, len(found))

    def test_cancelled_picker_or_scope_prompt_does_not_add_folder(self):
        before = dict(self.config.data)
        page, prompt, _ = self.add('')
        prompt.assert_not_called()
        page._populate_save_sync_directories.assert_not_called()
        page, prompt, _ = self.add(str(self.folder), None)
        prompt.assert_called_once()
        page._populate_save_sync_directories.assert_not_called()
        self.assertEqual(before, self.config.data)

    def test_existing_source_is_selected_without_prompt_or_setting_changes(self):
        save_sync.add_save_directory(self.config, str(self.folder))
        save_sync_sources.set_save_directory_recursive(self.config, str(self.folder), True)
        before = dict(self.config.data)
        page, prompt, _ = self.add(str(self.folder / 'inside' / '..'), False)
        prompt.assert_not_called()
        self.assertEqual(before, self.config.data)
        page._populate_save_sync_directories.assert_called_once_with([str(self.folder)], select_index=0)

    def test_scope_change_for_new_folder_preserves_other_sources(self):
        existing = self.root / 'Existing'
        existing.mkdir()
        save_sync.add_save_directory(self.config, str(existing))
        save_sync_sources.set_save_directory_recursive(self.config, str(existing), True)
        self.add(str(self.folder), False)
        self.assertTrue(save_sync_sources.is_save_directory_recursive(self.config, str(existing)))
        self.assertFalse(save_sync_sources.is_save_directory_recursive(self.config, str(self.folder)))

    def test_plain_language_prompt_defaults_to_only_this_folder_and_supports_cancel(self):
        for action, expected in (('default', False), ('include', True), ('cancel', None), ('close', None)):
            with self.subTest(action=action):
                widgets = []
                events = []
                class Value:
                    def __init__(self, **kwargs): self.value = kwargs['value']
                    def get(self): return self.value
                class Widget:
                    def __init__(self, parent=None, **kwargs): self.kwargs = kwargs; self.protocols = {}; widgets.append(self)
                    def pack(self, **kwargs): pass
                    def withdraw(self): events.append('withdraw')
                    def title(self, value): pass
                    def transient(self, parent): pass
                    def resizable(self, *args): pass
                    def protocol(self, name, call): self.protocols[name] = call
                    def bind(self, *args): pass
                    def destroy(self): events.append('destroy')
                    def focus_set(self): pass
                def wait(win):
                    choices = [w for w in widgets if 'variable' in w.kwargs]
                    self.assertFalse(choices[0].kwargs['variable'].get())
                    if action == 'close':
                        win.protocols['WM_DELETE_WINDOW']()
                        return
                    if action == 'include':
                        choices[1].kwargs['variable'].value = True
                    text = 'Cancel' if action == 'cancel' else 'Add Folder'
                    next(w for w in widgets if w.kwargs.get('text') == text).kwargs['command']()
                parent = SimpleNamespace(grab_current=lambda: None, winfo_screenwidth=lambda: 1920, wait_window=wait)
                def reveal(win, owner, grab=False):
                    self.assertIs(parent, owner)
                    self.assertTrue(grab)
                    events.append('reveal')
                call = function('ui/save_sync_folder_dialog.py', 'ask_include_save_subfolders', {
                    'tk': SimpleNamespace(Toplevel=Widget, BooleanVar=Value),
                    'ttk': SimpleNamespace(Frame=Widget, Label=Widget, Button=Widget, Radiobutton=Widget),
                    'reveal_window_on_parent': reveal,
                })
                self.assertIs(expected, call(parent, str(self.folder)))
                self.assertEqual(['withdraw', 'reveal', 'destroy'], events)
                labels = [w.kwargs.get('text', '') for w in widgets]
                self.assertIn('Include folders inside this folder?', labels)
                self.assertIn('This folder and all folders inside it', labels)
                self.assertNotIn('recursive', ' '.join(labels).lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)
