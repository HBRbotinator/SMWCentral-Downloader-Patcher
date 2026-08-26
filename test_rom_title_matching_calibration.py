"""Calibration regressions derived from a real existing ROM library."""
from __future__ import annotations

import unittest

from rom_title_matching import CatalogueMatcher


CALIBRATION_CATALOGUE = [
    {"id": 28543, "name": "The New Comfort Zone", "difficulty": "Expert"},
    {"id": 21909, "name": "new.sfc", "difficulty": "Intermediate"},
    {"id": 24739, "name": "Sayonara Mario World", "difficulty": "Expert"},
    {"id": 31276, "name": "Sayonara Mario World 2", "difficulty": "Master"},
    {"id": 37976, "name": "A Rose for Emily", "difficulty": "Master"},
    {"id": 35251, "name": "Rose Tinted Glasses", "difficulty": "Intermediate"},
    {"id": 21138, "name": "Under the Rose", "difficulty": "Newcomer"},
    {"id": 32479, "name": "*SUPERSTAR* - an EP by margot", "difficulty": "Master"},
    {"id": 9912, "name": "Luigi's Superstar Search", "difficulty": "Newcomer"},
    {"id": 19369, "name": "Superstar Mario World", "difficulty": "Intermediate"},
    {"id": 28247, "name": "Titan Mario", "difficulty": "Master"},
    {"id": 37767, "name": "Titan Mario 2", "difficulty": "Master"},
    {"id": 42385, "name": "Yoshi's Revenge", "difficulty": "Master"},
    {"id": 19279, "name": "Quickie World 2", "difficulty": "Intermediate"},
    {"id": 18835, "name": "Lil Mallow World", "difficulty": "Intermediate"},
    {"id": 24705, "name": "Little Mario World", "difficulty": "Advanced"},
    {"id": 30107, "name": "Lydian Mario World", "difficulty": "Master"},
    {"id": 18268, "name": "Super Ryu World", "difficulty": "Advanced"},
    {"id": 20717, "name": "Super Ryu World 2", "difficulty": "Expert"},
    {"id": 18529, "name": "Super Run World", "difficulty": "Advanced"},
    {"id": 20906, "name": "Luigi Kaizo King", "difficulty": "Expert"},
    {"id": 27282, "name": "Storks and Apes and Crocodiles", "difficulty": "Master"},
]


class RomTitleMatchingCalibrationTest(unittest.TestCase):
    def setUp(self):
        self.matcher = CatalogueMatcher(CALIBRATION_CATALOGUE)

    def test_real_library_review_cases_keep_expected_submission_on_top(self):
        cases = (
            ("NewComfy1.0", "Expert", 28543),
            ("Sayonara 1.1", "Expert", 24739),
            ("Rose", "Master", 37976),
            ("SUPERSTAR", "Master", 32479),
            ("titan1.1", "Master", 28247),
            ("titan2_1.1", "Master", 37767),
            ("YR", "Master", 42385),
            ("QW2", "Intermediate", 19279),
            ("LMW1.0", "Advanced", 24705),
            ("Super Ryu World 1", "Advanced", 18268),
            ("LKK", "Expert", 20906),
            ("Storks 1.13", "Master", 27282),
        )
        for query, difficulty, expected_id in cases:
            with self.subTest(query=query):
                result = self.matcher.find(query, difficulty_hint=difficulty)
                self.assertFalse(result.auto_selected)
                self.assertIsNotNone(result.suggestion)
                self.assertEqual(expected_id, result.suggestion.smwc_submission_id)

    def test_ambiguous_short_names_do_not_become_threshold_auto_matches(self):
        for query, difficulty in (
            ("Sayonara 1.1", "Expert"),
            ("Rose", "Master"),
            ("SUPERSTAR", "Master"),
            ("titan1.1", "Master"),
            ("LMW1.0", "Advanced"),
        ):
            with self.subTest(query=query):
                result = self.matcher.find(query, difficulty_hint=difficulty)
                self.assertIn(result.classification, {"Ambiguous", "Review"})
                self.assertIsNone(result.selected)

    def test_real_library_abbreviations_still_require_review(self):
        for query, difficulty, expected_id in (
            ("YR", "Master", 42385),
            ("QW2", "Intermediate", 19279),
            ("LKK", "Expert", 20906),
        ):
            with self.subTest(query=query):
                result = self.matcher.find(query, difficulty_hint=difficulty)
                self.assertEqual("Abbreviation - review", result.classification)
                self.assertEqual(expected_id, result.suggestion.smwc_submission_id)
                self.assertIsNone(result.selected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
