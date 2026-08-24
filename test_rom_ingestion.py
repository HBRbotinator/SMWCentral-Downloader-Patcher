"""Tests for local ROM scanning and catalogue resolution."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from collection_ingestion import IngestionSource
from rom_ingestion import (
    RomIngestionError,
    candidate_from_rom,
    resolve_rom_against_catalogue,
    scan_rom_library,
)
from rom_title_matching import CatalogueMatcher


CATALOGUE = [
    {
        "id": 41022,
        "name": "Super Dram World 3",
        "difficulty": "Grandmaster",
        "type": "Kaizo",
        "exits": 28,
    },
    {
        "id": 19279,
        "name": "Quickie World 2",
        "difficulty": "Intermediate",
        "type": "Kaizo",
        "exits": 22,
    },
    {"id": 30000, "name": "Grand Poo World 3", "difficulty": "Expert"},
]


class RomIngestionTest(unittest.TestCase):
    def test_scan_is_recursive_sfc_smc_only_and_hashes_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            nested = root / "Kaizo" / "05 - Grandmaster"
            nested.mkdir(parents=True)
            sfc = nested / "Super Dram World 3.sfc"
            smc = root / "QuickieWorld2_1.0.smc"
            ignored = root / "notes.txt"
            sfc.write_bytes(b"dram")
            smc.write_bytes(b"quickie")
            ignored.write_text("ignore", encoding="utf-8")

            scan = scan_rom_library(root, ["Grandmaster"])

            self.assertEqual(2, len(scan.roms))
            by_name = {rom.filename: rom for rom in scan.roms}
            self.assertEqual(
                hashlib.sha256(b"dram").hexdigest(),
                by_name[sfc.name].sha256,
            )
            self.assertEqual(
                "Grandmaster",
                by_name[sfc.name].difficulty_hint,
            )
            self.assertEqual((), scan.duplicate_groups)

    def test_scan_groups_byte_identical_duplicate_copies(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "A" / "Example.sfc"
            second = root / "B" / "Example Copy.smc"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_bytes(b"same-rom")
            second.write_bytes(b"same-rom")

            scan = scan_rom_library(root)

            self.assertEqual(1, len(scan.duplicate_groups))
            self.assertEqual(
                {str(first.resolve()), str(second.resolve())},
                set(scan.duplicate_groups[0].paths),
            )

    def test_scan_records_explicit_id_but_does_not_require_one(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            marked = root / "Super Dram World 3 [SMWC-ID-41022].sfc"
            normal = root / "Quickie World 2.sfc"
            marked.write_bytes(b"marked")
            normal.write_bytes(b"normal")

            scan = scan_rom_library(root)
            by_name = {rom.filename: rom for rom in scan.roms}

            self.assertEqual(
                41022,
                by_name[marked.name].embedded_smwc_submission_id,
            )
            self.assertIsNone(
                by_name[normal.name].embedded_smwc_submission_id
            )

    def test_conflicting_explicit_filename_ids_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rom = root / "Hack [SMWC-10] [SMWC-ID-11].sfc"
            rom.write_bytes(b"rom")

            with self.assertRaises(RomIngestionError):
                scan_rom_library(root)

    def test_candidate_is_local_rom_source_and_can_fall_back_to_manual(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "Unreleased Friend Hack.sfc"
            path.write_bytes(b"local")
            rom = scan_rom_library(root).roms[0]

            candidate = candidate_from_rom(rom)

            self.assertEqual(IngestionSource.ROM_SCAN, candidate.source)
            self.assertTrue(candidate.allow_local_only)
            self.assertEqual((rom,), candidate.rom_files)

    def test_explicit_id_auto_selects_only_when_title_is_plausible(self):
        matcher = CatalogueMatcher(CATALOGUE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / "Super Dram World 3 [SMWC-ID-41022].sfc"
            bad = root / "Completely Different [SMWC-ID-41022].sfc"
            good.write_bytes(b"good")
            bad.write_bytes(b"bad")
            scan = scan_rom_library(root)
            by_name = {rom.filename: rom for rom in scan.roms}

            good_result = resolve_rom_against_catalogue(
                by_name[good.name], matcher
            )
            bad_result = resolve_rom_against_catalogue(
                by_name[bad.name], matcher
            )

            self.assertTrue(good_result.auto_selected)
            self.assertEqual("Explicit SMWC ID", good_result.classification)
            self.assertEqual(41022, good_result.selected.smwc_submission_id)
            self.assertFalse(bad_result.auto_selected)
            self.assertEqual(
                "SMWC ID/title conflict - review",
                bad_result.classification,
            )
            self.assertEqual(41022, bad_result.suggestion.smwc_submission_id)


    def test_explicit_id_missing_from_catalogue_never_falls_back_to_title_reidentity(self):
        matcher = CatalogueMatcher(CATALOGUE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "Quickie World 2 [SMWC-ID-99999].sfc"
            path.write_bytes(b"rom")
            rom = scan_rom_library(root).roms[0]

            result = resolve_rom_against_catalogue(rom, matcher)

            self.assertFalse(result.auto_selected)
            self.assertIsNone(result.selected)
            self.assertIsNone(result.suggestion)
            self.assertEqual(
                "SMWC ID not in current catalogue - review",
                result.classification,
            )

    def test_filename_title_can_match_without_any_id_metadata(self):
        matcher = CatalogueMatcher(CATALOGUE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "QuickieWorld2_1.0.sfc"
            path.write_bytes(b"rom")
            rom = scan_rom_library(root).roms[0]

            result = resolve_rom_against_catalogue(rom, matcher)

            self.assertTrue(result.auto_selected)
            self.assertEqual(19279, result.selected.smwc_submission_id)

    def test_exact_parent_folder_is_review_only_when_filename_is_weak(self):
        matcher = CatalogueMatcher(CATALOGUE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            folder = root / "Grand Poo World 3"
            folder.mkdir()
            path = folder / "GPW3-build.sfc"
            path.write_bytes(b"rom")
            rom = scan_rom_library(root).roms[0]

            result = resolve_rom_against_catalogue(rom, matcher)

            self.assertFalse(result.auto_selected)
            self.assertEqual("Folder title - review", result.classification)
            self.assertEqual(30000, result.suggestion.smwc_submission_id)

    def test_unmatched_rom_keeps_manual_import_available(self):
        matcher = CatalogueMatcher(CATALOGUE)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "My Friend Unreleased Hack.sfc"
            path.write_bytes(b"rom")
            rom = scan_rom_library(root).roms[0]

            result = resolve_rom_against_catalogue(rom, matcher)

            self.assertFalse(result.auto_selected)
            self.assertEqual("Unmatched", result.classification)
            self.assertTrue(result.manual_import_available)


if __name__ == "__main__":
    unittest.main(verbosity=2)
