import os
import tempfile
import unittest
from pathlib import Path

from collection_rom_organization import (
    STATUS_IN_PLACE,
    STATUS_LEGACY_PATH,
    STATUS_MISSING_SOURCE,
    STATUS_NEEDS_ORGANIZATION,
    STATUS_REVIEW_PROVENANCE,
    STATUS_REVIEW_METADATA,
    STATUS_TARGET_COLLISION,
    STATUS_TARGET_OCCUPIED,
    assess_collection_rom_location,
    build_collection_rom_organization_audit,
    expected_collection_rom_path,
)


class CollectionRomOrganizationTests(unittest.TestCase):
    def _record(self, path, *, smwc_id=123, title="Hack", primary=True):
        return {
            "title": title,
            "hack_type": "kaizo",
            "current_difficulty": "Advanced",
            "file_path": str(path),
            "files": [
                {
                    "path": str(path),
                    "name": Path(path).name,
                    "primary": primary,
                    "smwc_submission_id": smwc_id,
                }
            ],
        }

    def test_expected_path_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "library"
            expected = expected_collection_rom_path(
                str(output), "kaizo", "Advanced", "Hack.sfc"
            )
            self.assertTrue(expected.endswith(os.path.join("04 - Advanced", "Hack.sfc")))
            self.assertFalse(output.exists())

    def test_primary_location_assessment_reports_drift_without_moving(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "old" / "Hack.sfc"
            current.parent.mkdir()
            current.write_bytes(b"rom")
            output = root / "library"
            record = self._record(current)

            assessment = assess_collection_rom_location(record, str(output))

            self.assertIsNotNone(assessment)
            self.assertTrue(assessment.exists)
            self.assertTrue(assessment.needs_organization)
            self.assertTrue(current.exists())
            self.assertFalse(output.exists())

    def test_audit_marks_current_submission_asset_as_move_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "elsewhere" / "Hack.sfc"
            current.parent.mkdir()
            current.write_bytes(b"rom")

            audit = build_collection_rom_organization_audit(
                {"123": self._record(current)}, str(root / "library")
            )

            self.assertEqual(audit.move_candidate_count, 1)
            self.assertEqual(audit.blocking_count, 0)
            self.assertEqual(audit.rows[0].status, STATUS_NEEDS_ORGANIZATION)
            self.assertTrue(current.exists())
            self.assertFalse((root / "library").exists())

    def test_audit_marks_asset_already_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "library"
            current = Path(
                expected_collection_rom_path(
                    str(output), "kaizo", "Advanced", "Hack.sfc"
                )
            )
            current.parent.mkdir(parents=True)
            current.write_bytes(b"rom")

            audit = build_collection_rom_organization_audit(
                {"123": self._record(current)}, str(output)
            )

            self.assertEqual(audit.in_place_count, 1)
            self.assertEqual(audit.rows[0].status, STATUS_IN_PLACE)

    def test_audit_marks_missing_source_as_blocking(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "missing" / "Hack.sfc"
            audit = build_collection_rom_organization_audit(
                {"123": self._record(missing)}, str(root / "library")
            )
            self.assertEqual(audit.rows[0].status, STATUS_MISSING_SOURCE)
            self.assertEqual(audit.blocking_count, 1)

    def test_audit_marks_existing_target_as_blocking_without_touching_it(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "elsewhere" / "Hack.sfc"
            current.parent.mkdir()
            current.write_bytes(b"source")
            expected = Path(
                expected_collection_rom_path(
                    str(root / "library"), "kaizo", "Advanced", "Hack.sfc"
                )
            )
            expected.parent.mkdir(parents=True)
            expected.write_bytes(b"occupied")

            audit = build_collection_rom_organization_audit(
                {"123": self._record(current)}, str(root / "library")
            )

            self.assertEqual(audit.rows[0].status, STATUS_TARGET_OCCUPIED)
            self.assertEqual(current.read_bytes(), b"source")
            self.assertEqual(expected.read_bytes(), b"occupied")

    def test_audit_refuses_to_infer_layout_for_retained_old_submission_asset(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "old" / "Old.sfc"
            current.parent.mkdir()
            current.write_bytes(b"rom")
            record = self._record(current, smwc_id=100)

            audit = build_collection_rom_organization_audit(
                {"200": record}, str(root / "library")
            )

            row = audit.rows[0]
            self.assertEqual(row.status, STATUS_REVIEW_PROVENANCE)
            self.assertEqual(row.expected_path, "")
            self.assertIn("SMWC 100", row.detail)
            self.assertIn("SMWC 200", row.detail)

    def test_audit_refuses_numeric_modern_asset_with_unknown_provenance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "old" / "Hack.sfc"
            current.parent.mkdir()
            current.write_bytes(b"rom")
            record = self._record(current)
            del record["files"][0]["smwc_submission_id"]

            audit = build_collection_rom_organization_audit(
                {"123": record}, str(root / "library")
            )

            self.assertEqual(audit.rows[0].status, STATUS_REVIEW_PROVENANCE)
            self.assertEqual(audit.rows[0].expected_path, "")

    def test_local_modern_asset_can_use_local_record_layout(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "elsewhere" / "Local.sfc"
            current.parent.mkdir()
            current.write_bytes(b"rom")
            record = self._record(current, smwc_id=None, title="Local")
            record["files"][0].pop("smwc_submission_id", None)

            audit = build_collection_rom_organization_audit(
                {"usr_0123456789abcdef": record}, str(root / "library")
            )

            self.assertEqual(audit.rows[0].status, STATUS_NEEDS_ORGANIZATION)
            self.assertTrue(audit.rows[0].expected_path)

    def test_legacy_file_path_is_visible_but_not_a_move_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            current = root / "legacy" / "Hack.sfc"
            current.parent.mkdir()
            current.write_bytes(b"rom")
            record = self._record(current)
            record.pop("files")

            audit = build_collection_rom_organization_audit(
                {"123": record}, str(root / "library")
            )

            self.assertEqual(audit.rows[0].status, STATUS_LEGACY_PATH)
            self.assertEqual(audit.rows[0].expected_path, "")

    def test_duplicate_target_candidates_are_blocked_as_collisions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "a" / "Same.sfc"
            second = root / "b" / "Same.sfc"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"a")
            second.write_bytes(b"b")
            record_a = self._record(first, title="A")
            record_b = self._record(second, title="B")

            audit = build_collection_rom_organization_audit(
                {"123": record_a, "456": self._record(second, smwc_id=456, title="B")},
                str(root / "library"),
            )

            self.assertEqual(
                [row.status for row in audit.rows],
                [STATUS_TARGET_COLLISION, STATUS_TARGET_COLLISION],
            )
            self.assertEqual(audit.blocking_count, 2)


    def test_malformed_modern_files_fail_closed_as_metadata_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            record = {
                "title": "Broken",
                "hack_type": "kaizo",
                "current_difficulty": "Advanced",
                "file_path": str(root / "Broken.sfc"),
                "files": [{"name": "Missing path"}],
            }

            audit = build_collection_rom_organization_audit(
                {"123": record}, str(root / "library")
            )

            self.assertEqual(audit.rows[0].status, STATUS_REVIEW_METADATA)
            self.assertEqual(audit.rows[0].expected_path, "")
            self.assertEqual(audit.blocking_count, 1)

    def test_empty_output_dir_fails_before_filesystem_work(self):
        with self.assertRaisesRegex(ValueError, "output directory"):
            build_collection_rom_organization_audit({}, "")


if __name__ == "__main__":
    unittest.main()
