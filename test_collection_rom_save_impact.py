from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from collection_rom_organization_plan import CollectionRomMoveOperation, CollectionRomOrganizationPlan
from collection_rom_save_impact import (
    SOURCE_COLOCATED,
    SOURCE_CONFIGURED_ASSOCIATION,
    SOURCE_CONFIGURED_NAME,
    build_collection_rom_save_impact_review,
)


class CollectionRomSaveImpactTests(unittest.TestCase):
    def _plan(self, root: Path, *, collection_id="123", title="Hack", rom_name="Hack.sfc"):
        source = root / "Old" / rom_name
        target = root / "ROMs" / "Kaizo" / "04 - Advanced" / rom_name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"rom")
        move = CollectionRomMoveOperation(
            collection_id=collection_id,
            title=title,
            asset_name=rom_name,
            source_path=str(source.resolve()),
            target_path=str(target.resolve()),
            sha256="a" * 64,
            size_bytes=3,
            source_mtime_ns=source.stat().st_mtime_ns,
            primary=True,
            smwc_submission_id=int(collection_id) if collection_id.isdigit() else None,
        )
        return CollectionRomOrganizationPlan(
            output_dir=str((root / "ROMs").resolve()),
            collection_revision_token="revision",
            moves=(move,),
            audit_row_count=1,
            in_place_count=0,
            excluded_blocking_count=0,
        )

    def test_discovers_colocated_same_basename_save_and_possible_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = root / "Old" / "Hack.srm"
            save.write_bytes(b"save")

            review = build_collection_rom_save_impact_review(plan)

            self.assertEqual(1, len(review.rows))
            row = review.rows[0]
            self.assertEqual(SOURCE_COLOCATED, row.source_kind)
            self.assertEqual(str(save.resolve()), row.save_path)
            self.assertEqual(
                str((root / "ROMs" / "Kaizo" / "04 - Advanced" / "Hack.srm").resolve()),
                row.possible_target_path,
            )
            self.assertFalse(row.target_occupied)


    def test_colocated_discovery_preserves_uppercase_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = root / "Old" / "Hack.SRM"
            save.write_bytes(b"save")

            review = build_collection_rom_save_impact_review(plan)

            self.assertEqual(1, len(review.rows))
            self.assertEqual("Hack.SRM", review.rows[0].save_name)
            self.assertTrue(review.rows[0].possible_target_path.endswith("Hack.SRM"))

    def test_colocated_save_reports_occupied_possible_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            (root / "Old" / "Hack.srm").write_bytes(b"old")
            target = root / "ROMs" / "Kaizo" / "04 - Advanced" / "Hack.srm"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"target")

            review = build_collection_rom_save_impact_review(plan)

            self.assertEqual(1, review.target_conflict_count)
            self.assertTrue(review.rows[0].target_occupied)

    def test_configured_matching_save_is_external_without_move_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save_dir = root / "Central Saves"
            save_dir.mkdir()
            save = save_dir / "Hack.sav"
            save.write_bytes(b"central")

            review = build_collection_rom_save_impact_review(plan, [str(save_dir)])

            self.assertEqual(1, len(review.rows))
            self.assertEqual(SOURCE_CONFIGURED_NAME, review.rows[0].source_kind)
            self.assertEqual("", review.rows[0].possible_target_path)
            self.assertEqual(1, review.external_count)

    def test_explicit_save_association_surfaces_different_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root, collection_id="19279", title="Quickie World 2", rom_name="Quickie World 2.sfc")
            save_dir = root / "Saves"
            save_dir.mkdir()
            save = save_dir / "QW2.srm"
            save.write_bytes(b"save")

            review = build_collection_rom_save_impact_review(
                plan,
                [str(save_dir)],
                {"QW2.srm": "19279"},
            )

            self.assertEqual(1, len(review.rows))
            self.assertEqual(SOURCE_CONFIGURED_ASSOCIATION, review.rows[0].source_kind)
            self.assertEqual("QW2.srm", review.rows[0].save_name)

    def test_colocated_save_is_not_duplicated_when_source_is_configured(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = root / "Old" / "Hack.srm"
            save.write_bytes(b"save")

            review = build_collection_rom_save_impact_review(
                plan,
                [str((root / "Old").resolve())],
            )

            self.assertEqual(1, len(review.rows))
            self.assertEqual(SOURCE_COLOCATED, review.rows[0].source_kind)



    def test_colocated_save_reports_save_sync_coverage_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = root / "Old" / "Hack.srm"
            save.write_bytes(b"save")

            review = build_collection_rom_save_impact_review(
                plan,
                [str((root / "Old").resolve())],
            )

            row = review.rows[0]
            self.assertTrue(row.save_sync_source_covered)
            self.assertFalse(row.save_sync_target_covered)
            self.assertTrue(row.save_sync_coverage_lost)
            self.assertEqual(1, review.save_sync_coverage_loss_count)

    def test_colocated_save_reports_retained_or_gained_save_sync_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save = root / "Old" / "Hack.srm"
            save.write_bytes(b"save")
            source_dir = str((root / "Old").resolve())
            target_dir = str((root / "ROMs" / "Kaizo" / "04 - Advanced").resolve())

            retained = build_collection_rom_save_impact_review(
                plan,
                [source_dir, target_dir],
            )
            retained_row = retained.rows[0]
            self.assertTrue(retained_row.save_sync_coverage_retained)
            self.assertEqual(0, retained.save_sync_coverage_loss_count)

            gained = build_collection_rom_save_impact_review(
                plan,
                [target_dir],
            )
            gained_row = gained.rows[0]
            self.assertTrue(gained_row.save_sync_coverage_gained)
            self.assertFalse(gained_row.save_sync_source_covered)
            self.assertTrue(gained_row.save_sync_target_covered)

    def test_configured_association_is_not_repeated_for_multiple_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self._plan(root, collection_id="19279", title="Quickie World 2", rom_name="Quickie World 2.sfc")
            second_source = root / "Old2" / "Quickie World 2 Practice.sfc"
            second_target = root / "ROMs" / "Kaizo" / "04 - Advanced" / second_source.name
            second_source.parent.mkdir(parents=True)
            second_source.write_bytes(b"rom2")
            second_move = CollectionRomMoveOperation(
                collection_id="19279",
                title="Quickie World 2",
                asset_name=second_source.name,
                source_path=str(second_source.resolve()),
                target_path=str(second_target.resolve()),
                sha256="b" * 64,
                size_bytes=4,
                source_mtime_ns=second_source.stat().st_mtime_ns,
                primary=False,
                smwc_submission_id=19279,
            )
            plan = CollectionRomOrganizationPlan(
                output_dir=first.output_dir,
                collection_revision_token="revision",
                moves=(first.moves[0], second_move),
                audit_row_count=2,
                in_place_count=0,
                excluded_blocking_count=0,
            )
            save_dir = root / "Saves"
            save_dir.mkdir()
            (save_dir / "QW2.srm").write_bytes(b"save")

            review = build_collection_rom_save_impact_review(
                plan,
                [str(save_dir)],
                {"QW2.srm": "19279"},
            )

            self.assertEqual(1, len(review.rows))
            self.assertEqual(SOURCE_CONFIGURED_ASSOCIATION, review.rows[0].source_kind)

    def test_configured_scan_is_non_recursive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            save_dir = root / "Saves"
            nested = save_dir / "Nested"
            nested.mkdir(parents=True)
            (nested / "Hack.srm").write_bytes(b"save")

            review = build_collection_rom_save_impact_review(plan, [str(save_dir)])

            self.assertEqual((), review.rows)

    def test_review_does_not_create_target_directories_or_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self._plan(root)
            (root / "Old" / "Hack.srm").write_bytes(b"save")
            target_dir = root / "ROMs" / "Kaizo" / "04 - Advanced"
            self.assertFalse(target_dir.exists())

            review = build_collection_rom_save_impact_review(plan)

            self.assertEqual(1, len(review.rows))
            self.assertFalse(target_dir.exists())


if __name__ == "__main__":
    unittest.main()
