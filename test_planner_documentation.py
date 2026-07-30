"""Documentation contract for the Planner foundation."""

from pathlib import Path
import unittest


class PlannerDocumentationTest(unittest.TestCase):
    """Keep user-facing Planner guidance aligned with the implemented model."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parent
        cls.guide = (cls.root / "PLANNER.md").read_text(encoding="utf-8")
        cls.readme = (cls.root / "README.md").read_text(encoding="utf-8")
        cls.changelog = (cls.root / "CHANGELOG.md").read_text(
            encoding="utf-8"
        )

    def test_readme_links_durable_planner_guide(self):
        self.assertIn("[PLANNER.md](PLANNER.md)", self.readme)
        self.assertIn("<!-- planner-guide:start -->", self.readme)
        self.assertIn("Someday / Soon / Next", self.readme)
        self.assertIn("Save Changes", self.readme)

    def test_guide_documents_complete_planner_contract(self):
        for status in (
            "Planned",
            "Playing",
            "Paused",
            "Beaten",
            "Completed",
            "Dropped",
            "Archived",
        ):
            self.assertIn(f"**{status}**", self.guide)

        for required in (
            "**Someday**",
            "**Soon**",
            "**Next**",
            "Move Next Up",
            "Move Next Down",
            "stable internal ID",
            "Unsaved Planner changes",
            "Save Changes",
            "Discard Changes",
            "planner_state.json",
            "processed.json",
            "atomic replacement",
            "legacy collection record",
            "explicit Planner lifecycle status",
            "does not yet add a Wheel interface",
            "wheel_enabled",
            "wheel_eligible",
            "fixed priority field",
        ):
            self.assertIn(required, self.guide)

    def test_guide_documents_filter_and_safety_boundaries(self):
        for required in (
            "lifecycle status",
            "planning horizon",
            "custom list",
            "downloaded state",
            "difficulty and hack-type filters",
            "Opening the Planner does not create or rewrite",
            "Planner edits do not modify `processed.json`",
            "written only through **Save Changes**",
            "preserves that inferred Completed",
        ):
            self.assertIn(required, self.guide)

    def test_changelog_records_foundation_without_shipping_wheel(self):
        self.assertIn("<!-- planner-foundation:start -->", self.changelog)
        self.assertIn("### Planner foundation", self.changelog)
        self.assertIn("separate versioned `planner_state.json`", self.changelog)
        self.assertIn("future filter-driven Wheel pool", self.changelog)
        self.assertNotIn("Added a Wheel interface", self.changelog)

    def test_documentation_files_are_utf8_with_final_newlines(self):
        for name in (
            "PLANNER.md",
            "README.md",
            "CHANGELOG.md",
            "test_planner_documentation.py",
        ):
            data = (self.root / name).read_bytes()
            data.decode("utf-8")
            self.assertTrue(data.endswith(b"\n"), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
