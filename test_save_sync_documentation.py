from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class SaveDataSyncDocumentationTest(unittest.TestCase):
    def test_readme_links_durable_guide(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("[SAVE_DATA_SYNC.md](SAVE_DATA_SYNC.md)", readme)
        self.assertIn("Apply Selected", readme)

    def test_guide_documents_safety_and_complete_lifecycle(self):
        guide = (ROOT / "SAVE_DATA_SYNC.md").read_text(encoding="utf-8")
        required = (
            "## Save analysis and confidence",
            "## Manual SMWCentral search",
            "## Saved filename associations",
            "## Local save-backed entries",
            "## Startup and periodic review scans",
            "## Apply Selected safety boundary",
            "## Privacy-safe diagnostics",
            "## Known limitations",
            "Save files are opened read-only and never rewritten",
            "never deletes save or ROM files",
        )
        for text in required:
            with self.subTest(text=text):
                self.assertIn(text, guide)

    def test_changelog_records_expansion_without_auto_apply_claim(self):
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("### Save Data Sync expansion", changelog)
        self.assertRegex(
            changelog,
            r"never apply collection\s+changes automatically",
        )
        self.assertNotIn(
            "Save Data Sync automatically applies collection changes",
            changelog,
        )


if __name__ == "__main__":
    unittest.main()
