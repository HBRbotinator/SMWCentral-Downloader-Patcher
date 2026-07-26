"""Regression tests for the reviewed runtime and build dependency baseline."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
_REQUIREMENT_PATTERN = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^;\s]+)"
    r"(?:;\s*(?P<marker>.+))?$"
)


def _normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _read_requirements(filename: str) -> list[tuple[str, str, str | None]]:
    result: list[tuple[str, str, str | None]] = []
    for line_number, raw_line in enumerate(
        (ROOT / filename).read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _REQUIREMENT_PATTERN.fullmatch(line)
        if match is None:
            raise AssertionError(f"{filename}:{line_number} is not an exact requirement: {line!r}")
        result.append((
            _normalized_name(match.group("name")),
            match.group("version"),
            match.group("marker"),
        ))
    return result


class DependencyConstraintTests(unittest.TestCase):
    def test_runtime_requirements_are_exactly_constrained(self) -> None:
        requirements = _read_requirements("requirements.txt")
        self.assertEqual(len(requirements), 10)
        self.assertEqual(len({name for name, _, _ in requirements}), len(requirements))

    def test_runtime_dependency_versions_match_reviewed_baseline(self) -> None:
        actual = {name: version for name, version, _ in _read_requirements("requirements.txt")}
        self.assertEqual(
            actual,
            {
                "requests": "2.34.2",
                "patch": "1.16",
                "pywinstyles": "1.8",
                "sv-ttk": "2.6.1",
                "pillow": "12.3.0",
                "ips-util": "1.0",
                "python-bps": "5",
                "packaging": "26.2",
                "customtkinter": "5.2.2",
                "websockets": "12.0",
            },
        )

    def test_windows_only_runtime_dependency_has_an_exact_marker(self) -> None:
        markers = {name: marker for name, _, marker in _read_requirements("requirements.txt")}
        self.assertEqual(markers["pywinstyles"], 'sys_platform == "win32"')
        self.assertTrue(all(marker is None for name, marker in markers.items() if name != "pywinstyles"))

    def test_build_requirements_are_separate_and_exactly_constrained(self) -> None:
        self.assertEqual(
            _read_requirements("requirements-build.txt"),
            [
                ("pyinstaller", "6.21.0", None),
                ("pefile", "2024.8.26", 'sys_platform == "win32"'),
            ],
        )

    def test_runtime_and_build_direct_dependencies_do_not_overlap(self) -> None:
        runtime = {name for name, _, _ in _read_requirements("requirements.txt")}
        build = {name for name, _, _ in _read_requirements("requirements-build.txt")}
        self.assertFalse(runtime & build)

    def test_import_name_mappings_are_documented_by_the_expected_packages(self) -> None:
        runtime = {name for name, _, _ in _read_requirements("requirements.txt")}
        self.assertIn("sv-ttk", runtime)      # import sv_ttk
        self.assertIn("ips-util", runtime)    # import ips_util
        self.assertIn("python-bps", runtime)  # import bps
        self.assertIn("pillow", runtime)      # import PIL

    def test_existing_compatibility_holds_are_explicit(self) -> None:
        runtime = {name: version for name, version, _ in _read_requirements("requirements.txt")}
        self.assertEqual(runtime["customtkinter"], "5.2.2")
        self.assertEqual(runtime["websockets"], "12.0")

    def test_requirement_files_end_with_newlines(self) -> None:
        for filename in ("requirements.txt", "requirements-build.txt"):
            self.assertTrue((ROOT / filename).read_bytes().endswith(b"\n"), filename)


if __name__ == "__main__":
    unittest.main()
