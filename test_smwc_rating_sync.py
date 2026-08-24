"""Regression coverage for SMWC rating persistence and backfill."""

from __future__ import annotations

import copy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


try:
    import patch_handler  # noqa: F401
except ModuleNotFoundError as error:
    if error.name not in {"ips_util", "bps", "bps_util"}:
        raise
    sys.modules.pop("patch_handler", None)
    patch_handler_stub = types.ModuleType("patch_handler")

    class _UnusedPatchHandler:
        @staticmethod
        def apply_patch(*_args, **_kwargs):
            raise AssertionError("Patch application was not expected")

    patch_handler_stub.PatchHandler = _UnusedPatchHandler
    sys.modules["patch_handler"] = patch_handler_stub

import api_pipeline


class SmwcRatingNormalizationTest(unittest.TestCase):
    def test_numeric_and_string_ratings_are_normalized(self):
        self.assertEqual(
            api_pipeline.extract_smwc_rating({"rating": 4.25}),
            4.25,
        )
        self.assertEqual(
            api_pipeline.extract_smwc_rating({"rating": "4.5"}),
            4.5,
        )
        self.assertEqual(
            api_pipeline.extract_smwc_rating({"rating": 0}),
            0.0,
        )

    def test_missing_invalid_and_out_of_range_values_are_unknown(self):
        for record in (
            {},
            {"rating": None},
            {"rating": "N/A"},
            {"rating": "bad"},
            {"rating": -1},
            {"rating": 5.1},
        ):
            with self.subTest(record=record):
                self.assertIsNone(api_pipeline.extract_smwc_rating(record))

    def test_personal_rating_is_never_used_as_smwc_rating(self):
        self.assertIsNone(
            api_pipeline.extract_smwc_rating({"personal_rating": 5})
        )
        self.assertEqual(api_pipeline.normalize_smwc_rating("N/A"), 0)


class BulkPipelineSmwcRatingTest(unittest.TestCase):
    def test_existing_collection_entry_refreshes_rating_when_download_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            rom_path = Path(directory) / "alpha.smc"
            rom_path.write_bytes(b"rom")
            processed = {
                "101": {
                    "title": "Alpha World",
                    "current_difficulty": "No Difficulty",
                    "file_path": str(rom_path),
                    "authors": [],
                    "rating": 3.5,
                }
            }
            api_hack = {
                "id": 101,
                "name": "Alpha World",
                "authors": [],
                "rating": "4.25",
                "raw_fields": {
                    "difficulty": "",
                    "length": 10,
                },
            }
            saved = []

            with (
                patch("api_pipeline.load_processed", return_value=processed),
                patch(
                    "api_pipeline.fetch_hack_list",
                    return_value={
                        "data": [api_hack],
                        "last_page": 1,
                        "current_page": 1,
                    },
                ),
                patch(
                    "api_pipeline.save_processed",
                    side_effect=lambda data: saved.append(copy.deepcopy(data)),
                ),
            ):
                api_pipeline.run_pipeline(
                    {
                        "type": ["standard"],
                        "difficulties": [],
                        "waiting": False,
                    },
                    str(Path(directory) / "base.smc"),
                    directory,
                )

            self.assertEqual(processed["101"]["rating"], 4.25)
            self.assertTrue(saved)
            self.assertEqual(saved[-1]["101"]["rating"], 4.25)

    def test_missing_list_rating_does_not_erase_known_collection_rating(self):
        with tempfile.TemporaryDirectory() as directory:
            rom_path = Path(directory) / "alpha.smc"
            rom_path.write_bytes(b"rom")
            processed = {
                "101": {
                    "title": "Alpha World",
                    "current_difficulty": "No Difficulty",
                    "file_path": str(rom_path),
                    "authors": [],
                    "rating": 4.75,
                }
            }
            api_hack = {
                "id": 101,
                "name": "Alpha World",
                "authors": [],
                "raw_fields": {"difficulty": ""},
            }

            with (
                patch("api_pipeline.load_processed", return_value=processed),
                patch(
                    "api_pipeline.fetch_hack_list",
                    return_value={
                        "data": [api_hack],
                        "last_page": 1,
                        "current_page": 1,
                    },
                ),
                patch("api_pipeline.save_processed"),
            ):
                api_pipeline.run_pipeline(
                    {
                        "type": ["standard"],
                        "difficulties": [],
                        "waiting": False,
                    },
                    str(Path(directory) / "base.smc"),
                    directory,
                )

            self.assertEqual(processed["101"]["rating"], 4.75)


