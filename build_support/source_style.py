"""Deterministic formatting checks for the build-foundation Python surface."""
from __future__ import annotations

import argparse
from pathlib import Path

from build_support.manifest import ROOT

DEFAULT_PATHS = (
    "product_identity.py",
    "package_metadata.py",
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
)


def _python_files(relative: str) -> list[Path]:
    path = ROOT / relative
    if path.is_dir():
        return sorted(
            item for item in path.rglob("*.py") if "__pycache__" not in item.parts
        )
    return [path]


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def validate_style(paths: tuple[str, ...] = DEFAULT_PATHS) -> list[Path]:
    """Validate UTF-8, final newlines, tabs, and trailing whitespace."""

    checked: list[Path] = []
    errors: list[str] = []
    for relative in paths:
        for path in _python_files(relative):
            if not path.exists():
                errors.append(f"Missing style-check input: {path}")
                continue
            checked.append(path)
            raw = path.read_bytes()
            if not raw.endswith(b"\n"):
                errors.append(f"{_display_path(path)}: missing final newline")
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as exc:
                errors.append(f"{_display_path(path)}: not UTF-8 ({exc})")
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if line.endswith((" ", "\t")):
                    errors.append(
                        f"{_display_path(path)}:{line_number}: trailing whitespace"
                    )
                if "\t" in line:
                    errors.append(
                        f"{_display_path(path)}:{line_number}: tab character"
                    )
    if errors:
        raise RuntimeError("Formatting contract failed:\n" + "\n".join(errors))
    return checked


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)
    selected = tuple(args.paths) if args.paths else DEFAULT_PATHS
    checked = validate_style(selected)
    print(f"Formatting contract OK: {len(checked)} Python files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
