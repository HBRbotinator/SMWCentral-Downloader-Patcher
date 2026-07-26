"""Regression tests for the manifest-derived native candidate workflow."""
from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from build_support.ci_matrix import candidate_matrix, render_matrix
from product_identity import PRODUCT_MANIFEST


ROOT = Path(__file__).resolve().parent
WORKFLOW = ROOT / ".github" / "workflows" / "smart-cicd.yml"


class CandidateMatrixTests(unittest.TestCase):
    def test_matrix_is_derived_from_every_manifest_target(self) -> None:
        matrix = candidate_matrix()
        rows = matrix["include"]
        self.assertEqual(
            [row["target"] for row in rows],
            list(PRODUCT_MANIFEST["targets"]),
        )
        for row in rows:
            target = PRODUCT_MANIFEST["targets"][row["target"]]
            self.assertEqual(row["runner"], target["runner"])
            self.assertEqual(row["platform"], target["platform"])
            self.assertEqual(row["architecture"], target["architecture"])
            self.assertEqual(row["artifact_name"], target["artifact_name"])

    def test_matrix_json_is_compact_stable_and_round_trips(self) -> None:
        rendered = render_matrix()
        self.assertNotIn("\n", rendered)
        self.assertEqual(json.loads(rendered), candidate_matrix())
        self.assertEqual(rendered, render_matrix())

    def test_matrix_command_prints_only_the_json_document(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "build_support.ci_matrix"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.stdout.strip(), render_matrix())


class CandidateWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = WORKFLOW.read_text(encoding="utf-8")

    def test_workflow_is_read_only_and_cancels_superseded_runs(self) -> None:
        self.assertIn("permissions:\n  contents: read", self.text)
        self.assertNotIn("contents: write", self.text)
        self.assertIn("cancel-in-progress: true", self.text)

    def test_feature_integration_and_pull_request_events_are_covered(self) -> None:
        self.assertIn('- "feature/**"', self.text)
        self.assertIn('- "integration/**"', self.text)
        self.assertIn("  pull_request:\n", self.text)
        self.assertNotIn("github.event_name != 'pull_request'", self.text)

    def test_workflow_uses_manifest_generated_matrix(self) -> None:
        self.assertIn("python -m build_support.ci_matrix", self.text)
        self.assertIn(
            "matrix: ${{ fromJSON(needs.source-quality.outputs.matrix) }}",
            self.text,
        )
        self.assertIn("runs-on: ${{ matrix.runner }}", self.text)

    def test_all_four_native_manifest_targets_have_distinct_runners(self) -> None:
        rows = candidate_matrix()["include"]
        self.assertEqual(len(rows), 4)
        by_target = {row["target"]: row["runner"] for row in rows}
        self.assertEqual(by_target["windows-x86_64"], "windows-latest")
        self.assertEqual(by_target["linux-x86_64"], "ubuntu-24.04")
        self.assertEqual(by_target["macos-arm64"], "macos-15")
        self.assertEqual(by_target["macos-x86_64"], "macos-15-intel")

    def test_source_gate_and_native_candidate_gate_are_both_required(self) -> None:
        self.assertIn("python -m build_support.quality --skip-build", self.text)
        self.assertIn("--target ${{ matrix.target }}", self.text)
        self.assertIn("--skip-static", self.text)
        self.assertIn("--skip-security", self.text)
        self.assertIn("needs: source-quality", self.text)

    def test_only_constrained_requirement_files_are_installed(self) -> None:
        self.assertIn("-r requirements.txt", self.text)
        self.assertIn("-r requirements-build.txt", self.text)
        self.assertIn("-r requirements-quality.txt", self.text)
        self.assertNotIn("pip install pyinstaller", self.text.casefold())
        self.assertNotIn("pip install --upgrade pip", self.text.casefold())

    def test_hidden_coverage_database_is_uploaded_as_required_evidence(self) -> None:
        self.assertIn("path: .coverage", self.text)
        self.assertIn("include-hidden-files: true", self.text)
        coverage_block = self.text.split("name: source-quality-coverage", 1)[1]
        coverage_block = coverage_block.split("candidate-build:", 1)[0]
        self.assertIn("if-no-files-found: error", coverage_block)

    def test_verified_outputs_are_uploaded_for_each_target(self) -> None:
        self.assertIn("artifacts/${{ matrix.artifact_name }}", self.text)
        self.assertIn("artifacts/${{ matrix.artifact_name }}.sha256", self.text)
        self.assertIn("${{ matrix.target }}-smoke.json", self.text)
        self.assertIn("${{ matrix.target }}-verification.json", self.text)
        self.assertIn("if-no-files-found: error", self.text)

    def test_obsolete_inline_specs_and_universal_claims_are_removed(self) -> None:
        self.assertNotIn("cat > \"SMWC Downloader Linux.spec\"", self.text)
        self.assertNotIn("cat > \"SMWC Updater Linux.spec\"", self.text)
        self.assertNotIn("Universal", self.text)
        self.assertNotIn("Get version from main.py", self.text)

    def test_current_official_action_major_versions_are_explicit(self) -> None:
        self.assertIn("actions/checkout@v6", self.text)
        self.assertIn("actions/setup-python@v7", self.text)
        self.assertIn("actions/upload-artifact@v7", self.text)


if __name__ == "__main__":
    unittest.main()
