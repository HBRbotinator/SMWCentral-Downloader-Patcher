"""Regression tests for the manifest-backed build and contributor documentation."""
from __future__ import annotations

import unittest
from pathlib import Path

from product_identity import PRODUCT_MANIFEST, PRODUCT_VERSION, RELEASE_CHANNEL

ROOT = Path(__file__).resolve().parent


class DocumentationContractTests(unittest.TestCase):
    """Keep public build instructions aligned with the executable contracts."""

    @staticmethod
    def _read(relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_contributor_guide_documents_authoritative_manifest_and_quality_gate(self) -> None:
        guide = self._read("CONTRIBUTING.md")
        self.assertIn("product_manifest.json", guide)
        self.assertIn("python -m build_support.quality --skip-build", guide)
        self.assertIn("python -m build_support.build_candidate", guide)
        self.assertIn("development builds", guide.casefold())

    def test_build_instructions_match_workflow_and_manifest_targets(self) -> None:
        instructions = self._read(".github/BUILD_INSTRUCTIONS.md")
        self.assertIn("v5.1 Candidate CI", instructions)
        self.assertIn("Final Release", instructions)
        self.assertIn("source-quality-coverage", instructions)
        for target_name, target in PRODUCT_MANIFEST["targets"].items():
            self.assertIn(target_name, instructions)
            self.assertIn(str(target["runner"]), instructions)
        for stale_path in (
            ".github/workflows/dev-builds.yml",
            ".github/workflows/release.yml",
            ".github/workflows/build-releases.yml",
        ):
            self.assertNotIn(stale_path, instructions)

    def test_version_documentation_uses_manifest_instead_of_main_constant(self) -> None:
        documentation = self._read("VERSION_MANAGEMENT.md")
        self.assertIn("product_manifest.json", documentation)
        self.assertIn(PRODUCT_VERSION, documentation)
        self.assertIn(RELEASE_CHANNEL, documentation)
        self.assertIn("update_policy.py", documentation)
        self.assertNotIn('VERSION = "v4.', documentation)
        self.assertNotIn("single location - the `VERSION` constant in `main.py`", documentation)

    def test_readme_describes_current_native_package_contract(self) -> None:
        readme = self._read("README.md")
        self.assertIn("Windows-x64.zip", readme)
        self.assertIn("macOS-arm64.dmg", readme)
        self.assertIn("macOS-x86_64.dmg", readme)
        self.assertIn("Linux-x64.tar.gz", readme)
        self.assertIn("does not currently publish a Universal macOS package", readme)
        self.assertIn("rather than an AppImage", readme)
        self.assertNotIn("SMWC-Downloader-macOS-Universal.dmg", readme)
        self.assertNotIn("SMWC-Downloader-x86_64.AppImage", readme)

    def test_documentation_files_are_utf8_with_final_newline(self) -> None:
        for relative in (
            "README.md",
            "CONTRIBUTING.md",
            "VERSION_MANAGEMENT.md",
            ".github/BUILD_INSTRUCTIONS.md",
        ):
            raw = (ROOT / relative).read_bytes()
            self.assertTrue(raw.endswith(b"\n"), relative)
            raw.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
