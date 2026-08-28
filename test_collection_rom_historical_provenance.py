import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from collection_rom_historical_provenance import (
    HistoricalRomProvenanceReviewError,
    STATUS_IN_PLACE,
    STATUS_READY,
    STATUS_TARGET_COLLISION,
    STATUS_TARGET_OCCUPIED,
    build_historical_rom_provenance_review,
    required_historical_submission_ids,
)
from collection_rom_organization import build_collection_rom_organization_audit


class HistoricalRomProvenanceReviewTests(unittest.TestCase):
    def _record(self, path, *, current_id=200, provenance=100, name=None):
        payload = path.read_bytes() if path.exists() else b"rom"
        import hashlib
        return {
            "title": f"Current {current_id}",
            "hack_type": "standard",
            "current_difficulty": "Normal",
            "file_path": str(path),
            "files": [
                {
                    "path": str(path),
                    "name": name or path.name,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                    "primary": True,
                    "smwc_submission_id": provenance,
                }
            ],
        }

    def _detail(self, identifier=100, *, difficulty="Advanced", hack_types=("kaizo",), title="Old Hack"):
        return SimpleNamespace(
            metadata=SimpleNamespace(
                smwc_submission_id=identifier,
                title=title,
                difficulty=difficulty,
                hack_types=hack_types,
            )
        )

    def test_required_ids_include_only_explicit_historical_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "old.sfc"
            old.write_bytes(b"old")
            same = root / "same.sfc"
            same.write_bytes(b"same")
            unknown = root / "unknown.sfc"
            unknown.write_bytes(b"unknown")
            historical = self._record(old, current_id=200, provenance=100)
            current = self._record(same, current_id=300, provenance=300)
            missing_provenance = self._record(unknown, current_id=400, provenance=400)
            missing_provenance["files"][0].pop("smwc_submission_id")
            audit = build_collection_rom_organization_audit(
                {"200": historical, "300": current, "400": missing_provenance},
                str(root / "library"),
            )
            self.assertEqual(required_historical_submission_ids(audit), (100,))
            self.assertEqual(audit.historical_provenance_count, 1)

    def test_review_uses_historical_metadata_not_current_collection_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "elsewhere" / "Old.sfc"
            rom.parent.mkdir()
            rom.write_bytes(b"rom")
            record = self._record(rom)
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))

            review = build_historical_rom_provenance_review(
                audit, {"200": record}, "revision", (self._detail(),)
            )

            self.assertEqual(review.ready_count, 1)
            row = review.rows[0]
            self.assertEqual(row.status, STATUS_READY)
            self.assertEqual(row.historical_smwc_submission_id, 100)
            self.assertIn("04 - Advanced", row.expected_path)
            self.assertNotIn("02 - Normal", row.expected_path)
            self.assertIn("SMWC 100", row.detail)

    def test_review_marks_historical_target_already_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "library" / "Kaizo" / "04 - Advanced" / "Old.sfc"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"rom")
            record = self._record(target)
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            review = build_historical_rom_provenance_review(
                audit, {"200": record}, "revision", (self._detail(),)
            )
            self.assertEqual(review.rows[0].status, STATUS_IN_PLACE)

    def test_review_blocks_existing_historical_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "elsewhere" / "Old.sfc"
            rom.parent.mkdir()
            rom.write_bytes(b"rom")
            target = root / "library" / "Kaizo" / "04 - Advanced" / "Old.sfc"
            target.parent.mkdir(parents=True)
            target.write_bytes(b"occupied")
            record = self._record(rom)
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            review = build_historical_rom_provenance_review(
                audit, {"200": record}, "revision", (self._detail(),)
            )
            self.assertEqual(review.rows[0].status, STATUS_TARGET_OCCUPIED)

    def test_review_detects_collision_between_historical_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a = root / "a" / "Same.sfc"
            b = root / "b" / "Same.sfc"
            a.parent.mkdir(); b.parent.mkdir()
            a.write_bytes(b"a"); b.write_bytes(b"b")
            first = self._record(a, current_id=200, provenance=100)
            second = self._record(b, current_id=300, provenance=101)
            audit = build_collection_rom_organization_audit(
                {"200": first, "300": second}, str(root / "library")
            )
            review = build_historical_rom_provenance_review(
                audit,
                {"200": first, "300": second},
                "revision",
                (self._detail(100), self._detail(101)),
            )
            self.assertEqual({row.status for row in review.rows}, {STATUS_TARGET_COLLISION})

    def test_review_detects_collision_with_normal_audit_move_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            historical_path = root / "historical" / "Same.sfc"
            current_path = root / "current" / "Same.sfc"
            historical_path.parent.mkdir(); current_path.parent.mkdir()
            historical_path.write_bytes(b"old"); current_path.write_bytes(b"new")
            historical = self._record(historical_path, current_id=200, provenance=100)
            current = self._record(current_path, current_id=300, provenance=300)
            current["hack_type"] = "kaizo"
            current["current_difficulty"] = "Advanced"
            audit = build_collection_rom_organization_audit(
                {"200": historical, "300": current}, str(root / "library")
            )
            review = build_historical_rom_provenance_review(
                audit, {"200": historical, "300": current}, "revision", (self._detail(),)
            )
            self.assertEqual(review.rows[0].status, STATUS_TARGET_COLLISION)

    def test_unknown_provenance_review_rows_remain_explicitly_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old = root / "old.sfc"; old.write_bytes(b"old")
            unknown = root / "unknown.sfc"; unknown.write_bytes(b"unknown")
            historical = self._record(old, current_id=200, provenance=100)
            missing = self._record(unknown, current_id=300, provenance=300)
            missing["files"][0].pop("smwc_submission_id")
            audit = build_collection_rom_organization_audit(
                {"200": historical, "300": missing}, str(root / "library")
            )
            review = build_historical_rom_provenance_review(
                audit,
                {"200": historical, "300": missing},
                "revision",
                (self._detail(),),
            )
            self.assertEqual(review.excluded_unknown_provenance_count, 1)

    def test_missing_requested_detail_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "old.sfc"; rom.write_bytes(b"rom")
            record = self._record(rom)
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            with self.assertRaises(HistoricalRomProvenanceReviewError):
                build_historical_rom_provenance_review(audit, {"200": record}, "revision", ())

    def test_review_detects_collection_asset_change_after_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            rom = root / "old.sfc"; rom.write_bytes(b"rom")
            record = self._record(rom)
            audit = build_collection_rom_organization_audit({"200": record}, str(root / "library"))
            changed = self._record(rom)
            changed["files"][0]["smwc_submission_id"] = 99
            with self.assertRaises(HistoricalRomProvenanceReviewError):
                build_historical_rom_provenance_review(
                    audit, {"200": changed}, "revision", (self._detail(),)
                )


if __name__ == "__main__":
    unittest.main()
