"""Tests for the real GiganticBucket checkpoint adapter rules."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collection_ingestion import (
    EvidenceStrength,
    IdentityEvidenceKind,
    IngestionSource,
)
from giganticbucket_ingestion import (
    GiganticBucketImportError,
    load_giganticbucket_export,
    parse_giganticbucket_export,
    resolve_giganticbucket_hack_against_catalogue,
)
from rom_title_matching import CatalogueMatcher


def _playthrough(time="1:57:20", completed="Mar 3, 2019"):
    return {
        "category": "100%",
        "playKind": "First Play",
        "icon": "Playthrough",
        "time": time,
        "version": None,
        "date_Completed": completed,
        "notes": None,
        "countsAsHack": False,
        "exitCount": None,
        "durationMilliseconds": None,
        "durationPrecision": None,
    }


def _export(*records):
    return {"serializationVersion": 1, "playedHacks": list(records)}


def _record(hack_id, title, link_id, source, creator="ExampleAuthor"):
    return {
        "hackId": hack_id,
        "title": title,
        "link_Id": link_id,
        "source": source,
        "playthroughs": [_playthrough()],
        "creators": [{"username": creator, "smwcCreatorId": None}],
    }


class GiganticBucketIngestionTest(unittest.TestCase):
    def test_smwchack_link_id_becomes_strong_submission_evidence(self):
        imported = parse_giganticbucket_export(
            _export(_record(556, "Quickie World 2", 19279, "SMWCHack"))
        )
        item = imported.hacks[0]
        evidence = {
            value.kind: value
            for value in item.candidate.identity_evidence
        }

        self.assertEqual(19279, item.smwc_submission_id)
        self.assertEqual(
            "19279",
            evidence[IdentityEvidenceKind.SMWC_SUBMISSION_ID].value,
        )
        self.assertEqual(
            EvidenceStrength.STRONG,
            evidence[IdentityEvidenceKind.SMWC_SUBMISSION_ID].strength,
        )
        self.assertEqual(IngestionSource.GIGANTIC_BUCKET, item.candidate.source)

    def test_external_and_smwcfilebin_link_ids_are_not_smwc_hack_identity(self):
        imported = parse_giganticbucket_export(
            _export(
                _record(2569, "External Example", 2569, "External"),
                _record(2589, "File Bin Example", 32572, "SMWCFileBin"),
            )
        )

        for item in imported.hacks:
            with self.subTest(source=item.source_kind):
                self.assertIsNone(item.smwc_submission_id)
                kinds = {evidence.kind for evidence in item.candidate.identity_evidence}
                self.assertNotIn(IdentityEvidenceKind.SMWC_SUBMISSION_ID, kinds)
                self.assertTrue(item.candidate.allow_local_only)

    def test_playthrough_time_and_completion_date_are_normalized_as_evidence(self):
        record = _record(1, "Long Hack", None, "External")
        record["playthroughs"] = [_playthrough("77:33:54", "Feb 8, 2026")]

        history = parse_giganticbucket_export(_export(record)).hacks[0].candidate.user_history[0]

        self.assertEqual(77 * 3600 + 33 * 60 + 54, history.elapsed_seconds)
        self.assertEqual("2026-02-08", history.completed_date_iso)
        self.assertEqual("77:33:54", history.elapsed_text)

    def test_user_export_cannot_supply_rom_or_save_paths_through_adapter(self):
        record = _record(1, "Example", None, "External")
        record["file_path"] = "C:/Injected/rom.sfc"
        record["save_path"] = "C:/Injected/save.srm"

        candidate = parse_giganticbucket_export(_export(record)).hacks[0].candidate

        self.assertEqual((), candidate.rom_files)
        self.assertFalse(hasattr(candidate.user_history[0], "file_path"))
        self.assertFalse(hasattr(candidate.user_history[0], "save_path"))

    def test_direct_smwc_id_is_cross_checked_against_catalogue_title(self):
        matcher = CatalogueMatcher(
            [{"id": 19279, "name": "Quickie World 2", "difficulty": "Intermediate"}]
        )
        good = parse_giganticbucket_export(
            _export(_record(1, "Quickie World 2", 19279, "SMWCHack"))
        ).hacks[0]
        bad = parse_giganticbucket_export(
            _export(_record(2, "Completely Different", 19279, "SMWCHack"))
        ).hacks[0]

        good_result = resolve_giganticbucket_hack_against_catalogue(good, matcher)
        bad_result = resolve_giganticbucket_hack_against_catalogue(bad, matcher)

        self.assertTrue(good_result.auto_selected)
        self.assertEqual(19279, good_result.selected.smwc_submission_id)
        self.assertFalse(bad_result.auto_selected)
        self.assertEqual("SMWC ID/title conflict - review", bad_result.classification)

    def test_non_smwchack_records_use_conservative_title_matching(self):
        matcher = CatalogueMatcher([{"id": 100, "name": "Unlisted Friend Hack"}])
        item = parse_giganticbucket_export(
            _export(_record(1, "Unlisted Friend Hack", 999, "External"))
        ).hacks[0]

        result = resolve_giganticbucket_hack_against_catalogue(item, matcher)

        self.assertTrue(result.auto_selected)
        self.assertEqual(100, result.selected.smwc_submission_id)

    def test_missing_direct_id_in_current_index_requires_review_not_reidentity(self):
        matcher = CatalogueMatcher([{"id": 999, "name": "Same Title"}])
        item = parse_giganticbucket_export(
            _export(_record(1, "Same Title", 12345, "SMWCHack"))
        ).hacks[0]

        result = resolve_giganticbucket_hack_against_catalogue(item, matcher)

        self.assertFalse(result.auto_selected)
        self.assertEqual("SMWC ID not in current catalogue - review", result.classification)
        self.assertIsNone(result.selected)

    def test_local_loader_accepts_utf8_bom_and_rejects_duplicate_json_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            good = root / "checkpoint.json"
            good.write_bytes(("\ufeff" + json.dumps(_export())).encode("utf-8"))

            parsed = load_giganticbucket_export(good)
            self.assertEqual((), parsed.hacks)

            bad = root / "duplicate.json"
            bad.write_text(
                '{"serializationVersion":1,"serializationVersion":1,"playedHacks":[]}',
                encoding="utf-8",
            )
            with self.assertRaises(GiganticBucketImportError):
                load_giganticbucket_export(bad)

    def test_unsupported_serialization_version_fails_closed(self):
        with self.assertRaises(GiganticBucketImportError):
            parse_giganticbucket_export(
                {"serializationVersion": 2, "playedHacks": []}
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
