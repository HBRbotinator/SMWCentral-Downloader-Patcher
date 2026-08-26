import hashlib
import tempfile
import unittest
from pathlib import Path

from collection_rom_organization import build_collection_rom_organization_audit
from collection_rom_organization_plan import (
    CollectionRomOrganizationPlanError,
    build_collection_rom_organization_plan,
)


class CollectionRomOrganizationPlanTests(unittest.TestCase):
    def _record(self, path: Path, *, smwc_id=123, title="Hack"):
        content = path.read_bytes()
        return {
            "title": title,
            "hack_type": "kaizo",
            "current_difficulty": "Advanced",
            "file_path": str(path),
            "files": [
                {
                    "path": str(path),
                    "name": path.name,
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "size_bytes": len(content),
                    "primary": True,
                    "smwc_submission_id": smwc_id,
                    "ingestion_sources": ["tool_patch"],
                }
            ],
        }

    def test_plan_freezes_only_safe_would_move_rows(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "elsewhere" / "Hack.sfc"
            source.parent.mkdir()
            source.write_bytes(b"rom-bytes")
            record = self._record(source)
            data = {"123": record}
            audit = build_collection_rom_organization_audit(data, str(root / "library"))

            plan = build_collection_rom_organization_plan(audit, data, "sha256:collection")

            self.assertEqual(len(plan.moves), 1)
            move = plan.moves[0]
            self.assertEqual(move.collection_id, "123")
            self.assertEqual(move.source_path, str(source.resolve()))
            self.assertTrue(move.target_path.endswith("Hack.sfc"))
            self.assertEqual(move.sha256, hashlib.sha256(b"rom-bytes").hexdigest())
            self.assertEqual(move.size_bytes, len(b"rom-bytes"))
            self.assertGreater(move.source_mtime_ns, 0)
            self.assertFalse(Path(move.target_path).exists())
            self.assertTrue(source.exists())

    def test_plan_excludes_audit_blockers_but_reports_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            safe = root / "safe" / "Safe.sfc"
            safe.parent.mkdir()
            safe.write_bytes(b"safe")
            missing = root / "missing" / "Missing.sfc"
            data = {
                "123": self._record(safe, smwc_id=123, title="Safe"),
                "456": {
                    "title": "Missing",
                    "hack_type": "kaizo",
                    "current_difficulty": "Advanced",
                    "file_path": str(missing),
                    "files": [
                        {
                            "path": str(missing),
                            "name": missing.name,
                            "sha256": "b" * 64,
                            "size_bytes": 3,
                            "primary": True,
                            "smwc_submission_id": 456,
                        }
                    ],
                },
            }
            audit = build_collection_rom_organization_audit(data, str(root / "library"))

            plan = build_collection_rom_organization_plan(audit, data, "sha256:collection")

            self.assertEqual(len(plan.moves), 1)
            self.assertEqual(plan.moves[0].collection_id, "123")
            self.assertEqual(plan.excluded_blocking_count, 1)
            self.assertEqual(plan.audit_row_count, 2)

    def test_plan_fails_if_target_becomes_occupied_after_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "elsewhere" / "Hack.sfc"
            source.parent.mkdir()
            source.write_bytes(b"rom")
            data = {"123": self._record(source)}
            audit = build_collection_rom_organization_audit(data, str(root / "library"))
            target = Path(audit.rows[0].expected_path)
            target.parent.mkdir(parents=True)
            target.write_bytes(b"other")

            with self.assertRaisesRegex(CollectionRomOrganizationPlanError, "occupied"):
                build_collection_rom_organization_plan(audit, data, "sha256:collection")

            self.assertEqual(source.read_bytes(), b"rom")
            self.assertEqual(target.read_bytes(), b"other")

    def test_plan_fails_if_source_size_changes_after_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "elsewhere" / "Hack.sfc"
            source.parent.mkdir()
            source.write_bytes(b"rom")
            data = {"123": self._record(source)}
            audit = build_collection_rom_organization_audit(data, str(root / "library"))
            source.write_bytes(b"changed-rom")

            with self.assertRaisesRegex(CollectionRomOrganizationPlanError, "size changed"):
                build_collection_rom_organization_plan(audit, data, "sha256:collection")

    def test_plan_fails_if_collection_layout_changes_after_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "elsewhere" / "Hack.sfc"
            source.parent.mkdir()
            source.write_bytes(b"rom")
            data = {"123": self._record(source)}
            audit = build_collection_rom_organization_audit(data, str(root / "library"))
            changed = {"123": dict(data["123"], current_difficulty="Expert")}

            with self.assertRaisesRegex(CollectionRomOrganizationPlanError, "layout.*changed"):
                build_collection_rom_organization_plan(audit, changed, "sha256:collection")

    def test_plan_requires_nonempty_collection_revision_token(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "elsewhere" / "Hack.sfc"
            source.parent.mkdir()
            source.write_bytes(b"rom")
            data = {"123": self._record(source)}
            audit = build_collection_rom_organization_audit(data, str(root / "library"))

            with self.assertRaisesRegex(CollectionRomOrganizationPlanError, "revision token"):
                build_collection_rom_organization_plan(audit, data, "")

    def test_plan_has_no_move_when_audit_has_no_safe_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "missing" / "Hack.sfc"
            data = {
                "123": {
                    "title": "Hack",
                    "hack_type": "kaizo",
                    "current_difficulty": "Advanced",
                    "file_path": str(missing),
                    "files": [
                        {
                            "path": str(missing),
                            "name": missing.name,
                            "sha256": "a" * 64,
                            "size_bytes": 3,
                            "primary": True,
                            "smwc_submission_id": 123,
                        }
                    ],
                }
            }
            audit = build_collection_rom_organization_audit(data, str(root / "library"))

            with self.assertRaisesRegex(CollectionRomOrganizationPlanError, "no safe ROM move"):
                build_collection_rom_organization_plan(audit, data, "sha256:collection")


if __name__ == "__main__":
    unittest.main()
