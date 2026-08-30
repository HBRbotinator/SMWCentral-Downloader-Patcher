import ast
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class LegacyDownloadIdentityWiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / "main.py").read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_removed_numeric_duplicate_version_heuristic(self):
        function_names = {
            node.name for node in ast.walk(self.tree) if isinstance(node, ast.FunctionDef)
        }
        self.assertNotIn("detect_and_handle_duplicates", function_names)
        self.assertNotIn("higher ID numbers are usually newer", self.source)
        self.assertNotIn("superseded by ID", self.source)

    def test_download_pipeline_uses_identity_safe_provider_helpers(self):
        pipeline = next(
            node
            for node in self.tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "run_single_download_pipeline"
        )
        calls = {
            node.func.id
            for node in ast.walk(pipeline)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertIn("provider_marks_obsolete", calls)
        self.assertIn("same_title_collection_ids", calls)
        self.assertIn("No version relationship was inferred.", self.source)


if __name__ == "__main__":
    unittest.main()
