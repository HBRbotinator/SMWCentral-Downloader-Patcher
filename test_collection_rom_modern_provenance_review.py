import hashlib
import tempfile
import unittest
from pathlib import Path

from collection_rom_modern_provenance_review import (
    ModernRomProvenanceReviewError,
    build_modern_rom_provenance_decision,
    build_modern_rom_provenance_review,
    missing_modern_provenance_audit_rows,
)
from collection_rom_organization import build_collection_rom_organization_audit


class ModernRomProvenanceReviewTests(unittest.TestCase):
    def _record(self, path, *, prior=None, primary=True, provenance_missing=True):
        payload = path.read_bytes()
        row = {
            "path": str(path),
            "name": path.name,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
            "primary": primary,
            "ingestion_sources": ["legacy"],
        }
        if not provenance_missing:
            row["smwc_submission_id"] = 200
        record = {
            "title": "Migrated Hack",
            "hack_type": "standard",
            "current_difficulty": "Normal",
            "file_path": str(path) if primary else "",
            "files": [row],
        }
        if prior is not None:
            record["prior_smwc_submission_ids"] = list(prior)
        return record

    def test_review_exposes_missing_modern_provenance_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "missing.sfc"; missing.write_bytes(b"missing")
            known = root / "known.sfc"; known.write_bytes(b"known")
            first = self._record(missing, prior=[100])
            second = self._record(known, provenance_missing=False)
            audit = build_collection_rom_organization_audit(
                {"200": first, "300": second}, str(root / "library")
            )
            rows = missing_modern_provenance_audit_rows(audit)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].collection_id, "200")
            self.assertEqual(audit.missing_provenance_count, 1)

    def test_review_candidates_are_current_and_recorded_prior_ids(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "hack.sfc"; rom.write_bytes(b"rom")
            record = self._record(rom, prior=[100, "150"])
            record["identity_migration_history"] = [
                {"source_key": "75", "target_key": "200"},
                {"source_key": "usr_old", "target_key": "200"},
            ]
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            review = build_modern_rom_provenance_review(audit, {"200": record}, "revision")
            self.assertEqual(review.rows[0].candidate_smwc_submission_ids, (75, 100, 150, 200))
            self.assertEqual(review.rows[0].current_smwc_submission_id, 200)

    def test_current_id_only_is_still_an_explicit_choice(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "hack.sfc"; rom.write_bytes(b"rom")
            record = self._record(rom)
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            review = build_modern_rom_provenance_review(audit, {"200": record}, "revision")
            self.assertEqual(review.rows[0].candidate_smwc_submission_ids, (200,))
            decision = build_modern_rom_provenance_decision(
                review, {review.rows[0].decision_key: 200}
            )
            self.assertEqual(decision.selections, (("200", str(rom.absolute()), 200),))

    def test_multiple_assets_on_same_collection_have_distinct_decision_keys(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a = root / "a.sfc"; a.write_bytes(b"a")
            b = root / "b.sfc"; b.write_bytes(b"b")
            record = self._record(a, prior=[100])
            second = self._record(b)["files"][0]
            second["primary"] = False
            record["files"].append(second)
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            review = build_modern_rom_provenance_review(audit, {"200": record}, "revision")
            self.assertEqual(len(review.rows), 2)
            self.assertEqual(len({row.decision_key for row in review.rows}), 2)
            decision = build_modern_rom_provenance_decision(
                review, {row.decision_key: 100 for row in review.rows}
            )
            self.assertEqual(len(decision.selections), 2)

    def test_invalid_unrecorded_selection_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "hack.sfc"; rom.write_bytes(b"rom")
            record = self._record(rom, prior=[100])
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            review = build_modern_rom_provenance_review(audit, {"200": record}, "revision")
            with self.assertRaises(ModernRomProvenanceReviewError):
                build_modern_rom_provenance_decision(
                    review, {review.rows[0].decision_key: 999}
                )

    def test_asset_provenance_added_after_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "hack.sfc"; rom.write_bytes(b"rom")
            record = self._record(rom, prior=[100])
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            changed = self._record(rom, prior=[100], provenance_missing=False)
            with self.assertRaises(ModernRomProvenanceReviewError):
                build_modern_rom_provenance_review(audit, {"200": changed}, "revision")

    def test_asset_hash_change_after_audit_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "hack.sfc"; rom.write_bytes(b"rom")
            record = self._record(rom, prior=[100])
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            changed = self._record(rom, prior=[100])
            changed["files"][0]["sha256"] = "0" * 64
            with self.assertRaises(ModernRomProvenanceReviewError):
                build_modern_rom_provenance_review(audit, {"200": changed}, "revision")


if __name__ == "__main__":
    unittest.main()
