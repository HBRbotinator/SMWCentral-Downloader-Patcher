from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from collection_rom_historical_organization_execution_plan import (
    HistoricalRomOrganizationExecutionPlanError,
    build_historical_rom_organization_execution_plan,
)
from collection_rom_historical_organization_plan import (
    HistoricalRomMoveOperation,
    HistoricalRomOrganizationPlan,
)
from collection_rom_save_disposition import (
    SaveDisposition,
    companion_disposition_key,
    finalize_collection_rom_save_disposition_decision,
)
from collection_rom_save_impact import build_collection_rom_save_impact_review


class HistoricalRomOrganizationExecutionPlanTests(unittest.TestCase):
    def _plan(self, root: Path) -> HistoricalRomOrganizationPlan:
        source = root / "Old" / "Hack.sfc"
        source.parent.mkdir(parents=True)
        payload = b"historical-rom"
        source.write_bytes(payload)
        target = root / "ROMs" / "Kaizo" / "04 - Advanced" / "Hack.sfc"
        move = HistoricalRomMoveOperation(
            collection_id="200",
            collection_title="Current Hack",
            asset_name="Hack.sfc",
            source_path=str(source.resolve()),
            target_path=str(target.resolve()),
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            source_mtime_ns=source.stat().st_mtime_ns,
            primary=True,
            historical_smwc_submission_id=100,
            historical_title="Historical Hack",
            historical_hack_type="Kaizo",
            historical_difficulty="Advanced",
        )
        return HistoricalRomOrganizationPlan(
            output_dir=str((root / "ROMs").resolve()),
            collection_revision_token="revision",
            moves=(move,),
            review_row_count=1,
            in_place_count=0,
            excluded_blocking_count=0,
        )

    def test_freezes_historical_provenance_and_hashes_migrated_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"save")
            review = build_collection_rom_save_impact_review(plan)
            row = next(row for row in review.rows if row.source_kind == "colocated")
            key = companion_disposition_key(row.collection_id, row.rom_source_path, row.save_path)
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={key: SaveDisposition.MIGRATE_WITH_ROM},
            )
            final = build_historical_rom_organization_execution_plan(
                plan, decision, current_collection_revision_token="revision"
            )
            self.assertEqual(100, final.rom_moves[0].historical_smwc_submission_id)
            self.assertEqual("Historical Hack", final.rom_moves[0].historical_title)
            self.assertEqual(hashlib.sha256(b"save").hexdigest(), final.save_moves[0].sha256)
            self.assertFalse(Path(final.rom_moves[0].target_path).exists())

    def test_no_save_acknowledgement_can_freeze_rom_only_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            final = build_historical_rom_organization_execution_plan(
                plan, decision, current_collection_revision_token="revision"
            )
            self.assertEqual(1, len(final.rom_moves))
            self.assertEqual(0, len(final.save_moves))

    def test_collection_revision_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review, companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            with self.assertRaisesRegex(HistoricalRomOrganizationExecutionPlanError, "Collection changed"):
                build_historical_rom_organization_execution_plan(
                    plan, decision, current_collection_revision_token="changed"
                )

    def test_new_save_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review, companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            Path(plan.moves[0].source_path).with_suffix(".srm").write_bytes(b"new")
            with self.assertRaisesRegex(HistoricalRomOrganizationExecutionPlanError, "Save evidence"):
                build_historical_rom_organization_execution_plan(
                    plan, decision, current_collection_revision_token="revision"
                )

    def test_same_size_rom_byte_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review, companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            source = Path(plan.moves[0].source_path)
            original = source.stat()
            source.write_bytes(b"X" * plan.moves[0].size_bytes)
            os.utime(source, ns=(original.st_atime_ns, plan.moves[0].source_mtime_ns))
            with self.assertRaisesRegex(HistoricalRomOrganizationExecutionPlanError, "frozen SHA-256"):
                build_historical_rom_organization_execution_plan(
                    plan, decision, current_collection_revision_token="revision"
                )

    def test_occupied_target_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(Path(tmp))
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review, companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            target = Path(plan.moves[0].target_path)
            target.parent.mkdir(parents=True)
            target.write_bytes(b"occupied")
            with self.assertRaisesRegex(HistoricalRomOrganizationExecutionPlanError, "became occupied"):
                build_historical_rom_organization_execution_plan(
                    plan, decision, current_collection_revision_token="revision"
                )


if __name__ == "__main__":
    unittest.main()
