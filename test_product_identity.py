"""Tests for the authoritative 5.1 product manifest."""
from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import product_identity


class ProductIdentityTests(unittest.TestCase):
    def _write_manifest(self, payload: dict) -> Path:
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        path = Path(temporary_directory.name) / "product_manifest.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_authoritative_manifest_loads(self):
        self.assertEqual("smwc-downloader", product_identity.PRODUCT_ID)
        self.assertEqual("SMWC Downloader & Patcher", product_identity.PRODUCT_DISPLAY_NAME)
        self.assertEqual("5.1.0-dev.1", product_identity.PRODUCT_VERSION)
        self.assertEqual("5.1.0.dev1", product_identity.PEP440_VERSION)
        self.assertEqual("v5.1.0-dev.1", product_identity.VERSION)
        self.assertEqual((5, 1, 0, 1), product_identity.WINDOWS_VERSION_TUPLE)
        self.assertEqual("5.1.0", product_identity.MACOS_SHORT_VERSION)
        self.assertEqual("5.1.0.1", product_identity.MACOS_BUNDLE_VERSION)

    def test_manifest_preserves_existing_component_names(self):
        application = product_identity.APPLICATION_IDENTITY
        updater = product_identity.UPDATER_IDENTITY
        self.assertEqual("SMWC Downloader", application["windows_name"])
        self.assertEqual("smwc-downloader", application["linux_name"])
        self.assertEqual("SMWC Downloader.app", application["macos_bundle_name"])
        self.assertEqual("SMWC Updater", updater["windows_name"])
        self.assertEqual("smwc-updater", updater["linux_name"])
        self.assertEqual("SMWC Updater.app", updater["macos_bundle_name"])

    def test_manifest_declares_required_native_targets(self):
        expected = {
            "windows-x86_64": ("windows", "x86_64"),
            "linux-x86_64": ("linux", "x86_64"),
            "macos-arm64": ("macos", "arm64"),
            "macos-x86_64": ("macos", "x86_64"),
        }
        self.assertEqual(expected.keys(), product_identity.PRODUCT_MANIFEST["targets"].keys())
        for target_name, (platform_name, architecture) in expected.items():
            target = product_identity.get_target(target_name)
            self.assertEqual(platform_name, target["platform"])
            self.assertEqual(architecture, target["architecture"])
            self.assertIn(product_identity.PRODUCT_VERSION, target["artifact_name"])

    def test_updater_identity_is_bound_to_the_same_product(self):
        updater = product_identity.UPDATER_IDENTITY
        self.assertEqual(product_identity.PRODUCT_ID, updater["product_id"])
        self.assertEqual(product_identity.RELEASE_CHANNEL, updater["release_channel"])

    def test_get_target_returns_an_isolated_copy(self):
        target = product_identity.get_target("windows-x86_64")
        target["runner"] = "changed"
        self.assertNotEqual(
            "changed",
            product_identity.PRODUCT_MANIFEST["targets"]["windows-x86_64"]["runner"],
        )

    def test_supported_python_range_accepts_declared_versions(self):
        self.assertEqual((3, 11), product_identity.validate_supported_python((3, 11)))
        self.assertEqual((3, 13), product_identity.validate_supported_python((3, 13)))

    def test_supported_python_range_rejects_outside_versions(self):
        with self.assertRaises(product_identity.ProductManifestError):
            product_identity.validate_supported_python((3, 10))
        with self.assertRaises(product_identity.ProductManifestError):
            product_identity.validate_supported_python((3, 14))

    def test_missing_required_product_field_is_rejected(self):
        payload = deepcopy(product_identity.PRODUCT_MANIFEST)
        del payload["product"]["display_name"]
        path = self._write_manifest(payload)
        with self.assertRaisesRegex(
            product_identity.ProductManifestError,
            r"product\.display_name must be a non-empty string",
        ):
            product_identity.load_product_manifest(path)

    def test_inconsistent_pep440_version_is_rejected(self):
        payload = deepcopy(product_identity.PRODUCT_MANIFEST)
        payload["product"]["pep440_version"] = "5.1.0.dev2"
        path = self._write_manifest(payload)
        with self.assertRaisesRegex(
            product_identity.ProductManifestError,
            r"product\.pep440_version does not match product\.version",
        ):
            product_identity.load_product_manifest(path)

    def test_inconsistent_platform_version_is_rejected(self):
        payload = deepcopy(product_identity.PRODUCT_MANIFEST)
        payload["versions"]["windows_numeric"] = [5, 1, 0, 2]
        path = self._write_manifest(payload)
        with self.assertRaisesRegex(
            product_identity.ProductManifestError,
            r"versions\.windows_numeric does not match product\.version",
        ):
            product_identity.load_product_manifest(path)

    def test_missing_native_target_is_rejected(self):
        payload = deepcopy(product_identity.PRODUCT_MANIFEST)
        del payload["targets"]["macos-arm64"]
        path = self._write_manifest(payload)
        with self.assertRaisesRegex(
            product_identity.ProductManifestError,
            r"manifest\.targets is invalid: missing macos-arm64",
        ):
            product_identity.load_product_manifest(path)

    def test_unsupported_schema_is_rejected(self):
        payload = deepcopy(product_identity.PRODUCT_MANIFEST)
        payload["schema_version"] = 2
        path = self._write_manifest(payload)
        with self.assertRaisesRegex(
            product_identity.ProductManifestError,
            r"Unsupported product manifest schema: 2",
        ):
            product_identity.load_product_manifest(path)


if __name__ == "__main__":
    unittest.main()
