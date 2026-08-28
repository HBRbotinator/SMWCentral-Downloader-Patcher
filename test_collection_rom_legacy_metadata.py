import os
import tempfile
import unittest
from pathlib import Path

from collection_rom_legacy_metadata import (
    STATUS_DUPLICATE_PATH,
    STATUS_MISSING_SOURCE,
    STATUS_READY,
    STATUS_REVIEW_METADATA,
    STATUS_REVIEW_PROVENANCE,
    STATUS_SYMLINK,
    build_legacy_rom_metadata_audit,
)


class LegacyRomMetadataAuditTests(unittest.TestCase):
    def _legacy_record(self, path, title="Hack"):
        return {"title": title, "file_path": str(path)}

    def test_numeric_legacy_record_is_ready_with_current_submission_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"rom")

            audit = build_legacy_rom_metadata_audit({"123": self._legacy_record(rom)})

            self.assertEqual(audit.ready_count, 1)
            row = audit.rows[0]
            self.assertEqual(row.status, STATUS_READY)
            self.assertEqual(row.proposed_smwc_submission_id, 123)
            self.assertEqual(row.size_bytes, 3)
            self.assertEqual(Path(row.current_path), rom.resolve())

    def test_local_legacy_record_is_ready_without_numeric_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Local.smc"
            rom.write_bytes(b"rom")
            audit = build_legacy_rom_metadata_audit(
                {"usr_0123456789abcdef": self._legacy_record(rom, "Local")}
            )
            self.assertEqual(audit.rows[0].status, STATUS_READY)
            self.assertIsNone(audit.rows[0].proposed_smwc_submission_id)

    def test_numeric_record_with_prior_identity_migration_requires_provenance_review(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"rom")
            record = self._legacy_record(rom)
            record["prior_smwc_submission_ids"] = [100]

            audit = build_legacy_rom_metadata_audit({"200": record})

            self.assertEqual(audit.rows[0].status, STATUS_REVIEW_PROVENANCE)
            self.assertIsNone(audit.rows[0].proposed_smwc_submission_id)

    def test_missing_legacy_path_is_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "Missing.sfc"
            audit = build_legacy_rom_metadata_audit({"123": self._legacy_record(missing)})
            self.assertEqual(audit.rows[0].status, STATUS_MISSING_SOURCE)
            self.assertEqual(audit.blocking_count, 1)

    def test_unsupported_extension_requires_metadata_review(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.zip"
            rom.write_bytes(b"archive")
            audit = build_legacy_rom_metadata_audit({"123": self._legacy_record(rom)})
            self.assertEqual(audit.rows[0].status, STATUS_REVIEW_METADATA)

    def test_existing_modern_files_rows_are_not_part_of_legacy_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"rom")
            record = self._legacy_record(rom)
            record["files"] = [{"path": str(rom), "primary": True}]
            audit = build_legacy_rom_metadata_audit({"123": record})
            self.assertEqual(audit.rows, ())

    def test_same_legacy_path_claimed_by_two_records_is_blocked(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Shared.sfc"
            rom.write_bytes(b"rom")
            audit = build_legacy_rom_metadata_audit(
                {
                    "123": self._legacy_record(rom, "A"),
                    "456": self._legacy_record(rom, "B"),
                }
            )
            self.assertEqual(
                {row.status for row in audit.rows},
                {STATUS_DUPLICATE_PATH},
            )
            self.assertEqual(audit.blocking_count, 2)

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_symlinked_legacy_rom_is_not_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            real = root / "real.sfc"
            link = root / "link.sfc"
            real.write_bytes(b"rom")
            try:
                os.symlink(real, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            audit = build_legacy_rom_metadata_audit({"123": self._legacy_record(link)})
            self.assertEqual(audit.rows[0].status, STATUS_SYMLINK)

    def test_audit_does_not_mutate_input(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"rom")
            record = self._legacy_record(rom)
            original = dict(record)
            build_legacy_rom_metadata_audit({"123": record})
            self.assertEqual(record, original)


if __name__ == "__main__":
    unittest.main()
