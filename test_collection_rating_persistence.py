"""Regression coverage for canonical SMWC community-rating persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collection_rating import (
    repair_processed_smwc_rating_file,
    repair_processed_smwc_ratings,
)


class CollectionRatingPersistenceTest(unittest.TestCase):
    def test_repairs_accidental_numeric_rating_field(self):
        data = {
            "123": {"title": "Hack", "smwc_rating": "4.75"},
        }

        repaired = repair_processed_smwc_ratings(data)

        self.assertEqual(repaired, 1)
        self.assertEqual(data["123"]["rating"], 4.75)
        self.assertNotIn("smwc_rating", data["123"])

    def test_valid_canonical_rating_wins_over_accidental_field(self):
        data = {
            "123": {"rating": 4.25, "smwc_rating": 4.9},
        }

        repaired = repair_processed_smwc_ratings(data)

        self.assertEqual(repaired, 1)
        self.assertEqual(data["123"]["rating"], 4.25)
        self.assertNotIn("smwc_rating", data["123"])

    def test_unrated_canonical_value_can_be_repaired_from_valid_legacy_value(self):
        data = {
            "123": {"rating": 0, "smwc_rating": 3.5},
        }

        repair_processed_smwc_ratings(data)

        self.assertEqual(data["123"]["rating"], 3.5)

    def test_local_records_are_not_given_provider_ratings(self):
        data = {
            "usr_aaaaaaaaaaaaaaaa": {"smwc_rating": 4.5},
        }

        repaired = repair_processed_smwc_ratings(data)

        self.assertEqual(repaired, 0)
        self.assertEqual(data["usr_aaaaaaaaaaaaaaaa"]["smwc_rating"], 4.5)
        self.assertNotIn("rating", data["usr_aaaaaaaaaaaaaaaa"])

    def test_file_repair_publishes_canonical_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "processed.json"
            path.write_text(
                json.dumps({"123": {"smwc_rating": 4.5}}),
                encoding="utf-8",
            )

            repaired = repair_processed_smwc_rating_file(path)

            self.assertEqual(repaired, 1)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["123"]["rating"], 4.5)
            self.assertNotIn("smwc_rating", data["123"])
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_hack_data_manager_canonicalizes_before_collection_ui_reads(self):
        source = Path("hack_data_manager.py").read_text(encoding="utf-8")

        self.assertIn("repair_processed_smwc_ratings(data)", source)

    def test_startup_quick_migration_persists_rating_repair(self):
        source = Path("main.py").read_text(encoding="utf-8")

        self.assertIn(
            "from collection_rating import repair_processed_smwc_rating_file",
            source,
        )
        self.assertIn(
            "repaired_smwc_ratings = repair_processed_smwc_rating_file(",
            source,
        )
        repair_position = source.index(
            "repaired_smwc_ratings = repair_processed_smwc_rating_file("
        )
        ui_position = source.index("download_button = setup_ui(")
        self.assertLess(repair_position, ui_position)
        self.assertIn("PROCESSED_JSON_PATH", source[repair_position:ui_position])


if __name__ == "__main__":
    unittest.main(verbosity=2)
