import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from collection_plan_apply import collection_revision_token
from collection_rom_organization_apply import (
    COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME,
    CollectionRomOrganizationApplyError,
    CollectionRomOrganizationRecoveryRequiredError,
    CollectionRomOrganizationStaleStateError,
    apply_collection_rom_organization_execution_plan,
    inspect_interrupted_collection_rom_organization,
    recover_interrupted_collection_rom_organization,
)
from collection_rom_organization_execution_plan import (
    CollectionRomOrganizationExecutionPlan,
    CollectionRomSaveMoveOperation,
)
from collection_rom_organization_plan import CollectionRomMoveOperation
from hack_data_manager import HackDataManager


class CollectionRomOrganizationApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data_root = self.root / "Data"
        self.data_root.mkdir()
        self.processed = self.data_root / "processed.json"
        self.loose = self.root / "Loose"
        self.loose.mkdir()
        self.output = self.root / "Library"
        self.rom = self.loose / "Hack.sfc"
        self.rom_bytes = b"rom-bytes-v1"
        self.rom.write_bytes(self.rom_bytes)
        stat = self.rom.stat()
        self.rom_sha = hashlib.sha256(self.rom_bytes).hexdigest()
        self.record = {
            "title": "Hack",
            "hack_type": "kaizo",
            "current_difficulty": "Advanced",
            "file_path": str(self.rom.resolve()),
            "files": [
                {
                    "path": str(self.rom.resolve()),
                    "name": "Hack.sfc",
                    "sha256": self.rom_sha,
                    "size_bytes": len(self.rom_bytes),
                    "primary": True,
                    "smwc_submission_id": 123,
                    "ingestion_sources": ["tool_patch"],
                    "future_field": {"kept": True},
                }
            ],
            "additional_paths": [],
            "notes": "keep me",
        }
        self.processed.write_text(
            json.dumps({"123": self.record}, indent=2) + "\n",
            encoding="utf-8",
        )
        self.manager = HackDataManager(str(self.processed))
        self.rom_mtime = stat.st_mtime_ns

    def _plan(self, *, with_save=False):
        target = self.output / "Kaizo" / "04 - Advanced" / "Hack.sfc"
        rom_move = CollectionRomMoveOperation(
            collection_id="123",
            title="Hack",
            asset_name="Hack.sfc",
            source_path=str(self.rom.resolve()),
            target_path=str(target.resolve()),
            sha256=self.rom_sha,
            size_bytes=len(self.rom_bytes),
            source_mtime_ns=self.rom_mtime,
            primary=True,
            smwc_submission_id=123,
        )
        save_moves = ()
        if with_save:
            save = self.loose / "Hack.srm"
            save_bytes = b"save-state"
            save.write_bytes(save_bytes)
            save_stat = save.stat()
            save_target = target.parent / save.name
            save_moves = (
                CollectionRomSaveMoveOperation(
                    collection_id="123",
                    title="Hack",
                    rom_source_path=str(self.rom.resolve()),
                    source_path=str(save.resolve()),
                    target_path=str(save_target.resolve()),
                    sha256=hashlib.sha256(save_bytes).hexdigest(),
                    size_bytes=len(save_bytes),
                    source_mtime_ns=save_stat.st_mtime_ns,
                ),
            )
        return CollectionRomOrganizationExecutionPlan(
            output_dir=str(self.output.resolve()),
            collection_revision_token=collection_revision_token(self.manager),
            save_review_fingerprint="sha256:" + "1" * 64,
            rom_moves=(rom_move,),
            save_moves=save_moves,
            save_leaves=(),
            blocked_move_count=0,
            external_save_evidence_count=0,
            rom_only_acknowledgement_count=0 if with_save else 1,
        )

    def test_success_copies_commits_then_removes_reviewed_sources(self):
        plan = self._plan(with_save=True)
        rom_target = Path(plan.rom_moves[0].target_path)
        save_source = Path(plan.save_moves[0].source_path)
        save_target = Path(plan.save_moves[0].target_path)
        before = self.processed.read_bytes()

        result = apply_collection_rom_organization_execution_plan(plan, self.manager)

        self.assertEqual(1, result.rom_move_count)
        self.assertEqual(1, result.save_move_count)
        self.assertFalse(self.rom.exists())
        self.assertFalse(save_source.exists())
        self.assertEqual(self.rom_bytes, rom_target.read_bytes())
        self.assertEqual(b"save-state", save_target.read_bytes())
        stored = json.loads(self.processed.read_text(encoding="utf-8"))
        row = stored["123"]["files"][0]
        self.assertEqual(str(rom_target.resolve()), row["path"])
        self.assertEqual(str(rom_target.resolve()), stored["123"]["file_path"])
        self.assertEqual({"kept": True}, row["future_field"])
        self.assertEqual("keep me", stored["123"]["notes"])
        self.assertEqual(before, Path(f"{self.processed}.backup").read_bytes())
        self.assertFalse((self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME).exists())

    def test_failure_after_target_copy_rolls_back_without_source_loss(self):
        plan = self._plan()
        target = Path(plan.rom_moves[0].target_path)
        before = self.processed.read_bytes()

        with self.assertRaisesRegex(CollectionRomOrganizationApplyError, "target copy"):
            apply_collection_rom_organization_execution_plan(
                plan,
                self.manager,
                fail_after_target_copy=1,
            )

        self.assertTrue(self.rom.exists())
        self.assertFalse(target.exists())
        self.assertEqual(before, self.processed.read_bytes())
        self.assertEqual(str(self.rom.resolve()), self.manager.data["123"]["file_path"])
        self.assertFalse((self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME).exists())

    def test_failure_after_processed_replace_rolls_collection_and_targets_back(self):
        plan = self._plan()
        target = Path(plan.rom_moves[0].target_path)
        before = self.processed.read_bytes()

        with self.assertRaisesRegex(CollectionRomOrganizationApplyError, "store replacement 2"):
            apply_collection_rom_organization_execution_plan(
                plan,
                self.manager,
                fail_after_store_replace=2,
            )

        self.assertTrue(self.rom.exists())
        self.assertFalse(target.exists())
        self.assertEqual(before, self.processed.read_bytes())
        self.assertFalse(Path(f"{self.processed}.backup").exists())
        self.assertFalse((self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME).exists())

    def test_committed_interruption_is_finished_by_recovery_not_rolled_back(self):
        plan = self._plan()
        target = Path(plan.rom_moves[0].target_path)

        with self.assertRaises(CollectionRomOrganizationRecoveryRequiredError):
            apply_collection_rom_organization_execution_plan(
                plan,
                self.manager,
                fail_after_commit=True,
            )

        self.assertTrue(self.rom.exists())
        self.assertTrue(target.exists())
        stored = json.loads(self.processed.read_text(encoding="utf-8"))
        self.assertEqual(str(target.resolve()), stored["123"]["file_path"])
        info = inspect_interrupted_collection_rom_organization(self.data_root)
        self.assertIsNotNone(info)
        self.assertEqual("committed", info.state)

        self.assertTrue(recover_interrupted_collection_rom_organization(self.data_root))
        self.assertFalse(self.rom.exists())
        self.assertTrue(target.exists())
        self.assertFalse((self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME).exists())

    def test_same_size_source_byte_change_with_restored_mtime_blocks_apply(self):
        plan = self._plan()
        original_stat = self.rom.stat()
        tampered = b"ROM-BYTES-V1"
        self.assertEqual(len(self.rom_bytes), len(tampered))
        self.rom.write_bytes(tampered)
        os.utime(
            self.rom,
            ns=(original_stat.st_atime_ns, self.rom_mtime),
        )

        with self.assertRaisesRegex(CollectionRomOrganizationStaleStateError, "SHA-256"):
            apply_collection_rom_organization_execution_plan(plan, self.manager)

        self.assertEqual(tampered, self.rom.read_bytes())
        self.assertFalse(Path(plan.rom_moves[0].target_path).exists())
        self.assertFalse((self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME).exists())

    def test_target_appearing_after_final_preview_blocks_without_overwrite(self):
        plan = self._plan()
        target = Path(plan.rom_moves[0].target_path)
        target.parent.mkdir(parents=True)
        target.write_bytes(b"existing-target")

        with self.assertRaisesRegex(CollectionRomOrganizationStaleStateError, "became occupied"):
            apply_collection_rom_organization_execution_plan(plan, self.manager)

        self.assertEqual(b"existing-target", target.read_bytes())
        self.assertTrue(self.rom.exists())
        self.assertFalse((self.data_root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME).exists())

    def test_new_colocated_save_after_final_preview_blocks_apply(self):
        plan = self._plan()
        unexpected = self.loose / "Hack.srm"
        unexpected.write_bytes(b"appeared")

        with self.assertRaisesRegex(CollectionRomOrganizationStaleStateError, "Colocated save evidence"):
            apply_collection_rom_organization_execution_plan(plan, self.manager)

        self.assertTrue(self.rom.exists())
        self.assertTrue(unexpected.exists())
        self.assertFalse(Path(plan.rom_moves[0].target_path).exists())

    def test_collection_metadata_reference_to_target_blocks_apply(self):
        plan = self._plan()
        target = plan.rom_moves[0].target_path
        self.manager.data["999"] = {
            "title": "Other",
            "file_path": target,
            "files": [],
        }
        self.manager.unsaved_changes = True
        # Re-finalize only the revision token so the metadata collision itself is what Apply rejects.
        plan = CollectionRomOrganizationExecutionPlan(
            output_dir=plan.output_dir,
            collection_revision_token=collection_revision_token(self.manager),
            save_review_fingerprint=plan.save_review_fingerprint,
            rom_moves=plan.rom_moves,
            save_moves=plan.save_moves,
            save_leaves=plan.save_leaves,
            blocked_move_count=0,
            external_save_evidence_count=0,
            rom_only_acknowledgement_count=1,
        )

        with self.assertRaisesRegex(CollectionRomOrganizationStaleStateError, "already referenced"):
            apply_collection_rom_organization_execution_plan(plan, self.manager)

        self.assertTrue(self.rom.exists())
        self.assertFalse(Path(target).exists())


if __name__ == "__main__":
    unittest.main()
