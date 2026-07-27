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


if __name__ == "__main__":
    unittest.main(verbosity=2)
