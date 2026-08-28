import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from collection_rom_legacy_metadata import build_legacy_rom_metadata_audit
from collection_rom_legacy_metadata_plan import (
    LegacyRomMetadataPlanError,
    build_legacy_rom_metadata_modernization_plan,
)


class LegacyRomMetadataModernizationPlanTests(unittest.TestCase):
    def _record(self, path, title="Hack", **extra):
        record = {"title": title, "file_path": str(path)}
        record.update(extra)
        return record

    def test_ready_numeric_row_hashes_into_modern_primary_asset_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"legacy-rom")
            data = {"123": self._record(rom, notes="keep me")}
            audit = build_legacy_rom_metadata_audit(data, "rev")

            plan = build_legacy_rom_metadata_modernization_plan(audit, data, "rev")

            self.assertEqual(plan.collection_revision_token, "rev")
            self.assertEqual(len(plan.operations), 1)
            operation = plan.operations[0]
            self.assertEqual(operation.collection_id, "123")
            self.assertEqual(operation.legacy_file_path, str(rom))
            self.assertEqual(Path(operation.canonical_path), rom.resolve())
            self.assertEqual(operation.sha256, hashlib.sha256(b"legacy-rom").hexdigest())
            self.assertEqual(operation.size_bytes, len(b"legacy-rom"))
            self.assertEqual(
                operation.proposed_files_row,
                {
                    "path": str(rom.resolve()),
                    "name": "Hack.sfc",
                    "sha256": hashlib.sha256(b"legacy-rom").hexdigest(),
                    "size_bytes": len(b"legacy-rom"),
                    "primary": True,
                    "ingestion_sources": ["legacy_collection_backfill"],
                    "smwc_submission_id": 123,
                },
            )
            self.assertNotIn("files", data["123"])
            self.assertEqual(data["123"]["file_path"], str(rom))
            self.assertEqual(data["123"]["notes"], "keep me")

    def test_local_row_has_no_numeric_smwc_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Local.smc"
            rom.write_bytes(b"local")
            data = {"usr_0123456789abcdef": self._record(rom, "Local")}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            operation = build_legacy_rom_metadata_modernization_plan(
                audit, data, "rev"
            ).operations[0]
            self.assertIsNone(operation.smwc_submission_id)
            self.assertNotIn("smwc_submission_id", operation.proposed_files_row)

    def test_blocking_audit_rows_are_excluded_not_reinterpreted(self):
        with tempfile.TemporaryDirectory() as temp:
            good = Path(temp) / "Good.sfc"
            good.write_bytes(b"good")
            missing = Path(temp) / "Missing.sfc"
            data = {
                "123": self._record(good, "Good"),
                "456": self._record(missing, "Missing"),
            }
            audit = build_legacy_rom_metadata_audit(data, "rev")
            plan = build_legacy_rom_metadata_modernization_plan(audit, data, "rev")
            self.assertEqual([op.collection_id for op in plan.operations], ["123"])
            self.assertEqual(plan.excluded_blocking_count, 1)

    def test_no_ready_rows_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            data = {"123": self._record(Path(temp) / "Missing.sfc")}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "no ready ROMs"):
                build_legacy_rom_metadata_modernization_plan(audit, data, "rev")

    def test_collection_revision_change_after_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"rom")
            data = {"123": self._record(rom)}
            audit = build_legacy_rom_metadata_audit(data, "rev-a")
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "Collection changed"):
                build_legacy_rom_metadata_modernization_plan(audit, data, "rev-b")

    def test_changed_file_path_after_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            original = root / "A.sfc"
            replacement = root / "B.sfc"
            original.write_bytes(b"a")
            replacement.write_bytes(b"b")
            data = {"123": self._record(original)}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            changed = {"123": self._record(replacement)}
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "file_path ownership"):
                build_legacy_rom_metadata_modernization_plan(audit, changed, "rev")

    def test_modern_files_metadata_appearing_after_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"rom")
            data = {"123": self._record(rom)}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            changed = {"123": self._record(rom, files=[{"path": str(rom)}])}
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, r"files\[\]"):
                build_legacy_rom_metadata_modernization_plan(audit, changed, "rev")

    def test_new_duplicate_collection_path_ownership_after_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            other = Path(temp) / "Other.sfc"
            rom.write_bytes(b"rom")
            other.write_bytes(b"other")
            data = {"123": self._record(rom), "456": self._record(other, "Other")}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            changed = {"123": data["123"], "456": self._record(rom, "Other")}
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "ownership.*changed"):
                build_legacy_rom_metadata_modernization_plan(audit, changed, "rev")

    def test_size_change_after_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"abc")
            data = {"123": self._record(rom)}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            rom.write_bytes(b"abcd")
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "size.*changed"):
                build_legacy_rom_metadata_modernization_plan(audit, data, "rev")

    def test_file_change_during_hashing_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"abc")
            data = {"123": self._record(rom)}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            with mock.patch(
                "collection_rom_legacy_metadata_plan._stat_fingerprint",
                side_effect=[(1, 2, 3, 100, 200), (1, 2, 3, 101, 200)],
            ):
                with self.assertRaisesRegex(LegacyRomMetadataPlanError, "changed while SHA-256"):
                    build_legacy_rom_metadata_modernization_plan(audit, data, "rev")

    def test_additional_paths_are_not_promoted_into_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            extra = Path(temp) / "Extra.sfc"
            rom.write_bytes(b"rom")
            extra.write_bytes(b"extra")
            data = {"123": self._record(rom, additional_paths=[str(extra)])}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            plan = build_legacy_rom_metadata_modernization_plan(audit, data, "rev")
            self.assertEqual(len(plan.operations), 1)
            self.assertEqual(plan.operations[0].canonical_path, str(rom.resolve()))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_source_becoming_symlink_after_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "Hack.sfc"
            target = root / "Target.sfc"
            rom.write_bytes(b"rom")
            target.write_bytes(b"rom")
            data = {"123": self._record(rom)}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            rom.unlink()
            try:
                os.symlink(target, rom)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "symbolic link"):
                build_legacy_rom_metadata_modernization_plan(audit, data, "rev")


if __name__ == "__main__":
    unittest.main()
