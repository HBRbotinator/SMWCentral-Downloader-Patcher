"""Tests for target-bound candidate build and verification support."""
from __future__ import annotations

import json
import os
import stat
import struct
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from build_support import build_candidate
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


class CandidateVerificationTests(unittest.TestCase):
    @staticmethod
    def _write_pe(path: Path, machine: int) -> None:
        payload = bytearray(256)
        payload[0:2] = b"MZ"
        struct.pack_into("<I", payload, 0x3C, 0x80)
        payload[0x80:0x84] = b"PE\x00\x00"
        struct.pack_into("<H", payload, 0x84, machine)
        path.write_bytes(payload)

    @staticmethod
    def _write_elf(path: Path, machine: int) -> None:
        payload = bytearray(64)
        payload[0:4] = b"\x7fELF"
        payload[4] = 2
        payload[5] = 1
        struct.pack_into("<H", payload, 18, machine)
        path.write_bytes(payload)

    def test_pe_architecture_reader_supports_x86_64_and_arm64(self):
        with tempfile.TemporaryDirectory() as temporary:
            x64 = Path(temporary) / "x64.exe"
            arm64 = Path(temporary) / "arm64.exe"
            self._write_pe(x64, 0x8664)
            self._write_pe(arm64, 0xAA64)
            self.assertEqual("x86_64", build_candidate._read_binary_architecture(x64))
            self.assertEqual("arm64", build_candidate._read_binary_architecture(arm64))

    def test_elf_architecture_reader_supports_x86_64_and_arm64(self):
        with tempfile.TemporaryDirectory() as temporary:
            x64 = Path(temporary) / "x64"
            arm64 = Path(temporary) / "arm64"
            self._write_elf(x64, 62)
            self._write_elf(arm64, 183)
            self.assertEqual("x86_64", build_candidate._read_binary_architecture(x64))
            self.assertEqual("arm64", build_candidate._read_binary_architecture(arm64))

    def test_unknown_binary_format_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "unknown"
            binary.write_bytes(b"not an executable")
            with self.assertRaisesRegex(RuntimeError, "Unsupported executable format"):
                build_candidate._read_binary_architecture(
                    binary, host_platform="linux"
                )

    def test_checksum_file_matches_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary) / "candidate.zip"
            artifact.write_bytes(b"candidate payload")
            checksum = build_candidate._write_checksum(artifact)
            digest, filename = checksum.read_text(encoding="utf-8").split()
            self.assertEqual(build_candidate._sha256(artifact), digest)
            self.assertEqual(artifact.name, filename)

    def test_smoke_result_requires_matching_target_version_and_product(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "smoke.json"
            payload = {
                "status": "ok",
                "version": PRODUCT_VERSION,
                "identity": {
                    "target": "linux-x86_64",
                    "product_id": PRODUCT_ID,
                },
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = build_candidate._validate_smoke_result(path, "linux-x86_64")
            self.assertEqual("ok", result["status"])
            payload["identity"]["target"] = "windows-x86_64"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "requested target"):
                build_candidate._validate_smoke_result(path, "linux-x86_64")

    def test_smoke_result_rejects_failed_status(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "smoke.json"
            path.write_text(json.dumps({"status": "failed"}), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "did not report success"):
                build_candidate._validate_smoke_result(path, "linux-x86_64")

    def test_platform_specs_are_selected_explicitly(self):
        self.assertEqual(
            ("SMWC Downloader.spec", "SMWC Updater.spec"),
            build_candidate._specs("windows-x86_64"),
        )
        self.assertEqual(
            ("SMWC Downloader Linux.spec", "SMWC Updater Linux.spec"),
            build_candidate._specs("linux-x86_64"),
        )
        self.assertEqual(
            ("SMWC Downloader macOS.spec", "SMWC Updater macOS.spec"),
            build_candidate._specs("macos-arm64"),
        )

    def test_host_guard_accepts_only_the_matching_native_target(self):
        build_candidate._host_guard(
            "windows-x86_64",
            host_platform="win32",
            host_machine="AMD64",
        )
        with self.assertRaisesRegex(RuntimeError, "must be built"):
            build_candidate._host_guard(
                "macos-arm64",
                host_platform="win32",
                host_machine="AMD64",
            )

    def test_component_binary_paths_follow_manifest_names(self):
        self.assertEqual(
            build_candidate.DIST_DIR / "SMWC Downloader.exe",
            build_candidate._main_binary("windows-x86_64"),
        )
        self.assertEqual(
            build_candidate.DIST_DIR / "smwc-updater",
            build_candidate._updater_binary("linux-x86_64"),
        )
        self.assertEqual(
            build_candidate.DIST_DIR
            / "SMWC Downloader.app"
            / "Contents"
            / "MacOS"
            / "SMWC Downloader",
            build_candidate._main_binary("macos-arm64"),
        )

    def test_windows_package_contains_application_updater_and_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            dist.mkdir()
            (dist / "SMWC Downloader.exe").write_bytes(b"main")
            (dist / "SMWC Updater.exe").write_bytes(b"updater")
            identity = root / "build_identity.json"
            identity.write_text("{}\n", encoding="utf-8")
            artifact = root / "candidate.zip"
            with patch.object(build_candidate, "DIST_DIR", dist):
                build_candidate._package_windows(
                    "windows-x86_64", identity, artifact
                )
            members = build_candidate._artifact_members(artifact, "zip")
            self.assertIn("SMWC Downloader/SMWC Downloader.exe", members)
            self.assertIn(
                "SMWC Downloader/updater/SMWC Updater.exe", members
            )
            self.assertIn("SMWC Downloader/build_identity.json", members)

    def test_linux_package_marks_launchers_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dist = root / "dist"
            dist.mkdir()
            (dist / "smwc-downloader").write_bytes(b"main")
            (dist / "smwc-updater").write_bytes(b"updater")
            identity = root / "build_identity.json"
            identity.write_text("{}\n", encoding="utf-8")
            artifact = root / "candidate.tar.gz"
            with patch.object(build_candidate, "DIST_DIR", dist):
                build_candidate._package_linux("linux-x86_64", identity, artifact)
            with tarfile.open(artifact, "r:gz") as archive:
                launcher = archive.getmember(
                    "smwc-downloader/run-smwc-downloader.sh"
                )
                application = archive.getmember("smwc-downloader/smwc-downloader")
                updater = archive.getmember(
                    "smwc-downloader/updater/smwc-updater"
                )
            self.assertTrue(launcher.mode & stat.S_IXUSR)
            self.assertTrue(application.mode & stat.S_IXUSR)
            self.assertTrue(updater.mode & stat.S_IXUSR)

    def test_verification_report_is_stable_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = Path(temporary)
            with patch.object(build_candidate, "ARTIFACTS_DIR", artifacts):
                path = build_candidate._write_verification(
                    "linux-x86_64",
                    {"status": "ok", "target": "linux-x86_64"},
                )
            self.assertEqual(
                {"status": "ok", "target": "linux-x86_64"},
                json.loads(path.read_text(encoding="utf-8")),
            )

    def test_command_line_defaults_to_native_target(self):
        with patch.object(
            build_candidate, "auto_target", return_value="linux-x86_64"
        ), patch.object(build_candidate, "build_candidate") as build:
            self.assertEqual(0, build_candidate.main([]))
        build.assert_called_once_with("linux-x86_64")


if __name__ == "__main__":
    unittest.main()
