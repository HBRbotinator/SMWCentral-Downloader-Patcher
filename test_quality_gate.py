from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_support.quality import (
    QualityGateError,
    QualityStage,
    execute_stages,
    quality_stages,
    run_stage,
)
from build_support.source_style import validate_style
from build_support.validate_manifest import validate_manifest_state


class QualityGateTests(unittest.TestCase):
    def test_required_stage_propagates_nonzero_exit(self):
        stage = QualityStage(
            "intentional failure",
            (sys.executable, "-c", "raise SystemExit(7)"),
        )
        with self.assertRaises(QualityGateError):
            run_stage(stage)

    def test_required_stage_accepts_success(self):
        stage = QualityStage(
            "intentional success",
            (sys.executable, "-c", "raise SystemExit(0)"),
        )
        self.assertEqual(run_stage(stage), 0)

    def test_report_only_stage_does_not_raise(self):
        stage = QualityStage(
            "intentional report",
            (sys.executable, "-c", "raise SystemExit(9)"),
            required=False,
        )
        self.assertEqual(run_stage(stage), 9)

    def test_execute_stages_stops_after_required_failure(self):
        seen: list[str] = []

        def runner(stage: QualityStage) -> int:
            seen.append(stage.name)
            if stage.name == "second":
                raise QualityGateError("stop")
            return 0

        stages = (
            QualityStage("first", ("first",)),
            QualityStage("second", ("second",)),
            QualityStage("third", ("third",)),
        )
        with self.assertRaises(QualityGateError):
            execute_stages(stages, runner=runner)
        self.assertEqual(seen, ["first", "second"])

    def test_default_plan_contains_static_security_and_build_stages(self):
        stages = quality_stages(
            target="windows-x86_64",
            skip_build=False,
            skip_static=False,
            skip_security=False,
        )
        names = [stage.name for stage in stages]
        self.assertIn("Ruff lint", names)
        self.assertIn("Mypy contract checks", names)
        self.assertIn("Dependency vulnerability scan", names)
        self.assertEqual(names[-1], "Candidate build, smoke, and verification")
        self.assertEqual(stages[-1].command[-1], "windows-x86_64")

    def test_skip_flags_remove_optional_stage_groups(self):
        stages = quality_stages(
            target=None,
            skip_build=True,
            skip_static=True,
            skip_security=True,
        )
        names = [stage.name for stage in stages]
        self.assertEqual(
            names,
            [
                "Manifest and generated metadata",
                "Unit and integration tests with coverage",
                "Coverage report",
                "Full source byte-compilation",
            ],
        )

    def test_security_stages_are_report_only(self):
        stages = quality_stages(
            target=None,
            skip_build=True,
            skip_static=True,
            skip_security=False,
        )
        security = stages[-3:]
        self.assertEqual(len(security), 3)
        self.assertTrue(all(not stage.required for stage in security))

    def test_manifest_validation_reports_all_native_targets(self):
        result = validate_manifest_state()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["version"], "5.1.0-dev.1")
        self.assertEqual(len(result["targets"]), 4)

    def test_manifest_validation_cli_emits_json(self):
        result = subprocess.run(
            [sys.executable, "-m", "build_support.validate_manifest", "--json"],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["product_id"], "smwc-downloader")

    def test_quality_dependencies_are_exactly_constrained(self):
        expected = {
            "coverage": "7.15.2",
            "ruff": "0.15.22",
            "mypy": "2.3.0",
            "bandit": "1.9.4",
            "pip-audit": "2.10.1",
            "detect-secrets": "1.5.0",
        }
        requirements = {}
        for raw in Path("requirements-quality.txt").read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            name, version = line.split("==", 1)
            requirements[name] = version
        self.assertEqual(requirements, expected)

    def test_quality_requirements_end_with_newline(self):
        self.assertTrue(Path("requirements-quality.txt").read_bytes().endswith(b"\n"))

    def test_source_style_rejects_trailing_whitespace(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad.py"
            path.write_text("value = 1  \n", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                validate_style((str(path),))


if __name__ == "__main__":
    unittest.main()
