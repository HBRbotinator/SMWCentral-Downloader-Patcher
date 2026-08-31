from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from collection_change_plan import (
    CollectionChangePlan,
    PlannedRomAsset,
    RecordIntent,
    RecordIntentKind,
    RomAssetsOperation,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion import IngestionSource
from collection_plan_apply import CollectionPlanStaleStateError, collect_store_preconditions
from collection_update_current_refresh import (
    CurrentRomDisposition,
    FinalizedCurrentSubmissionRefreshPlan,
)
from collection_update_current_refresh_apply import apply_finalized_current_submission_refresh
from collection_update_current_rom_disposition import (
    CollectionCurrentRomDispositionError,
    build_current_rom_disposition_review,
    finalize_current_rom_disposition,
)
from collection_update_current_rom_replace_apply import (
    COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME,
    CollectionCurrentRomReplaceRecoveryError,
    CollectionCurrentRomReplaceRecoveryRequiredError,
    apply_current_rom_replacement,
    inspect_interrupted_current_rom_replacement,
    recover_interrupted_current_rom_replacement,
)
from hack_data_manager import HackDataManager
from rom_title_matching import CatalogueEntry


class CurrentRomDispositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.processed = self.root / "processed.json"
        self.old = self.root / "Quickie World.sfc"
        self.other = self.root / "Quickie World old.sfc"
        self.new = self.root / "Quickie World (1).sfc"
        self.old.write_bytes(b"old-current-rom")
        self.other.write_bytes(b"other-rom")
        self.new.write_bytes(b"downloaded-current-rom")
        self.old_sha = self._sha(self.old)
        self.other_sha = self._sha(self.other)
        self.new_sha = self._sha(self.new)
        self.record = {
            "title": "Quickie World",
            "notes": "keep me",
            "completed": True,
            "file_path": str(self.old),
            "files": [
                {
                    "path": str(self.old),
                    "name": self.old.name,
                    "sha256": self.old_sha,
                    "size_bytes": self.old.stat().st_size,
                    "primary": True,
                    "smwc_submission_id": 17441,
                },
                {
                    "path": str(self.other),
                    "name": self.other.name,
                    "sha256": self.other_sha,
                    "size_bytes": self.other.stat().st_size,
                    "primary": False,
                    "smwc_submission_id": 17441,
                },
            ],
        }
        self.processed.write_text(json.dumps({"17441": self.record}, indent=2) + "\n", encoding="utf-8")
        self.manager = HackDataManager(str(self.processed))
        self.hints = CollectionIdentityHintsStore.beside_processed_json(self.processed)
        self.finalized = self._finalized()

    def tearDown(self):
        self.tmp.cleanup()

    def test_keep_both_requires_primary_and_downloaded_is_review_default(self):
        review = self._review()
        self.assertEqual(review.downloaded_default_primary_path, str(self.new))
        self.assertTrue(review.can_replace_current)
        with self.assertRaises(CollectionCurrentRomDispositionError):
            finalize_current_rom_disposition(
                self.processed, self.finalized, review, CurrentRomDisposition.KEEP_BOTH,
                primary_path="", manager=self.manager, identity_hints=self.hints, participants=(),
            )
        kept = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.KEEP_BOTH,
            primary_path=str(self.new), manager=self.manager, identity_hints=self.hints, participants=(),
        )
        self.assertIs(kept.rom_disposition, CurrentRomDisposition.KEEP_BOTH)
        self.assertEqual(kept.reviewed_primary_path, str(self.new))
        self.assertIsNotNone(kept.reviewed_primary_precondition)
        self.assertEqual(kept.reviewed_primary_precondition.path, str(self.new))
        self.assertEqual(kept.reviewed_primary_precondition.sha256, self.new_sha)
        self.assertEqual(kept.plan.primary_rom_selections[0].primary_path, str(self.new))
        self.assertTrue(kept.plan.rom_updates[0].preserve_existing_primary)

    def test_keep_both_existing_primary_freezes_and_revalidates_exact_bytes(self):
        review = self._review()
        kept = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.KEEP_BOTH,
            primary_path=str(self.other), manager=self.manager, identity_hints=self.hints, participants=(),
        )
        frozen = kept.reviewed_primary_precondition
        self.assertIsNotNone(frozen)
        self.assertEqual(frozen.path, str(self.other))
        self.assertEqual(frozen.sha256, self.other_sha)
        self.assertEqual(frozen.size_bytes, self.other.stat().st_size)

        original_mtime = frozen.mtime_ns
        original_size = self.other.stat().st_size
        self.other.write_bytes(b"x" * original_size)
        os.utime(self.other, ns=(original_mtime, original_mtime))

        with self.assertRaises(CollectionPlanStaleStateError):
            apply_finalized_current_submission_refresh(
                self.processed, kept, manager=self.manager, identity_hints=self.hints, participants=(),
            )
        self.assertEqual(self.manager.data["17441"]["file_path"], str(self.old))
        self.assertTrue(self.new.exists())

    def test_keep_both_existing_primary_rejects_mtime_only_change(self):
        review = self._review()
        kept = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.KEEP_BOTH,
            primary_path=str(self.other), manager=self.manager, identity_hints=self.hints, participants=(),
        )
        frozen = kept.reviewed_primary_precondition
        self.assertIsNotNone(frozen)
        os.utime(self.other, ns=(frozen.mtime_ns + 1_000_000_000, frozen.mtime_ns + 1_000_000_000))

        with self.assertRaises(CollectionPlanStaleStateError):
            apply_finalized_current_submission_refresh(
                self.processed, kept, manager=self.manager, identity_hints=self.hints, participants=(),
            )
        self.assertEqual(self.manager.data["17441"]["file_path"], str(self.old))


    def test_keep_both_choice_can_be_reopened_and_changed_to_replace(self):
        review = self._review()
        kept = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.KEEP_BOTH,
            primary_path=str(self.new), manager=self.manager, identity_hints=self.hints, participants=(),
        )
        reopened = build_current_rom_disposition_review(
            self.processed, kept, manager=self.manager, identity_hints=self.hints, participants=(),
        )
        replaced = finalize_current_rom_disposition(
            self.processed, kept, reopened, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        self.assertIs(replaced.rom_disposition, CurrentRomDisposition.REPLACE_CURRENT)
        self.assertEqual(replaced.rom_replacement.target_path, str(self.old))

    def test_replace_supports_file_path_primary_projection_without_legacy_primary_flag(self):
        self.manager.data["17441"]["files"][0].pop("primary", None)
        self.manager.data["17441"]["files"][1]["primary"] = False
        self.processed.write_text(
            json.dumps(self.manager.data, indent=2) + "\n", encoding="utf-8"
        )
        self.manager = HackDataManager(str(self.processed))
        self.finalized = self._finalized()
        review = self._review()
        self.assertTrue(review.can_replace_current)
        replaced = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        apply_finalized_current_submission_refresh(
            self.processed, replaced, manager=self.manager, identity_hints=self.hints, participants=(),
        )
        self.assertEqual(self.old.read_bytes(), b"downloaded-current-rom")
        self.assertEqual(self.manager.data["17441"]["file_path"], str(self.old))

    def test_replace_freezes_old_and_downloaded_bytes_without_version_inference(self):
        review = self._review()
        replaced = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        frozen = replaced.rom_replacement
        self.assertIsNotNone(frozen)
        self.assertEqual(frozen.source_path, str(self.new))
        self.assertEqual(frozen.target_path, str(self.old))
        self.assertEqual(frozen.source_sha256, self.new_sha)
        self.assertEqual(frozen.target_sha256, self.old_sha)
        operation = replaced.plan.rom_updates[0]
        self.assertEqual(operation.primary_path, str(self.old))
        self.assertIn(str(self.old), {asset.path for asset in operation.assets})
        self.assertNotIn(str(self.new), {asset.path for asset in operation.assets})

    def test_keep_both_apply_retains_both_and_uses_explicit_primary(self):
        review = self._review()
        kept = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.KEEP_BOTH,
            primary_path=str(self.new), manager=self.manager, identity_hints=self.hints, participants=(),
        )
        apply_finalized_current_submission_refresh(
            self.processed, kept, manager=self.manager, identity_hints=self.hints, participants=(),
        )
        record = self.manager.data["17441"]
        self.assertEqual(record["file_path"], str(self.new))
        self.assertEqual({row["path"] for row in record["files"]}, {str(self.old), str(self.other), str(self.new)})
        self.assertEqual(record["notes"], "keep me")
        self.assertTrue(self.old.exists())
        self.assertTrue(self.new.exists())

    def test_replace_apply_preserves_path_replaces_bytes_and_removes_downloaded_sibling(self):
        review = self._review()
        replaced = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        apply_finalized_current_submission_refresh(
            self.processed, replaced, manager=self.manager, identity_hints=self.hints, participants=(),
        )
        self.assertEqual(self.old.read_bytes(), b"downloaded-current-rom")
        self.assertFalse(self.new.exists())
        record = self.manager.data["17441"]
        self.assertEqual(record["file_path"], str(self.old))
        target_rows = [row for row in record["files"] if row["path"] == str(self.old)]
        self.assertEqual(len(target_rows), 1)
        self.assertEqual(target_rows[0]["sha256"], self.new_sha)
        self.assertTrue(target_rows[0]["primary"])
        self.assertEqual(record["notes"], "keep me")
        self.assertTrue(self.other.exists())

    def test_prepared_replacement_recovery_restores_old_bytes_and_keeps_downloaded_source(self):
        review = self._review()
        replaced = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        with self.assertRaises(BaseException):
            apply_current_rom_replacement(
                self.processed, replaced, manager=self.manager, identity_hints=self.hints,
                participants=(), _crash_after="rom",
            )
        self.assertTrue((self.root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME).exists())
        self.assertEqual(self.old.read_bytes(), b"downloaded-current-rom")
        self.assertTrue(recover_interrupted_current_rom_replacement(self.root))
        self.assertEqual(self.old.read_bytes(), b"old-current-rom")
        self.assertTrue(self.new.exists())
        on_disk = json.loads(self.processed.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["17441"]["files"][0]["sha256"], self.old_sha)

    def test_post_processed_crash_recovery_finishes_committed_replacement(self):
        review = self._review()
        replaced = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        with self.assertRaises(BaseException):
            apply_current_rom_replacement(
                self.processed, replaced, manager=self.manager, identity_hints=self.hints,
                participants=(), _crash_after="store2",
            )
        self.assertTrue(recover_interrupted_current_rom_replacement(self.root))
        self.assertEqual(self.old.read_bytes(), b"downloaded-current-rom")
        self.assertFalse(self.new.exists())
        on_disk = json.loads(self.processed.read_text(encoding="utf-8"))
        row = next(row for row in on_disk["17441"]["files"] if row["path"] == str(self.old))
        self.assertEqual(row["sha256"], self.new_sha)

    def test_committed_cleanup_failure_keeps_live_manager_on_committed_collection_state(self):
        review = self._review()
        replaced = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        with patch(
            "collection_update_current_rom_replace_apply._finish_committed",
            side_effect=OSError("simulated cleanup failure"),
        ):
            with self.assertRaises(CollectionCurrentRomReplaceRecoveryRequiredError):
                apply_current_rom_replacement(
                    self.processed, replaced, manager=self.manager, identity_hints=self.hints,
                    participants=(),
                )

        row = next(
            row for row in self.manager.data["17441"]["files"]
            if row["path"] == str(self.old)
        )
        self.assertEqual(row["sha256"], self.new_sha)
        self.assertEqual(self.manager.data["17441"]["file_path"], str(self.old))
        self.assertTrue((self.root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME).exists())
        self.assertTrue(recover_interrupted_current_rom_replacement(self.root))

    def test_recovery_rejects_unsafe_temp_paths_in_journal_without_touching_them(self):
        review = self._review()
        replaced = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        with self.assertRaises(BaseException):
            apply_current_rom_replacement(
                self.processed, replaced, manager=self.manager, identity_hints=self.hints,
                participants=(), _crash_after="rom",
            )
        journal_path = self.root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME
        document = json.loads(journal_path.read_text(encoding="utf-8"))
        outside = self.root / "outside"
        outside.mkdir()
        sentinel = outside / "sentinel.tmp"
        sentinel.write_bytes(b"do-not-touch")
        document["rom"]["rollback"] = str(sentinel.resolve())
        journal_path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")

        with self.assertRaises(CollectionCurrentRomReplaceRecoveryError):
            inspect_interrupted_current_rom_replacement(self.root)
        self.assertEqual(sentinel.read_bytes(), b"do-not-touch")
        self.assertTrue(journal_path.exists())

    def test_logically_committed_recovery_refuses_changed_store_before_cleanup(self):
        review = self._review()
        replaced = finalize_current_rom_disposition(
            self.processed, self.finalized, review, CurrentRomDisposition.REPLACE_CURRENT,
            manager=self.manager, identity_hints=self.hints, participants=(),
        )
        with self.assertRaises(BaseException):
            apply_current_rom_replacement(
                self.processed, replaced, manager=self.manager, identity_hints=self.hints,
                participants=(), _crash_after="store2",
            )
        backup = Path(f"{self.processed}.backup")
        backup.write_bytes(b"externally-changed-backup")

        with self.assertRaises(CollectionCurrentRomReplaceRecoveryError):
            recover_interrupted_current_rom_replacement(self.root)
        self.assertTrue((self.root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME).exists())
        self.assertTrue(self.new.exists())
        self.assertEqual(self.old.read_bytes(), b"downloaded-current-rom")

    def _review(self):
        return build_current_rom_disposition_review(
            self.processed, self.finalized, manager=self.manager,
            identity_hints=self.hints, participants=(),
        )

    def _finalized(self):
        preconditions = collect_store_preconditions(self.manager, self.hints, ())
        asset = PlannedRomAsset(
            path=str(self.new), filename=self.new.name, sha256=self.new_sha,
            size_bytes=self.new.stat().st_size, sources=(IngestionSource.TOOL_PATCH,),
            source_candidate_ids=("current-download",), smwc_submission_id=17441,
        )
        plan = CollectionChangePlan(
            preconditions=tuple(preconditions),
            record_intents=(RecordIntent("17441", RecordIntentKind.UPDATE, "Quickie World"),),
            catalogue_updates=(), local_record_seeds=(),
            rom_updates=(RomAssetsOperation("17441", (asset,), primary_path=str(self.new)),),
            user_history_updates=(), user_state_updates=(), identity_migrations=(),
            reference_migrations=(), ignored_roms=(), remembered_associations=(),
            skipped_candidate_ids=(), ignored_candidate_ids=(),
        )
        return FinalizedCurrentSubmissionRefreshPlan(
            source_collection_key="17441",
            source_entry=CatalogueEntry(smwc_submission_id=17441, title="Quickie World", difficulty="Advanced", hack_type="kaizo", exits=14, authors=("Valdio",)),
            plan=plan, detail_fetched_at=1.0, detail_source="test", detail_stale=False,
            download_url="https://example.invalid/quickie.zip", rom_acquisition_checked=True,
            rom_matches_existing=False, acquired_default_primary_path=str(self.new),
        )

    @staticmethod
    def _sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    unittest.main()
