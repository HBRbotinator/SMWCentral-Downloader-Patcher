import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from collection_rom_legacy_metadata import build_legacy_rom_metadata_audit
from collection_rom_legacy_metadata_plan import (
    LegacyRomMetadataPlanError,
    build_reviewed_legacy_rom_metadata_modernization_plan,
)
from collection_rom_legacy_provenance_review import (
    build_legacy_rom_provenance_decision,
    build_legacy_rom_provenance_review,
)


class ReviewedLegacyRomMetadataPlanTests(unittest.TestCase):
    def _record(self, path, **extra):
        record = {
            "title": "Migrated Hack",
            "file_path": str(path),
            "prior_smwc_submission_ids": [100],
            "identity_migration_history": [{"source_key": "100", "target_key": "200"}],
            "notes": "preserve me",
        }
        record.update(extra)
        return record

    def _reviewed(self, rom, selected=100):
        data = {"200": self._record(rom)}
        audit = build_legacy_rom_metadata_audit(data, "rev")
        review = build_legacy_rom_provenance_review(audit, data, "rev")
        decision = build_legacy_rom_provenance_decision(review, {"200": selected})
        return data, audit, review, decision

    def test_explicit_prior_provenance_hashes_into_read_only_files_row(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            rom.write_bytes(b"legacy-rom")
            data, audit, review, decision = self._reviewed(rom, 100)
            before = repr(data)

            plan = build_reviewed_legacy_rom_metadata_modernization_plan(
                audit, review, decision, data, "rev"
            )

            self.assertEqual(1, len(plan.operations))
            operation = plan.operations[0]
            self.assertEqual("200", operation.collection_id)
            self.assertEqual(100, operation.smwc_submission_id)
            self.assertEqual(hashlib.sha256(b"legacy-rom").hexdigest(), operation.sha256)
            self.assertEqual(
                "legacy_collection_backfill_reviewed_provenance",
                operation.ingestion_source,
            )
            self.assertEqual(100, operation.proposed_files_row["smwc_submission_id"])
            self.assertEqual(before, repr(data))
            self.assertNotIn("files", data["200"])
            self.assertEqual(str(rom), data["200"]["file_path"])

    def test_explicit_current_provenance_is_preserved_as_selected(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.smc"
            rom.write_bytes(b"current")
            data, audit, review, decision = self._reviewed(rom, 200)
            operation = build_reviewed_legacy_rom_metadata_modernization_plan(
                audit, review, decision, data, "rev"
            ).operations[0]
            self.assertEqual(200, operation.smwc_submission_id)

    def test_changed_collection_revision_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"; rom.write_bytes(b"rom")
            data, audit, review, decision = self._reviewed(rom)
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "changed"):
                build_reviewed_legacy_rom_metadata_modernization_plan(
                    audit, review, decision, data, "new-rev"
                )

    def test_decision_must_cover_exact_review_set(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"; rom.write_bytes(b"rom")
            data, audit, review, decision = self._reviewed(rom)
            broken = type(decision)(decision.collection_revision_token, ())
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "exact reviewed"):
                build_reviewed_legacy_rom_metadata_modernization_plan(
                    audit, review, broken, data, "rev"
                )

    def test_new_files_metadata_after_review_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"; rom.write_bytes(b"rom")
            data, audit, review, decision = self._reviewed(rom)
            changed = {"200": self._record(rom, files=[{"path": str(rom)}])}
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, r"files\[\]"):
                build_reviewed_legacy_rom_metadata_modernization_plan(
                    audit, review, decision, changed, "rev"
                )

    def test_changed_path_ownership_after_review_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            original = Path(temp) / "Hack.sfc"; original.write_bytes(b"a")
            replacement = Path(temp) / "Other.sfc"; replacement.write_bytes(b"b")
            data, audit, review, decision = self._reviewed(original)
            changed = {"200": self._record(replacement)}
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "file_path ownership"):
                build_reviewed_legacy_rom_metadata_modernization_plan(
                    audit, review, decision, changed, "rev"
                )

    def test_size_change_after_review_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"; rom.write_bytes(b"abc")
            data, audit, review, decision = self._reviewed(rom)
            rom.write_bytes(b"abcd")
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "size.*changed"):
                build_reviewed_legacy_rom_metadata_modernization_plan(
                    audit, review, decision, data, "rev"
                )

    def test_file_change_during_hashing_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"; rom.write_bytes(b"abc")
            data, audit, review, decision = self._reviewed(rom)
            with mock.patch(
                "collection_rom_legacy_metadata_plan._stat_fingerprint",
                side_effect=[(1, 2, 3, 100, 200), (1, 2, 3, 101, 200)],
            ):
                with self.assertRaisesRegex(LegacyRomMetadataPlanError, "changed while SHA-256"):
                    build_reviewed_legacy_rom_metadata_modernization_plan(
                        audit, review, decision, data, "rev"
                    )

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink unavailable")
    def test_source_becoming_symlink_after_review_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"
            target = Path(temp) / "Target.sfc"
            rom.write_bytes(b"rom"); target.write_bytes(b"rom")
            data, audit, review, decision = self._reviewed(rom)
            rom.unlink()
            try:
                os.symlink(target, rom)
            except (OSError, NotImplementedError):
                self.skipTest("symlink creation unavailable")
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "symbolic link"):
                build_reviewed_legacy_rom_metadata_modernization_plan(
                    audit, review, decision, data, "rev"
                )

    def test_duplicate_current_ownership_after_review_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "Hack.sfc"; rom.write_bytes(b"rom")
            other = Path(temp) / "Other.sfc"; other.write_bytes(b"other")
            data, audit, review, decision = self._reviewed(rom)
            changed = {
                "200": data["200"],
                "300": {"title": "Other", "file_path": str(rom)},
            }
            with self.assertRaisesRegex(LegacyRomMetadataPlanError, "ownership changed"):
                build_reviewed_legacy_rom_metadata_modernization_plan(
                    audit, review, decision, changed, "rev"
                )


if __name__ == "__main__":
    unittest.main()
