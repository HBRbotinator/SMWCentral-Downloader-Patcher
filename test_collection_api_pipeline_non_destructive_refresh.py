"""Regression coverage for non-destructive legacy bulk Collection refresh."""
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

    class _PatchHandler:
        @staticmethod
        def apply_patch(*_args, **_kwargs):
            raise AssertionError("Patch handler should not run during metadata-only refresh")

    patch_handler_stub.PatchHandler = _PatchHandler
    sys.modules["patch_handler"] = patch_handler_stub

import api_pipeline


class _Config:
    def get(self, key, default=None):
        if key == "include_smwc_id_in_filename":
            return False
        return default


def _api_hack(*, difficulty="diff_4", download_url="https://example.invalid/alpha.zip"):
    row = {
        "id": 101,
        "name": "Alpha World",
        "authors": [{"id": 1, "name": "Author"}],
        "rating": 4.25,
        "raw_fields": {
            "difficulty": difficulty,
            "length": 12,
            "hof": False,
            "sa1": False,
            "collab": False,
            "demo": False,
            "obsolete": False,
        },
    }
    if download_url is not None:
        row["download_url"] = download_url
    return row


class LegacyBulkRefreshNonDestructiveTest(unittest.TestCase):
    def test_difficulty_refresh_updates_metadata_without_moving_existing_rom(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rom_path = root / "custom-layout" / "Alpha World.smc"
            rom_path.parent.mkdir(parents=True)
            rom_path.write_bytes(b"rom")
            processed = {
                "101": {
                    "title": "Alpha World",
                    "difficulty_id": "diff_3",
                    "current_difficulty": "Intermediate",
                    "folder_name": api_pipeline.get_sorted_folder_name("Intermediate"),
                    "hack_type": "standard",
                    "file_path": str(rom_path),
                    "files": [
                        {
                            "path": str(rom_path),
                            "name": rom_path.name,
                            "primary": True,
                            "sha256": "a" * 64,
                            "size_bytes": 3,
                            "smwc_submission_id": 101,
                            "ingestion_sources": ["tool_patch"],
                        }
                    ],
                    "notes": "preserve me",
                }
            }
            saved = []
            logs = []

            def log(message, level=None, **_kwargs):
                logs.append((message, level))

            with (
                patch("api_pipeline.load_processed", return_value=processed),
                patch(
                    "api_pipeline.fetch_hack_list",
                    return_value={"data": [_api_hack()], "last_page": 1, "current_page": 1},
                ),
                patch("api_pipeline.save_processed", side_effect=lambda data: saved.append(copy.deepcopy(data))),
                patch("config_manager.ConfigManager", return_value=_Config()),
                patch("api_pipeline.os.rename") as rename,
                patch("api_pipeline.requests.get") as request_get,
                patch("api_pipeline.PatchHandler.apply_patch") as apply_patch,
            ):
                api_pipeline.run_pipeline(
                    {"type": ["standard"], "difficulties": [], "waiting": False},
                    str(root / "base.smc"),
                    str(root / "output"),
                    log=log,
                )

            rename.assert_not_called()
            request_get.assert_not_called()
            apply_patch.assert_not_called()
            self.assertTrue(rom_path.exists())
            self.assertEqual(str(rom_path), processed["101"]["file_path"])
            self.assertEqual(str(rom_path), processed["101"]["files"][0]["path"])
            self.assertEqual("Advanced", processed["101"]["current_difficulty"])
            self.assertEqual("diff_4", processed["101"]["difficulty_id"])
            self.assertEqual(
                api_pipeline.get_sorted_folder_name("Advanced"),
                processed["101"]["folder_name"],
            )
            self.assertEqual("preserve me", processed["101"]["notes"])
            self.assertTrue(saved)
            self.assertTrue(
                any("left in place for explicit Collection organization" in message for message, _ in logs)
            )

    def test_missing_recorded_rom_never_relocates_an_inferred_old_layout_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output_dir = root / "output"
            old_folder = api_pipeline.make_output_path(
                str(output_dir),
                "standard",
                api_pipeline.get_sorted_folder_name("Intermediate"),
            )
            inferred_old_path = Path(old_folder) / "Alpha World.smc"
            inferred_old_path.parent.mkdir(parents=True, exist_ok=True)
            inferred_old_path.write_bytes(b"untracked-old-layout-rom")
            expected_new_path = Path(
                api_pipeline.make_output_path(
                    str(output_dir),
                    "standard",
                    api_pipeline.get_sorted_folder_name("Advanced"),
                )
            ) / "Alpha World.smc"

            processed = {
                "101": {
                    "title": "Alpha World",
                    "difficulty_id": "diff_3",
                    "current_difficulty": "Intermediate",
                    "hack_type": "standard",
                    "file_path": str(root / "missing-recorded.smc"),
                }
            }
            logs = []

            def log(message, level=None, **_kwargs):
                logs.append((message, level))

            with (
                patch("api_pipeline.load_processed", return_value=processed),
                patch(
                    "api_pipeline.fetch_hack_list",
                    return_value={
                        "data": [_api_hack(download_url=None)],
                        "last_page": 1,
                        "current_page": 1,
                    },
                ),
                patch("api_pipeline.save_processed"),
                patch("config_manager.ConfigManager", return_value=_Config()),
                patch("api_pipeline.os.rename") as rename,
                patch("api_pipeline.requests.get") as request_get,
            ):
                api_pipeline.run_pipeline(
                    {"type": ["standard"], "difficulties": [], "waiting": False},
                    str(root / "base.smc"),
                    str(output_dir),
                    log=log,
                )

            rename.assert_not_called()
            request_get.assert_not_called()
            self.assertTrue(inferred_old_path.exists())
            self.assertFalse(expected_new_path.exists())
            self.assertEqual(str(root / "missing-recorded.smc"), processed["101"]["file_path"])
            self.assertTrue(any("Source Not Found: Redownloading Alpha World" in message for message, _ in logs))


if __name__ == "__main__":
    unittest.main()
