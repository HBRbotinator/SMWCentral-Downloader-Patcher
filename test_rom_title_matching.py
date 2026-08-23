"""Regression tests for conservative ROM title matching."""
from __future__ import annotations

import unittest

from rom_title_matching import (
    CatalogueMatcher,
    clean_title_for_match,
    extract_explicit_smwc_submission_ids,
    is_probable_base_rom,
)


CATALOGUE = [
    {"id": 101, "name": "Beautiful Dangerous", "difficulty": "Advanced"},
    {"id": 102, "name": "Sauna Mario World 2", "difficulty": "Expert"},
    {"id": 103, "name": "Akogare 2", "difficulty": "Master"},
    {"id": 104, "name": "ESCAPE FROM LA PLUME", "difficulty": "Advanced"},
    {"id": 105, "name": "Super DGR World", "difficulty": "Intermediate"},
    {"id": 106, "name": "Super Sonic Saves the World World"},
    {"id": 107, "name": "2 Kaizo 2 Learn"},
    {"id": 108, "name": "Ultra Kaizo World"},
    {"id": 109, "name": "Ultra Kaizo World 2"},
    {"id": 110, "name": "A Rose for Emily"},
    {"id": 111, "name": "Rose"},
    {"id": 112, "name": "Backwards Mario World"},
    {
        "id": 41022,
        "name": "Super Dram World 3",
        "difficulty": "Grandmaster",
        "type": "Kaizo",
        "exits": 28,
    },
]


