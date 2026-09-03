"""Execute review row population and window sizing without a display server."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).parent


def methods(*names):
    path = ROOT / 'ui/collection_ingestion_review_dialog.py'
    tree = ast.parse(path.read_text(encoding='utf-8'))
    namespace = {}
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace, tree


class ReviewSmokeUiTest(unittest.TestCase):
    def test_each_displayed_value_matches_its_actual_column_definition(self):
        namespace, tree = methods('_populate_suggestions', '_populate_local_suggestions', '_catalogue_author_text')
        columns = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ('columns', 'local_columns') and isinstance(node.value, ast.Tuple):
                    values = ast.literal_eval(node.value)
                    if 'score' in values:
                        columns[node.targets[0].id] = values
        suggestion = SimpleNamespace(title='Grand Poo World 3', target_key='12345', authors=('Barb',),
                                     difficulty='Master', hack_type='kaizo', hack_types=('kaizo',), exits=41, confidence=.99)
        numeric = Mock()
        numeric.get_children.return_value = ()
        local = Mock()
        local.get_children.return_value = ()
        dialog = SimpleNamespace(suggestion_tree=numeric, local_tree=local,
                                 model=SimpleNamespace(collection_status=lambda key: 'Already in Collection'))
        namespace['_populate_suggestions'](dialog, [suggestion])
        namespace['_populate_local_suggestions'](dialog, [suggestion])
        numeric_values = numeric.insert.call_args.kwargs['values']
        local_values = local.insert.call_args.kwargs['values']
        self.assertEqual(len(columns['columns']), len(numeric_values))
        self.assertEqual(len(columns['local_columns']), len(local_values))
        self.assertEqual({'title': suggestion.title, 'id': '12345', 'collection': 'Already in Collection',
                          'author': 'Barb', 'difficulty': 'Master', 'type': 'kaizo', 'exits': 41, 'score': '99%'},
                         dict(zip(columns['columns'], numeric_values)))
        self.assertEqual({'title': suggestion.title, 'id': '12345', 'difficulty': 'Master',
                          'type': 'kaizo', 'exits': 41, 'score': '99%'},
                         dict(zip(columns['local_columns'], local_values)))

    def test_review_grows_on_large_displays_and_fits_small_displays(self):
        namespace, _ = methods('_size_item_review_window')
        for screen, expected in (((1920, 1080), '1180x960'), ((1366, 768), '1180x668'), ((700, 500), '620x400')):
            win = Mock()
            win.winfo_vrootwidth.return_value, win.winfo_vrootheight.return_value = screen
            namespace['_size_item_review_window'](SimpleNamespace(review_win=win))
            win.geometry.assert_called_once_with(expected)
            minimum = win.minsize.call_args.args
            self.assertLessEqual(minimum[0], screen[0]-80)
            self.assertLessEqual(minimum[1], screen[1]-100)

    def test_personal_data_shortcut_scrolls_to_choices(self):
        namespace, _ = methods('_show_personal_data')
        area = Mock()
        area.winfo_y.return_value = 720
        details = Mock()
        details.winfo_height.return_value = 1200
        canvas = Mock()
        win = Mock()
        dialog = SimpleNamespace(_item_canvas=canvas, _user_conflicts_area=area, details=details, review_win=win)
        namespace['_show_personal_data'](dialog)
        win.update_idletasks.assert_called_once()
        canvas.yview_moveto.assert_called_once_with(712/1200)


if __name__ == '__main__':
    unittest.main(verbosity=2)
