from __future__ import annotations

import unittest
from pathlib import Path

from build_support.manifest import (
    ROOT,
    SUPPORTED_TARGETS,
    auto_target,
    build_resources,
    component_build_config,
    component_output_name,
    hidden_imports,
    package_data_packages,
    validate_build_manifest,
)
from product_identity import ProductManifestError


class BuildManifestTests(unittest.TestCase):
    def test_all_native_targets_are_declared(self):
        self.assertEqual(
            set(SUPPORTED_TARGETS),
            {"windows-x86_64", "linux-x86_64", "macos-arm64", "macos-x86_64"},
        )
        result = validate_build_manifest()
        self.assertEqual(set(result["targets"]), set(SUPPORTED_TARGETS))

    def test_application_resources_are_manifest_owned_and_exist(self):
        resources = component_build_config("application")["resources"]
        self.assertEqual(
            [resource["source"] for resource in resources],
            ["assets", "ui", "product_manifest.json"],
        )
        for source, _ in build_resources("application"):
            self.assertTrue(Path(source).exists(), source)

    def test_updater_carries_only_shared_product_identity_data(self):
        self.assertEqual(
            component_build_config("updater")["resources"],
            [
                {
                    "source": "product_manifest.json",
                    "destination": ".",
                    "kind": "file",
                }
            ],
        )
        self.assertEqual(hidden_imports("updater"), ["product_identity"])
        self.assertEqual(package_data_packages("updater"), [])

    def test_theme_and_pillow_packaging_are_explicit(self):
        self.assertEqual(package_data_packages("application"), ["sv_ttk"])
        imports = hidden_imports("application")
        self.assertIn("PIL.Image", imports)
        self.assertIn("PIL.ImageTk", imports)
        self.assertIn("ui.save_sync_dialog", imports)

    def test_output_names_preserve_existing_component_names(self):
        self.assertEqual(
            component_output_name("application", "windows-x86_64"),
            "SMWC Downloader",
        )
        self.assertEqual(
            component_output_name("application", "linux-x86_64"),
            "smwc-downloader",
        )
        self.assertEqual(
            component_output_name("application", "macos-arm64"),
            "SMWC Downloader",
        )
        self.assertEqual(
            component_output_name("updater", "macos-x86_64"),
            "SMWC Updater",
        )

    def test_host_target_detection_is_architecture_aware(self):
        self.assertEqual(auto_target("win32", "AMD64"), "windows-x86_64")
        self.assertEqual(auto_target("linux", "x86_64"), "linux-x86_64")
        self.assertEqual(auto_target("darwin", "arm64"), "macos-arm64")
        self.assertEqual(auto_target("darwin", "x86_64"), "macos-x86_64")
        with self.assertRaises(ProductManifestError):
            auto_target("darwin", "ppc64")

    def test_unknown_component_and_target_fail_closed(self):
        with self.assertRaises(ProductManifestError):
            component_build_config("unknown")
        with self.assertRaises(ProductManifestError):
            component_output_name("application", "unknown")

    def test_specs_are_thin_shared_wrappers(self):
        specs = {
            "SMWC Downloader.spec": "build_application",
            "SMWC Downloader Linux.spec": "build_application",
            "SMWC Downloader macOS.spec": "build_application",
            "SMWC Updater.spec": "build_updater",
            "SMWC Updater Linux.spec": "build_updater",
            "SMWC Updater macOS.spec": "build_updater",
        }
        for relative, function_name in specs.items():
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("build_support.pyinstaller_common", text)
            self.assertIn(function_name, text)
            self.assertNotIn("Analysis(", text)
            self.assertNotIn("excludes=['PIL'", text)
            self.assertNotIn("4.9.0", text)

    def test_obsolete_main_spec_is_removed(self):
        self.assertFalse((ROOT / "main.spec").exists())

    def test_linux_builder_uses_checked_in_specs(self):
        text = (ROOT / "build_release_linux.py").read_text(encoding="utf-8")
        self.assertIn('"SMWC Downloader Linux.spec"', text)
        self.assertIn('"SMWC Updater Linux.spec"', text)
        self.assertIn('"SMWC_BUILD_TARGET": "linux-x86_64"', text)
        self.assertNotIn("main_spec_content", text)
        self.assertNotIn("updater_spec_content", text)


if __name__ == "__main__":
    unittest.main()
