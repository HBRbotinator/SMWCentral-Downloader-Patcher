"""
Unit tests for save_sync.

Primary goal (per feature spec): prove that .sav and .srm files are read
identically -- same raw SMW SRAM bytes must yield the same collected-exit count
regardless of extension. Also covers the read guards, classification rule, and
filename-to-hack matching.

Run:  python -m pytest test_save_sync.py      (or)  python test_save_sync.py
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import save_sync
from save_sync import (
    SMW_EXIT_COUNT_OFFSET,
    MIN_SAVE_SIZE,
    STATUS_COMPLETED,
    STATUS_IN_PROGRESS,
    STATUS_UNCERTAIN,
    STATUS_ALREADY_COMPLETED,
    STATUS_UNMATCHED,
    read_collected_exits,
    classify,
    build_hack_index,
    scan_saves,
)


def _make_srm_bytes(exit_count, size=8192, fill=0x00):
    """Build a synthetic SMW SRAM blob with a specific exit count at 0x8C."""
    data = bytearray([fill]) * size
    data[SMW_EXIT_COUNT_OFFSET] = exit_count & 0xFF
    return bytes(data)


class SavSrmParityTest(unittest.TestCase):
    """The core requirement: .sav and .srm parse identically."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="savesync_")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def _write(self, name, blob):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(blob)
        return path

    def test_identical_bytes_same_result_across_extensions(self):
        """Same bytes, different extension -> identical collected-exit count."""
        for exit_count in (0, 1, 6, 12, 15, 62, 96):
            blob = _make_srm_bytes(exit_count)
            srm = self._write(f"hack_{exit_count}.srm", blob)
            sav = self._write(f"hack_{exit_count}.sav", blob)

            srm_result = read_collected_exits(srm)
            sav_result = read_collected_exits(sav)

            self.assertEqual(srm_result, exit_count)
            self.assertEqual(
                srm_result, sav_result,
                f".srm and .sav disagreed for exit_count={exit_count}",
            )

    def test_parity_across_common_save_sizes(self):
        """Extensions agree while unvalidated expanded saves fail closed."""
        for size in (2048, 4096, 8192, 65536, 131072):
            blob = _make_srm_bytes(9, size=size)
            srm = self._write(f"s{size}.srm", blob)
            sav = self._write(f"s{size}.sav", blob)
            srm_result = read_collected_exits(srm)
            self.assertEqual(srm_result, read_collected_exits(sav))
            expected = None if size >= 65536 else 9
            self.assertEqual(srm_result, expected)


class ReadGuardsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="savesync_g_")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def _write(self, name, blob):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as f:
            f.write(blob)
        return path

    def test_uninitialized_0xFF_returns_none(self):
        path = self._write("ff.srm", _make_srm_bytes(0xFF))
        self.assertIsNone(read_collected_exits(path))

    def test_file_too_small_returns_none(self):
        path = self._write("tiny.srm", b"\x00" * (MIN_SAVE_SIZE - 1))
        self.assertIsNone(read_collected_exits(path))

    def test_missing_file_returns_none(self):
        self.assertIsNone(read_collected_exits(os.path.join(self.tmp, "nope.srm")))


class ClassifyTest(unittest.TestCase):
    def test_completed_when_collected_meets_total(self):
        self.assertEqual(classify(12, 12, False, False), STATUS_COMPLETED)
        self.assertEqual(classify(20, 12, False, False), STATUS_COMPLETED)

    def test_in_progress_when_below_total(self):
        self.assertEqual(classify(5, 12, False, False), STATUS_IN_PROGRESS)

    def test_uncertain_when_unreadable_or_no_reference(self):
        self.assertEqual(classify(None, 12, False, False), STATUS_UNCERTAIN)
        self.assertEqual(classify(6, 0, False, False), STATUS_UNCERTAIN)

    def test_uncertain_when_garbage_oversized(self):
        # 220 exits vs a 15-exit hack -> padded/garbage read, not a completion.
        self.assertEqual(classify(220, 15, False, False), STATUS_UNCERTAIN)

    def test_already_completed_takes_precedence(self):
        self.assertEqual(classify(3, 12, True, False), STATUS_ALREADY_COMPLETED)
        self.assertEqual(classify(3, 12, True, True), STATUS_ALREADY_COMPLETED)

    def test_mark_all_completes_regardless_of_exits(self):
        self.assertEqual(classify(1, 12, False, True), STATUS_COMPLETED)
        self.assertEqual(classify(None, 0, False, True), STATUS_COMPLETED)


class MatchingTest(unittest.TestCase):
    HACKS = [
        {"id": "1", "title": "Le Plume", "exits": 12, "completed": False},
        {"id": "2", "title": "Fresh Hops", "exits": 36, "completed": False},
        {"id": "3", "title": "Grand Poo World 2", "exits": 6, "completed": True},
    ]

    def test_version_suffix_and_case_and_spacing(self):
        index = build_hack_index(self.HACKS)
        # le_plume_v0.3 -> "Le Plume"; FreshHops -> "Fresh Hops"
        self.assertIn(save_sync._normalize("le_plume_v0.3.srm"), index)
        self.assertIs(index[save_sync._normalize("le_plume_v0.3.srm")], self.HACKS[0])
        self.assertIs(index[save_sync._normalize("FreshHops.srm")], self.HACKS[1])

    def test_unmatched_name(self):
        index = build_hack_index(self.HACKS)
        self.assertNotIn(save_sync._normalize("SMW_20250920.srm"), index)


class ScanIntegrationTest(unittest.TestCase):
    HACKS = [
        {"id": "1", "title": "Alpha Hack", "exits": 4, "completed": False},
        {"id": "2", "title": "Beta Hack", "exits": 10, "completed": False},
        {"id": "3", "title": "Done Hack", "exits": 3, "completed": True},
    ]

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="savesync_scan_")

    def tearDown(self):
        for name in os.listdir(self.tmp):
            os.remove(os.path.join(self.tmp, name))
        os.rmdir(self.tmp)

    def _write(self, name, exit_count):
        with open(os.path.join(self.tmp, name), "wb") as f:
            f.write(_make_srm_bytes(exit_count))

    def test_scan_classifies_and_dedupes(self):
        self._write("Alpha Hack.srm", 4)          # completed (4>=4)
        self._write("Beta Hack.sav", 2)           # in progress (2<10)
        self._write("Done Hack.srm", 3)           # already completed
        self._write("Unknown Thing.srm", 1)       # unmatched
        # Duplicate for hack 1 with fewer exits -> should be dropped in favor of 4.
        self._write("alphahack_v1.1.srm", 1)

        results = {c.title or c.save_name: c for c in scan_saves(self.tmp, self.HACKS)}

        self.assertEqual(results["Alpha Hack"].status, STATUS_COMPLETED)
        self.assertEqual(results["Alpha Hack"].collected_exits, 4)  # best kept
        self.assertEqual(results["Beta Hack"].status, STATUS_IN_PROGRESS)
        self.assertEqual(results["Done Hack"].status, STATUS_ALREADY_COMPLETED)
        self.assertEqual(results["Unknown Thing.srm"].status, STATUS_UNMATCHED)

    def test_mark_all_mode(self):
        self._write("Beta Hack.srm", 1)  # would be in-progress under default rule
        results = scan_saves(self.tmp, self.HACKS, mark_all=True)
        beta = next(c for c in results if c.title == "Beta Hack")
        self.assertEqual(beta.status, STATUS_COMPLETED)


class FakeDataManager:
    """Minimal stand-in for HackDataManager for import tests."""

    def __init__(self, data=None):
        self.data = data or {}
        self.saved = False

    def add_user_hack(self, key, hack_data):
        self.data[key] = hack_data
        return True

    def update_hack(self, hack_id, field, value):
        self.data.setdefault(hack_id, {})[field] = value
        return True

    def force_save(self):
        self.saved = True
        return True


def _fake_fetch(results):
    """Return a fetch_hack_list-style callable yielding fixed results."""
    def _fetch(config, page=1, waiting_mode=False, log=None):
        return {"data": results, "last_page": 1, "current_page": 1}
    return _fetch


def _smwc_hack(hid, name, difficulty="diff_4", htype="kaizo", length=10,
               obsolete=False, time_ts=1704067200):
    return {
        "id": hid,
        "name": name,
        "time": time_ts,
        "authors": ["someone"],
        "raw_fields": {
            "difficulty": difficulty, "type": htype, "length": length,
            "hof": False, "sa1": False, "collab": False, "demo": False,
            "obsolete": obsolete,
        },
    }


class SearchQueryTest(unittest.TestCase):
    def test_strips_version_and_separators(self):
        self.assertEqual(save_sync.make_search_query("le_plume_v0.3.srm"), "le plume")
        self.assertEqual(save_sync.make_search_query("Grand Poo World 2.srm"), "Grand Poo World 2")
        self.assertEqual(save_sync.make_search_query("FreshHops.srm"), "FreshHops")
        self.assertEqual(save_sync.make_search_query("SMW_20250920.srm"), "SMW 20250920")


