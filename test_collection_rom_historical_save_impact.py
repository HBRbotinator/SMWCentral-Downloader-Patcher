from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from collection_rom_historical_organization_plan import (
    HistoricalRomMoveOperation,
    HistoricalRomOrganizationPlan,
)
from collection_rom_save_disposition import (
    finalize_collection_rom_save_disposition_decision,
    save_impact_review_fingerprint,
)
from collection_rom_save_impact import (
    SOURCE_COLOCATED,
    SOURCE_CONFIGURED_ASSOCIATION,
    build_collection_rom_save_impact_review,
)


class HistoricalRomSaveImpactTests(unittest.TestCase):
    def _plan(self, root: Path) -> HistoricalRomOrganizationPlan:
        source = root / "Old" / "Historical.sfc"
        target = root / "ROMs" / "Kaizo" / "04 - Advanced" / "Historical.sfc"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"rom")
        move = HistoricalRomMoveOperation(
            collection_id="200",
            collection_title="Current Submission",
            asset_name="Historical.sfc",
            source_path=str(source.resolve()),
            target_path=str(target.resolve()),
            sha256="a" * 64,
            size_bytes=3,
            source_mtime_ns=source.stat().st_mtime_ns,
            primary=False,
            historical_smwc_submission_id=100,
            historical_title="Historical Submission",
            historical_hack_type="Kaizo",
            historical_difficulty="Advanced",
        )
        return HistoricalRomOrganizationPlan(
            output_dir=str((root / "ROMs").resolve()),
            collection_revision_token="sha256:collection",
            moves=(move,),
            review_row_count=1,
            in_place_count=0,
            excluded_blocking_count=0,
        )

    def test_historical_plan_discovers_colocated_save_against_frozen_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self._plan(root)
            save = root / "Old" / "Historical.srm"
            save.write_bytes(b"save")

            review = build_collection_rom_save_impact_review(plan)

            self.assertIs(review.plan, plan)
            self.assertEqual(1, review.colocated_count)
            row = review.rows[0]
            self.assertEqual(SOURCE_COLOCATED, row.source_kind)
            self.assertEqual("Current Submission", row.title)
            self.assertEqual(plan.moves[0].source_path, row.rom_source_path)
            self.assertEqual(plan.moves[0].target_path, row.rom_target_path)
            self.assertTrue(row.possible_target_path.endswith("Historical.srm"))

    def test_historical_plan_uses_same_save_sync_association_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self._plan(root)
            saves = root / "Saves"
            saves.mkdir()
            (saves / "OldSlot.sav").write_bytes(b"save")

            review = build_collection_rom_save_impact_review(
                plan,
                [str(saves)],
                {"OldSlot.sav": "200"},
            )

            self.assertEqual(1, len(review.rows))
            self.assertEqual(SOURCE_CONFIGURED_ASSOCIATION, review.rows[0].source_kind)
            self.assertEqual("", review.rows[0].possible_target_path)

    def test_historical_no_colocated_save_can_be_explicitly_acknowledged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self._plan(root)
            review = build_collection_rom_save_impact_review(plan)

            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )

            self.assertEqual(1, decision.approved_move_count)
            self.assertEqual(1, decision.rom_only_acknowledgement_count)
            self.assertEqual(plan.collection_revision_token, decision.collection_revision_token)

    def test_save_review_fingerprint_binds_historical_layout_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self._plan(root)
            first = build_collection_rom_save_impact_review(plan)
            changed_move = replace(plan.moves[0], historical_difficulty="Expert")
            changed_plan = replace(plan, moves=(changed_move,))
            second = build_collection_rom_save_impact_review(changed_plan)

            self.assertNotEqual(
                save_impact_review_fingerprint(first),
                save_impact_review_fingerprint(second),
            )

    def test_save_review_fingerprint_binds_historical_submission_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan = self._plan(root)
            first = build_collection_rom_save_impact_review(plan)
            changed_move = replace(plan.moves[0], historical_smwc_submission_id=101)
            changed_plan = replace(plan, moves=(changed_move,))
            second = build_collection_rom_save_impact_review(changed_plan)

            self.assertNotEqual(
                save_impact_review_fingerprint(first),
                save_impact_review_fingerprint(second),
            )


if __name__ == "__main__":
    unittest.main()
