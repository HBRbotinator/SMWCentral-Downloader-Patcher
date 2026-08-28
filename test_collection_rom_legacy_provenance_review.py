import tempfile
import unittest
from pathlib import Path

from collection_rom_legacy_metadata import build_legacy_rom_metadata_audit
from collection_rom_legacy_provenance_review import (
    LegacyRomProvenanceReviewError,
    build_legacy_rom_provenance_decision,
    build_legacy_rom_provenance_review,
)


class LegacyRomProvenanceReviewTests(unittest.TestCase):
    def _record(self, path, **extra):
        record = {"title": "Migrated Hack", "file_path": str(path), "prior_smwc_submission_ids": [100]}
        record.update(extra)
        return record

    def test_review_offers_only_recorded_current_and_prior_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "hack.sfc"
            rom.write_bytes(b"rom")
            data = {"200": self._record(rom, identity_migration_history=[{"source_key": "100", "target_key": "200"}])}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            review = build_legacy_rom_provenance_review(audit, data, "rev")
            self.assertEqual(1, len(review.rows))
            self.assertEqual((100, 200), review.rows[0].candidate_smwc_submission_ids)

    def test_numeric_history_ids_are_included_but_non_numeric_history_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "hack.sfc"
            rom.write_bytes(b"rom")
            data = {"300": self._record(rom, prior_smwc_submission_ids=[100, "250"], identity_migration_history=[{"source_key": "usr_deadbeef", "target_key": "300"}])}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            review = build_legacy_rom_provenance_review(audit, data, "rev")
            self.assertEqual((100, 250, 300), review.rows[0].candidate_smwc_submission_ids)

    def test_changed_revision_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "hack.sfc"
            rom.write_bytes(b"rom")
            data = {"200": self._record(rom)}
            audit = build_legacy_rom_metadata_audit(data, "old")
            with self.assertRaises(LegacyRomProvenanceReviewError):
                build_legacy_rom_provenance_review(audit, data, "new")

    def test_selection_must_be_one_of_recorded_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "hack.sfc"
            rom.write_bytes(b"rom")
            data = {"200": self._record(rom)}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            review = build_legacy_rom_provenance_review(audit, data, "rev")
            with self.assertRaises(LegacyRomProvenanceReviewError):
                build_legacy_rom_provenance_decision(review, {"200": 999})

    def test_all_rows_require_explicit_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            rom1 = Path(temp) / "one.sfc"; rom1.write_bytes(b"1")
            rom2 = Path(temp) / "two.sfc"; rom2.write_bytes(b"2")
            data = {"200": self._record(rom1), "400": self._record(rom2, prior_smwc_submission_ids=[300])}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            review = build_legacy_rom_provenance_review(audit, data, "rev")
            with self.assertRaises(LegacyRomProvenanceReviewError):
                build_legacy_rom_provenance_decision(review, {"200": 100})

    def test_valid_decisions_are_frozen_without_mutating_collection(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "hack.sfc"
            rom.write_bytes(b"rom")
            data = {"200": self._record(rom)}
            before = repr(data)
            audit = build_legacy_rom_metadata_audit(data, "rev")
            review = build_legacy_rom_provenance_review(audit, data, "rev")
            decision = build_legacy_rom_provenance_decision(review, {"200": 100})
            self.assertEqual((("200", 100),), decision.selections)
            self.assertEqual(before, repr(data))
            self.assertEqual(b"rom", rom.read_bytes())

    def test_unknown_legacy_identity_is_not_promoted_into_choice_review(self):
        with tempfile.TemporaryDirectory() as temp:
            rom = Path(temp) / "hack.sfc"; rom.write_bytes(b"rom")
            data = {"legacy-key": {"title": "Odd", "file_path": str(rom)}}
            audit = build_legacy_rom_metadata_audit(data, "rev")
            with self.assertRaises(LegacyRomProvenanceReviewError):
                build_legacy_rom_provenance_review(audit, data, "rev")


if __name__ == "__main__":
    unittest.main()
