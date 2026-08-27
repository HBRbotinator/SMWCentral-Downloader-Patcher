from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from collection_rom_organization_execution_plan import (
    CollectionRomOrganizationExecutionPlanError,
    build_collection_rom_organization_execution_plan,
)
from collection_rom_organization_plan import (
    CollectionRomMoveOperation,
    CollectionRomOrganizationPlan,
)
from collection_rom_save_disposition import (
    SaveDisposition,
    companion_disposition_key,
    finalize_collection_rom_save_disposition_decision,
)
from collection_rom_save_impact import build_collection_rom_save_impact_review


class CollectionRomOrganizationExecutionPlanTests(unittest.TestCase):
    def _plan(self, root: Path, *, moves: int = 1) -> CollectionRomOrganizationPlan:
        rows = []
        for index in range(moves):
            title = "Hack" if index == 0 else f"Hack {index + 1}"
            name = f"{title}.sfc"
            source = root / f"Old{index}" / name
            target = root / "ROMs" / "Kaizo" / "04 - Advanced" / name
            source.parent.mkdir(parents=True, exist_ok=True)
            payload = f"rom-{index}".encode("ascii")
            source.write_bytes(payload)
            rows.append(
                CollectionRomMoveOperation(
                    collection_id=str(123 + index),
                    title=title,
                    asset_name=name,
                    source_path=str(source.resolve()),
                    target_path=str(target.resolve()),
                    sha256=hashlib.sha256(payload).hexdigest(),
                    size_bytes=len(payload),
                    source_mtime_ns=source.stat().st_mtime_ns,
                    primary=True,
                    smwc_submission_id=123 + index,
                )
            )
        return CollectionRomOrganizationPlan(
            output_dir=str((root / "ROMs").resolve()),
            collection_revision_token="revision",
            moves=tuple(rows),
            audit_row_count=len(rows),
            in_place_count=0,
            excluded_blocking_count=0,
        )

    @staticmethod
    def _key(row) -> str:
        return companion_disposition_key(
            row.collection_id,
            row.rom_source_path,
            row.save_path,
        )

    def test_freezes_exact_rom_and_selected_save_moves(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"save-bytes")
            review = build_collection_rom_save_impact_review(plan)
            row = review.rows[0]
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={self._key(row): SaveDisposition.MIGRATE_WITH_ROM},
            )

            final_plan = build_collection_rom_organization_execution_plan(
                plan,
                decision,
                current_collection_revision_token="revision",
            )

            self.assertEqual(1, len(final_plan.rom_moves))
            self.assertEqual(1, len(final_plan.save_moves))
            self.assertEqual(0, len(final_plan.save_leaves))
            self.assertEqual(2, final_plan.filesystem_move_count)
            save_move = final_plan.save_moves[0]
            self.assertEqual(hashlib.sha256(b"save-bytes").hexdigest(), save_move.sha256)
            self.assertEqual(str(save.resolve()), save_move.source_path)
            self.assertEqual(str(Path(row.possible_target_path).resolve()), save_move.target_path)
            self.assertEqual(b"save-bytes", save.read_bytes())
            self.assertFalse(Path(save_move.target_path).exists())

    def test_leave_in_place_is_retained_without_becoming_a_save_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".sav")
            save.write_bytes(b"save")
            review = build_collection_rom_save_impact_review(plan)
            row = review.rows[0]
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={self._key(row): SaveDisposition.LEAVE_IN_PLACE},
            )

            final_plan = build_collection_rom_organization_execution_plan(
                plan,
                decision,
                current_collection_revision_token="revision",
            )

            self.assertEqual(1, len(final_plan.rom_moves))
            self.assertEqual(0, len(final_plan.save_moves))
            self.assertEqual(1, len(final_plan.save_leaves))
            self.assertEqual(str(save.resolve()), final_plan.save_leaves[0].save_path)
            self.assertTrue(save.exists())

    def test_blocked_rom_moves_are_excluded_with_all_their_save_actions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root, moves=2)
            first_save = Path(plan.moves[0].source_path).with_suffix(".srm")
            second_save = Path(plan.moves[1].source_path).with_suffix(".srm")
            first_save.write_bytes(b"first")
            second_save.write_bytes(b"second")
            review = build_collection_rom_save_impact_review(plan)
            rows = {row.collection_id: row for row in review.rows}
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={
                    self._key(rows["123"]): SaveDisposition.MIGRATE_WITH_ROM,
                    self._key(rows["124"]): SaveDisposition.BLOCK_ROM_MOVE,
                },
            )

            final_plan = build_collection_rom_organization_execution_plan(
                plan,
                decision,
                current_collection_revision_token="revision",
            )

            self.assertEqual(["123"], [item.collection_id for item in final_plan.rom_moves])
            self.assertEqual(["123"], [item.collection_id for item in final_plan.save_moves])
            self.assertEqual(1, final_plan.blocked_move_count)

    def test_all_blocked_moves_cannot_become_an_execution_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"save")
            review = build_collection_rom_save_impact_review(plan)
            row = review.rows[0]
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={self._key(row): SaveDisposition.BLOCK_ROM_MOVE},
            )

            with self.assertRaisesRegex(
                CollectionRomOrganizationExecutionPlanError,
                "No approved ROM moves",
            ):
                build_collection_rom_organization_execution_plan(
                    plan,
                    decision,
                    current_collection_revision_token="revision",
                )

    def test_collection_revision_must_still_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )

            with self.assertRaisesRegex(
                CollectionRomOrganizationExecutionPlanError,
                "Collection changed",
            ):
                build_collection_rom_organization_execution_plan(
                    plan,
                    decision,
                    current_collection_revision_token="different",
                )

    def test_new_save_evidence_after_review_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            Path(plan.moves[0].source_path).with_suffix(".srm").write_bytes(b"appeared")

            with self.assertRaisesRegex(
                CollectionRomOrganizationExecutionPlanError,
                "Save evidence changed",
            ):
                build_collection_rom_organization_execution_plan(
                    plan,
                    decision,
                    current_collection_revision_token="revision",
                )

    def test_same_size_rom_byte_change_is_caught_by_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            source = Path(plan.moves[0].source_path)
            original_stat = source.stat()
            source.write_bytes(b"bad!!")
            self.assertEqual(plan.moves[0].size_bytes, source.stat().st_size)
            os.utime(
                source,
                ns=(original_stat.st_atime_ns, plan.moves[0].source_mtime_ns),
            )

            with self.assertRaisesRegex(
                CollectionRomOrganizationExecutionPlanError,
                "recorded SHA-256",
            ):
                build_collection_rom_organization_execution_plan(
                    plan,
                    decision,
                    current_collection_revision_token="revision",
                )

    def test_rom_target_that_becomes_occupied_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            review = build_collection_rom_save_impact_review(plan)
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            target = Path(plan.moves[0].target_path)
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing")

            with self.assertRaisesRegex(
                CollectionRomOrganizationExecutionPlanError,
                "target became occupied",
            ):
                build_collection_rom_organization_execution_plan(
                    plan,
                    decision,
                    current_collection_revision_token="revision",
                )
            self.assertEqual(b"existing", target.read_bytes())

    def test_configured_save_evidence_is_retained_only_as_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            central = root / "Saves"
            central.mkdir()
            central_save = central / "Hack.srm"
            central_save.write_bytes(b"central")
            review = build_collection_rom_save_impact_review(plan, [str(central)])
            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )

            final_plan = build_collection_rom_organization_execution_plan(
                plan,
                decision,
                current_collection_revision_token="revision",
                configured_save_directories=[str(central)],
            )

            self.assertEqual(1, final_plan.external_save_evidence_count)
            self.assertEqual(0, len(final_plan.save_moves))
            self.assertTrue(central_save.exists())


if __name__ == "__main__":
    unittest.main()