class RomTitleMatchingTest(unittest.TestCase):
    def test_filename_normalisation_preserves_old_useful_cases(self):
        examples = {
            "Beautiful Dangerous v1.1.sfc": "Beautiful Dangerous",
            "SaunaMarioWorld2_1.5.sfc": "Sauna Mario World 2",
            "Akogare2 v1.10.sfc": "Akogare 2",
            "EscapeFromLaPlume.sfc": "Escape From La Plume",
            "SuperDGRWorld.sfc": "Super DGR World",
            "2Kaizo2Learn_1.0.sfc": "2 Kaizo 2 Learn",
            "BackwardsMarioWorld1.11.sfc": "Backwards Mario World",
        }
        for filename, expected in examples.items():
            with self.subTest(filename=filename):
                self.assertEqual(expected, clean_title_for_match(filename))

    def test_explicit_smwc_filename_markers_are_optional_metadata(self):
        self.assertEqual(
            (41022,),
            extract_explicit_smwc_submission_ids(
                "Super Dram World 3 [SMWC-ID-41022].sfc"
            ),
        )
        self.assertEqual(
            (41022,),
            extract_explicit_smwc_submission_ids(
                "Super Dram World 3 [SMWC-41022].sfc"
            ),
        )
        self.assertEqual(
            (),
            extract_explicit_smwc_submission_ids(
                "Super Dram World 3 [41022].sfc"
            ),
        )
        self.assertEqual(
            "Super Dram World 3",
            clean_title_for_match(
                "Super Dram World 3 [SMWC-ID-41022].sfc"
            ),
        )

    def test_clear_filename_matches_remain_auto_selected(self):
        matcher = CatalogueMatcher(CATALOGUE)
        for filename, expected_id in (
            ("Beautiful Dangerous v1.1.sfc", 101),
            ("SaunaMarioWorld2_1.5.sfc", 102),
            ("Akogare2 v1.10.sfc", 103),
            ("EscapeFromLaPlume.sfc", 104),
            ("SuperDGRWorld.sfc", 105),
            ("2Kaizo2Learn_1.0.sfc", 107),
            ("BackwardsMarioWorld1.11.sfc", 112),
        ):
            with self.subTest(filename=filename):
                result = matcher.find(filename)
                self.assertTrue(result.auto_selected)
                self.assertEqual("Exact", result.classification)
                self.assertEqual(expected_id, result.selected.smwc_submission_id)

    def test_abbreviations_are_suggested_but_require_review(self):
        matcher = CatalogueMatcher(
            [
                {"id": 201, "name": "Yoshi's Revenge"},
                {"id": 202, "name": "Quickie World 2"},
                {"id": 203, "name": "Luigi Kaizo King"},
            ]
        )
        for query, expected_id in (("YR", 201), ("QW2", 202), ("LKK", 203)):
            with self.subTest(query=query):
                result = matcher.find(query)
                self.assertFalse(result.auto_selected)
                self.assertEqual("Abbreviation - review", result.classification)
                self.assertEqual(expected_id, result.suggestion.smwc_submission_id)

    def test_edition_and_local_variant_suffixes_keep_strong_matches(self):
        matcher = CatalogueMatcher(
            [
                {"id": 301, "name": "Super Lani World (Remastered)"},
                {"id": 302, "name": "In Absentia of Knowing"},
                {"id": 303, "name": "Learning to Fly"},
                {"id": 304, "name": "Ultra Kaizo World 2"},
                {"id": 305, "name": "Legends of the Hidden Thwimple"},
            ]
        )
        cases = (
            ("Super Lani World", 301),
            ("In Absentia of Knowing (1.0).sfc", 302),
            ("LearningToFly2_0.sfc", 303),
            ("UltraKaizoWorld2_1.2 (Censored).sfc", 304),
            (
                "Legends Of The Hidden Thwimple v1.1 ContentIDSafe.sfc",
                305,
            ),
        )
        for title, expected_id in cases:
            with self.subTest(title=title):
                result = matcher.find(title)
                self.assertTrue(result.auto_selected)
                self.assertEqual(expected_id, result.selected.smwc_submission_id)

    def test_distinctive_token_outranks_generic_fuzzy_titles(self):
        matcher = CatalogueMatcher(
            [
                {"id": 401, "name": "Super Marina World", "difficulty": "Expert"},
                {"id": 402, "name": "Super Salary World", "difficulty": "Expert"},
                {"id": 403, "name": "Samsara Mario World", "difficulty": "Expert"},
            ]
        )
        result = matcher.find("Super Samsara World", difficulty_hint="Expert")
        self.assertTrue(result.auto_selected)
        self.assertEqual(403, result.selected.smwc_submission_id)
        self.assertGreaterEqual(result.confidence, 0.88)

    def test_provisional_catalogue_title_is_review_only(self):
        matcher = CatalogueMatcher(
            [
                {"id": 501, "name": "Tortured Souls 3 DEMO"},
                {"id": 502, "name": "Tortured Souls II Rapture"},
            ]
        )
        result = matcher.find("Tortured Souls 3")
        self.assertFalse(result.auto_selected)
        self.assertEqual(501, result.suggestion.smwc_submission_id)

    def test_duplicate_exact_catalogue_titles_require_review(self):
        matcher = CatalogueMatcher(
            [
                {"id": 200, "name": "Same Name"},
                {"id": 201, "name": "Same Name"},
            ]
        )
        result = matcher.find("Same Name")
        self.assertFalse(result.auto_selected)
        self.assertEqual("Ambiguous", result.classification)
        self.assertIsNone(result.selected)

    def test_sequel_number_conflict_is_not_auto_selected(self):
        matcher = CatalogueMatcher([{"id": 108, "name": "Ultra Kaizo World"}])
        result = matcher.find("Ultra Kaizo World 2")
        self.assertFalse(result.auto_selected)

    def test_short_containment_is_not_false_exact(self):
        matcher = CatalogueMatcher([{"id": 110, "name": "A Rose for Emily"}])
        result = matcher.find("Rose")
        self.assertFalse(result.auto_selected)

    def test_base_rom_is_only_marked_as_probable(self):
        self.assertTrue(is_probable_base_rom("Super Mario World (USA).sfc"))
        self.assertFalse(is_probable_base_rom("Super Mario World Odyssey.sfc"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