class ResolveOrphanTest(unittest.TestCase):
    def test_resolved_single_exact_match(self):
        fetch = _fake_fetch([_smwc_hack("12345", "Le Plume")])
        r = save_sync.resolve_orphan("le_plume_v0.3.srm", set(), fetch_fn=fetch)
        self.assertEqual(r["status"], save_sync.RESOLUTION_RESOLVED)
        self.assertEqual(r["hack_id"], "12345")

    def test_exists_when_already_in_collection(self):
        fetch = _fake_fetch([_smwc_hack("12345", "Le Plume")])
        r = save_sync.resolve_orphan("le plume.srm", {"12345"}, fetch_fn=fetch)
        self.assertEqual(r["status"], save_sync.RESOLUTION_EXISTS)

    def test_no_match_when_titles_differ(self):
        fetch = _fake_fetch([_smwc_hack("1", "Totally Different Hack")])
        r = save_sync.resolve_orphan("SMW_20250920.srm", set(), fetch_fn=fetch)
        self.assertEqual(r["status"], save_sync.RESOLUTION_NO_MATCH)

    def test_ambiguous_two_live_matches(self):
        fetch = _fake_fetch([_smwc_hack("1", "Colors"), _smwc_hack("2", "Colors")])
        r = save_sync.resolve_orphan("Colors.srm", set(), fetch_fn=fetch)
        self.assertEqual(r["status"], save_sync.RESOLUTION_AMBIGUOUS)

    def test_obsolete_disambiguates(self):
        fetch = _fake_fetch([
            _smwc_hack("1", "Colors", obsolete=True),
            _smwc_hack("2", "Colors", obsolete=False),
        ])
        r = save_sync.resolve_orphan("Colors.srm", set(), fetch_fn=fetch)
        self.assertEqual(r["status"], save_sync.RESOLUTION_RESOLVED)
        self.assertEqual(r["hack_id"], "2")

    def test_error_on_fetch_exception(self):
        def boom(config, page=1, waiting_mode=False, log=None):
            raise RuntimeError("network down")
        r = save_sync.resolve_orphan("Anything.srm", set(), fetch_fn=boom)
        self.assertEqual(r["status"], save_sync.RESOLUTION_ERROR)


class EntryFieldsTest(unittest.TestCase):
    def test_maps_core_fields(self):
        fields = save_sync._smwc_entry_fields(_smwc_hack("9", "6 Hours", length=6))
        self.assertEqual(fields["exits"], 6)
        self.assertEqual(fields["difficulty_id"], "diff_4")
        self.assertEqual(fields["hack_type"], "kaizo")
        self.assertEqual(fields["file_path"], "")            # no local ROM yet
        # date derives from the unix timestamp (compare in local time, TZ-safe)
        from datetime import datetime
        expected = datetime.fromtimestamp(1704067200).strftime("%Y-%m-%d")
        self.assertEqual(fields["date"], expected)
        self.assertTrue(fields["title"])


class ImportOrphanTest(unittest.TestCase):
    def test_import_creates_id_keyed_entry(self):
        dm = FakeDataManager()
        cand = save_sync.SyncCandidate(
            save_path="x", save_name="6 Hours.srm", mtime=1719800000.0,
            collected_exits=6, resolution=save_sync.RESOLUTION_RESOLVED,
            resolved_hack=_smwc_hack("777", "6 Hours", length=6),
            resolved_hack_id="777",
        )
        ok = save_sync.import_orphan(cand, dm)
        self.assertTrue(ok)
        self.assertIn("777", dm.data)                        # keyed by real SMWC id
        self.assertTrue(dm.data["777"]["completed"])         # 6>=6 -> completed
        self.assertEqual(dm.data["777"]["completed_date"], cand.completed_date)

    def test_import_dedupes_against_existing_id(self):
        dm = FakeDataManager({"777": {"title": "Existing"}})
        cand = save_sync.SyncCandidate(
            save_path="x", save_name="6 Hours.srm", mtime=1.0, collected_exits=6,
            resolved_hack=_smwc_hack("777", "6 Hours"), resolved_hack_id="777",
        )
        self.assertFalse(save_sync.import_orphan(cand, dm))   # no duplicate
        self.assertEqual(dm.data["777"], {"title": "Existing"})

    def test_attach_resolution_exists_becomes_completion(self):
        dm = FakeDataManager({"55": {"title": "Owned", "exits": 4, "completed": False}})
        cand = save_sync.SyncCandidate(
            save_path="x", save_name="owned.srm", mtime=1.0, collected_exits=4,
        )
        save_sync.attach_resolution(
            cand, {"status": save_sync.RESOLUTION_EXISTS,
                   "hack": _smwc_hack("55", "Owned", length=4), "hack_id": "55"}, dm,
        )
        self.assertEqual(cand.hack_id, "55")
        self.assertEqual(cand.status, save_sync.STATUS_COMPLETED)  # 4>=4


