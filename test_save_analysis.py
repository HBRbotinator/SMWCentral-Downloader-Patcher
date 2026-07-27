"""Regression tests for the structured Save Data Sync parser boundary."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import save_analysis
import save_sync


def _blob(value: int, extra: int = 0) -> bytes:
    data = bytearray(save_analysis.MIN_LEGACY_SAVE_SIZE + extra)
    data[save_analysis.LEGACY_COUNTER_OFFSET] = value
    return bytes(data)


class SaveAnalysisReadTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="save_analysis_")
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write(self, name: str, data: bytes) -> Path:
        path = self.root / name
        path.write_bytes(data)
        return path

    def test_missing_file_returns_structured_unreadable_result(self):
        path = self.root / "missing.srm"
        result = save_analysis.analyze_save(path)
        self.assertEqual(result.path, os.path.abspath(path))
        self.assertEqual(result.profile, save_analysis.PROFILE_UNREADABLE)
        self.assertEqual(result.confidence, save_analysis.CONFIDENCE_NONE)
        self.assertIsNone(result.selected_value)
        self.assertFalse(result.readable)
        self.assertFalse(result.has_value)
        self.assertEqual(len(result.attempts), 1)
        self.assertFalse(result.attempts[0].accepted)

    def test_os_error_is_captured_without_escaping(self):
        path = self.root / "blocked.srm"
        with mock.patch("builtins.open", side_effect=OSError("access denied")):
            result = save_analysis.analyze_save(path)
        self.assertIn("access denied", result.warnings[0])
        self.assertEqual(result.profile, save_analysis.PROFILE_UNREADABLE)

    def test_short_file_records_required_size(self):
        path = self._write("short.srm", b"tiny")
        result = save_analysis.analyze_save(path)
        self.assertEqual(result.size, 4)
        self.assertEqual(result.profile, save_analysis.PROFILE_UNKNOWN)
        self.assertIsNone(result.selected_value)
        self.assertIn(str(save_analysis.MIN_LEGACY_SAVE_SIZE), result.warnings[0])

    def test_uninitialized_counter_is_rejected_with_evidence(self):
        path = self._write("empty.srm", _blob(0xFF))
        result = save_analysis.analyze_save(path)
        self.assertEqual(result.profile, save_analysis.PROFILE_UNKNOWN)
        self.assertIsNone(result.selected_value)
        self.assertEqual(result.attempts[0].counter_value, 0xFF)
        self.assertIn("uninitialized", result.attempts[0].reason)

    def test_zero_is_preserved_as_a_real_raw_value(self):
        path = self._write("zero.srm", _blob(0))
        result = save_analysis.analyze_save(path)
        self.assertEqual(result.selected_value, 0)
        self.assertTrue(result.has_value)

    def test_repeated_0x60_empty_slot_pattern_is_rejected(self):
        image = bytes(
            [save_analysis.LEGACY_EMPTY_SLOT_PATTERN]
            * save_analysis.STANDARD_SRAM_SIZE
        )
        path = self._write("empty-pattern.srm", image)
        result = save_analysis.analyze_save(path)
        self.assertEqual(result.profile, save_analysis.PROFILE_UNKNOWN)
        self.assertEqual(result.confidence, save_analysis.CONFIDENCE_NONE)
        self.assertIsNone(result.selected_value)
        self.assertEqual(
            result.attempts[-1].counter_value,
            save_analysis.LEGACY_EMPTY_SLOT_PATTERN,
        )
        self.assertFalse(result.attempts[-1].accepted)
        self.assertIn("empty-slot pattern", result.attempts[-1].reason)
        self.assertIn("6 checksum-invalid", result.attempts[-1].reason)

    def test_isolated_raw_96_remains_low_confidence_evidence(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        image[save_analysis.LEGACY_COUNTER_OFFSET] = 96
        path = self._write("isolated-96.srm", bytes(image))
        result = save_analysis.analyze_save(path)
        self.assertEqual(result.profile, save_analysis.PROFILE_LEGACY_RAW_COUNTER)
        self.assertEqual(result.confidence, save_analysis.CONFIDENCE_LOW)
        self.assertEqual(result.selected_value, 96)

    def test_non_ff_byte_is_low_confidence_legacy_evidence(self):
        path = self._write("progress.sav", _blob(17, extra=32))
        result = save_analysis.analyze_save(path)
        self.assertEqual(result.size, save_analysis.MIN_LEGACY_SAVE_SIZE + 32)
        self.assertEqual(result.profile, save_analysis.PROFILE_LEGACY_RAW_COUNTER)
        self.assertEqual(result.confidence, save_analysis.CONFIDENCE_LOW)
        self.assertEqual(result.counter_kind, save_analysis.COUNTER_OVERWORLD_EVENTS)
        self.assertEqual(result.selected_value, 17)
        self.assertTrue(result.readable)
        self.assertIn("not checksum-validated", result.warnings[0])

    def test_raw_254_remains_available_for_existing_classifier_guard(self):
        path = self._write("raw.srm", _blob(0xFE))
        result = save_analysis.analyze_save(path)
        self.assertEqual(result.selected_value, 254)
        self.assertEqual(
            save_sync.classify(result.selected_value, 15, False, False),
            save_sync.STATUS_UNCERTAIN,
        )


class SaveAnalysisEvidenceTest(unittest.TestCase):
    def test_attempt_and_analysis_are_json_friendly(self):
        attempt = save_analysis.ProfileAttempt(
            profile="example",
            accepted=True,
            confidence="medium",
            reason="validated",
            counter_offset=12,
            counter_kind="progress",
            counter_value=8,
        )
        result = save_analysis.SaveAnalysis(
            path="x.srm",
            size=100,
            profile="example",
            confidence="medium",
            counter_kind="progress",
            selected_value=8,
            warnings=("note",),
            attempts=(attempt,),
        )
        evidence = result.as_dict()
        self.assertEqual(evidence["warnings"], ["note"])
        self.assertEqual(evidence["attempts"][0]["counter_value"], 8)
        self.assertIsInstance(evidence["attempts"], list)

    def test_candidate_prefers_attached_analysis_evidence(self):
        analysis = save_analysis.SaveAnalysis(
            path="C:/saves/example.srm",
            size=2048,
            profile="example",
            confidence="high",
            counter_kind="progress",
            selected_value=7,
            warnings=(),
            attempts=(),
        )
        candidate = save_sync.SyncCandidate(
            save_path=analysis.path,
            save_name="example.srm",
            mtime=1,
            collected_exits=7,
            analysis=analysis,
        )
        self.assertEqual(candidate.evidence(), analysis.as_dict())

    def test_candidate_fallback_evidence_is_stable(self):
        candidate = save_sync.SyncCandidate(
            save_path="x.srm",
            save_name="x.srm",
            mtime=1,
            collected_exits=None,
            save_size=4,
            profile="unknown",
            confidence="none",
            warnings=("tiny",),
        )
        evidence = candidate.evidence()
        self.assertEqual(evidence["size"], 4)
        self.assertIsNone(evidence["selected_value"])
        self.assertEqual(evidence["warnings"], ["tiny"])


class SaveSyncCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="save_sync_analysis_")
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_legacy_reader_delegates_to_structured_analysis(self):
        expected = save_analysis.SaveAnalysis(
            path="x.srm",
            size=200,
            profile="test",
            confidence="low",
            counter_kind="overworld_events",
            selected_value=23,
            warnings=(),
            attempts=(),
        )
        with mock.patch("save_sync.analyze_save", return_value=expected) as analyze:
            self.assertEqual(save_sync.read_collected_exits("x.srm"), 23)
        analyze.assert_called_once_with("x.srm")

    def test_scan_preserves_status_while_attaching_evidence(self):
        path = self.root / "Known Hack.srm"
        path.write_bytes(_blob(3))
        hacks = [
            {
                "id": "1",
                "title": "Known Hack",
                "exits": 5,
                "completed": False,
            }
        ]
        candidates = save_sync.scan_saves(str(self.root), hacks)
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertEqual(candidate.collected_exits, 3)
        self.assertEqual(candidate.status, save_sync.STATUS_IN_PROGRESS)
        self.assertIsNotNone(candidate.analysis)
        self.assertEqual(
            candidate.profile,
            save_analysis.PROFILE_LEGACY_RAW_COUNTER,
        )
        self.assertEqual(candidate.evidence()["selected_value"], 3)


def _write_standard_copy(
    image: bytearray,
    *,
    slot: str,
    copy_kind: str,
    value: int,
    fill: int = 0,
) -> None:
    offsets = {
        name: {
            save_analysis.COPY_PRIMARY: primary,
            save_analysis.COPY_BACKUP: backup,
        }
        for name, primary, backup in save_analysis.STANDARD_SLOT_OFFSETS
    }
    offset = offsets[slot][copy_kind]
    slot_data = bytearray([fill] * save_analysis.STANDARD_SLOT_DATA_SIZE)
    slot_data[save_analysis.STANDARD_EVENT_COUNTER_OFFSET] = value
    checksum = save_analysis.calculate_standard_checksum(bytes(slot_data))
    image[offset : offset + save_analysis.STANDARD_SLOT_DATA_SIZE] = slot_data
    checksum_start = offset + save_analysis.STANDARD_CHECKSUM_OFFSET
    image[checksum_start : checksum_start + 2] = checksum.to_bytes(2, "little")


class StandardSmwSlotAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="standard_smw_slots_")
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _analyze(self, image: bytes | bytearray) -> save_analysis.SaveAnalysis:
        path = self.root / "standard.srm"
        path.write_bytes(bytes(image))
        return save_analysis.analyze_save(path)

    def test_checksum_seed_matches_zero_filled_slot(self):
        slot_data = bytes(save_analysis.STANDARD_SLOT_DATA_SIZE)
        self.assertEqual(
            save_analysis.calculate_standard_checksum(slot_data),
            save_analysis.STANDARD_CHECKSUM_SEED,
        )

    def test_checksum_requires_exact_standard_data_size(self):
        with self.assertRaises(ValueError):
            save_analysis.calculate_standard_checksum(b"short")

    def test_checksum_valid_slot_uses_medium_confidence_profile(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        _write_standard_copy(
            image,
            slot="A",
            copy_kind=save_analysis.COPY_PRIMARY,
            value=4,
        )
        _write_standard_copy(
            image,
            slot="A",
            copy_kind=save_analysis.COPY_BACKUP,
            value=4,
        )
        result = self._analyze(image)
        self.assertEqual(result.profile, save_analysis.PROFILE_STANDARD_SMW_SLOTS)
        self.assertEqual(result.confidence, save_analysis.CONFIDENCE_MEDIUM)
        self.assertEqual(result.selected_value, 4)
        self.assertEqual(result.selected_slot, "A")
        self.assertEqual(result.selected_copy, save_analysis.COPY_PRIMARY)
        self.assertEqual(result.valid_slots, ("A",))

    def test_checksum_valid_standard_96_is_not_treated_as_fill(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        for copy_kind in (
            save_analysis.COPY_PRIMARY,
            save_analysis.COPY_BACKUP,
        ):
            _write_standard_copy(
                image,
                slot="A",
                copy_kind=copy_kind,
                value=96,
            )
        result = self._analyze(image)
        self.assertEqual(result.profile, save_analysis.PROFILE_STANDARD_SMW_SLOTS)
        self.assertEqual(result.selected_value, 96)

    def test_highest_checksum_valid_slot_is_selected(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        for copy_kind in (save_analysis.COPY_PRIMARY, save_analysis.COPY_BACKUP):
            _write_standard_copy(
                image,
                slot="A",
                copy_kind=copy_kind,
                value=2,
            )
            _write_standard_copy(
                image,
                slot="C",
                copy_kind=copy_kind,
                value=13,
            )
        result = self._analyze(image)
        self.assertEqual(result.selected_value, 13)
        self.assertEqual(result.selected_slot, "C")
        self.assertEqual(result.valid_slots, ("A", "C"))

    def test_invalid_high_counter_is_ignored(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        for copy_kind in (save_analysis.COPY_PRIMARY, save_analysis.COPY_BACKUP):
            _write_standard_copy(
                image,
                slot="A",
                copy_kind=copy_kind,
                value=2,
            )
        b_primary = save_analysis.STANDARD_SLOT_OFFSETS[1][1]
        image[b_primary + save_analysis.STANDARD_EVENT_COUNTER_OFFSET] = 96
        result = self._analyze(image)
        self.assertEqual(result.selected_value, 2)
        self.assertEqual(result.selected_slot, "A")
        b_attempt = next(
            attempt
            for attempt in result.attempts
            if attempt.slot == "B"
            and attempt.copy_kind == save_analysis.COPY_PRIMARY
        )
        self.assertFalse(b_attempt.checksum_valid)
        self.assertEqual(b_attempt.counter_value, 96)

    def test_backup_copy_recovers_when_primary_checksum_is_invalid(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        _write_standard_copy(
            image,
            slot="B",
            copy_kind=save_analysis.COPY_BACKUP,
            value=17,
        )
        result = self._analyze(image)
        self.assertEqual(result.selected_value, 17)
        self.assertEqual(result.selected_slot, "B")
        self.assertEqual(result.selected_copy, save_analysis.COPY_BACKUP)
        self.assertTrue(any("only one usable" in item for item in result.warnings))

    def test_divergent_valid_copies_select_higher_counter_with_warning(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        _write_standard_copy(
            image,
            slot="A",
            copy_kind=save_analysis.COPY_PRIMARY,
            value=7,
        )
        _write_standard_copy(
            image,
            slot="A",
            copy_kind=save_analysis.COPY_BACKUP,
            value=9,
        )
        result = self._analyze(image)
        self.assertEqual(result.selected_value, 9)
        self.assertEqual(result.selected_copy, save_analysis.COPY_BACKUP)
        self.assertTrue(any("counters differ" in item for item in result.warnings))

    def test_padded_save_can_still_use_standard_slot_region(self):
        image = bytearray(128 * 1024)
        _write_standard_copy(
            image,
            slot="C",
            copy_kind=save_analysis.COPY_PRIMARY,
            value=44,
        )
        _write_standard_copy(
            image,
            slot="C",
            copy_kind=save_analysis.COPY_BACKUP,
            value=44,
        )
        result = self._analyze(image)
        self.assertEqual(result.size, 128 * 1024)
        self.assertEqual(result.profile, save_analysis.PROFILE_STANDARD_SMW_SLOTS)
        self.assertEqual(result.selected_value, 44)

    def test_no_valid_standard_copy_preserves_legacy_fallback(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        image[save_analysis.LEGACY_COUNTER_OFFSET] = 6
        result = self._analyze(image)
        self.assertEqual(result.profile, save_analysis.PROFILE_LEGACY_RAW_COUNTER)
        self.assertEqual(result.confidence, save_analysis.CONFIDENCE_LOW)
        self.assertEqual(result.selected_value, 6)
        self.assertEqual(len(result.attempts), 7)
        self.assertTrue(all(not item.accepted for item in result.attempts[:6]))
        self.assertIn("No usable checksum-valid", result.warnings[0])

    def test_evidence_includes_slot_and_checksum_details(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        _write_standard_copy(
            image,
            slot="C",
            copy_kind=save_analysis.COPY_PRIMARY,
            value=22,
        )
        result = self._analyze(image)
        evidence = result.as_dict()
        self.assertEqual(evidence["selected_slot"], "C")
        self.assertEqual(evidence["valid_slots"], ["C"])
        selected_attempt = next(
            attempt
            for attempt in evidence["attempts"]
            if attempt["accepted"]
        )
        self.assertEqual(selected_attempt["slot"], "C")
        self.assertTrue(selected_attempt["checksum_valid"])
        self.assertEqual(
            selected_attempt["stored_checksum"],
            selected_attempt["expected_checksum"],
        )

    def test_compatibility_reader_returns_selected_standard_slot(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        for copy_kind in (save_analysis.COPY_PRIMARY, save_analysis.COPY_BACKUP):
            _write_standard_copy(
                image,
                slot="A",
                copy_kind=copy_kind,
                value=2,
            )
            _write_standard_copy(
                image,
                slot="C",
                copy_kind=copy_kind,
                value=13,
            )
        path = self.root / "reader.srm"
        path.write_bytes(image)
        self.assertEqual(save_sync.read_collected_exits(path), 13)

    def test_scan_classifies_from_selected_standard_slot(self):
        image = bytearray(save_analysis.STANDARD_SRAM_SIZE)
        for copy_kind in (save_analysis.COPY_PRIMARY, save_analysis.COPY_BACKUP):
            _write_standard_copy(
                image,
                slot="C",
                copy_kind=copy_kind,
                value=13,
            )
        path = self.root / "Known Hack.srm"
        path.write_bytes(image)
        candidates = save_sync.scan_saves(
            str(self.root),
            [{"id": "1", "title": "Known Hack", "exits": 13}],
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].collected_exits, 13)
        self.assertEqual(candidates[0].status, save_sync.STATUS_COMPLETED)
        self.assertEqual(
            candidates[0].profile,
            save_analysis.PROFILE_STANDARD_SMW_SLOTS,
        )


class ExpandedSramGuardTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="expanded_sram_")
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write(self, name: str, image: bytes | bytearray) -> Path:
        path = self.root / name
        path.write_bytes(bytes(image))
        return path

    def test_expanded_invalid_layout_suppresses_legacy_counter(self):
        image = bytearray(128 * 1024)
        image[save_analysis.LEGACY_COUNTER_OFFSET] = 96
        result = save_analysis.analyze_save(
            self._write("expanded.srm", image)
        )
        self.assertEqual(
            result.profile,
            save_analysis.PROFILE_EXPANDED_SRAM_UNKNOWN,
        )
        self.assertEqual(result.confidence, save_analysis.CONFIDENCE_NONE)
        self.assertIsNone(result.selected_value)
        self.assertEqual(result.attempts[-1].counter_value, 96)
        self.assertFalse(result.attempts[-1].accepted)
        self.assertIn("suppressed", result.warnings[0])

    def test_expanded_guard_begins_at_declared_boundary(self):
        expanded = bytearray(save_analysis.EXPANDED_SRAM_MIN_SIZE)
        expanded[save_analysis.LEGACY_COUNTER_OFFSET] = 11
        expanded_result = save_analysis.analyze_save(
            self._write("boundary.srm", expanded)
        )
        self.assertIsNone(expanded_result.selected_value)

        smaller = bytearray(save_analysis.EXPANDED_SRAM_MIN_SIZE - 1)
        smaller[save_analysis.LEGACY_COUNTER_OFFSET] = 11
        smaller_result = save_analysis.analyze_save(
            self._write("smaller.srm", smaller)
        )
        self.assertEqual(
            smaller_result.profile,
            save_analysis.PROFILE_LEGACY_RAW_COUNTER,
        )
        self.assertEqual(smaller_result.selected_value, 11)

    def test_expanded_evidence_keeps_raw_byte_without_selecting_it(self):
        image = bytearray(128 * 1024)
        image[save_analysis.LEGACY_COUNTER_OFFSET] = 44
        result = save_analysis.analyze_save(
            self._write("evidence.srm", image)
        )
        evidence = result.as_dict()
        self.assertIsNone(evidence["selected_value"])
        self.assertEqual(evidence["attempts"][-1]["counter_value"], 44)
        self.assertEqual(
            evidence["attempts"][-1]["profile"],
            save_analysis.PROFILE_EXPANDED_SRAM_UNKNOWN,
        )

    def test_compatibility_reader_returns_none_for_unproven_expanded_layout(self):
        image = bytearray(128 * 1024)
        image[save_analysis.LEGACY_COUNTER_OFFSET] = 96
        path = self._write("reader.srm", image)
        self.assertIsNone(save_sync.read_collected_exits(path))

    def test_scan_classifies_unproven_expanded_layout_as_uncertain(self):
        image = bytearray(128 * 1024)
        image[save_analysis.LEGACY_COUNTER_OFFSET] = 96
        self._write("Known Hack.srm", image)
        candidates = save_sync.scan_saves(
            str(self.root),
            [{"id": "1", "title": "Known Hack", "exits": 12}],
        )
        self.assertEqual(len(candidates), 1)
        candidate = candidates[0]
        self.assertIsNone(candidate.collected_exits)
        self.assertEqual(candidate.status, save_sync.STATUS_UNCERTAIN)
        self.assertEqual(
            candidate.profile,
            save_analysis.PROFILE_EXPANDED_SRAM_UNKNOWN,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
