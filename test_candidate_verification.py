"""Tests for target-bound candidate build and verification support."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_support.manifest import (
    ROOT,
    component_build_config,
    required_package_resources,
    required_runtime_resources,
)
from build_support.metadata import build_identity, write_build_identity
from product_identity import (
    PRODUCT_ID,
    PRODUCT_VERSION,
    ProductManifestError,
    load_build_identity,
    validate_runtime_resources,
)


class CandidateMetadataTests(unittest.TestCase):
    def test_build_identity_is_target_bound_and_uses_source_overrides(self):
        with patch.dict(
            os.environ,
            {
                "SMWC_SOURCE_REVISION": "0123456789abcdef",
                "SMWC_SOURCE_DIRTY": "false",
            },
            clear=False,
        ):
            identity = build_identity("macos-arm64")
        self.assertEqual(PRODUCT_ID, identity["product_id"])
        self.assertEqual(PRODUCT_VERSION, identity["version"])
        self.assertEqual("macos-arm64", identity["target"])
        self.assertEqual("macos", identity["platform"])
        self.assertEqual("arm64", identity["architecture"])
        self.assertEqual("0123456789abcdef", identity["source_revision"])
        self.assertFalse(identity["source_dirty"])

    def test_build_identity_file_round_trips_through_runtime_validation(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(
                os.environ,
                {
                    "SMWC_SOURCE_REVISION": "abcdef",
                    "SMWC_SOURCE_DIRTY": "true",
                },
                clear=False,
            ):
                path = write_build_identity("windows-x86_64", temporary)
            payload = load_build_identity(path)
        self.assertEqual("windows-x86_64", payload["target"])
        self.assertEqual("windows", payload["platform"])
        self.assertEqual("x86_64", payload["architecture"])
        self.assertEqual("abcdef", payload["source_revision"])
        self.assertTrue(payload["source_dirty"])

    def test_build_identity_rejects_mismatched_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "build_identity.json"
            payload = build_identity("linux-x86_64")
            payload["product_id"] = "another-product"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ProductManifestError, "product_id"):
                load_build_identity(path)

    def test_missing_explicit_build_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.json"
            with self.assertRaisesRegex(ProductManifestError, "missing"):
                load_build_identity(missing)

    def test_runtime_resource_contract_exists_in_source_tree(self):
        expected = [
            "product_manifest.json",
            "assets/icon.ico",
            "assets/icon.icns",
            "assets/moon.png",
        ]
        self.assertEqual(expected, required_runtime_resources("application"))
        self.assertEqual(expected, validate_runtime_resources("application"))

    def test_theme_package_resource_is_declared_for_frozen_smoke(self):
        self.assertEqual(
            [{"package": "sv_ttk", "suffix": ".tcl"}],
            required_package_resources("application"),
        )
        self.assertEqual([], required_package_resources("updater"))

    def test_build_identity_is_added_to_both_pyinstaller_components(self):
        source = (ROOT / "build_support" / "pyinstaller_common.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("write_build_identity(target_name)", source)
        self.assertIn("_datas(component_name, target_name)", source)
        self.assertIn(
            "build_support.runtime_smoke",
            component_build_config("application")["hidden_imports"],
        )

    def test_application_entry_point_exposes_non_gui_smoke_mode(self):
        source = (ROOT / "main.py").read_text(encoding="utf-8")
        self.assertIn('if "--smoke-test" in sys.argv:', source)
        self.assertIn("run_runtime_smoke", source)


if __name__ == "__main__":
    unittest.main()
