"""Tests for the aggregate matcher calibration developer tool."""
from __future__ import annotations

import unittest

from tools.rom_match_calibration import calibrate_collection


class RomMatchCalibrationToolTest(unittest.TestCase):
    def test_summary_counts_safe_auto_and_review_results_without_paths(self):
        catalogue = {
            "data": [
                {"id": 101, "name": "Beautiful Dangerous", "difficulty": "Advanced"},
                {"id": 201, "name": "Yoshi's Revenge", "difficulty": "Master"},
                {"id": 202, "name": "Your Reality", "difficulty": "Newcomer"},
            ]
        }
        collection = {
            "101": {
                "current_difficulty": "Advanced",
                "file_path": r"D:\Private\Beautiful Dangerous v1.1.sfc",
            },
            "201": {
                "current_difficulty": "Master",
                "files": [
                    {
                        "path": "/Users/private/ROMs/YR.sfc",
                        "primary": True,
                    }
                ],
            },
            "999": {"file_path": "/roms/MissingFromCatalogue.sfc"},
            "usr_deadbeefdeadbeef": {"file_path": "/roms/Local.sfc"},
        }

        summary = calibrate_collection(collection, catalogue)

        self.assertEqual(2, summary.eligible_records)
        self.assertEqual(1, summary.missing_catalogue_records)
        self.assertEqual(1, summary.auto_correct)
        self.assertEqual(0, summary.auto_wrong)
        self.assertEqual(1, summary.review_with_correct_top)
        self.assertEqual(0, summary.top_wrong)
        self.assertEqual(2, summary.top_correct)

    def test_wrong_automatic_match_is_visible_in_summary(self):
        catalogue = {
            "data": [
                {"id": 101, "name": "Correct Hack"},
                {"id": 102, "name": "Wrong Hack"},
            ]
        }
        collection = {"101": {"file_path": "/roms/Wrong Hack.sfc"}}

        summary = calibrate_collection(collection, catalogue)

        self.assertEqual(1, summary.auto_wrong)
        self.assertEqual(1, summary.top_wrong)
        self.assertEqual(0, summary.top_correct)


if __name__ == "__main__":
    unittest.main(verbosity=2)
