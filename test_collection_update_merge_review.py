import json
import tempfile
import unittest
from pathlib import Path

from collection_update_discovery import CollectionUpdateSelection
from collection_update_merge_review import (
    CollectionUpdateMergeReviewError,
    MergeValueOrigin,
    build_collection_update_existing_target_merge_review,
    finalize_collection_update_existing_target_merge_decision,
)
from hack_data_manager import HackDataManager
from rom_title_matching import CatalogueEntry


def _entry(identifier, title):
    return CatalogueEntry(
        smwc_submission_id=identifier,
        title=title,
        difficulty="Expert",
        hack_type="Kaizo",
        exits=10,
    )


def _selection(*, already=True):
    return CollectionUpdateSelection(
        source_collection_key="100",
        source_entry=_entry(100, "Old Hack"),
        target_entry=_entry(200, "New Hack"),
        target_already_in_collection=already,
        catalogue_fetched_at=1.0,
        catalogue_source="network",
        catalogue_stale=False,
    )


class ExistingTargetMergeReviewTests(unittest.TestCase):
    def _manager(self, source, target):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "processed.json"
        path.write_text(json.dumps({"100": source, "200": target}), encoding="utf-8")
        manager = HackDataManager(str(path))
        manager.unsaved_changes = False
        return manager

    def test_reviews_conflicting_user_values_and_primary_rom(self):
        manager = self._manager(
            {
                "title": "Old Hack",
                "completed": True,
                "completed_date": "2025-01-01",
                "personal_rating": 5,
                "notes": "source notes",
                "time_to_beat": 500,
                "file_path": "C:/roms/old.sfc",
                "files": [
                    {"path": "C:/roms/old.sfc", "sha256": "a" * 64, "primary": True}
                ],
                "playthroughs": [{"source": "giganticbucket", "source_record_id": "1"}],
                "obsolete": True,
            },
            {
                "title": "New Hack",
                "completed": False,
                "completed_date": "2026-02-02",
                "personal_rating": 4,
                "notes": "target notes",
                "time_to_beat": 400,
                "file_path": "C:/roms/new.sfc",
                "files": [
                    {"path": "C:/roms/new.sfc", "sha256": "b" * 64, "primary": True}
                ],
                "playthroughs": [{"source": "giganticbucket", "source_record_id": "2"}],
                "obsolete": False,
            },
        )
        review = build_collection_update_existing_target_merge_review(_selection(), manager)
        self.assertEqual(
            {"completed_date", "personal_rating", "notes", "time_to_beat"},
            {item.field for item in review.field_conflicts},
        )
        self.assertTrue(review.primary_rom_required)
        self.assertEqual(
            {"C:/roms/old.sfc", "C:/roms/new.sfc"},
            {item.path for item in review.primary_rom_choices},
        )
        self.assertFalse(review.unsupported_conflicts)
        self.assertTrue(any("Completion remains true" in note for note in review.safe_combination_notes))
        self.assertTrue(any("ROM paths" in note for note in review.safe_combination_notes))

    def test_first_clear_conflict_requires_explicit_choice(self):
        manager = self._manager(
            {
                "title": "Old Hack",
                "first_clear_playthrough": {"source": "giganticbucket", "source_record_id": "1"},
            },
            {
                "title": "New Hack",
                "first_clear_playthrough": {"source": "giganticbucket", "source_record_id": "2"},
            },
        )
        review = build_collection_update_existing_target_merge_review(_selection(), manager)
        self.assertEqual(["first_clear_playthrough"], [item.field for item in review.field_conflicts])

    def test_missing_or_default_user_value_is_not_a_conflict(self):
        manager = self._manager(
            {"title": "Old Hack", "notes": "source", "personal_rating": 5},
            {"title": "New Hack", "notes": "", "personal_rating": 0},
        )
        review = build_collection_update_existing_target_merge_review(_selection(), manager)
        self.assertEqual((), review.field_conflicts)

    def test_unknown_conflicting_user_state_fails_closed(self):
        manager = self._manager(
            {"title": "Old Hack", "future_user_state": "source"},
            {"title": "New Hack", "future_user_state": "target"},
        )
        review = build_collection_update_existing_target_merge_review(_selection(), manager)
        self.assertTrue(review.unsupported_conflicts)
        with self.assertRaises(CollectionUpdateMergeReviewError):
            finalize_collection_update_existing_target_merge_decision(
                review,
                field_origins={},
            )

    def test_conflicting_playthrough_identity_fails_closed(self):
        manager = self._manager(
            {
                "title": "Old Hack",
                "playthroughs": [
                    {"source": "giganticbucket", "source_record_id": "1", "time": "1:00"}
                ],
            },
            {
                "title": "New Hack",
                "playthroughs": [
                    {"source": "giganticbucket", "source_record_id": "1", "time": "2:00"}
                ],
            },
        )
        review = build_collection_update_existing_target_merge_review(_selection(), manager)
        self.assertTrue(any("playthrough identity" in item for item in review.unsupported_conflicts))

    def test_same_path_with_different_hash_fails_closed(self):
        manager = self._manager(
            {
                "title": "Old Hack",
                "files": [{"path": "C:/rom.sfc", "sha256": "a" * 64}],
            },
            {
                "title": "New Hack",
                "files": [{"path": "C:/rom.sfc", "sha256": "b" * 64}],
            },
        )
        review = build_collection_update_existing_target_merge_review(_selection(), manager)
        self.assertTrue(any("different SHA-256" in item for item in review.unsupported_conflicts))

    def test_distinct_legacy_file_path_only_records_fail_closed(self):
        manager = self._manager(
            {"title": "Old Hack", "file_path": "C:/old.sfc"},
            {"title": "New Hack", "file_path": "C:/new.sfc"},
        )
        review = build_collection_update_existing_target_merge_review(_selection(), manager)
        self.assertTrue(any("legacy file_path-only" in item for item in review.unsupported_conflicts))

    def test_final_decision_requires_every_conflict_and_primary(self):
        manager = self._manager(
            {
                "title": "Old Hack",
                "notes": "source",
                "file_path": "C:/old.sfc",
                "files": [{"path": "C:/old.sfc", "sha256": "a" * 64, "primary": True}],
            },
            {
                "title": "New Hack",
                "notes": "target",
                "file_path": "C:/new.sfc",
                "files": [{"path": "C:/new.sfc", "sha256": "b" * 64, "primary": True}],
            },
        )
        review = build_collection_update_existing_target_merge_review(_selection(), manager)
        with self.assertRaises(CollectionUpdateMergeReviewError):
            finalize_collection_update_existing_target_merge_decision(review, field_origins={})
        with self.assertRaises(CollectionUpdateMergeReviewError):
            finalize_collection_update_existing_target_merge_decision(
                review,
                field_origins={"notes": MergeValueOrigin.SOURCE},
            )
        decision = finalize_collection_update_existing_target_merge_decision(
            review,
            field_origins={"notes": MergeValueOrigin.SOURCE},
            primary_rom_path="C:/new.sfc",
        )
        self.assertEqual("100", decision.source_collection_key)
        self.assertEqual("200", decision.target_collection_key)
        self.assertEqual(MergeValueOrigin.SOURCE, decision.field_decisions[0].origin)
        self.assertEqual("C:/new.sfc", decision.primary_rom_path)
        self.assertTrue(decision.collection_revision_token.startswith("sha256:"))

    def test_review_requires_target_to_still_exist_and_selection_to_be_existing_target(self):
        manager = self._manager({"title": "Old Hack"}, {"title": "New Hack"})
        with self.assertRaises(CollectionUpdateMergeReviewError):
            build_collection_update_existing_target_merge_review(_selection(already=False), manager)
        del manager.data["200"]
        with self.assertRaises(CollectionUpdateMergeReviewError):
            build_collection_update_existing_target_merge_review(_selection(), manager)


if __name__ == "__main__":
    unittest.main()
