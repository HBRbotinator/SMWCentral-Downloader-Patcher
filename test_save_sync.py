"""
Unit tests for save_sync.

Primary goal (per feature spec): prove that .sav and .srm files are read
identically -- same raw SMW SRAM bytes must yield the same collected-exit count
regardless of extension. Also covers the read guards, classification rule, and
filename-to-hack matching.

Run:  python -m pytest test_save_sync.py      (or)  python test_save_sync.py
"""

import os
import shutil
import sys
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
