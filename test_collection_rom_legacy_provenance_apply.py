import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from collection_plan_apply import collection_revision_token
from collection_rom_legacy_metadata import build_legacy_rom_metadata_audit
from collection_rom_legacy_metadata_apply import (
    LegacyRomMetadataApplyError,
    LegacyRomMetadataApplyStaleStateError,
    apply_reviewed_legacy_rom_metadata_modernization_plan,
)
from collection_rom_legacy_metadata_plan import (
    build_reviewed_legacy_rom_metadata_modernization_plan,
)
from collection_rom_legacy_provenance_review import (
    build_legacy_rom_provenance_decision,
    build_legacy_rom_provenance_review,
)
from hack_data_manager import HackDataManager


class ReviewedLegacyRomMetadataApplyTests(unittest.TestCase):
    def _fixture(self, *, selected_id=100):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        rom = root / "Migrated.sfc"
        rom.write_bytes(b"reviewed-legacy-rom")
        data = {
            "200": {
                "title": "Migrated Hack",
                "file_path": str(rom),
                "prior_smwc_submission_ids": [100],
                "identity_migration_history": [
                    {"source_key": "100", "target_key": "200"}
                ],
                "notes": "preserve",
                "additional_paths": [str(root / "Other.sfc")],
                "unknown_future_field": {"keep": True},
            }
        }
        processed = root / "processed.json"
        processed.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        manager = HackDataManager(str(processed))
        revision = collection_revision_token(manager)
        audit = build_legacy_rom_metadata_audit(copy.deepcopy(manager.data), revision)
        review = build_legacy_rom_provenance_review(
            audit, copy.deepcopy(manager.data), revision
        )
        decision = build_legacy_rom_provenance_decision(
            review, {"200": selected_id}
        )
        plan = build_reviewed_legacy_rom_metadata_modernization_plan(
            audit,
            review,
            decision,
            copy.deepcopy(manager.data),
            revision,
        )
        return root, rom, processed, manager, plan

    def test_apply_persists_explicit_prior_provenance_only(self):
        root, rom, processed, manager, plan = self._fixture(selected_id=100)
        before = copy.deepcopy(manager.data["200"])

        result = apply_reviewed_legacy_rom_metadata_modernization_plan(plan, manager)

        self.assertEqual(result.collection_record_count, 1)
        record = manager.data["200"]
        self.assertEqual(record["files"], [plan.operations[0].proposed_files_row])
        self.assertEqual(record["files"][0]["smwc_submission_id"], 100)
        self.assertEqual(record["file_path"], before["file_path"])
        self.assertEqual(record["additional_paths"], before["additional_paths"])
        self.assertEqual(record["notes"], "preserve")
        self.assertEqual(record["unknown_future_field"], {"keep": True})
        self.assertEqual(json.loads(processed.read_text(encoding="utf-8"))["200"], record)
        self.assertEqual(rom.read_bytes(), b"reviewed-legacy-rom")
        self.assertFalse((root / "Other.sfc").exists())

    def test_apply_can_persist_explicit_current_provenance(self):
        _, _, _, manager, plan = self._fixture(selected_id=200)
        apply_reviewed_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertEqual(manager.data["200"]["files"][0]["smwc_submission_id"], 200)

    def test_collection_revision_change_fails_closed(self):
        _, _, processed, manager, plan = self._fixture()
        before = processed.read_bytes()
        manager.data["200"]["notes"] = "changed"
        with self.assertRaisesRegex(LegacyRomMetadataApplyStaleStateError, "Collection changed"):
            apply_reviewed_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertEqual(processed.read_bytes(), before)

    def test_selected_provenance_removed_from_history_fails_closed(self):
        _, _, processed, manager, plan = self._fixture(selected_id=100)
        before = processed.read_bytes()
        # Preserve the manager's original revision token artificially by updating the plan
        # is not allowed; the normal revision guard should fail first. This still proves
        # provenance history changes cannot pass the writable boundary.
        manager.data["200"]["prior_smwc_submission_ids"] = []
        manager.data["200"]["identity_migration_history"] = []
        with self.assertRaisesRegex(
            LegacyRomMetadataApplyStaleStateError, "no longer recorded in Collection history"
        ):
            apply_reviewed_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertEqual(processed.read_bytes(), before)

    def test_rom_bytes_changed_after_preview_fail_closed(self):
        _, rom, processed, manager, plan = self._fixture()
        before = processed.read_bytes()
        rom.write_bytes(b"changed-reviewed-rom")
        with self.assertRaises(LegacyRomMetadataApplyStaleStateError):
            apply_reviewed_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertEqual(processed.read_bytes(), before)
        self.assertNotIn("files", manager.data["200"])

    def test_existing_files_metadata_fails_closed(self):
        _, _, processed, manager, plan = self._fixture()
        before = processed.read_bytes()
        manager.data["200"]["files"] = [{"path": "unexpected"}]
        with self.assertRaises(LegacyRomMetadataApplyStaleStateError):
            apply_reviewed_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertEqual(processed.read_bytes(), before)

    def test_injected_transaction_failure_does_not_partially_write(self):
        _, _, processed, manager, plan = self._fixture()
        before = processed.read_bytes()
        with self.assertRaises(LegacyRomMetadataApplyError):
            apply_reviewed_legacy_rom_metadata_modernization_plan(
                plan, manager, fail_before_replace=True
            )
        self.assertEqual(processed.read_bytes(), before)
        self.assertNotIn("files", manager.data["200"])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_source_replaced_by_symlink_after_preview_fails_closed(self):
        root, rom, processed, manager, plan = self._fixture()
        before = processed.read_bytes()
        target = root / "Target.sfc"
        target.write_bytes(rom.read_bytes())
        rom.unlink()
        try:
            os.symlink(target, rom)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(LegacyRomMetadataApplyStaleStateError, "symbolic link"):
            apply_reviewed_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertEqual(processed.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