class SmwcRatingBackfillTest(unittest.TestCase):
    def test_rating_only_backfill_updates_complete_date_record(self):
        processed = {
            "101": {
                "title": "Alpha World",
                "time": 1_600_000_000,
                "date": "2020-09-13",
            },
            "usr_aaaaaaaaaaaaaaaa": {
                "title": "Local Save Entry",
                "time": 0,
                "date": "",
            },
        }
        saved = []

        def fetch_list(_config, page, waiting_mode, log=None):
            if waiting_mode:
                return {"data": [], "last_page": 1, "current_page": page}
            return {
                "data": [
                    {
                        "id": 101,
                        "rating": "4.6",
                        "downloads": 900,
                    }
                ],
                "last_page": 1,
                "current_page": page,
            }

        with (
            patch("api_pipeline.load_processed", return_value=processed),
            patch("api_pipeline.fetch_hack_list", side_effect=fetch_list),
            patch("api_pipeline.fetch_file_metadata") as fetch_individual,
            patch(
                "api_pipeline.save_processed",
                side_effect=lambda data: saved.append(copy.deepcopy(data)),
            ),
            patch("api_pipeline.time.sleep"),
        ):
            updated = api_pipeline.backfill_metadata()

        self.assertEqual(updated, 1)
        self.assertEqual(processed["101"]["rating"], 4.6)
        self.assertEqual(processed["101"]["time"], 1_600_000_000)
        self.assertEqual(processed["101"]["date"], "2020-09-13")
        self.assertNotIn("rating", processed["usr_aaaaaaaaaaaaaaaa"])
        fetch_individual.assert_not_called()
        self.assertEqual(saved[-1]["101"]["rating"], 4.6)

    def test_zero_rating_is_known_unrated_and_does_not_refetch(self):
        processed = {
            "101": {
                "title": "Unrated Hack",
                "time": 1_600_000_000,
                "date": "2020-09-13",
                "rating": 0,
            }
        }

        with (
            patch("api_pipeline.load_processed", return_value=processed),
            patch("api_pipeline.fetch_hack_list") as fetch_list,
            patch("api_pipeline.fetch_file_metadata") as fetch_individual,
            patch("api_pipeline.save_processed") as save_processed,
        ):
            updated = api_pipeline.backfill_metadata()

        self.assertEqual(updated, 0)
        fetch_list.assert_not_called()
        fetch_individual.assert_not_called()
        save_processed.assert_not_called()

    def test_individual_fallback_can_complete_rating_without_rewriting_time(self):
        processed = {
            "404": {
                "title": "Obsolete Hack",
                "time": 1_500_000_000,
                "date": "2017-07-14",
                "rating": "N/A",
            }
        }

        def fetch_list(_config, page, waiting_mode, log=None):
            return {"data": [], "last_page": 1, "current_page": page}

        with (
            patch("api_pipeline.load_processed", return_value=processed),
            patch("api_pipeline.fetch_hack_list", side_effect=fetch_list),
            patch(
                "api_pipeline.fetch_file_metadata",
                return_value={"data": {"rating": 3.75}},
            ),
            patch("api_pipeline.save_processed"),
            patch("api_pipeline.time.sleep"),
        ):
            updated = api_pipeline.backfill_metadata()

        self.assertEqual(updated, 1)
        self.assertEqual(processed["404"]["rating"], 3.75)
        self.assertEqual(processed["404"]["time"], 1_500_000_000)
        self.assertEqual(processed["404"]["date"], "2017-07-14")


class SmwcRatingSourceContractTest(unittest.TestCase):
    def test_all_download_paths_persist_smwc_rating(self):
        api_source = Path("api_pipeline.py").read_text(encoding="utf-8")
        main_source = Path("main.py").read_text(encoding="utf-8")

        for required in (
            'page_metadata["rating"] = page_rating',
            'existing_hack.get("rating", 0)',
            '"rating": normalize_smwc_rating(hack_data.get("rating", 0))',
            'rating = normalize_smwc_rating(metadata["rating"])',
        ):
            self.assertIn(required, api_source)

        for required in (
            "smwc_rating = extract_smwc_rating(hack)",
            'existing_hack["rating"] = smwc_rating',
            'smwc_rating = extract_smwc_rating(detailed_hack)',
            'processed.get(hack_id, {}).get("rating", 0)',
        ):
            self.assertIn(required, main_source)

    def test_backfill_excludes_non_smwc_collection_identities(self):
        source = Path("api_pipeline.py").read_text(encoding="utf-8")
        self.assertIn("not _is_smwc_hack_id(hack_id)", source)
        self.assertIn("extract_smwc_rating(data) is None", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
