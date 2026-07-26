"""Regression tests for complete same-revision final-release evidence."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_support.manifest import SUPPORTED_TARGETS, canonical_machine, target_config
from build_support.release_gate import (
    ReleaseGateError,
    validate_release_inputs,
    validate_release_tag,
)
from product_identity import (
    PRODUCT_DISPLAY_NAME,
    PRODUCT_ID,
    PRODUCT_VERSION,
    RELEASE_CHANNEL,
)

ROOT = Path(__file__).resolve().parent
FINAL_RELEASE_WORKFLOW = ROOT / ".github" / "workflows" / "final-release.yml"
REVISION = "0123456789abcdef0123456789abcdef01234567"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _create_release_evidence(root: Path, revision: str = REVISION) -> None:
    for target_name in SUPPORTED_TARGETS:
        target = target_config(target_name)
        target_root = root / target_name
        target_root.mkdir(parents=True)
        artifact_name = str(target["artifact_name"])
        artifact = target_root / artifact_name
        artifact.write_bytes(f"native candidate for {target_name}\n".encode())
        digest = _sha256(artifact)
        checksum_name = artifact_name + ".sha256"
        (target_root / checksum_name).write_text(
            f"{digest}  {artifact_name}\n",
            encoding="utf-8",
        )
        identity = {
            "schema_version": 1,
            "product_id": PRODUCT_ID,
            "product_name": PRODUCT_DISPLAY_NAME,
            "version": PRODUCT_VERSION,
            "release_channel": RELEASE_CHANNEL,
            "target": target_name,
            "platform": target["platform"],
            "architecture": target["architecture"],
            "artifact_name": artifact_name,
            "source_revision": revision,
            "source_dirty": False,
        }
        smoke = {
            "status": "ok",
            "product": PRODUCT_DISPLAY_NAME,
            "version": PRODUCT_VERSION,
            "identity": identity,
        }
        _write_json(target_root / f"{target_name}-smoke.json", smoke)
        expected_architecture = canonical_machine(str(target["architecture"]))
        verification = {
            "status": "ok",
            "target": target_name,
            "product_id": PRODUCT_ID,
            "product": PRODUCT_DISPLAY_NAME,
            "version": PRODUCT_VERSION,
            "platform": target["platform"],
            "expected_architecture": expected_architecture,
            "application_architecture": expected_architecture,
            "updater_architecture": expected_architecture,
            "artifact": artifact_name,
            "artifact_type": target["artifact_type"],
            "artifact_sha256": digest,
            "checksum": checksum_name,
            "source_revision": revision,
            "source_dirty": False,
        }
        _write_json(
            target_root / f"{target_name}-verification.json",
            verification,
        )


class ReleaseTagTests(unittest.TestCase):
    def test_exact_stable_tag_is_accepted_for_stable_channel(self) -> None:
        self.assertEqual(
            validate_release_tag(
                "v5.1.0",
                version="5.1.0",
                release_channel="stable",
            ),
            "v5.1.0",
        )

    def test_development_channel_cannot_publish_final_release(self) -> None:
        with self.assertRaisesRegex(ReleaseGateError, "disabled"):
            validate_release_tag(
                "v5.1.0",
                version="5.1.0",
                release_channel="development",
            )

    def test_tag_must_match_manifest_version_exactly(self) -> None:
        with self.assertRaisesRegex(ReleaseGateError, "does not match"):
            validate_release_tag(
                "v5.1.1",
                version="5.1.0",
                release_channel="stable",
            )


class ReleaseEvidenceTests(unittest.TestCase):
    def test_complete_same_revision_evidence_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_release_evidence(root)
            payload = validate_release_inputs(root, expected_revision=REVISION)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["source_revision"], REVISION)
        self.assertEqual(list(payload["targets"]), list(SUPPORTED_TARGETS))

    def test_missing_native_target_artifact_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_release_evidence(root)
            target = target_config(SUPPORTED_TARGETS[-1])
            (root / SUPPORTED_TARGETS[-1] / str(target["artifact_name"])).unlink()
            with self.assertRaisesRegex(ReleaseGateError, "missing"):
                validate_release_inputs(root, expected_revision=REVISION)

    def test_checksum_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_release_evidence(root)
            target_name = SUPPORTED_TARGETS[0]
            target = target_config(target_name)
            artifact = root / target_name / str(target["artifact_name"])
            artifact.write_bytes(b"tampered candidate\n")
            with self.assertRaisesRegex(ReleaseGateError, "Checksum mismatch"):
                validate_release_inputs(root, expected_revision=REVISION)

    def test_mixed_source_revisions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_release_evidence(root)
            target_name = SUPPORTED_TARGETS[1]
            path = root / target_name / f"{target_name}-verification.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["source_revision"] = "f" * 40
            _write_json(path, payload)
            with self.assertRaisesRegex(ReleaseGateError, "source_revision"):
                validate_release_inputs(root, expected_revision=REVISION)

    def test_dirty_candidate_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_release_evidence(root)
            target_name = SUPPORTED_TARGETS[2]
            path = root / target_name / f"{target_name}-smoke.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["identity"]["source_dirty"] = True
            _write_json(path, payload)
            with self.assertRaisesRegex(ReleaseGateError, "source_dirty"):
                validate_release_inputs(root, expected_revision=REVISION)

    def test_duplicate_evidence_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_release_evidence(root)
            target_name = SUPPORTED_TARGETS[0]
            source = root / target_name / f"{target_name}-smoke.json"
            duplicate = root / "duplicate"
            duplicate.mkdir()
            (duplicate / source.name).write_bytes(source.read_bytes())
            with self.assertRaisesRegex(ReleaseGateError, "exactly once"):
                validate_release_inputs(root, expected_revision=REVISION)

    def test_cli_writes_consolidated_release_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _create_release_evidence(root)
            output = root / "release-manifest.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "build_support.release_gate",
                    "--artifacts-dir",
                    str(root),
                    "--expected-revision",
                    REVISION,
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            payload = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(result.stderr, "")
        self.assertEqual(payload["status"], "ok")

    def test_target_listing_is_manifest_derived(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "build_support.release_gate", "--print-targets"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.splitlines(), list(SUPPORTED_TARGETS))


class FinalReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.text = FINAL_RELEASE_WORKFLOW.read_text(encoding="utf-8")

    def test_release_workflow_has_only_required_write_permissions(self) -> None:
        self.assertIn("permissions:\n  contents: write\n  actions: read", self.text)

    def test_release_is_bound_to_successful_same_revision_candidate_ci(self) -> None:
        self.assertIn("actions/workflows/smart-cicd.yml/runs", self.text)
        self.assertIn('-f head_sha="$REVISION"', self.text)
        self.assertIn("-f event=push", self.text)
        self.assertIn(".head_sha == $revision", self.text)
        self.assertIn(".conclusion == \"success\"", self.text)
        self.assertIn(".event == \"push\"", self.text)
        self.assertIn(".head_repository.full_name == $repository", self.text)

    def test_all_target_artifacts_are_downloaded_from_manifest_list(self) -> None:
        self.assertIn("build_support.release_gate --print-targets", self.text)
        self.assertIn('download_args+=(--name "$target")', self.text)
        self.assertIn('gh run download "$RUN_ID"', self.text)

    def test_release_gate_runs_before_publication(self) -> None:
        gate = self.text.index("Require complete verified same-revision artifacts")
        publish = self.text.index("Publish verified release assets")
        self.assertLess(gate, publish)
        self.assertIn("--expected-revision \"$REVISION\"", self.text)
        self.assertIn("--expected-tag \"$RELEASE_TAG\"", self.text)

    def test_legacy_unverified_release_fallback_is_removed(self) -> None:
        self.assertNotIn("Find existing pre-release", self.text)
        self.assertNotIn("Promote pre-release", self.text)
        self.assertNotIn("No pre-release found", self.text)
        self.assertNotIn("macOS (Universal", self.text)

    def test_existing_release_is_never_silently_replaced(self) -> None:
        self.assertIn("Refuse to replace an existing release", self.text)
        self.assertIn('gh release view "$RELEASE_TAG"', self.text)

    def test_current_action_majors_are_explicit(self) -> None:
        self.assertIn("actions/checkout@v6", self.text)
        self.assertIn("actions/setup-python@v7", self.text)


if __name__ == "__main__":
    unittest.main()
