"""Fail-fast cross-platform quality and native-candidate command."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from build_support.manifest import ROOT, SUPPORTED_TARGETS, auto_target
from product_identity import ProductManifestError


class QualityGateError(RuntimeError):
    """Raised as soon as a required quality stage fails."""


@dataclass(frozen=True)
class QualityStage:
    """One ordered quality command and whether it blocks the gate."""

    name: str
    command: tuple[str, ...]
    required: bool = True


_STATIC_SCOPE = (
    "product_identity.py",
    "package_metadata.py",
    "update_policy.py",
    "build_support",
    "test_product_identity.py",
    "test_runtime_identity.py",
    "test_package_metadata.py",
    "test_build_configuration.py",
    "test_candidate_verification.py",
    "test_dependency_constraints.py",
    "test_quality_gate.py",
    "test_ci_workflow.py",
    "test_release_gate.py",
    "test_update_policy.py",
)


def _compile_command() -> tuple[str, ...]:
    excluded = r"(^|/)(\.git|\.venv|build|dist|artifacts|__pycache__)(/|$)"
    return (
        sys.executable,
        "-m",
        "compileall",
        "-q",
        "-x",
        excluded,
        ".",
    )



def _test_modules() -> tuple[str, ...]:
    modules = tuple(path.name for path in sorted(ROOT.glob("test_*.py")))
    if not modules:
        raise QualityGateError("No test_*.py modules were found in the repository root")
    return modules


def quality_stages(
    *,
    target: str | None,
    skip_build: bool,
    skip_static: bool,
    skip_security: bool,
) -> tuple[QualityStage, ...]:
    """Build the deterministic stage plan used locally and by CI."""

    stages = [
        QualityStage(
            "Manifest and generated metadata",
            (sys.executable, "-m", "build_support.validate_manifest", "--json"),
        ),
        QualityStage(
            "Unit and integration tests with coverage",
            (
                sys.executable,
                "-m",
                "coverage",
                "run",
                "--branch",
                "--source=.",
                "-m",
                "unittest",
                "-v",
                *_test_modules(),
            ),
        ),
        QualityStage(
            "Coverage report",
            (
                sys.executable,
                "-m",
                "coverage",
                "report",
                "--show-missing",
                "--fail-under=0",
            ),
        ),
        QualityStage("Full source byte-compilation", _compile_command()),
    ]

    if not skip_static:
        stages.extend(
            (
                QualityStage(
                    "Formatting contract",
                    (sys.executable, "-m", "build_support.source_style"),
                ),
                QualityStage(
                    "Ruff lint",
                    (sys.executable, "-m", "ruff", "check", *_STATIC_SCOPE),
                ),
                QualityStage(
                    "Mypy contract checks",
                    (
                        sys.executable,
                        "-m",
                        "mypy",
                        "--ignore-missing-imports",
                        "--check-untyped-defs",
                        "product_identity.py",
                        "package_metadata.py",
                        "update_policy.py",
                        "build_support",
                    ),
                ),
            )
        )

    if not skip_security:
        stages.extend(
            (
                QualityStage(
                    "Bandit static-security scan",
                    (
                        sys.executable,
                        "-m",
                        "bandit",
                        "-q",
                        "-r",
                        ".",
                        "-x",
                        ".venv,build,dist,artifacts",
                    ),
                    required=False,
                ),
                QualityStage(
                    "Dependency vulnerability scan",
                    (
                        sys.executable,
                        "-m",
                        "pip_audit",
                        "-r",
                        "requirements.txt",
                        "-r",
                        "requirements-build.txt",
                        "-r",
                        "requirements-quality.txt",
                    ),
                    required=False,
                ),
                QualityStage(
                    "Secret scan",
                    (
                        sys.executable,
                        "-m",
                        "detect_secrets",
                        "scan",
                        "--all-files",
                        "--exclude-files",
                        r"(^|/)(\.git|\.venv|build|dist|artifacts)/",
                        ".",
                    ),
                    required=False,
                ),
            )
        )

    if not skip_build:
        selected = target or auto_target()
        stages.append(
            QualityStage(
                "Candidate build, smoke, and verification",
                (
                    sys.executable,
                    "-m",
                    "build_support.build_candidate",
                    "--target",
                    selected,
                ),
            )
        )
    return tuple(stages)


def run_stage(
    stage: QualityStage,
    *,
    env: Mapping[str, str] | None = None,
) -> int:
    """Run one stage, raising immediately when a required stage fails."""

    suffix = "" if stage.required else " (report-only)"
    print(f"\n=== {stage.name}{suffix} ===", flush=True)
    print("+ " + " ".join(stage.command), flush=True)
    result = subprocess.run(
        list(stage.command),
        cwd=ROOT,
        env=dict(env) if env is not None else None,
        check=False,
    )
    if result.returncode and stage.required:
        raise QualityGateError(
            f"{stage.name} failed with exit code {result.returncode}"
        )
    if result.returncode:
        print(f"REPORT-ONLY FINDINGS/ERROR: exit code {result.returncode}")
    return result.returncode


def execute_stages(
    stages: Sequence[QualityStage],
    *,
    runner: Callable[[QualityStage], int] = run_stage,
) -> None:
    """Execute stages in order; required failures stop later stages."""

    for stage in stages:
        runner(stage)


def _render_stage_plan(stages: Sequence[QualityStage]) -> None:
    for index, stage in enumerate(stages, start=1):
        policy = "required" if stage.required else "report-only"
        print(f"{index:02d}. [{policy}] {stage.name}")
        print("    " + " ".join(stage.command))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=SUPPORTED_TARGETS)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-static", action="store_true")
    parser.add_argument("--skip-security", action="store_true")
    parser.add_argument("--list-stages", action="store_true")
    args = parser.parse_args(argv)

    try:
        stages = quality_stages(
            target=args.target,
            skip_build=args.skip_build,
            skip_static=args.skip_static,
            skip_security=args.skip_security,
        )
        if args.list_stages:
            _render_stage_plan(stages)
            return 0
        environment = os.environ.copy()
        execute_stages(stages, runner=lambda stage: run_stage(stage, env=environment))
    except (ProductManifestError, QualityGateError, RuntimeError) as exc:
        print(f"\nQUALITY GATE FAILED: {exc}", file=sys.stderr)
        return 1

    print("\nQUALITY GATE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
