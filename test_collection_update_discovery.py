import unittest

from collection_update_discovery import (
    CollectionUpdateDiscoveryError,
    build_collection_update_discovery,
    search_collection_update_catalogue,
    select_possible_collection_replacement,
)
from kaizoff_provider import KaizOffIndexSnapshot
from rom_title_matching import CatalogueEntry


class CollectionUpdateDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = KaizOffIndexSnapshot(
            entries=(
                CatalogueEntry(
                    41022,
                    "Super Dram World 3",
                    difficulty="Grandmaster",
                    hack_type="Kaizo",
                    exits=28,
                ),
                CatalogueEntry(
                    43123,
                    "Super Dram World 3",
                    difficulty="Grandmaster",
                    hack_type="Kaizo",
                    exits=28,
                ),
                CatalogueEntry(
                    41021,
                    "Super Dram World 2",
                    difficulty="Grandmaster",
                    hack_type="Kaizo",
                    exits=19,
                ),
                CatalogueEntry(
                    50000,
                    "A Completely Different Hack",
                    difficulty="Casual",
                    hack_type="Standard",
                    exits=8,
                ),
            ),
            fetched_at=1234.5,
            source="network",
            stale=False,
        )
        self.record = {
            "title": "Super Dram World 3",
            "current_difficulty": "Grandmaster",
            "hack_types": ["Kaizo"],
            "exits": 28,
            "authors": ["PangaeaPanga"],
        }

    def test_numeric_collection_identity_is_required(self):
        with self.assertRaises(CollectionUpdateDiscoveryError):
            build_collection_update_discovery(
                "usr_1234567890abcdef",
                self.record,
                self.snapshot,
            )

    def test_current_submission_is_never_suggested_as_its_own_replacement(self):
        discovery = build_collection_update_discovery(
            "41022",
            self.record,
            self.snapshot,
        )
        ids = [item.entry.smwc_submission_id for item in discovery.suggestions]
        self.assertNotIn(41022, ids)
        self.assertIn(43123, ids)

    def test_suggestions_are_related_rows_not_automatic_lineage(self):
        discovery = build_collection_update_discovery(
            41022,
            self.record,
            self.snapshot,
        )
        same_title = next(
            item for item in discovery.suggestions if item.entry.smwc_submission_id == 43123
        )
        self.assertEqual(same_title.title_score, 1.0)
        self.assertIn("Same normalized title", same_title.reasons)
        self.assertIn("Same difficulty", same_title.reasons)
        self.assertIn("Same type", same_title.reasons)
        self.assertIn("Same exit count", same_title.reasons)

    def test_generic_metadata_does_not_manufacture_related_suggestions(self):
        discovery = build_collection_update_discovery(
            41022,
            self.record,
            self.snapshot,
        )
        suggested_ids = {item.entry.smwc_submission_id for item in discovery.suggestions}
        self.assertNotIn(50000, suggested_ids)

    def test_existing_target_is_visible_without_merging_it(self):
        discovery = build_collection_update_discovery(
            41022,
            self.record,
            self.snapshot,
            existing_collection_keys=("41022", "43123", "usr_deadbeefdeadbeef"),
        )
        candidate = next(
            item for item in discovery.suggestions if item.entry.smwc_submission_id == 43123
        )
        self.assertTrue(candidate.already_in_collection)
        selection = select_possible_collection_replacement(discovery, 43123)
        self.assertTrue(selection.target_already_in_collection)
        self.assertEqual(selection.source_collection_key, "41022")
        self.assertEqual(selection.target_entry.smwc_submission_id, 43123)

    def test_manual_numeric_search_uses_only_the_frozen_index(self):
        discovery = build_collection_update_discovery(
            41022,
            self.record,
            self.snapshot,
        )
        self.assertEqual(
            [entry.smwc_submission_id for entry in search_collection_update_catalogue(
                discovery, "SMWC-ID 50000"
            )],
            [50000],
        )
        self.assertEqual(
            search_collection_update_catalogue(discovery, "SMWC 41022"),
            (),
        )

    def test_manual_title_search_can_find_rows_outside_suggestions(self):
        discovery = build_collection_update_discovery(
            41022,
            self.record,
            self.snapshot,
        )
        results = search_collection_update_catalogue(discovery, "Completely Different")
        self.assertEqual(results[0].smwc_submission_id, 50000)

    def test_selection_rejects_current_or_missing_submission(self):
        discovery = build_collection_update_discovery(
            41022,
            self.record,
            self.snapshot,
        )
        with self.assertRaises(CollectionUpdateDiscoveryError):
            select_possible_collection_replacement(discovery, 41022)
        with self.assertRaises(CollectionUpdateDiscoveryError):
            select_possible_collection_replacement(discovery, 99999)

    def test_catalogue_freshness_metadata_is_frozen(self):
        stale = KaizOffIndexSnapshot(
            entries=self.snapshot.entries,
            fetched_at=777.0,
            source="stale_disk_cache",
            stale=True,
        )
        discovery = build_collection_update_discovery(
            41022,
            self.record,
            stale,
        )
        self.assertEqual(discovery.catalogue_fetched_at, 777.0)
        self.assertEqual(discovery.catalogue_source, "stale_disk_cache")
        self.assertTrue(discovery.catalogue_stale)


if __name__ == "__main__":
    unittest.main()
