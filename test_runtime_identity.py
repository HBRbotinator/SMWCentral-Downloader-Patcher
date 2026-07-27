"""Tests for runtime identity consumption of the product manifest."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

import product_identity
import version_manager


ROOT = Path(__file__).resolve().parent


class RuntimeIdentityTests(unittest.TestCase):
    def test_version_manager_uses_authoritative_identity(self):
        self.assertEqual(product_identity.VERSION, version_manager.get_version())
        self.assertEqual(
            product_identity.PRODUCT_VERSION,
            version_manager.get_version_number(),
        )
        self.assertEqual(
            product_identity.WINDOWS_VERSION_TUPLE,
            version_manager.get_version_tuple(),
        )
        self.assertEqual(
            product_identity.PRODUCT_VERSION,
            version_manager.get_version_string(),
        )

    def test_legacy_package_helpers_use_authoritative_version(self):
        self.assertEqual(
            "SMWC_Downloader_v5.1.0-dev.1",
            version_manager.get_package_name(),
        )
        self.assertEqual(
            "SMWC_Downloader_v5.1.0-dev.1.zip",
            version_manager.get_zip_name(),
        )

    def test_main_imports_runtime_identity_without_hard_coding_version(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = {
            alias.name
            for node in tree.body
            if isinstance(node, ast.ImportFrom) and node.module == "product_identity"
            for alias in node.names
        }
        self.assertIn("PRODUCT_DISPLAY_NAME", imports)
        self.assertIn("VERSION", imports)
        self.assertNotIn('VERSION = "v5.1"', source)
        self.assertIn("root.title(PRODUCT_DISPLAY_NAME)", source)

    def test_ui_pages_do_not_import_version_from_main(self):
        settings_source = (ROOT / "ui/pages/settings_page.py").read_text(
            encoding="utf-8"
        )
        collection_source = (ROOT / "ui/pages/collection_page.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from product_identity import VERSION", settings_source)
        self.assertIn("from product_identity import VERSION", collection_source)
        self.assertNotIn("from main import VERSION", settings_source)
        self.assertNotIn("from main import VERSION", collection_source)

    def test_version_manager_does_not_import_application_entry_point(self):
        source = (ROOT / "version_manager.py").read_text(encoding="utf-8")
        self.assertNotIn("from main import VERSION", source)
        self.assertNotIn("main.py", source)


if __name__ == "__main__":
    unittest.main()
