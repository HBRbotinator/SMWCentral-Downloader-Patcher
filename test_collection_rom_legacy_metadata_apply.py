import copy
import hashlib
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
    apply_legacy_rom_metadata_modernization_plan,
)
from collection_rom_legacy_metadata_plan import build_legacy_rom_metadata_modernization_plan
from hack_data_manager import HackDataManager


class LegacyRomMetadataApplyTests(unittest.TestCase):
    def _fixture(self, *, local=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        rom = root / ("Local.smc" if local else "Hack.sfc")
        rom.write_bytes(b"legacy-rom-bytes")
        key = "usr_0123456789abcdef" if local else "123"
        data = {
            key: {
                "title": "Local" if local else "Hack",
                "file_path": str(rom),
                "notes": "preserve me",
                "personal_rating": 4,
                "additional_paths": [str(root / "Other.sfc")],
                "unknown_future_field": {"keep": True},
            }
        }
        processed = root / "processed.json"
        processed.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        manager = HackDataManager(str(processed))
        revision = collection_revision_token(manager)
        audit = build_legacy_rom_metadata_audit(copy.deepcopy(manager.data), revision)
        plan = build_legacy_rom_metadata_modernization_plan(
            audit, copy.deepcopy(manager.data), revision
        )
        return root, rom, key, processed, manager, plan

    def test_apply_writes_only_modern_files_metadata_and_preserves_other_fields(self):
        root, rom, key, processed, manager, plan = self._fixture()
        before = copy.deepcopy(manager.data[key])

        result = apply_legacy_rom_metadata_modernization_plan(plan, manager)

        self.assertEqual(result.collection_record_count, 1)
        record = manager.data[key]
        self.assertEqual(record["file_path"], before["file_path"])
        self.assertEqual(record["additional_paths"], before["additional_paths"])
        self.assertEqual(record["notes"], "preserve me")
        self.assertEqual(record["personal_rating"], 4)
        self.assertEqual(record["unknown_future_field"], {"keep": True})
        self.assertEqual(record["files"], [plan.operations[0].proposed_files_row])
        self.assertEqual(json.loads(processed.read_text(encoding="utf-8"))[key], record)
        self.assertEqual(rom.read_bytes(), b"legacy-rom-bytes")
        self.assertFalse((root / "Other.sfc").exists())

    def test_local_apply_does_not_invent_numeric_smwc_provenance(self):
        _, _, key, _, manager, plan = self._fixture(local=True)
        apply_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertNotIn("smwc_submission_id", manager.data[key]["files"][0])

    def test_collection_revision_change_fails_closed(self):
        _, _, key, processed, manager, plan = self._fixture()
        before_disk = processed.read_bytes()
        manager.data[key]["notes"] = "changed"
        with self.assertRaisesRegex(LegacyRomMetadataApplyStaleStateError, "Collection changed"):
            apply_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertEqual(processed.read_bytes(), before_disk)
        self.assertNotIn("files", json.loads(before_disk)[key])

    def test_exact_file_path_change_fails_closed_even_for_same_bytes(self):
        root, rom, key, processed, manager, plan = self._fixture()
        alternate = root / "Alternate.sfc"
        alternate.write_bytes(rom.read_bytes())
        manager.data[key]["file_path"] = str(alternate)
        manager.unsaved_changes = True
        with self.assertRaises(LegacyRomMetadataApplyStaleStateError):
            apply_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertNotIn("files", json.loads(processed.read_text(encoding="utf-8"))[key])

    def test_rom_byte_change_after_preview_fails_closed(self):
        _, rom, key, processed, manager, plan = self._fixture()
        rom.write_bytes(b"changed-rom-bytes")
        with self.assertRaises(LegacyRomMetadataApplyStaleStateError):
            apply_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertNotIn("files", manager.data[key])
        self.assertNotIn("files", json.loads(processed.read_text(encoding="utf-8"))[key])

    def test_rom_mtime_change_after_preview_fails_closed_even_if_bytes_match(self):
        _, rom, key, processed, manager, plan = self._fixture()
        stat = rom.stat()
        os.utime(rom, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
        with self.assertRaisesRegex(LegacyRomMetadataApplyStaleStateError, "modification time"):
            apply_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertNotIn("files", json.loads(processed.read_text(encoding="utf-8"))[key])

    def test_existing_modern_files_metadata_fails_closed(self):
        _, _, key, processed, manager, plan = self._fixture()
        manager.data[key]["files"] = [{"path": "unexpected"}]
        manager.unsaved_changes = True
        with self.assertRaises(LegacyRomMetadataApplyStaleStateError):
            apply_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertNotIn("files", json.loads(processed.read_text(encoding="utf-8"))[key])

    def test_injected_transaction_failure_does_not_partially_write(self):
        _, _, key, processed, manager, plan = self._fixture()
        before = processed.read_bytes()
        with self.assertRaises(LegacyRomMetadataApplyError):
            apply_legacy_rom_metadata_modernization_plan(
                plan, manager, fail_before_replace=True
            )
        self.assertEqual(processed.read_bytes(), before)
        self.assertNotIn("files", manager.data[key])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_source_replaced_by_symlink_after_preview_fails_closed(self):
        root, rom, key, processed, manager, plan = self._fixture()
        target = root / "Target.sfc"
        target.write_bytes(rom.read_bytes())
        rom.unlink()
        try:
            os.symlink(target, rom)
        except (OSError, NotImplementedError):
            self.skipTest("symlink creation unavailable")
        with self.assertRaisesRegex(LegacyRomMetadataApplyStaleStateError, "symbolic link"):
            apply_legacy_rom_metadata_modernization_plan(plan, manager)
        self.assertNotIn("files", json.loads(processed.read_text(encoding="utf-8"))[key])


if __name__ == "__main__":
    unittest.main()
