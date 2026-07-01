"""
Unit tests for save_sync.

Primary goal (per feature spec): prove that .sav and .srm files are read
identically -- same raw SMW SRAM bytes must yield the same collected-exit count
regardless of extension. Also covers the read guards, classification rule, and
filename-to-hack matching.

Run:  python -m pytest test_save_sync.py      (or)  python test_save_sync.py
"""

import os
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
        """.srm and .sav agree across the real-world SRAM sizes (2K-128K)."""
        for size in (2048, 4096, 8192, 131072):
            blob = _make_srm_bytes(9, size=size)
            srm = self._write(f"s{size}.srm", blob)
            sav = self._write(f"s{size}.sav", blob)
            self.assertEqual(read_collected_exits(srm), read_collected_exits(sav))
            self.assertEqual(read_collected_exits(srm), 9)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
