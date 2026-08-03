"""Documentation contract for the native Collection Wheel."""

from __future__ import annotations

import unittest
from pathlib import Path


class CollectionWheelDocumentationTest(unittest.TestCase):
    def setUp(self):
        self.guide_path = Path("docs/COLLECTION_WHEEL.md")
        self.readme_path = Path("README.md")
        self.changelog_path = Path("CHANGELOG.md")

    @staticmethod
    def _normalized(path):
        return " ".join(path.read_text(encoding="utf-8").split())

    def test_guide_documents_native_workflow(self):
        guide = self._normalized(self.guide_path)
        for required in (
            "Collection → Open Wheel",
            "complete Collection",
            "Search",
            "Completion",
            "Type",
            "Difficulty",
            "Download status",
            "SMWC rating",
            "Released from",
            "Released through",
            "Optional Planner refinements",
            "Lifecycle",
            "Planning horizon",
            "Custom list",
            "Spin Wheel",
            "Spin Again",
            "equal chance",
            "selected segment beneath the pointer",
            "Collection result focus",
        ):
            self.assertIn(required, guide)

    def test_guide_documents_ratings_and_safety(self):
        guide = self._normalized(self.guide_path)
        for required in (
            "Personal Rating",
            "SMWC Rating",
            "Fetch Missing Metadata",
            "Wheel operations are read-only",
            "Spin results are not persisted",
            "Planner entries and lists are not modified",
            "Candidate snapshots are detached",
        ):
            self.assertIn(required, guide)

    def test_guide_marks_browser_runtime_as_future_work(self):
        guide = self._normalized(self.guide_path)
        for required in (
            "planned as a separate browser-runtime stage",
            "are not part of the native Wheel feature",
            "OBS browser-source overlay",
            "Local HTTP or WebSocket API",
            "Standalone or tray-hosted Wheel service",
            "Python remains the source of truth",
        ):
            self.assertIn(required, guide)

    def test_readme_links_guide(self):
        readme = self.readme_path.read_text(encoding="utf-8")
        self.assertIn(
            "[Collection Wheel guide](docs/COLLECTION_WHEEL.md)",
            readme,
        )

    def test_changelog_records_native_scope(self):
        changelog = self.changelog_path.read_text(encoding="utf-8")
        start = "<!-- collection-wheel:start -->"
        end = "<!-- collection-wheel:end -->"
        self.assertEqual(changelog.count(start), 1)
        self.assertEqual(changelog.count(end), 1)

        block = " ".join(
            changelog.split(start, 1)[1].split(end, 1)[0].split()
        )
        for required in (
            "Collection Wheel",
            "independent Collection filters",
            "optional Planner refinements",
            "animated circular Wheel",
            "SMWC Rating",
            "read-only",
            "browser overlay and API runtime remain future work",
        ):
            self.assertIn(required, block)

    def test_documentation_files_are_utf8_with_final_newlines(self):
        for path in (
            self.guide_path,
            self.readme_path,
            self.changelog_path,
        ):
            data = path.read_bytes()
            data.decode("utf-8")
            self.assertTrue(data.endswith(b"\n"), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
