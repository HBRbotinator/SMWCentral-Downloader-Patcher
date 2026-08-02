"""Regression tests for Collection Personal and SMWC rating presentation."""

from __future__ import annotations

import unittest
from pathlib import Path

from collection_rating import (
    format_smwc_rating,
    migrate_smwc_rating_column,
    smwc_rating_sort_value,
)


class CollectionRatingDisplayTest(unittest.TestCase):
    def test_smwc_rating_formats_numeric_values_without_fake_precision(self):
        self.assertEqual(format_smwc_rating(4), "4 / 5")
        self.assertEqual(format_smwc_rating("4.5"), "4.5 / 5")
        self.assertEqual(format_smwc_rating(4.25), "4.25 / 5")
        self.assertEqual(format_smwc_rating(5), "5 / 5")

    def test_missing_zero_non_numeric_and_out_of_range_are_unrated(self):
        for value in (None, "", "N/A", 0, "0", -1, 5.1, True):
            with self.subTest(value=value):
                self.assertEqual(format_smwc_rating(value), "Unrated")
                self.assertEqual(smwc_rating_sort_value(value), 0.0)

    def test_smwc_rating_sort_uses_numeric_community_value(self):
        values = ["4.5", 0, "3.25", None, 5]
        values.sort(key=smwc_rating_sort_value)
        self.assertEqual(values, [0, None, "3.25", "4.5", 5])

    def test_existing_column_configuration_shows_new_column_once(self):
        visible, order, migrated = migrate_smwc_rating_column(
            ["completed", "title", "rating", "notes"],
            ["completed", "title", "rating", "notes"],
        )

        self.assertTrue(migrated)
        self.assertEqual(
            visible,
            ["completed", "title", "rating", "smwc_rating", "notes"],
        )
        self.assertEqual(
            order,
            ["completed", "title", "rating", "smwc_rating", "notes"],
        )

    def test_user_can_hide_migrated_smwc_column_later(self):
        visible, order, migrated = migrate_smwc_rating_column(
            ["completed", "title", "rating", "notes"],
            ["completed", "title", "rating", "smwc_rating", "notes"],
        )

        self.assertFalse(migrated)
        self.assertNotIn("smwc_rating", visible)
        self.assertIn("smwc_rating", order)

    def test_fresh_configuration_uses_page_defaults_without_migration(self):
        visible, order, migrated = migrate_smwc_rating_column(
            ["completed", "title", "rating", "smwc_rating"],
            None,
        )

        self.assertFalse(migrated)
        self.assertIsNone(order)
        self.assertIn("smwc_rating", visible)

    def test_legacy_visibility_without_saved_order_is_migrated_once(self):
        visible, order, migrated = migrate_smwc_rating_column(
            ["completed", "title", "rating"],
            None,
        )

        self.assertTrue(migrated)
        self.assertIsNone(order)
        self.assertEqual(
            visible,
            ["completed", "title", "rating", "smwc_rating"],
        )

    def test_collection_page_displays_and_sorts_both_rating_types(self):
        source = Path("ui/pages/collection_page.py").read_text(
            encoding="utf-8"
        )
        manager_source = Path("hack_data_manager.py").read_text(
            encoding="utf-8"
        )

        for required in (
            '"id": "rating", "header": "Personal Rating"',
            '"id": "smwc_rating", "header": "SMWC Rating"',
            '"smwc_rating": smwc_rating_display',
            'format_smwc_rating(hack.get("rating", 0))',
            'self.sort_column == "smwc_rating"',
            'smwc_rating_sort_value(hack.get("rating", 0))',
            '"Personal Rating: "',
            '"SMWC Rating: "',
        ):
            self.assertIn(required, source)

        self.assertIn(
            '"rating": hack_data.get("rating", 0)',
            manager_source,
        )

    def test_personal_rating_controls_are_named_explicitly(self):
        source = Path("ui/components/table_filters.py").read_text(
            encoding="utf-8"
        )

        self.assertEqual(source.count('text="Personal Rating:"'), 2)
        self.assertNotIn('text="Rating:"', source)
        self.assertIn('hack.get("personal_rating", 0)', source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
