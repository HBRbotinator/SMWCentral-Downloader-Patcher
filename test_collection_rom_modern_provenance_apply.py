import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from collection_plan_apply import collection_revision_token
from collection_rom_modern_provenance_apply import (
    ModernRomProvenanceApplyError,
    ModernRomProvenanceApplyStaleStateError,
    apply_modern_rom_provenance_decision,
)
from collection_rom_modern_provenance_review import (
    build_modern_rom_provenance_decision,
    build_modern_rom_provenance_review,
)
from collection_rom_organization import build_collection_rom_organization_audit
from hack_data_manager import HackDataManager


class ModernRomProvenanceApplyTests(unittest.TestCase):
    def _manager(self, root, data):
        path = root / "processed.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        manager = HackDataManager(str(path))
        manager.data = copy.deepcopy(data)
        manager.unsaved_changes = False
        return manager

    def _record(self, a, b=None):
        def row(path, primary):
            payload = path.read_bytes()
            return {
                "path": str(path), "name": path.name,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload), "primary": primary,
                "ingestion_sources": ["legacy"], "future_field": {"keep": True},
            }
        files = [row(a, True)]
        if b is not None:
            files.append(row(b, False))
        return {
            "title": "Migrated Hack", "hack_type": "standard",
            "current_difficulty": "Normal", "file_path": str(a),
            "files": files, "prior_smwc_submission_ids": [100],
            "notes": "keep me", "unknown": {"x": 1},
        }

    def _review_decision(self, manager, root, selections=None):
        audit = build_collection_rom_organization_audit(manager.data, str(root / "library"))
        review = build_modern_rom_provenance_review(audit, manager.data, collection_revision_token(manager))
        chosen = selections or {row.decision_key: 100 for row in review.rows}
        return review, build_modern_rom_provenance_decision(review, chosen)

    def test_applies_only_selected_provenance_and_preserves_fields(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); a = root / "a.sfc"; b = root / "b.sfc"
            a.write_bytes(b"a"); b.write_bytes(b"b")
            manager = self._manager(root, {"200": self._record(a, b)})
            review, decision = self._review_decision(manager, root)
            result = apply_modern_rom_provenance_decision(review, decision, manager)
            self.assertEqual((result.collection_record_count, result.asset_count), (1, 2))
            self.assertEqual([x["smwc_submission_id"] for x in manager.data["200"]["files"]], [100, 100])
            self.assertEqual(manager.data["200"]["notes"], "keep me")
            self.assertEqual(manager.data["200"]["unknown"], {"x": 1})
            self.assertTrue(manager.data["200"]["files"][0]["future_field"]["keep"])
            self.assertEqual(manager.data["200"]["file_path"], str(a))

    def test_current_id_selection_is_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); a = root / "a.sfc"; a.write_bytes(b"a")
            manager = self._manager(root, {"200": self._record(a)})
            audit = build_collection_rom_organization_audit(manager.data, str(root / "library"))
            review = build_modern_rom_provenance_review(audit, manager.data, collection_revision_token(manager))
            decision = build_modern_rom_provenance_decision(review, {review.rows[0].decision_key: 200})
            apply_modern_rom_provenance_decision(review, decision, manager)
            self.assertEqual(manager.data["200"]["files"][0]["smwc_submission_id"], 200)

    def test_removed_recorded_history_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); a = root / "a.sfc"; a.write_bytes(b"a")
            manager = self._manager(root, {"200": self._record(a)})
            review, decision = self._review_decision(manager, root)
            manager.data["200"]["prior_smwc_submission_ids"] = []
            with self.assertRaises(ModernRomProvenanceApplyStaleStateError):
                apply_modern_rom_provenance_decision(review, decision, manager)

    def test_changed_asset_metadata_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); a = root / "a.sfc"; a.write_bytes(b"a")
            manager = self._manager(root, {"200": self._record(a)})
            review, decision = self._review_decision(manager, root)
            manager.data["200"]["files"][0]["sha256"] = "0" * 64
            with self.assertRaises(ModernRomProvenanceApplyStaleStateError):
                apply_modern_rom_provenance_decision(review, decision, manager)

    def test_existing_provenance_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); a = root / "a.sfc"; a.write_bytes(b"a")
            manager = self._manager(root, {"200": self._record(a)})
            review, decision = self._review_decision(manager, root)
            manager.data["200"]["files"][0]["smwc_submission_id"] = 200
            with self.assertRaises(ModernRomProvenanceApplyStaleStateError):
                apply_modern_rom_provenance_decision(review, decision, manager)

    def test_atomic_failure_does_not_partially_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); a = root / "a.sfc"; a.write_bytes(b"a")
            manager = self._manager(root, {"200": self._record(a)})
            before = copy.deepcopy(manager.data)
            review, decision = self._review_decision(manager, root)
            with self.assertRaises(ModernRomProvenanceApplyError):
                apply_modern_rom_provenance_decision(review, decision, manager, fail_before_replace=True)
            self.assertEqual(manager.data, before)

    def test_missing_rom_file_does_not_block_metadata_only_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); a = root / "a.sfc"; a.write_bytes(b"a")
            manager = self._manager(root, {"200": self._record(a)})
            review, decision = self._review_decision(manager, root)
            a.unlink()
            apply_modern_rom_provenance_decision(review, decision, manager)
            self.assertEqual(manager.data["200"]["files"][0]["smwc_submission_id"], 100)


if __name__ == "__main__":
    unittest.main()
