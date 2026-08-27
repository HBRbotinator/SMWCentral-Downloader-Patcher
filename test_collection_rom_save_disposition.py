from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collection_rom_organization_plan import CollectionRomMoveOperation, CollectionRomOrganizationPlan
from collection_rom_save_disposition import (
    CollectionRomSaveDispositionError,
    SaveDisposition,
    companion_disposition_key,
    finalize_collection_rom_save_disposition_decision,
    save_impact_review_fingerprint,
)
from collection_rom_save_impact import build_collection_rom_save_impact_review


class CollectionRomSaveDispositionTests(unittest.TestCase):
    def _plan(self, root: Path, *, moves=1):
        rows = []
        for index in range(moves):
            name = "Hack.sfc" if index == 0 else f"Hack {index + 1}.sfc"
            source = root / f"Old{index}" / name
            target = root / "ROMs" / "Kaizo" / "04 - Advanced" / name
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(b"rom")
            rows.append(
                CollectionRomMoveOperation(
                    collection_id=str(123 + index),
                    title="Hack" if index == 0 else f"Hack {index + 1}",
                    asset_name=name,
                    source_path=str(source.resolve()),
                    target_path=str(target.resolve()),
                    sha256=("a" if index == 0 else "b") * 64,
                    size_bytes=3,
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

    def _key(self, row):
        return companion_disposition_key(row.collection_id, row.rom_source_path, row.save_path)

    def test_finalizes_migrate_leave_and_block_choices(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root, moves=2)
            first_save = Path(plan.moves[0].source_path).with_suffix(".srm")
            second_save = Path(plan.moves[1].source_path).with_suffix(".sav")
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

            self.assertEqual(1, decision.approved_move_count)
            self.assertEqual(1, decision.blocked_move_count)
            self.assertEqual(1, decision.migrate_save_count)
            self.assertEqual(0, decision.leave_save_count)
            self.assertEqual("revision", decision.collection_revision_token)
            self.assertTrue(decision.review_fingerprint.startswith("sha256:"))
            self.assertTrue(first_save.exists())
            self.assertTrue(second_save.exists())
            self.assertFalse(Path(rows["123"].possible_target_path).exists())

    def test_leave_in_place_is_explicit_and_non_destructive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"save")
            review = build_collection_rom_save_impact_review(plan)
            row = review.rows[0]

            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={self._key(row): "leave_in_place"},
            )

            self.assertEqual(1, decision.leave_save_count)
            self.assertEqual(1, decision.approved_move_count)
            self.assertEqual(b"save", save.read_bytes())
            self.assertFalse(Path(row.possible_target_path).exists())

    def test_occupied_colocated_target_cannot_be_selected_for_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"source")
            target = Path(plan.moves[0].target_path).with_suffix(".srm")
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing")
            review = build_collection_rom_save_impact_review(plan)
            row = review.rows[0]

            with self.assertRaisesRegex(CollectionRomSaveDispositionError, "occupied"):
                finalize_collection_rom_save_disposition_decision(
                    review,
                    companion_dispositions={self._key(row): "migrate_with_rom"},
                )

            self.assertEqual(b"source", save.read_bytes())
            self.assertEqual(b"existing", target.read_bytes())

    def test_occupied_target_can_be_left_or_block_the_rom_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"source")
            target = Path(plan.moves[0].target_path).with_suffix(".srm")
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing")
            review = build_collection_rom_save_impact_review(plan)
            row = review.rows[0]

            leave = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={self._key(row): "leave_in_place"},
            )
            blocked = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={self._key(row): "block_rom_move"},
            )

            self.assertEqual(0, leave.blocked_move_count)
            self.assertEqual(1, blocked.blocked_move_count)

    def test_every_colocated_save_requires_a_disposition(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            Path(plan.moves[0].source_path).with_suffix(".srm").write_bytes(b"save")
            review = build_collection_rom_save_impact_review(plan)

            with self.assertRaisesRegex(CollectionRomSaveDispositionError, "every detected"):
                finalize_collection_rom_save_disposition_decision(
                    review,
                    companion_dispositions={},
                )

    def test_unknown_or_external_save_rows_cannot_receive_dispositions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            central = root / "Saves"
            central.mkdir()
            (central / "Hack.srm").write_bytes(b"central")
            review = build_collection_rom_save_impact_review(plan, [str(central)])
            external = review.rows[0]

            with self.assertRaisesRegex(CollectionRomSaveDispositionError, "not part"):
                finalize_collection_rom_save_disposition_decision(
                    review,
                    companion_dispositions={self._key(external): "leave_in_place"},
                    rom_only_acknowledgements=[plan.moves[0].source_path],
                )

    def test_move_without_colocated_save_requires_explicit_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            review = build_collection_rom_save_impact_review(plan)

            with self.assertRaisesRegex(CollectionRomSaveDispositionError, "acknowledge every ROM move"):
                finalize_collection_rom_save_disposition_decision(
                    review,
                    companion_dispositions={},
                )

            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={},
                rom_only_acknowledgements=[plan.moves[0].source_path],
            )
            self.assertEqual(1, decision.rom_only_acknowledgement_count)
            self.assertEqual(1, decision.approved_move_count)

    def test_acknowledgement_is_rejected_when_colocated_save_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            Path(plan.moves[0].source_path).with_suffix(".srm").write_bytes(b"save")
            review = build_collection_rom_save_impact_review(plan)
            row = review.rows[0]

            with self.assertRaisesRegex(CollectionRomSaveDispositionError, "cannot use"):
                finalize_collection_rom_save_disposition_decision(
                    review,
                    companion_dispositions={self._key(row): "leave_in_place"},
                    rom_only_acknowledgements=[plan.moves[0].source_path],
                )


    def test_migrating_colocated_save_out_of_save_sync_coverage_requires_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"save")
            review = build_collection_rom_save_impact_review(
                plan,
                [str(save.parent.resolve())],
            )
            row = review.rows[0]
            key = self._key(row)
            self.assertTrue(row.save_sync_coverage_lost)

            with self.assertRaisesRegex(CollectionRomSaveDispositionError, "out of configured Save Sync coverage"):
                finalize_collection_rom_save_disposition_decision(
                    review,
                    companion_dispositions={key: "migrate_with_rom"},
                )

            decision = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={key: "migrate_with_rom"},
                save_sync_coverage_loss_acknowledgements=[key],
            )
            companion = decision.move_decisions[0].companions[0]
            self.assertTrue(companion.save_sync_coverage_loss_acknowledged)
            self.assertEqual(1, decision.migrate_save_count)

    def test_leave_or_block_does_not_require_save_sync_coverage_loss_acknowledgement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"save")
            review = build_collection_rom_save_impact_review(
                plan,
                [str(save.parent.resolve())],
            )
            row = review.rows[0]
            key = self._key(row)

            leave = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={key: "leave_in_place"},
            )
            blocked = finalize_collection_rom_save_disposition_decision(
                review,
                companion_dispositions={key: "block_rom_move"},
            )
            self.assertFalse(leave.move_decisions[0].companions[0].save_sync_coverage_loss_acknowledged)
            self.assertEqual(1, blocked.blocked_move_count)

    def test_save_sync_coverage_acknowledgement_rejects_non_loss_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"save")
            review = build_collection_rom_save_impact_review(plan)
            row = review.rows[0]
            key = self._key(row)

            with self.assertRaisesRegex(CollectionRomSaveDispositionError, "do not lose configured coverage"):
                finalize_collection_rom_save_disposition_decision(
                    review,
                    companion_dispositions={key: "leave_in_place"},
                    save_sync_coverage_loss_acknowledgements=[key],
                )

    def test_review_fingerprint_changes_when_save_evidence_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = Path(plan.moves[0].source_path).with_suffix(".srm")
            save.write_bytes(b"one")
            first = build_collection_rom_save_impact_review(plan)
            first_fingerprint = save_impact_review_fingerprint(first)

            save.write_bytes(b"longer")
            second = build_collection_rom_save_impact_review(plan)
            second_fingerprint = save_impact_review_fingerprint(second)

            self.assertNotEqual(first_fingerprint, second_fingerprint)

    def test_review_fingerprint_is_stable_for_same_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            Path(plan.moves[0].source_path).with_suffix(".srm").write_bytes(b"save")
            first = build_collection_rom_save_impact_review(plan)
            second = build_collection_rom_save_impact_review(plan)

            self.assertEqual(
                save_impact_review_fingerprint(first),
                save_impact_review_fingerprint(second),
            )


if __name__ == "__main__":
    unittest.main()