class LegacyLayoutContractTest(unittest.TestCase):
    """Lock the vanilla-layout assumptions that later work will replace explicitly."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="savesync_layout_")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write(self, name, blob):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as handle:
            handle.write(blob)
        return path

    def test_legacy_exit_offset_and_minimum_size_are_fixed(self):
        self.assertEqual(SMW_EXIT_COUNT_OFFSET, 0x8C)
        self.assertEqual(MIN_SAVE_SIZE, 0x8D)

    def test_reader_uses_only_the_legacy_exit_counter_byte(self):
        data = bytearray(MIN_SAVE_SIZE + 4)
        data[SMW_EXIT_COUNT_OFFSET - 1] = 91
        data[SMW_EXIT_COUNT_OFFSET] = 17
        data[SMW_EXIT_COUNT_OFFSET + 1] = 73
        path = self._write("layout.srm", bytes(data))
        self.assertEqual(read_collected_exits(path), 17)

    def test_zero_is_a_valid_initialized_exit_count(self):
        path = self._write("new-game.srm", _make_srm_bytes(0))
        self.assertEqual(read_collected_exits(path), 0)

    def test_reader_returns_raw_non_ff_byte_before_classification(self):
        path = self._write("raw.srm", _make_srm_bytes(0xFE))
        self.assertEqual(read_collected_exits(path), 254)
        self.assertEqual(classify(254, 15, False, False), STATUS_UNCERTAIN)


class SaveFileDiscoveryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="savesync_list_")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _touch(self, relative, payload=b"x"):
        path = os.path.join(self.tmp, relative)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def test_extensions_are_case_insensitive_and_results_are_sorted_absolute_paths(self):
        second = self._touch("b.SAV")
        first = self._touch("A.sRm")
        self.assertEqual(
            save_sync.list_save_files(self.tmp),
            sorted([os.path.abspath(first), os.path.abspath(second)]),
        )

    def test_unsupported_extensions_and_nested_saves_are_ignored(self):
        self._touch("notes.txt")
        self._touch("rom.smc")
        self._touch(os.path.join("nested", "hidden.srm"))
        self.assertEqual(save_sync.list_save_files(self.tmp), [])

    def test_directory_named_like_a_save_is_ignored(self):
        os.mkdir(os.path.join(self.tmp, "folder.srm"))
        self.assertEqual(save_sync.list_save_files(self.tmp), [])

    def test_missing_directory_returns_empty_list(self):
        missing = os.path.join(self.tmp, "missing")
        self.assertEqual(save_sync.list_save_files(missing), [])


class NormalizationRegressionTest(unittest.TestCase):
    def test_trailing_decimal_versions_are_removed(self):
        expected = "leplume"
        for name in (
            "Le Plume v1.1.srm",
            "Le_Plume_v0.3.sav",
            "Le-Plume-2.0.srm",
            "Le Plume1.2.srm",
        ):
            self.assertEqual(save_sync._normalize(name), expected)

    def test_integer_title_suffix_is_preserved(self):
        self.assertEqual(
            save_sync._normalize("Grand Poo World 2.srm"),
            "grandpooworld2",
        )

    def test_directory_extension_case_and_punctuation_are_ignored(self):
        name = os.path.join("some", "folder", "Fresh-Hops!.SRM")
        self.assertEqual(save_sync._normalize(name), "freshhops")

    def test_known_rom_paths_and_additional_file_paths_are_indexed(self):
        hack = {
            "id": "10",
            "title": "Canonical Title",
            "file_path": "/roms/Downloaded_Name_v1.2.smc",
            "files": [
                {"path": "/archive/Alternate Name.sfc"},
                "not-a-dictionary",
                {},
            ],
        }
        index = build_hack_index([hack])
        self.assertIs(index[save_sync._normalize("Canonical Title.srm")], hack)
        self.assertIs(index[save_sync._normalize("Downloaded_Name.srm")], hack)
        self.assertIs(index[save_sync._normalize("Alternate Name.sav")], hack)

    def test_first_collection_entry_wins_normalized_title_collision(self):
        first = {"id": "1", "title": "Same Hack"}
        second = {"id": "2", "title": "Same-Hack"}
        index = build_hack_index([first, second])
        self.assertIs(index["samehack"], first)


class CandidatePropertiesTest(unittest.TestCase):
    def test_completed_date_uses_local_calendar_date(self):
        mtime = 1719800000.0
        candidate = save_sync.SyncCandidate("x", "x.srm", mtime, 1)
        expected = save_sync.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
        self.assertEqual(candidate.completed_date, expected)

    def test_zero_mtime_has_no_completed_date(self):
        candidate = save_sync.SyncCandidate("x", "x.srm", 0, 1)
        self.assertEqual(candidate.completed_date, "")

    def test_will_complete_only_tracks_completed_status(self):
        candidate = save_sync.SyncCandidate("x", "x.srm", 1, 1)
        for status in (
            STATUS_IN_PROGRESS,
            STATUS_UNCERTAIN,
            STATUS_ALREADY_COMPLETED,
            STATUS_UNMATCHED,
        ):
            candidate.status = status
            self.assertFalse(candidate.will_complete)
        candidate.status = STATUS_COMPLETED
        self.assertTrue(candidate.will_complete)

    def test_exits_display_preserves_readable_and_unknown_values(self):
        readable = save_sync.SyncCandidate("x", "x.srm", 1, 7, total_exits=12)
        unknown = save_sync.SyncCandidate("x", "x.srm", 1, None, total_exits=12)
        self.assertEqual(readable.exits_display, "7 / 12")
        self.assertEqual(unknown.exits_display, "? / 12")


class DuplicateSelectionRegressionTest(unittest.TestCase):
    HACK = {"id": "1", "title": "Tie Hack", "exits": 10, "completed": False}

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="savesync_duplicates_")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _write(self, name, blob, mtime):
        path = os.path.join(self.tmp, name)
        with open(path, "wb") as handle:
            handle.write(blob)
        os.utime(path, (mtime, mtime))
        return path

    def _single_result(self):
        results = scan_saves(self.tmp, [self.HACK])
        self.assertEqual(len(results), 1)
        return results[0]

    def test_more_exits_beats_a_newer_save(self):
        self._write("Tie Hack v1.0.srm", _make_srm_bytes(8), 1700000000)
        self._write("Tie Hack v1.1.srm", _make_srm_bytes(3), 1800000000)
        self.assertEqual(self._single_result().collected_exits, 8)

    def test_equal_exits_use_the_newest_mtime(self):
        self._write("Tie Hack v1.0.srm", _make_srm_bytes(5), 1700000000)
        newest = self._write("Tie Hack v1.1.srm", _make_srm_bytes(5), 1800000000)
        self.assertEqual(self._single_result().save_path, newest)

    def test_readable_zero_beats_an_unreadable_duplicate(self):
        self._write("Tie Hack v1.0.srm", b"tiny", 1800000000)
        readable = self._write("Tie Hack v1.1.srm", _make_srm_bytes(0), 1700000000)
        result = self._single_result()
        self.assertEqual(result.save_path, readable)
        self.assertEqual(result.collected_exits, 0)


class RecordingDataManager(FakeDataManager):
    def __init__(self, data=None):
        super().__init__(data)
        self.operations = []

    def update_hack(self, hack_id, field, value):
        self.operations.append(("update", hack_id, field, value))
        return super().update_hack(hack_id, field, value)

    def force_save(self):
        self.operations.append(("force_save",))
        return super().force_save()


class ApplyCandidatesRegressionTest(unittest.TestCase):
    def test_date_is_written_before_completed_and_saved_once(self):
        manager = RecordingDataManager({"1": {"completed": False}})
        candidate = save_sync.SyncCandidate(
            "x", "x.srm", 1719800000.0, 4, hack_id="1", status=STATUS_COMPLETED
        )
        applied = save_sync.apply_candidates([candidate], manager)
        self.assertEqual(applied, 1)
        self.assertEqual(
            manager.operations,
            [
                ("update", "1", "completed_date", candidate.completed_date),
                ("update", "1", "completed", True),
                ("force_save",),
            ],
        )

    def test_unmatched_candidates_are_skipped_without_saving(self):
        manager = RecordingDataManager()
        candidate = save_sync.SyncCandidate("x", "x.srm", 1, 1)
        self.assertEqual(save_sync.apply_candidates([candidate], manager), 0)
        self.assertEqual(manager.operations, [])
        self.assertFalse(manager.saved)

    def test_unknown_mtime_sets_completion_without_overwriting_date(self):
        manager = RecordingDataManager(
            {"1": {"completed": False, "completed_date": "2024-01-02"}}
        )
        candidate = save_sync.SyncCandidate("x", "x.srm", 0, 4, hack_id="1")
        save_sync.apply_candidates([candidate], manager)
        self.assertEqual(manager.data["1"]["completed_date"], "2024-01-02")
        self.assertTrue(manager.data["1"]["completed"])

    def test_apply_never_writes_completed_false(self):
        manager = RecordingDataManager({"1": {"completed": True}})
        candidate = save_sync.SyncCandidate(
            "x", "x.srm", 1, 0, hack_id="1", status=STATUS_ALREADY_COMPLETED
        )
        save_sync.apply_candidates([candidate], manager)
        self.assertNotIn(("update", "1", "completed", False), manager.operations)
        self.assertTrue(manager.data["1"]["completed"])


class OrphanResolutionRegressionTest(unittest.TestCase):
    def test_empty_query_returns_no_match_without_fetching(self):
        calls = []

        def fetch(config, page=1, waiting_mode=False, log=None):
            calls.append(config)
            return {"data": []}

        result = save_sync.resolve_orphan("", set(), fetch_fn=fetch)
        self.assertEqual(result["status"], save_sync.RESOLUTION_NO_MATCH)
        self.assertEqual(calls, [])

    def test_non_dictionary_fetch_result_is_no_match(self):
        def fetch(config, page=1, waiting_mode=False, log=None):
            return ["unexpected"]

        result = save_sync.resolve_orphan("Known Hack.srm", set(), fetch_fn=fetch)
        self.assertEqual(result["status"], save_sync.RESOLUTION_NO_MATCH)

    def test_exact_title_without_an_id_is_no_match(self):
        hack = _smwc_hack("", "Known Hack")
        result = save_sync.resolve_orphan(
            "Known Hack.srm", set(), fetch_fn=_fake_fetch([hack])
        )
        self.assertEqual(result["status"], save_sync.RESOLUTION_NO_MATCH)

    def test_versioned_save_matches_unversioned_smwc_title(self):
        result = save_sync.resolve_orphan(
            "Known_Hack_v1.2.srm",
            set(),
            fetch_fn=_fake_fetch([_smwc_hack("42", "Known Hack")]),
        )
        self.assertEqual(result["status"], save_sync.RESOLUTION_RESOLVED)
        self.assertEqual(result["hack_id"], "42")


class OrphanImportRegressionTest(unittest.TestCase):
    def test_incomplete_import_stays_incomplete_without_completion_date(self):
        manager = FakeDataManager()
        candidate = save_sync.SyncCandidate(
            save_path="x",
            save_name="Long Hack.srm",
            mtime=1719800000.0,
            collected_exits=3,
            resolution=save_sync.RESOLUTION_RESOLVED,
            resolved_hack=_smwc_hack("80", "Long Hack", length=10),
            resolved_hack_id="80",
        )
        self.assertTrue(save_sync.import_orphan(candidate, manager))
        self.assertFalse(manager.data["80"]["completed"])
        self.assertEqual(manager.data["80"]["completed_date"], "")

    def test_mark_all_import_completes_an_unreadable_save(self):
        manager = FakeDataManager()
        candidate = save_sync.SyncCandidate(
            save_path="x",
            save_name="Unknown Layout.srm",
            mtime=1719800000.0,
            collected_exits=None,
            resolution=save_sync.RESOLUTION_RESOLVED,
            resolved_hack=_smwc_hack("81", "Unknown Layout", length=10),
            resolved_hack_id="81",
        )
        self.assertTrue(save_sync.import_orphan(candidate, manager, mark_all=True))
        self.assertTrue(manager.data["81"]["completed"])
        self.assertEqual(manager.data["81"]["completed_date"], candidate.completed_date)

    def test_resolved_attachment_populates_metadata_and_status(self):
        manager = FakeDataManager()
        candidate = save_sync.SyncCandidate("x", "x.srm", 1, 2)
        resolution = {
            "status": save_sync.RESOLUTION_RESOLVED,
            "hack": _smwc_hack("82", "Resolved Hack", length=5),
            "hack_id": "82",
        }
        returned = save_sync.attach_resolution(candidate, resolution, manager)
        self.assertIs(returned, candidate)
        self.assertEqual(candidate.title, "Resolved Hack")
        self.assertEqual(candidate.total_exits, 5)
        self.assertEqual(candidate.status, STATUS_IN_PROGRESS)

    def test_unresolved_candidate_cannot_be_imported(self):
        manager = FakeDataManager()
        candidate = save_sync.SyncCandidate("x", "x.srm", 1, 1)
        self.assertFalse(save_sync.import_orphan(candidate, manager))
        self.assertEqual(manager.data, {})

class DiagnosticReportTest(unittest.TestCase):
    def _candidate(
        self,
        *,
        save_name="Example Hack.srm",
        save_path="C:/Users/example/private/saves/Example Hack.srm",
        profile="legacy_raw_counter",
        confidence="low",
        status=STATUS_IN_PROGRESS,
        hack_id="42",
        resolution=save_sync.RESOLUTION_NONE,
        resolved_hack_id="",
    ):
        return save_sync.SyncCandidate(
            save_path=save_path,
            save_name=save_name,
            mtime=1_700_000_000,
            collected_exits=3,
            save_size=8192,
            profile=profile,
            counter_kind="overworld_events",
            confidence=confidence,
            warnings=("example warning",),
            hack_id=hack_id,
            title="Example Hack" if hack_id else "",
            total_exits=10 if hack_id else 0,
            status=status,
            resolution=resolution,
            resolved_hack_id=resolved_hack_id,
        )

    def test_report_redacts_paths_and_raw_save_data(self):
        private_path = "C:/Users/example/private/saves/Example Hack.srm"
        report = save_sync.build_diagnostic_report(
            [self._candidate(save_path=private_path)],
            generated_at=datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc),
        )
        encoded = json.dumps(report)
        self.assertNotIn(private_path, encoded)
        self.assertNotIn("C:/Users/example/private", encoded)
        self.assertFalse(report["privacy"]["absolute_paths_included"])
        self.assertFalse(report["privacy"]["raw_save_bytes_included"])
        self.assertNotIn("path", report["candidates"][0]["analysis"])

    def test_report_summarizes_and_sorts_candidates(self):
        candidates = [
            self._candidate(
                save_name="Zulu.srm",
                profile="expanded_sram_unknown",
                confidence="none",
                status=STATUS_UNCERTAIN,
                hack_id="",
            ),
            self._candidate(save_name="Alpha.sav"),
        ]
        report = save_sync.build_diagnostic_report(
            candidates,
            generated_at=datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(report["generated_at_utc"], "2026-07-27T10:30:00Z")
        self.assertEqual(
            [row["save"]["name"] for row in report["candidates"]],
            ["Alpha.sav", "Zulu.srm"],
        )
        self.assertEqual(report["summary"]["candidate_count"], 2)
        self.assertEqual(report["summary"]["matched_count"], 1)
        self.assertEqual(report["summary"]["unmatched_count"], 1)
        self.assertEqual(
            report["summary"]["confidence_counts"],
            {"low": 1, "none": 1},
        )

    def test_report_distinguishes_direct_resolved_and_unresolved_matches(self):
        candidates = [
            self._candidate(save_name="Direct.srm", hack_id="42"),
            self._candidate(
                save_name="Resolved New.srm",
                hack_id="",
                resolution=save_sync.RESOLUTION_RESOLVED,
                resolved_hack_id="99",
            ),
            self._candidate(
                save_name="Resolved Existing.srm",
                hack_id="7",
                resolution=save_sync.RESOLUTION_EXISTS,
                resolved_hack_id="7",
            ),
            self._candidate(
                save_name="Unresolved.srm",
                hack_id="",
                resolution=save_sync.RESOLUTION_NO_MATCH,
            ),
        ]
        report = save_sync.build_diagnostic_report(candidates)
        summary = report["summary"]
        self.assertEqual(summary["direct_match_count"], 1)
        self.assertEqual(summary["resolved_through_smwc_count"], 2)
        self.assertEqual(summary["effective_matched_count"], 3)
        self.assertEqual(summary["unresolved_count"], 1)
        self.assertEqual(summary["matched_count"], 3)
        self.assertEqual(summary["unmatched_count"], 1)
        self.assertEqual(
            summary["resolution_counts"],
            {"exists": 1, "no_match": 1, "not_attempted": 1, "resolved": 1},
        )

    def test_report_includes_review_only_catalogue_suggestion_evidence(self):
        candidate = self._candidate(
            save_name="CR2.srm",
            hack_id="",
            resolution=save_sync.RESOLUTION_REVIEW,
        )
        candidate.suggested_hack_id = "40504"
        candidate.suggested_title = "Chain Reaction 2"
        candidate.suggested_difficulty = "Advanced"
        candidate.suggested_classification = "Abbreviation - review"
        candidate.suggested_confidence = 0.92
        candidate.suggested_margin = 0.20
        candidate.suggested_candidates = (
            {"hack_id": "40504", "title": "Chain Reaction 2", "score": 0.92},
        )

        report = save_sync.build_diagnostic_report([candidate])
        row = report["candidates"][0]

        self.assertFalse(row["match"]["effective"])
        self.assertEqual("review", row["resolution"]["status"])
        self.assertEqual("40504", row["resolution"]["suggestion"]["hack_id"])
        self.assertEqual(
            "Abbreviation - review",
            row["resolution"]["suggestion"]["classification"],
        )
        self.assertEqual(0.92, row["resolution"]["suggestion"]["confidence"])

    def test_candidate_rows_expose_effective_match_source(self):
        candidates = [
            self._candidate(save_name="Direct.srm", hack_id="42"),
            self._candidate(
                save_name="Resolved New.srm",
                hack_id="",
                resolution=save_sync.RESOLUTION_RESOLVED,
                resolved_hack_id="99",
            ),
            self._candidate(
                save_name="Resolved Existing.srm",
                hack_id="7",
                resolution=save_sync.RESOLUTION_EXISTS,
                resolved_hack_id="7",
            ),
            self._candidate(save_name="None.srm", hack_id=""),
        ]
        report = save_sync.build_diagnostic_report(candidates)
        rows = {row["save"]["name"]: row["match"] for row in report["candidates"]}
        self.assertEqual(rows["Direct.srm"]["source"], "collection")
        self.assertEqual(rows["Direct.srm"]["effective_hack_id"], "42")
        self.assertEqual(rows["Resolved New.srm"]["source"], "smwc_new")
        self.assertEqual(rows["Resolved New.srm"]["effective_hack_id"], "99")
        self.assertEqual(rows["Resolved Existing.srm"]["source"], "smwc_existing")
        self.assertEqual(rows["None.srm"]["source"], "none")
        self.assertFalse(rows["None.srm"]["effective"])

    def test_writer_produces_stable_json_and_creates_parent(self):
        with tempfile.TemporaryDirectory(prefix="save_diag_report_") as root:
            destination = Path(root) / "nested" / "report.json"
            written = save_sync.write_diagnostic_report(
                destination,
                [self._candidate()],
                generated_at=datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc),
            )
            self.assertTrue(Path(written).is_absolute())
            self.assertTrue(os.path.samefile(written, destination))
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(payload["schema_version"], 4)
            self.assertTrue(
                destination.read_text(encoding="utf-8").endswith("\n")
            )
            self.assertFalse(destination.with_suffix(".json.tmp").exists())

    def test_default_filename_uses_supplied_timestamp(self):
        stamp = datetime(2026, 7, 27, 10, 30, 45)
        self.assertEqual(
            save_sync.diagnostic_filename(stamp),
            "SMWC-Save-Diagnostics-20260727-103045.json",
        )

    def test_review_dialog_exposes_diagnostic_export(self):
        source = (
            Path(__file__).parent / "ui" / "save_sync_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertIn('text="Export Diagnostics..."', source)
        self.assertIn("save_sync.write_diagnostic_report", source)
        self.assertIn("no absolute paths or raw save bytes", source)

class LegacyEmptySlotPatternTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="legacy_fill_")
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write(self, name, fill):
        path = self.root / name
        path.write_bytes(bytes([fill]) * 2048)
        return path

    def test_repeated_0x60_pattern_is_unknown_for_both_extensions(self):
        srm = self._write("empty.srm", 0x60)
        sav = self._write("empty.sav", 0x60)
        self.assertIsNone(save_sync.read_collected_exits(srm))
        self.assertEqual(
            save_sync.read_collected_exits(srm),
            save_sync.read_collected_exits(sav),
        )

    def test_scan_does_not_complete_from_repeated_0x60_pattern(self):
        self._write("Known Hack.srm", 0x60)
        candidates = save_sync.scan_saves(
            str(self.root),
            [{"id": "1", "title": "Known Hack", "exits": 5}],
        )
        self.assertEqual(len(candidates), 1)
        self.assertIsNone(candidates[0].collected_exits)
        self.assertEqual(candidates[0].status, save_sync.STATUS_UNCERTAIN)

class ManualOrphanSearchTest(unittest.TestCase):
    def _hack(
        self,
        hack_id,
        name,
        *,
        obsolete=False,
        difficulty="diff_3",
    ):
        return {
            "id": hack_id,
            "name": name,
            "raw_fields": {
                "obsolete": obsolete,
                "difficulty": difficulty,
                "type": "kaizo",
                "length": 10,
            },
        }

    def test_empty_query_does_not_fetch(self):
        calls = []

        def fetch(params, log=None):
            calls.append(params)
            return {"data": []}

        result = save_sync.search_orphan_options(
            "   ",
            set(),
            fetch_fn=fetch,
        )
        self.assertEqual(result["status"], save_sync.RESOLUTION_NO_MATCH)
        self.assertEqual(result["options"], [])
        self.assertEqual(calls, [])

    def test_manual_results_are_ranked_deduplicated_and_annotated(self):
        exact_existing = self._hack("2", "Quickie World 2")
        exact_obsolete = self._hack(
            "3",
            "Quickie World 2",
            obsolete=True,
        )
        near = self._hack("1", "Quickie World")

        def fetch(params, log=None):
            self.assertEqual(params, {"name": "Quickie World 2"})
            return {
                "data": [
                    near,
                    exact_obsolete,
                    exact_existing,
                    exact_existing,
                ]
            }

        result = save_sync.search_orphan_options(
            "Quickie_World_2.srm",
            {"2"},
            fetch_fn=fetch,
        )
        self.assertEqual(result["status"], save_sync.SEARCH_RESULTS)
        self.assertEqual(
            [item["hack_id"] for item in result["options"]],
            ["2", "3", "1"],
        )
        first = result["options"][0]
        self.assertTrue(first["exact_title"])
        self.assertTrue(first["in_collection"])
        self.assertFalse(first["obsolete"])
        self.assertEqual(first["difficulty"], "Intermediate")

    def test_manual_search_does_not_weaken_strict_automatic_resolution(self):
        near = self._hack("1", "Quickie World 2")

        def fetch(params, log=None):
            return {"data": [near]}

        automatic = save_sync.resolve_orphan(
            "QW2.srm",
            set(),
            fetch_fn=fetch,
        )
        manual = save_sync.search_orphan_options(
            "Quickie World 2",
            set(),
            fetch_fn=fetch,
        )
        self.assertEqual(
            automatic["status"],
            save_sync.RESOLUTION_NO_MATCH,
        )
        self.assertEqual(manual["status"], save_sync.SEARCH_RESULTS)
        self.assertEqual(manual["options"][0]["hack_id"], "1")

    def test_search_error_is_reported_without_options(self):
        def fetch(params, log=None):
            raise RuntimeError("offline")

        result = save_sync.search_orphan_options(
            "Akogare 2",
            set(),
            fetch_fn=fetch,
        )
        self.assertEqual(result["status"], save_sync.RESOLUTION_ERROR)
        self.assertEqual(result["options"], [])

    def test_selected_hack_resolution_respects_existing_collection(self):
        hack = self._hack("42", "A Pretty View")
        new = save_sync.resolution_for_selected_hack(hack, set())
        existing = save_sync.resolution_for_selected_hack(hack, {42})
        invalid = save_sync.resolution_for_selected_hack(
            {"name": "No ID"},
            set(),
        )
        self.assertEqual(new["status"], save_sync.RESOLUTION_RESOLVED)
        self.assertEqual(existing["status"], save_sync.RESOLUTION_EXISTS)
        self.assertEqual(invalid["status"], save_sync.RESOLUTION_NO_MATCH)

    def test_limit_is_applied_after_deduplication(self):
        hacks = [
            self._hack(str(index), f"Hack {index}")
            for index in range(5)
        ]

        def fetch(params, log=None):
            return {"data": hacks}

        result = save_sync.search_orphan_options(
            "Hack",
            set(),
            fetch_fn=fetch,
            limit=2,
        )
        self.assertEqual(len(result["options"]), 2)

class ManualOrphanSearchUiTest(unittest.TestCase):
    def _source(self):
        return (
            Path(__file__).parent / "ui" / "save_sync_dialog.py"
        ).read_text(encoding="utf-8")

    def test_review_dialog_exposes_manual_search_action(self):
        source = self._source()
        self.assertIn('text="Search Selected..."', source)
        self.assertIn('selectmode="browse"', source)
        self.assertIn("def _manual_search_selected", source)

    def test_manual_dialog_uses_explicit_search_and_selection_contract(self):
        source = self._source()
        self.assertIn("class ManualSmwcSearchDialog", source)
        self.assertIn("save_sync.search_orphan_options", source)
        self.assertIn("save_sync.resolution_for_selected_hack", source)
        self.assertIn("No result is chosen automatically.", source)

    def test_manual_search_runs_off_tk_main_thread(self):
        source = self._source()
        self.assertIn("target=self._search_worker", source)
        self.assertIn("self._ui(self._show_results, result)", source)

    def test_bulk_lookup_remains_strict_and_selection_reuses_attach_flow(self):
        source = self._source()
        self.assertIn("save_sync.resolve_orphan(", source)
        self.assertIn("def _set_orphan_resolution", source)
        self.assertIn("save_sync.attach_resolution(", source)

    def test_manual_results_show_release_and_collection_state(self):
        source = self._source()
        self.assertIn('if obsolete is True:', source)
        self.assertIn('release = "Obsolete"', source)
        self.assertIn('elif obsolete is False:', source)
        self.assertIn('release = "Current"', source)
        self.assertIn('release = "Catalogue"', source)
        self.assertIn(
            'collection = "Already added" '
            'if option["in_collection"] else "New"',
            source,
        )

class SaveAssociationTest(unittest.TestCase):
    class FakeConfig:
        def __init__(self, initial=None):
            self.values = dict(initial or {})
            self.set_calls = []

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value
            self.set_calls.append((key, value))

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="save_alias_")
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _write_save(self, name, exits=22):
        path = self.root / name
        path.write_bytes(_make_srm_bytes(exits, size=8192))
        return path

    def test_remember_replace_and_forget_use_normalized_filename_key(self):
        config = self.FakeConfig()
        self.assertTrue(
            save_sync.remember_save_association(
                config, "/private/saves/QW2.srm", "19279"
            )
        )
        self.assertEqual(
            config.values[save_sync.ASSOCIATION_CONFIG_KEY],
            {"qw2": "19279"},
        )
        self.assertFalse(
            save_sync.remember_save_association(
                config, "qw2.sav", "19279"
            )
        )
        self.assertTrue(
            save_sync.remember_save_association(
                config, "QW2.srm", "99999"
            )
        )
        self.assertEqual(
            config.values[save_sync.ASSOCIATION_CONFIG_KEY]["qw2"],
            "99999",
        )
        self.assertTrue(
            save_sync.forget_save_association(config, "QW2.srm")
        )
        self.assertEqual(
            config.values[save_sync.ASSOCIATION_CONFIG_KEY], {}
        )

    def test_prune_drops_targets_missing_from_collection(self):
        valid, removed = save_sync.prune_save_associations(
            {"QW2.srm": "19279", "Old.srm": "404"},
            {"19279"},
        )
        self.assertEqual(valid, {"qw2": "19279"})
        self.assertEqual(removed, 1)

    def test_scan_uses_saved_association_as_fallback(self):
        self._write_save("QW2.srm")
        hacks = [
            {"id": "19279", "title": "Quickie World 2", "exits": 22}
        ]
        unmatched = save_sync.scan_saves(str(self.root), hacks)
        self.assertEqual(unmatched[0].status, save_sync.STATUS_UNMATCHED)

        matched = save_sync.scan_saves(
            str(self.root),
            hacks,
            associations={"QW2.srm": "19279"},
        )
        self.assertEqual(matched[0].hack_id, "19279")
        self.assertEqual(matched[0].status, save_sync.STATUS_COMPLETED)
        self.assertEqual(
            matched[0].match_source,
            save_sync.MATCH_SOURCE_SAVED_ALIAS,
        )

    def test_direct_collection_match_takes_precedence_over_saved_alias(self):
        self._write_save("Quickie World 2.srm")
        hacks = [
            {"id": "19279", "title": "Quickie World 2", "exits": 22},
            {"id": "99999", "title": "Different Hack", "exits": 22},
        ]
        candidates = save_sync.scan_saves(
            str(self.root),
            hacks,
            associations={"Quickie World 2.srm": "99999"},
        )
        self.assertEqual(candidates[0].hack_id, "19279")
        self.assertEqual(
            candidates[0].match_source,
            save_sync.MATCH_SOURCE_COLLECTION,
        )

    def test_diagnostics_identify_saved_associations(self):
        candidate = save_sync.SyncCandidate(
            save_path="QW2.srm",
            save_name="QW2.srm",
            mtime=0,
            collected_exits=22,
            hack_id="19279",
            title="Quickie World 2",
            total_exits=22,
            status=save_sync.STATUS_COMPLETED,
            match_source=save_sync.MATCH_SOURCE_SAVED_ALIAS,
        )
        report = save_sync.build_diagnostic_report([candidate])
        self.assertEqual(report["schema_version"], 4)
        self.assertEqual(report["summary"]["direct_match_count"], 0)
        self.assertEqual(report["summary"]["saved_association_count"], 1)
        match = report["candidates"][0]["match"]
        self.assertEqual(match["source"], "saved_alias")
        self.assertTrue(match["saved_association"])

    def test_config_and_ui_sources_expose_association_lifecycle(self):
        config_source = (
            Path(__file__).parent / "config_manager.py"
        ).read_text(encoding="utf-8")
        settings_source = (
            Path(__file__).parent / "ui" / "pages" / "settings_page.py"
        ).read_text(encoding="utf-8")
        dialog_source = (
            Path(__file__).parent / "ui" / "save_sync_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"save_sync_associations": {}', config_source)
        self.assertIn("associations=associations", settings_source)
        self.assertIn(
            "config_manager=self.setup_section.config", settings_source
        )
        self.assertIn("manual=True", dialog_source)
        self.assertIn("save_sync.remember_save_association", dialog_source)
        self.assertIn('text="Forget Saved Match"', dialog_source)
        self.assertIn("save_sync.forget_save_association", dialog_source)
        self.assertIn(
            "and c.status == save_sync.STATUS_COMPLETED", dialog_source
        )

class SaveSourceDirectoryTest(unittest.TestCase):
    class Config:
        def __init__(self, values=None):
            self.values = dict(values or {})

        def get(self, key, default=""):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="save_sources_")
        self.first = os.path.join(self.root, "first")
        self.second = os.path.join(self.root, "second")
        os.makedirs(self.first)
        os.makedirs(self.second)

    def tearDown(self):
        import shutil

        shutil.rmtree(self.root)

    def test_legacy_directory_migrates_to_canonical_source_list(self):
        config = self.Config(
            {
                "save_sync_dir": self.first,
                "save_sync_dirs": [],
            }
        )
        directories = save_sync.get_save_directories(config)
        self.assertEqual(directories, [os.path.abspath(self.first)])
        self.assertEqual(config.values["save_sync_dirs"], directories)
        self.assertEqual(config.values["save_sync_dir"], directories[0])

    def test_add_remove_deduplicate_and_mirror_legacy_source(self):
        config = self.Config()
        self.assertTrue(save_sync.add_save_directory(config, self.first))
        self.assertFalse(save_sync.add_save_directory(config, self.first))
        self.assertTrue(save_sync.add_save_directory(config, self.second))
        self.assertEqual(
            config.values["save_sync_dirs"],
            [os.path.abspath(self.first), os.path.abspath(self.second)],
        )
        self.assertTrue(save_sync.remove_save_directory(config, self.first))
        self.assertEqual(
            config.values["save_sync_dir"],
            os.path.abspath(self.second),
        )
        self.assertFalse(save_sync.remove_save_directory(config, self.first))

    def test_discovery_combines_sources_and_deduplicates_repeated_folder(self):
        first_save = os.path.join(self.first, "First.srm")
        second_save = os.path.join(self.second, "Second.SAV")
        with open(first_save, "wb") as handle:
            handle.write(b"x")
        with open(second_save, "wb") as handle:
            handle.write(b"y")
        with open(os.path.join(self.second, "ignore.txt"), "wb") as handle:
            handle.write(b"z")

        found = save_sync.list_save_files_from_directories(
            [self.first, self.second, self.first]
        )
        self.assertEqual(set(found), {first_save, second_save})

    def test_multi_source_scan_keeps_strongest_candidate_across_folders(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        first_save = os.path.join(self.first, "Shared Hack.srm")
        second_save = os.path.join(self.second, "Shared Hack.srm")
        for path in (first_save, second_save):
            with open(path, "wb") as handle:
                handle.write(b"save")

        def analysis_for(path):
            value = 2 if os.path.dirname(path) == self.first else 5
            return SimpleNamespace(
                selected_value=value,
                size=4,
                profile="test",
                counter_kind="overworld_events",
                confidence="medium",
                warnings=[],
            )

        hacks = [
            {
                "id": "42",
                "title": "Shared Hack",
                "exits": 10,
                "completed": False,
            }
        ]
        with patch("save_sync.analyze_save", side_effect=analysis_for):
            candidates = save_sync.scan_save_directories(
                [self.first, self.second],
                hacks,
            )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].collected_exits, 5)
        self.assertEqual(candidates[0].save_path, second_save)

    def test_config_and_settings_sources_expose_multiple_folder_lifecycle(self):
        from pathlib import Path

        root = Path(__file__).parent
        config_source = (root / "config_manager.py").read_text(
            encoding="utf-8"
        )
        settings_source = (
            root / "ui" / "pages" / "settings_page.py"
        ).read_text(encoding="utf-8")
        self.assertIn('"save_sync_dirs": []', config_source)
        self.assertIn('text="Add Folder..."', settings_source)
        self.assertIn('text="Remove Selected"', settings_source)
        self.assertIn("save_sync.scan_save_directories(", settings_source)
        self.assertIn("Unavailable Save Folders", settings_source)

class StartupSaveScanTest(unittest.TestCase):
    def _candidate(self, *, status, hack_id="42"):
        return save_sync.SyncCandidate(
            save_path="C:/Saves/Test.srm",
            save_name="Test.srm",
            mtime=1,
            collected_exits=1,
            hack_id=hack_id,
            title="Test",
            total_exits=2,
            status=status,
        )

    def test_auto_review_keeps_completions_and_unmatched_only(self):
        candidates = [
            self._candidate(status=save_sync.STATUS_COMPLETED),
            self._candidate(status=save_sync.STATUS_IN_PROGRESS),
            self._candidate(status=save_sync.STATUS_UNCERTAIN),
            self._candidate(status=save_sync.STATUS_ALREADY_COMPLETED),
            self._candidate(
                status=save_sync.STATUS_UNMATCHED,
                hack_id="",
            ),
        ]
        selected = save_sync.auto_review_candidates(candidates)
        self.assertEqual(selected, [candidates[0], candidates[4]])

    def test_config_declares_opt_in_startup_scan(self):
        from pathlib import Path

        source = (Path(__file__).parent / "config_manager.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"save_sync_auto_scan": False', source)
        self.assertIn('"save_sync_auto_scan"', source)
        self.assertIn('"save_sync_associations"', source)

    def test_settings_expose_review_only_startup_scan(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "ui" / "pages" / "settings_page.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Check save folders automatically on startup",
            source,
        )
        self.assertIn("nothing is applied automatically", source)
        self.assertIn('text="Review Auto-Scan..."', source)
        self.assertIn(
            "self.frame.after(2000, self.start_save_sync_auto_scan)",
            source,
        )

    def test_startup_scan_is_noninteractive_and_retains_review_candidates(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "ui" / "pages" / "settings_page.py"
        ).read_text(encoding="utf-8")
        self.assertIn("self._scan_saves(auto=True)", source)
        self.assertIn("interactive=not auto", source)
        self.assertIn(
            "review_candidates = save_sync.auto_review_candidates(",
            source,
        )
        self.assertIn("collection=collection", source)
        self.assertIn("def _review_auto_scan", source)
        self.assertNotIn(
            "apply_candidates(review_candidates",
            source,
        )

class PeriodicSaveScanTest(unittest.TestCase):
    def test_interval_normalization_is_closed_to_supported_values(self):
        self.assertEqual(save_sync.normalize_auto_scan_interval(5), 5)
        self.assertEqual(save_sync.normalize_auto_scan_interval("60"), 60)
        self.assertEqual(save_sync.normalize_auto_scan_interval(7), 15)
        self.assertEqual(save_sync.normalize_auto_scan_interval("bad"), 15)

    def test_config_declares_opt_in_periodic_scan(self):
        from pathlib import Path

        source = (Path(__file__).parent / "config_manager.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"save_sync_periodic_scan": False', source)
        self.assertIn('"save_sync_scan_interval_minutes": 15', source)

    def test_settings_expose_controlled_periodic_review_scan(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "ui" / "pages" / "settings_page.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Continue checking while the application is open",
            source,
        )
        self.assertIn(
            "self.frame.after(2500, self.start_save_sync_periodic_scan)",
            source,
        )
        self.assertIn("def _restart_periodic_save_sync_scan", source)
        self.assertIn("minutes * 60 * 1000", source)

    def test_periodic_scan_defers_while_review_is_pending(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "ui" / "pages" / "settings_page.py"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "not self._auto_scan_running "
            "and not self._pending_auto_scan_candidates",
            source,
        )
        self.assertIn("self._scan_saves(auto=True)", source)
        self.assertNotIn("apply_candidates(self._pending_auto_scan_candidates", source)

class LocalSaveEntryTest(unittest.TestCase):
    class DataManager:
        def __init__(self):
            self.data = {}

        def add_user_hack(self, hack_id, entry):
            self.data[hack_id] = dict(entry)
            return True

    def test_local_entry_id_is_opaque_random_and_evidence_independent(self):
        first_id, first = save_sync.build_local_entry(
            os.path.join("private", "QW2.srm"), "Unlisted Hack", 12
        )
        second_id, second = save_sync.build_local_entry(
            os.path.join("other", "QW2.srm"), "Unlisted Hack", "12"
        )
        self.assertRegex(first_id, r"^usr_[0-9a-f]{16}$")
        self.assertRegex(second_id, r"^usr_[0-9a-f]{16}$")
        self.assertNotEqual(first_id, second_id)
        self.assertNotIn("private", first_id)
        self.assertNotIn("qw2", first_id.casefold())
        self.assertEqual(first["exits"], 12)
        self.assertTrue(first["local_save_entry"])
        self.assertEqual(first, second)

    def test_local_entry_validation_rejects_invalid_fields(self):
        with self.assertRaises(ValueError):
            save_sync.build_local_entry("save.srm", "", 4)
        with self.assertRaises(ValueError):
            save_sync.build_local_entry("save.srm", "Hack", "many")
        with self.assertRaises(ValueError):
            save_sync.build_local_entry("save.srm", "Hack", -1)

    def test_attach_and_import_local_entry_preserve_review_boundary(self):
        manager = self.DataManager()
        candidate = save_sync.SyncCandidate(
            save_path="/private/Unlisted.srm",
            save_name="Unlisted.srm",
            mtime=0,
            collected_exits=5,
        )
        resolution = save_sync.resolution_for_local_entry(
            candidate.save_name, "Unlisted Hack", 10, manager.data.keys()
        )
        save_sync.attach_resolution(candidate, resolution, manager)
        self.assertEqual(candidate.resolution, save_sync.RESOLUTION_LOCAL)
        self.assertEqual(candidate.status, save_sync.STATUS_IN_PROGRESS)
        self.assertEqual(manager.data, {})

        self.assertTrue(save_sync.import_local_orphan(candidate, manager))
        entry = manager.data[candidate.resolved_hack_id]
        self.assertEqual(entry["title"], "Unlisted Hack")
        self.assertFalse(entry["completed"])
        self.assertTrue(entry["local_save_entry"])


    def test_local_resolution_never_reidentifies_existing_entry_by_title(self):
        hack_id, _entry = save_sync.build_local_entry(
            "Unlisted.srm", "Unlisted Hack", 10
        )
        resolution = save_sync.resolution_for_local_entry(
            "Unlisted.srm", "Unlisted Hack", 10, {hack_id}
        )
        self.assertEqual(resolution["status"], save_sync.RESOLUTION_LOCAL)
        self.assertNotEqual(resolution["hack_id"], hack_id)
        self.assertRegex(resolution["hack_id"], r"^usr_[0-9a-f]{16}$")

    def test_diagnostics_identify_local_custom_resolution(self):
        manager = self.DataManager()
        candidate = save_sync.SyncCandidate(
            save_path="/private/Unlisted.srm",
            save_name="Unlisted.srm",
            mtime=0,
            collected_exits=10,
        )
        resolution = save_sync.resolution_for_local_entry(
            candidate.save_name, "Unlisted Hack", 10, manager.data.keys()
        )
        save_sync.attach_resolution(candidate, resolution, manager)
        report = save_sync.build_diagnostic_report([candidate])
        self.assertEqual(report["schema_version"], 4)
        self.assertEqual(report["summary"]["local_custom_count"], 1)
        match = report["candidates"][0]["match"]
        self.assertEqual(match["source"], "local_custom")
        self.assertTrue(match["effective"])
        self.assertFalse(match["resolved_through_smwc"])

    def test_review_ui_exposes_explicit_local_entry_creation(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "ui" / "save_sync_dialog.py"
        ).read_text(encoding="utf-8")
        self.assertIn("class LocalSaveEntryDialog", source)
        self.assertIn('text="Create Local Entry..."', source)
        self.assertIn("save_sync.resolution_for_local_entry", source)
        self.assertIn("save_sync.import_local_orphan", source)
        self.assertIn("Apply Selected", source)

class LocalSaveEntryLifecycleRegressionTest(unittest.TestCase):
    @staticmethod
    def _local_hack():
        return {
            "id": "usr_cc154f1fc78c6ebd",
            "title": "Grand Poo World 3",
            "exits": 41,
            "completed": False,
            "local_save_entry": True,
        }

    @staticmethod
    def _analysis(path):
        from types import SimpleNamespace

        return SimpleNamespace(
            selected_value=41,
            size=4096,
            profile="standard_smw_slots",
            counter_kind="overworld_events",
            confidence="medium",
            warnings=[],
            as_dict=lambda: {
                "path": path,
                "size": 4096,
                "profile": "standard_smw_slots",
                "counter_kind": "overworld_events",
                "confidence": "medium",
                "selected_value": 41,
                "warnings": [],
                "attempts": [],
            },
        )

    def test_local_entries_are_excluded_from_automatic_title_matching(self):
        local = self._local_hack()
        normal = {
            "id": "123",
            "title": "Normal Hack",
            "exits": 5,
        }

        index = save_sync.build_hack_index([local, normal])

        self.assertNotIn(
            save_sync._normalize("Grand_Poo_World_3.srm"),
            index,
        )
        self.assertEqual(
            index[save_sync._normalize("Normal Hack.srm")]["id"],
            "123",
        )

    def test_local_save_without_association_remains_unmatched(self):
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as directory:
            save_path = os.path.join(directory, "Grand_Poo_World_3.srm")
            with open(save_path, "wb") as handle:
                handle.write(b"save")

            with patch(
                "save_sync.analyze_save",
                return_value=self._analysis(save_path),
            ):
                candidates = save_sync.scan_saves(
                    directory,
                    [self._local_hack()],
                    associations={},
                )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].status, save_sync.STATUS_UNMATCHED)
        self.assertEqual(candidates[0].hack_id, "")

    def test_local_save_uses_saved_alias_and_reports_it(self):
        from unittest.mock import patch

        local = self._local_hack()
        with tempfile.TemporaryDirectory() as directory:
            save_path = os.path.join(directory, "Grand_Poo_World_3.srm")
            with open(save_path, "wb") as handle:
                handle.write(b"save")

            with patch(
                "save_sync.analyze_save",
                return_value=self._analysis(save_path),
            ):
                candidates = save_sync.scan_saves(
                    directory,
                    [local],
                    associations={
                        "grandpooworld3": local["id"],
                    },
                )

        self.assertEqual(len(candidates), 1)
        self.assertEqual(
            candidates[0].match_source,
            save_sync.MATCH_SOURCE_SAVED_ALIAS,
        )
        report = save_sync.build_diagnostic_report(candidates)
        self.assertEqual(report["summary"]["saved_association_count"], 1)
        self.assertEqual(
            report["candidates"][0]["match"]["source"],
            "saved_alias",
        )
        self.assertTrue(
            report["candidates"][0]["match"]["saved_association"]
        )

    def test_local_resolution_refreshes_apply_state_immediately(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "ui" / "save_sync_dialog.py"
        ).read_text(encoding="utf-8")
        method = source.split(
            "    def _set_orphan_resolution", 1
        )[1].split("    def _lookup_done", 1)[0]

        self.assertIn("self._update_orph_header()", method)
        self.assertIn("self._update_apply_state()", method)

class LocalSaveEntryManagementTest(unittest.TestCase):
    class DataManager:
        def __init__(self, data, save_result=True):
            self.data = data
            self.unsaved_changes = False
            self.save_result = save_result
            self.save_calls = 0

        def force_save(self):
            self.save_calls += 1
            return self.save_result

    class Config:
        def __init__(self, values=None):
            self.values = dict(values or {})

        def get(self, key, default=None):
            return self.values.get(key, default)

        def set(self, key, value):
            self.values[key] = value

    def test_edit_preserves_identity_and_collection_state(self):
        entry = {
            "title": "Old Title",
            "exits": 10,
            "completed": True,
            "completed_date": "2026-01-02",
            "notes": "keep me",
            "personal_rating": 5,
            "local_save_entry": True,
        }
        manager = self.DataManager({"usr_aaaaaaaaaaaaaaaa": entry})

        changed = save_sync.update_local_entry(
            manager,
            "usr_aaaaaaaaaaaaaaaa",
            "New Title",
            25,
        )

        self.assertTrue(changed)
        self.assertIn("usr_aaaaaaaaaaaaaaaa", manager.data)
        self.assertEqual(entry["title"], "New Title")
        self.assertEqual(entry["exits"], 25)
        self.assertTrue(entry["completed"])
        self.assertEqual(entry["completed_date"], "2026-01-02")
        self.assertEqual(entry["notes"], "keep me")
        self.assertEqual(entry["personal_rating"], 5)
        self.assertEqual(manager.save_calls, 1)

    def test_normal_collection_entry_cannot_be_edited_or_removed(self):
        entry = {
            "title": "SMWC Hack",
            "exits": 10,
            "local_save_entry": False,
        }
        manager = self.DataManager({"123": entry})
        config = self.Config({
            save_sync.ASSOCIATION_CONFIG_KEY: {"smwchack": "123"}
        })

        self.assertFalse(
            save_sync.update_local_entry(manager, "123", "Changed", 20)
        )
        removed, aliases = save_sync.remove_local_entry(
            manager, config, "123"
        )
        self.assertFalse(removed)
        self.assertEqual(aliases, 0)
        self.assertIn("123", manager.data)
        self.assertEqual(
            config.values[save_sync.ASSOCIATION_CONFIG_KEY],
            {"smwchack": "123"},
        )

    def test_remove_deletes_only_local_record_and_targeting_aliases(self):
        with tempfile.TemporaryDirectory() as directory:
            recorded_path = os.path.join(directory, "must-remain.srm")
            with open(recorded_path, "wb") as handle:
                handle.write(b"save")

            entry = {
                "title": "Local Hack",
                "exits": 12,
                "local_save_entry": True,
                "file_path": recorded_path,
            }
            manager = self.DataManager({"usr_aaaaaaaaaaaaaaaa": entry})
            config = self.Config({
                save_sync.ASSOCIATION_CONFIG_KEY: {
                    "localhack": "usr_aaaaaaaaaaaaaaaa",
                    "alternate": "usr_aaaaaaaaaaaaaaaa",
                    "other": "456",
                }
            })

            removed, aliases = save_sync.remove_local_entry(
                manager, config, "usr_aaaaaaaaaaaaaaaa"
            )

            self.assertTrue(removed)
            self.assertEqual(aliases, 2)
            self.assertNotIn("usr_aaaaaaaaaaaaaaaa", manager.data)
            self.assertTrue(os.path.isfile(recorded_path))
            self.assertEqual(
                config.values[save_sync.ASSOCIATION_CONFIG_KEY],
                {"other": "456"},
            )

    def test_review_ui_exposes_local_edit_and_safe_removal(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "ui" / "save_sync_dialog.py"
        ).read_text(encoding="utf-8")

        self.assertIn("class EditLocalSaveEntryDialog", source)
        self.assertIn('text="Edit Local Entry..."', source)
        self.assertIn('text="Remove Local Entry..."', source)
        self.assertIn("save_sync.update_local_entry(", source)
        self.assertIn("save_sync.remove_local_entry(", source)
        self.assertIn("The save file will not be deleted", source)

class AutomaticReviewFreshnessTest(unittest.TestCase):
    @staticmethod
    def _candidate(hack_id, status, already_completed=False):
        from types import SimpleNamespace

        return SimpleNamespace(
            hack_id=hack_id,
            status=status,
            already_completed=already_completed,
        )

    def test_auto_review_excludes_scan_evidence_already_completed(self):
        candidate = self._candidate(
            "123",
            save_sync.STATUS_COMPLETED,
            already_completed=True,
        )

        result = save_sync.auto_review_candidates([candidate])

        self.assertEqual(result, [])

    def test_auto_review_excludes_stale_completion_from_current_collection(self):
        candidate = self._candidate(
            "123",
            save_sync.STATUS_COMPLETED,
        )

        result = save_sync.auto_review_candidates(
            [candidate],
            collection={"123": {"completed": True}},
        )

        self.assertEqual(result, [])
        self.assertTrue(candidate.already_completed)
        self.assertEqual(
            candidate.status,
            save_sync.STATUS_ALREADY_COMPLETED,
        )

    def test_auto_review_keeps_current_completion_and_unmatched_save(self):
        completion = self._candidate(
            "123",
            save_sync.STATUS_COMPLETED,
        )
        unmatched = self._candidate(
            "",
            save_sync.STATUS_UNMATCHED,
        )

        result = save_sync.auto_review_candidates(
            [completion, unmatched],
            collection={"123": {"completed": False}},
        )

        self.assertEqual(result, [completion, unmatched])

    def test_settings_revalidate_pending_review_and_use_automatic_wording(self):
        from pathlib import Path

        source = (
            Path(__file__).parent / "ui" / "pages" / "settings_page.py"
        ).read_text(encoding="utf-8")
        method = source.split(
            "    def _review_auto_scan", 1
        )[1].split("    def _show_save_sync_dialog", 1)[0]

        self.assertIn("save_sync.auto_review_candidates(", method)
        self.assertIn("collection=collection", method)
        self.assertIn(
            'text="Auto-scan: no changes to review"',
            method,
        )
        self.assertIn(
            "Save Data Sync automatic scan skipped ",
            source,
        )
        self.assertNotIn(
            "Save Data Sync startup scan skipped ",
            source,
        )

class ConfidenceReviewUiTest(unittest.TestCase):
    class Candidate:
        def __init__(
            self,
            confidence,
            profile,
            selected_value=None,
            selected_slot=None,
            attempts=None,
        ):
            self.confidence = confidence
            self.profile = profile
            self.status = save_sync.STATUS_COMPLETED
            self.hack_id = "123"
            self.title = "Example Hack"
            self.save_name = "Example Hack.srm"
            self.completed_date = ""
            self.exits_display = "13 / 13"
            self.match_source = "collection"
            self._evidence = {
                "confidence": confidence,
                "profile": profile,
                "selected_value": selected_value,
                "selected_slot": selected_slot,
                "attempts": list(attempts or []),
            }

        def evidence(self):
            return dict(self._evidence)

    class Tree:
        def insert(self, _parent, _index, values, tags=()):
            self.values = values
            self.tags = tags
            return "row"

        def heading(self, *_args, **_kwargs):
            return None

    def test_confidence_labels_and_selected_row_evidence(self):
        from ui import save_sync_dialog

        relocated = self.Candidate(
            "medium",
            "relocated_standard_smw_slots",
            selected_value=13,
            selected_slot="C",
        )
        legacy = self.Candidate(
            "low",
            "legacy_raw_counter",
            selected_value=14,
        )
        expanded = self.Candidate(
            "none",
            "expanded_sram_unknown",
        )

        self.assertEqual(
            save_sync_dialog._confidence_label(relocated),
            "Medium",
        )
        self.assertIn(
            "Relocated standard slot C + backup",
            save_sync_dialog._analysis_detail(relocated),
        )
        self.assertEqual(
            save_sync_dialog._confidence_label(legacy),
            "Low",
        )
        self.assertIn(
            "Unvalidated legacy raw counter",
            save_sync_dialog._analysis_detail(legacy),
        )
        self.assertEqual(
            save_sync_dialog._confidence_label(expanded),
            "None",
        )
        self.assertIn(
            "No confidence · Unknown expanded SRAM layout",
            save_sync_dialog._analysis_detail(expanded),
        )

    def test_standard_summary_identifies_matching_backup(self):
        from ui import save_sync_dialog

        candidate = self.Candidate(
            "medium",
            "standard_smw_slots",
            selected_value=11,
            selected_slot="A",
            attempts=[
                {
                    "accepted": True,
                    "slot": "A",
                    "copy_kind": "primary",
                },
                {
                    "accepted": True,
                    "slot": "A",
                    "copy_kind": "backup",
                },
            ],
        )

        self.assertIn(
            "Standard slot A + backup",
            save_sync_dialog._analysis_detail(candidate),
        )

    def test_low_confidence_completion_requires_manual_selection(self):
        from ui import save_sync_dialog

        results = {}
        for confidence, expected in (("medium", True), ("low", False)):
            candidate = self.Candidate(
                confidence,
                (
                    "standard_smw_slots"
                    if confidence == "medium"
                    else "legacy_raw_counter"
                ),
                selected_value=13,
                selected_slot="A",
            )
            dialog = object.__new__(save_sync_dialog.SaveSyncDialog)
            dialog.matched = [candidate]
            dialog.comp_tree = self.Tree()
            dialog.comp_cand = {}
            dialog.comp_checked = {}
            dialog._update_comp_header = lambda: None

            dialog._populate_completion()
            results[confidence] = dialog.comp_checked["row"]

        self.assertEqual(results, {"medium": True, "low": False})

    def test_review_ui_and_guide_expose_confidence_contract(self):
        from pathlib import Path

        root = Path(__file__).parent
        source = (
            root / "ui" / "save_sync_dialog.py"
        ).read_text(encoding="utf-8")
        guide = (root / "SAVE_DATA_SYNC.md").read_text(encoding="utf-8")

        self.assertGreaterEqual(
            source.count('"confidence": ("Confidence"'),
            2,
        )
        self.assertIn("self.comp_analysis_label", source)
        self.assertIn("self.orph_analysis_label", source)
        self.assertIn("xscrollcommand=hsb.set", source)
        self.assertIn(
            'and _confidence_key(cand) == "medium"',
            source,
        )
        self.assertIn("### Confidence in the review window", guide)
        self.assertIn(
            "Low-confidence completion candidates remain reviewable",
            guide,
        )
        self.assertIn("`relocated_standard_smw_slots`", guide)

if __name__ == "__main__":
    unittest.main(verbosity=2)
