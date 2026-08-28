import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from collection_rom_historical_organization_plan import (
    HistoricalRomOrganizationPlanError,
    build_historical_rom_organization_plan,
)
from collection_rom_historical_provenance import build_historical_rom_provenance_review
from collection_rom_organization import build_collection_rom_organization_audit


class HistoricalRomOrganizationPlanTests(unittest.TestCase):
    def _record(self, path: Path, *, current_id=200, provenance=100, title="Current"):
        payload = path.read_bytes()
        return {
            "title": title,
            "hack_type": "standard",
            "current_difficulty": "Normal",
            "file_path": str(path),
            "files": [{
                "path": str(path),
                "name": path.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
                "primary": True,
                "smwc_submission_id": provenance,
                "ingestion_sources": ["tool_patch"],
            }],
        }

    def _detail(self, identifier=100, *, title="Historical", difficulty="Advanced", hack_type="Kaizo"):
        class Metadata:
            smwc_submission_id = identifier
            pass
        metadata = Metadata()
        metadata.title = title
        metadata.difficulty = difficulty
        metadata.hack_types = (hack_type,)
        return metadata

    def _review(self, root: Path, record, revision="sha256:collection"):
        audit = build_collection_rom_organization_audit(
            {"200": record}, str(root / "library")
        )
        return build_historical_rom_provenance_review(
            audit, {"200": record}, revision, (self._detail(),)
        )

    def test_plan_freezes_reviewed_historical_metadata_and_exact_rom_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "elsewhere" / "Old.sfc"
            source.parent.mkdir()
            source.write_bytes(b"historical-rom")
            record = self._record(source)
            review = self._review(root, record)

            plan = build_historical_rom_organization_plan(
                review, {"200": record}, "sha256:collection"
            )

            self.assertEqual(len(plan.moves), 1)
            move = plan.moves[0]
            self.assertEqual(move.collection_id, "200")
            self.assertEqual(move.historical_smwc_submission_id, 100)
            self.assertEqual(move.historical_title, "Historical")
            self.assertEqual(move.historical_hack_type, "Kaizo")
            self.assertEqual(move.historical_difficulty, "Advanced")
            self.assertEqual(move.sha256, hashlib.sha256(b"historical-rom").hexdigest())
            self.assertEqual(move.size_bytes, len(b"historical-rom"))
            self.assertGreater(move.source_mtime_ns, 0)
            self.assertIn("04 - Advanced", move.target_path)
            self.assertTrue(source.exists())
            self.assertFalse(Path(move.target_path).exists())

    def test_plan_requires_same_collection_revision_as_review(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Old.sfc"; source.write_bytes(b"rom")
            record = self._record(source)
            review = self._review(root, record)

            with self.assertRaisesRegex(HistoricalRomOrganizationPlanError, "Collection changed"):
                build_historical_rom_organization_plan(
                    review, {"200": record}, "sha256:different"
                )

    def test_plan_rejects_collection_asset_provenance_change(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Old.sfc"; source.write_bytes(b"rom")
            record = self._record(source)
            review = self._review(root, record)
            changed = self._record(source)
            changed["files"][0]["smwc_submission_id"] = 99

            with self.assertRaisesRegex(HistoricalRomOrganizationPlanError, "metadata changed"):
                build_historical_rom_organization_plan(
                    review, {"200": changed}, "sha256:collection"
                )

    def test_plan_rejects_changed_rom_bytes_even_when_size_is_same(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Old.sfc"; source.write_bytes(b"abc")
            record = self._record(source)
            review = self._review(root, record)
            source.write_bytes(b"xyz")
            stat = source.stat()
            os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))

            with self.assertRaisesRegex(HistoricalRomOrganizationPlanError, "SHA-256"):
                build_historical_rom_organization_plan(
                    review, {"200": record}, "sha256:collection"
                )

    def test_plan_rejects_source_replaced_by_symlink_after_review(self):
        if not hasattr(os, "symlink"):
            self.skipTest("symlink unsupported")
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Old.sfc"; source.write_bytes(b"rom")
            other = root / "Other.sfc"; other.write_bytes(b"rom")
            record = self._record(source)
            review = self._review(root, record)
            source.unlink()
            try:
                source.symlink_to(other)
            except OSError as error:
                self.skipTest(f"symlink unavailable: {error}")

            with self.assertRaisesRegex(HistoricalRomOrganizationPlanError, "symbolic link"):
                build_historical_rom_organization_plan(
                    review, {"200": record}, "sha256:collection"
                )

    def test_plan_rejects_target_that_becomes_occupied(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Old.sfc"; source.write_bytes(b"rom")
            record = self._record(source)
            review = self._review(root, record)
            target = Path(review.rows[0].expected_path)
            target.parent.mkdir(parents=True)
            target.write_bytes(b"occupied")

            with self.assertRaisesRegex(HistoricalRomOrganizationPlanError, "occupied"):
                build_historical_rom_organization_plan(
                    review, {"200": record}, "sha256:collection"
                )

    def test_plan_has_no_ready_rows_when_review_only_in_place(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "library" / "Kaizo" / "04 - Advanced" / "Old.sfc"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"rom")
            record = self._record(source)
            review = self._review(root, record)

            with self.assertRaisesRegex(HistoricalRomOrganizationPlanError, "no ready"):
                build_historical_rom_organization_plan(
                    review, {"200": record}, "sha256:collection"
                )

    def test_plan_rejects_file_that_changes_during_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "Old.sfc"; source.write_bytes(b"rom")
            record = self._record(source)
            review = self._review(root, record)

            original_stat = os.stat
            calls = {"count": 0}
            def changing_stat(path, *args, **kwargs):
                result = original_stat(path, *args, **kwargs)
                if Path(path) == source and kwargs.get("follow_symlinks") is False:
                    calls["count"] += 1
                    if calls["count"] >= 2:
                        class Changed:
                            st_size = result.st_size
                            st_mtime = result.st_mtime
                            st_mtime_ns = result.st_mtime_ns + 1
                            st_dev = result.st_dev
                            st_ino = result.st_ino
                        return Changed()
                return result

            with mock.patch("collection_rom_historical_organization_plan.os.stat", side_effect=changing_stat):
                with self.assertRaisesRegex(HistoricalRomOrganizationPlanError, "changed while"):
                    build_historical_rom_organization_plan(
                        review, {"200": record}, "sha256:collection"
                    )


if __name__ == "__main__":
    unittest.main()
