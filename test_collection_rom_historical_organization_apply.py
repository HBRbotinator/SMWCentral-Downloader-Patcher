from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from collection_plan_apply import collection_revision_token
from collection_rom_historical_organization_apply import (
    apply_historical_rom_organization_execution_plan,
)
from collection_rom_historical_organization_execution_plan import (
    HistoricalRomOrganizationExecutionPlan,
)
from collection_rom_historical_organization_plan import HistoricalRomMoveOperation
from collection_rom_organization_apply import (
    CollectionRomOrganizationApplyError,
    CollectionRomOrganizationStaleStateError,
)
from hack_data_manager import HackDataManager


class HistoricalRomOrganizationApplyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data_root = self.root / "Data"
        self.data_root.mkdir()
        self.processed = self.data_root / "processed.json"
        self.source = self.root / "Loose" / "Hack.sfc"
        self.source.parent.mkdir()
        self.payload = b"historical-rom"
        self.source.write_bytes(self.payload)
        self.sha = hashlib.sha256(self.payload).hexdigest()
        self.target = self.root / "Library" / "Kaizo" / "04 - Advanced" / "Hack.sfc"
        self.record = {
            "title": "Current Hack",
            "file_path": str(self.source.resolve()),
            "files": [{
                "path": str(self.source.resolve()),
                "name": "Hack.sfc",
                "sha256": self.sha,
                "size_bytes": len(self.payload),
                "primary": True,
                "smwc_submission_id": 100,
                "ingestion_sources": ["tool_patch"],
                "future_field": {"kept": True},
            }],
            "notes": "keep",
        }
        self.processed.write_text(json.dumps({"200": self.record}, indent=2) + "\n", encoding="utf-8")
        self.manager = HackDataManager(str(self.processed))

    def _plan(self):
        stat = self.source.stat()
        move = HistoricalRomMoveOperation(
            collection_id="200",
            collection_title="Current Hack",
            asset_name="Hack.sfc",
            source_path=str(self.source.resolve()),
            target_path=str(self.target.resolve()),
            sha256=self.sha,
            size_bytes=len(self.payload),
            source_mtime_ns=stat.st_mtime_ns,
            primary=True,
            historical_smwc_submission_id=100,
            historical_title="Historical Hack",
            historical_hack_type="Kaizo",
            historical_difficulty="Advanced",
        )
        return HistoricalRomOrganizationExecutionPlan(
            output_dir=str((self.root / "Library").resolve()),
            collection_revision_token=collection_revision_token(self.manager),
            save_review_fingerprint="sha256:" + "1" * 64,
            rom_moves=(move,), save_moves=(), save_leaves=(),
            blocked_move_count=0, external_save_evidence_count=0,
            rom_only_acknowledgement_count=1,
        )

    def test_apply_moves_historical_asset_and_preserves_current_collection_identity(self):
        result = apply_historical_rom_organization_execution_plan(self._plan(), self.manager)
        self.assertEqual(1, result.rom_move_count)
        self.assertFalse(self.source.exists())
        self.assertEqual(self.payload, self.target.read_bytes())
        stored = json.loads(self.processed.read_text(encoding="utf-8"))
        self.assertIn("200", stored)
        row = stored["200"]["files"][0]
        self.assertEqual(100, row["smwc_submission_id"])
        self.assertEqual(str(self.target.resolve()), row["path"])
        self.assertEqual(str(self.target.resolve()), stored["200"]["file_path"])
        self.assertEqual({"kept": True}, row["future_field"])
        self.assertEqual("keep", stored["200"]["notes"])

    def test_changed_historical_provenance_blocks_before_copy(self):
        plan = self._plan()
        self.manager.data["200"]["files"][0]["smwc_submission_id"] = 200
        self.manager.save_data()
        with self.assertRaisesRegex(CollectionRomOrganizationStaleStateError, "Collection changed|provenance"):
            apply_historical_rom_organization_execution_plan(plan, self.manager)
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())

    def test_injected_precommit_failure_rolls_back(self):
        plan = self._plan()
        before = self.processed.read_bytes()
        with self.assertRaises(CollectionRomOrganizationApplyError):
            apply_historical_rom_organization_execution_plan(
                plan, self.manager, fail_after_target_copy=1
            )
        self.assertTrue(self.source.exists())
        self.assertFalse(self.target.exists())
        self.assertEqual(before, self.processed.read_bytes())


if __name__ == "__main__":
    unittest.main()
