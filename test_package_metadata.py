"""Tests for manifest-derived platform package metadata."""
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import package_metadata
import product_identity
import update_version


class PackageMetadataTests(unittest.TestCase):
    def test_application_windows_metadata_uses_manifest_identity(self):
        text = package_metadata.windows_version_text("application")
        self.assertIn("filevers=(5, 1, 0, 1)", text)
        self.assertIn("SMWC Downloader & Patcher", text)
        self.assertIn("SMWC Downloader.exe", text)
        self.assertIn("5.1.0-dev.1", text)
        self.assertNotIn("SMWCentral Downloader", text)

    def test_updater_windows_metadata_uses_updater_identity(self):
        text = package_metadata.windows_version_text("updater")
        self.assertIn("SMWC Downloader & Patcher Updater", text)
        self.assertIn("SMWC Updater.exe", text)
        self.assertIn("5.1.0-dev.1", text)

    def test_macos_application_metadata_is_manifest_derived(self):
        metadata = package_metadata.macos_bundle_metadata("application")
        self.assertEqual("SMWC Downloader.app", metadata["bundle_name"])
        self.assertEqual(
            "com.iamtheratio.smwc-downloader",
            metadata["bundle_identifier"],
        )
        self.assertEqual("SMWC Downloader & Patcher", metadata["display_name"])
        self.assertEqual("5.1.0", metadata["short_version"])
        self.assertEqual("5.1.0.1", metadata["bundle_version"])

    def test_macos_updater_metadata_is_manifest_derived(self):
        metadata = package_metadata.macos_bundle_metadata("updater")
        self.assertEqual("SMWC Updater.app", metadata["bundle_name"])
        self.assertEqual("com.iamtheratio.smwc-updater", metadata["bundle_identifier"])
        self.assertEqual("SMWC Updater", metadata["display_name"])
        self.assertEqual("5.1.0", metadata["short_version"])
        self.assertEqual("5.1.0.1", metadata["bundle_version"])

    def test_unknown_component_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown component"):
            package_metadata.windows_version_text("unknown")

    def test_version_files_are_written_deterministically(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            paths = package_metadata.write_windows_version_files(temporary_directory)
            application_text = paths["application"].read_text(encoding="utf-8")
            updater_text = paths["updater"].read_text(encoding="utf-8")
            self.assertEqual(
                package_metadata.windows_version_text("application"),
                application_text,
            )
            self.assertEqual(
                package_metadata.windows_version_text("updater"),
                updater_text,
            )

    def test_update_version_updates_manifest_artifacts_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            manifest_path = directory / "product_manifest.json"
            manifest_path.write_text(
                json.dumps(deepcopy(product_identity.PRODUCT_MANIFEST), indent=2) + "\n",
                encoding="utf-8",
            )
            result = update_version.update_version(
                "v5.1.0-dev.2",
                manifest_path=manifest_path,
                metadata_directory=directory,
            )
            self.assertEqual("5.1.0-dev.2", result)
            payload = product_identity.load_product_manifest(manifest_path)
            self.assertEqual("5.1.0-dev.2", payload["product"]["version"])
            self.assertEqual("5.1.0.dev2", payload["product"]["pep440_version"])
            self.assertEqual([5, 1, 0, 2], payload["versions"]["windows_numeric"])
            for target in payload["targets"].values():
                self.assertIn("5.1.0-dev.2", target["artifact_name"])
                self.assertNotIn("5.1.0-dev.1", target["artifact_name"])
            self.assertIn(
                "filevers=(5, 1, 0, 2)",
                (directory / "version.txt").read_text(encoding="utf-8"),
            )
            self.assertIn(
                "SMWC Updater.exe",
                (directory / "updater_version.txt").read_text(encoding="utf-8"),
            )

    def test_update_version_rejects_unsupported_format_without_writing(self):
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            manifest_path = directory / "product_manifest.json"
            original = json.dumps(product_identity.PRODUCT_MANIFEST, indent=2) + "\n"
            manifest_path.write_text(original, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "MAJOR.MINOR.PATCH-dev.BUILD"):
                update_version.update_version(
                    "5.1",
                    manifest_path=manifest_path,
                    metadata_directory=directory,
                )
            self.assertEqual(original, manifest_path.read_text(encoding="utf-8"))
            self.assertFalse((directory / "version.txt").exists())


if __name__ == "__main__":
    unittest.main()
