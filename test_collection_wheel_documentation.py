"""Documentation contracts for native and managed Collection Wheel modes."""

from __future__ import annotations

import unittest
from pathlib import Path


class CollectionWheelDocumentationTest(unittest.TestCase):
    def setUp(self):
        self.guide_path = Path("docs/COLLECTION_WHEEL.md")
        self.browser_guide_path = Path(
            "docs/WHEEL_BROWSER_RUNTIME.md"
        )
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
            "Browser Wheel is stopped",
            "five turns, 61 frames",
            "approximately 1.68 seconds",
            "managed Browser Wheel is running",
            "shared presentation schedule",
            "5.5 seconds, nine turns",
            "one weighted landing offset",
            "both renderers use that exact offset",
            "presentation-synchronized",
            "not guaranteed to match on every rendered frame",
            "Collection result focus",
        ):
            self.assertIn(required, guide)

    def test_guide_documents_managed_browser_workflow(self):
        guide = self._normalized(self.guide_path)
        for required in (
            "Browser / OBS Wheel",
            "Start Browser Wheel",
            "exact current filtered pool",
            "Copy OBS URL",
            "Spin Again publishes the exact reroll pool",
            "Python selects the winner once",
            "one weighted landing offset for both renderers",
            "native Wheel uses the same 5.5-second schedule",
            "same position inside the winner segment",
            "browser receives and animates that predetermined winner",
            "Closing the Collection Wheel dialog stops",
            "Preview and OBS overlay modes",
            "/wheel/?mode=overlay",
            "fully hidden while idle",
            "eight seconds",
            "5.5 seconds total",
            "nine full turns",
            "one continuous frame-driven motion curve",
            "continuous deceleration over the final 73%",
            "nine weighted bands",
            "each receive 47%",
            "center receives 6%",
            "0.025 to 0.055",
            "0.945 to 0.975",
            "flip by 180 degrees",
            "complete title",
            "responsive size tiers",
            "Spark count, angle, distance, delay, hue, and scale",
            "immutable Python-authored spin identity",
            "cannot influence filtering or winner selection",
            "Browser / OBS Wheel guide",
        ):
            self.assertIn(required, guide)

    def test_guide_documents_ratings_and_safety(self):
        guide = self._normalized(self.guide_path)
        for required in (
            "Personal Rating",
            "SMWC Rating",
            "Fetch Missing Metadata",
            "Wheel operations remain read-only",
            "Spin results are not persisted",
            "Planner entries and lists are not modified",
            "Candidate snapshots are detached",
            "Local ROM paths",
            "Browser clients cannot select a winner",
        ):
            self.assertIn(required, guide)

    def test_guide_distinguishes_current_and_future_runtime_scope(self):
        guide = self._normalized(self.guide_path)
        for required in (
            "Two renderers are available",
            "managed HTML/CSS/JavaScript Browser / OBS Wheel",
            "loopback-only",
            "application must remain open",
            "Standalone or tray-hosted Wheel service",
            "Streamer.bot command triggers",
            "LAN or remote-network exposure",
            "Python remains the source of truth",
        ):
            self.assertIn(required, guide)

        for stale in (
            "planned as a separate browser-runtime stage",
            "are not part of the native Wheel feature",
            "browser overlay and API runtime remain future work",
        ):
            self.assertNotIn(stale, guide)

    def test_readme_links_both_guides(self):
        readme = self.readme_path.read_text(encoding="utf-8")
        self.assertIn(
            "[Collection Wheel guide](docs/COLLECTION_WHEEL.md)",
            readme,
        )
        self.assertIn(
            "[Browser / OBS Wheel guide]"
            "(docs/WHEEL_BROWSER_RUNTIME.md)",
            readme,
        )

    def test_changelog_records_native_and_browser_scope(self):
        changelog = self.changelog_path.read_text(encoding="utf-8")

        native_start = "<!-- collection-wheel:start -->"
        native_end = "<!-- collection-wheel:end -->"
        self.assertEqual(changelog.count(native_start), 1)
        self.assertEqual(changelog.count(native_end), 1)
        native = " ".join(
            changelog
            .split(native_start, 1)[1]
            .split(native_end, 1)[0]
            .split()
        )
        for required in (
            "Collection Wheel",
            "independent Collection filters",
            "optional Planner refinements",
            "animated circular Wheel",
            "SMWC Rating",
            "read-only",
        ):
            self.assertIn(required, native)
        self.assertNotIn(
            "browser overlay and API runtime remain future work",
            native,
        )

        browser_start = "<!-- wheel-browser-runtime:start -->"
        browser_end = "<!-- wheel-browser-runtime:end -->"
        self.assertEqual(changelog.count(browser_start), 1)
        self.assertEqual(changelog.count(browser_end), 1)
        browser = " ".join(
            changelog
            .split(browser_start, 1)[1]
            .split(browser_end, 1)[0]
            .split()
        )
        for required in (
            "Browser / OBS Wheel",
            "loopback-only",
            "exact filtered and reroll pools",
            "Python-authored predetermined winner",
            "read-only health, snapshot, and spin-state API",
            "self-contained browser renderer",
            "5.5-second",
            "nine weighted landing bands",
            "eight-second result hold",
            "spin-seeded celebration variation",
            "Synchronized the native Wheel",
            "quick five-turn, 61-frame native-only animation",
        ):
            self.assertIn(required, browser)

    def test_documentation_files_are_utf8_with_final_newlines(self):
        for path in (
            self.guide_path,
            self.browser_guide_path,
            self.readme_path,
            self.changelog_path,
        ):
            data = path.read_bytes()
            data.decode("utf-8")
            self.assertTrue(data.endswith(b"\n"), path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
