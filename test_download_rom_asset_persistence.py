"""Regression coverage for download-to-Collection ROM asset persistence."""
from __future__ import annotations

import copy
import os
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

    class _PatchHandler:
        @staticmethod
        def apply_patch(*_args, **_kwargs):
            raise AssertionError("Patch handler should be mocked by the test")

    patch_handler_stub.PatchHandler = _PatchHandler
    sys.modules["patch_handler"] = patch_handler_stub

import api_pipeline


class _Response:
    content = b"fake-archive"


class _Config:
    def get(self, key, default=None):
        if key == "include_smwc_id_in_filename":
            return False
        return default


class DownloadRomAssetPersistenceTest(unittest.TestCase):
    def test_bulk_redownload_records_modern_asset_and_preserves_user_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            processed = {
                "41022": {
                    "title": "Old Display Title",
                    "file_path": str(root / "missing.sfc"),
                    "completed": True,
                    "completed_date": "2026-01-02",
                    "personal_rating": 5,
                    "notes": "keep this",
                    "playthroughs": [{"source": "giganticbucket", "source_record_id": "run-1"}],
                    "future_local_field": {"keep": True},
                }
            }
            hack = {
                "id": 41022,
                "name": "Super Dram World 3",
                "authors": [{"id": 3491, "name": "PangaeaPanga"}],
                "rating": 4.625,
                "download_url": "https://dl.smwcentral.net/41022/example.zip",
                "raw_fields": {
                    "difficulty": "diff_7",
                    "length": 28,
                    "hof": True,
                    "type": ["kaizo"],
                },
            }
            saved = []

            def fake_patch(_patch_path, _base_rom, output_path, _log=None):
                output = Path(output_path)
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(b"newly-patched-rom")
                return True

            with (
                patch("api_pipeline.load_processed", return_value=processed),
                patch(
                    "api_pipeline.fetch_hack_list",
                    return_value={"data": [hack], "last_page": 1, "current_page": 1},
                ),
                patch("api_pipeline.requests.get", return_value=_Response()),
                patch(
                    "api_pipeline.extract_patches_from_zip",
                    return_value=[str(root / "patch.bps")],
                ),
                patch("api_pipeline.PatchHandler.apply_patch", side_effect=fake_patch),
                patch("api_pipeline.save_processed", side_effect=lambda data: saved.append(copy.deepcopy(data))),
                patch("config_manager.ConfigManager", return_value=_Config()),
            ):
                api_pipeline.run_pipeline(
                    {"type": ["kaizo"], "difficulties": [], "waiting": False},
                    str(root / "base.sfc"),
                    str(root / "output"),
                )

            record = processed["41022"]
            self.assertTrue(saved)
            self.assertTrue(record["completed"])
            self.assertEqual("2026-01-02", record["completed_date"])
            self.assertEqual(5, record["personal_rating"])
            self.assertEqual("keep this", record["notes"])
            self.assertEqual("run-1", record["playthroughs"][0]["source_record_id"])
            self.assertEqual({"keep": True}, record["future_local_field"])
            self.assertEqual(1, len(record["files"]))
            asset = record["files"][0]
            self.assertEqual(record["file_path"], asset["path"])
            self.assertTrue(asset["primary"])
            self.assertEqual(41022, asset["smwc_submission_id"])
            self.assertEqual(["tool_patch"], asset["ingestion_sources"])
            self.assertEqual(len(b"newly-patched-rom"), asset["size_bytes"])
            self.assertRegex(asset["sha256"], r"^[0-9a-f]{64}$")
            self.assertTrue(os.path.exists(asset["path"]))

    def test_single_download_pipeline_uses_same_modern_asset_helpers(self):
        source = Path("main.py").read_text(encoding="utf-8")
        self.assertIn("build_tool_patch_rom_asset", source)
        self.assertIn("merge_collection_rom_assets", source)
        self.assertIn('"ingestion_sources": ["tool_patch"]', Path("rom_asset_metadata.py").read_text(encoding="utf-8"))
        self.assertIn("updated_record = dict(existing_record)", source)
        self.assertIn('updated_record["files"] = merge_collection_rom_assets(', source)


if __name__ == "__main__":
    unittest.main()
