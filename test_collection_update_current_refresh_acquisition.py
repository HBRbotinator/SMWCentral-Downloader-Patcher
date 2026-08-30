import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from collection_identity_hints import CollectionIdentityHintsStore
from collection_update_current_refresh import finalize_current_submission_refresh_plan
from collection_update_current_refresh_acquisition import acquire_current_submission_rom
from collection_update_current_refresh_apply import apply_finalized_current_submission_refresh
from collection_plan_apply import CollectionPlanStaleStateError
from collection_update_current_refresh_acquisition import (
    CollectionCurrentRefreshAcquisitionStaleStateError,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffCatalogueProvider, KaizOffDetailSnapshot, KaizOffHackMetadata
from smwc_patch_acquisition import hash_file_stable
from utils import DIFFICULTY_SORTED, TYPE_DISPLAY_LOOKUP


SOURCE_ID = "12345"


def _zip_bytes():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("patch.bps", b"dummy-patch")
    return stream.getvalue()


class _Response:
    def __init__(self, payload):
        self.payload = payload
        self.url = f"https://dl.smwcentral.net/{SOURCE_ID}/hack.zip"
        self.headers = {"Content-Length": str(len(payload))}

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        yield self.payload

    def close(self):
        return None


class _Provider(KaizOffCatalogueProvider):
    def __init__(self):
        pass

    def get_hack(self, smwc_submission_id, *, force_refresh=False):
        return KaizOffDetailSnapshot(
            metadata=KaizOffHackMetadata(
                smwc_submission_id=int(SOURCE_ID),
                title="Quickie World",
                authors=("Author",), tags=(), image_urls=(), rating=4.0,
                size_bytes=100, downloads=1,
                download_url=f"https://dl.smwcentral.net/{SOURCE_ID}/hack.zip",
                release_timestamp=1800000000,
                difficulty="Intermediate",
                hack_types=("kaizo",), exits=12, demo=False,
                hall_of_fame=False, sa1_compatible=False, collaboration=False,
                description="", active=True, last_fetched="now",
                obsoleted_by_submission_id=None,
            ),
            fetched_at=1.0, source="network", stale=False,
        )


class CurrentSubmissionRefreshAcquisitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="current_refresh_acq_")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.processed = self.root / "processed.json"
        self.output = self.root / "roms"
        self.output.mkdir()
        self.base_rom = self.root / "base.sfc"
        self.base_rom.write_bytes(b"base")
        self.old_rom = self.root / "old.sfc"
        self.old_rom.write_bytes(b"old-rom")
        old_sha, old_size = hash_file_stable(self.old_rom)
        self.processed.write_text(json.dumps({SOURCE_ID: {
            "title": "Quickie World", "authors": ["Author"],
            "current_difficulty": "Intermediate", "hack_type": "kaizo",
            "hack_types": ["kaizo"], "exits": 12,
            "file_path": str(self.old_rom),
            "files": [{"path": str(self.old_rom), "name": self.old_rom.name,
                       "sha256": old_sha, "size_bytes": old_size, "primary": True,
                       "smwc_submission_id": int(SOURCE_ID), "keep": "yes"}],
            "notes": "keep me",
        }}, indent=2), encoding="utf-8")
        self.manager = HackDataManager(str(self.processed))
        self.hints = CollectionIdentityHintsStore.beside_processed_json(self.processed)
        self.finalized = finalize_current_submission_refresh_plan(
            self.processed, SOURCE_ID, provider=_Provider(), manager=self.manager,
            identity_hints=self.hints, participants=(),
        )

    def _request_get(self, url, timeout=30, stream=True):
        return _Response(_zip_bytes())

    def _extract(self, archive, temp_dir, title, return_all=True):
        path = Path(temp_dir) / "selected.bps"
        path.write_bytes(b"patch")
        return [str(path)]

    def test_acquisition_never_overwrites_same_filename_and_apply_keeps_same_identity(self):
        display_type = TYPE_DISPLAY_LOOKUP.get("kaizo", "Unknown")
        folder = DIFFICULTY_SORTED["Intermediate"]
        occupied = self.output / display_type / folder / "Quickie World.sfc"
        occupied.parent.mkdir(parents=True)
        occupied.write_bytes(b"do-not-overwrite")

        def patch_apply(patch, base, output, log=None):
            Path(output).write_bytes(b"new-current-rom")
            return True

        result = acquire_current_submission_rom(
            self.processed, self.finalized,
            base_rom_path=self.base_rom, output_dir=self.output,
            participants=(), request_get=self._request_get,
            extract_patches=self._extract, patch_apply=patch_apply,
        )
        self.assertFalse(result.identical_to_existing)
        self.assertEqual(b"do-not-overwrite", occupied.read_bytes())
        self.assertTrue(result.primary_path.endswith("Quickie World (2).sfc"))
        self.assertTrue(Path(result.primary_path).is_file())

        apply_finalized_current_submission_refresh(
            self.processed, result.finalized, manager=self.manager,
            identity_hints=self.hints, participants=(),
        )
        self.assertEqual([SOURCE_ID], list(self.manager.data))
        record = self.manager.data[SOURCE_ID]
        self.assertEqual(result.primary_path, record["file_path"])
        self.assertEqual(2, len(record["files"]))
        self.assertEqual("yes", next(r for r in record["files"] if r["path"] == str(self.old_rom))["keep"])
        new = next(r for r in record["files"] if r["path"] == result.primary_path)
        self.assertEqual(int(SOURCE_ID), new["smwc_submission_id"])
        self.assertTrue(new["primary"])


    def test_acquisition_rejects_collection_change_before_publish(self):
        def patch_apply(patch, base, output, log=None):
            Path(output).write_bytes(b"new-current-rom")
            payload = json.loads(self.processed.read_text(encoding="utf-8"))
            payload[SOURCE_ID]["notes"] = "changed on disk"
            self.processed.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            return True

        with self.assertRaises(CollectionCurrentRefreshAcquisitionStaleStateError):
            acquire_current_submission_rom(
                self.processed, self.finalized,
                base_rom_path=self.base_rom, output_dir=self.output,
                participants=(), request_get=self._request_get,
                extract_patches=self._extract, patch_apply=patch_apply,
            )
        self.assertEqual([], list(self.output.rglob("*.sfc")))

    def test_apply_rejects_acquired_rom_if_bytes_change_after_preview(self):
        def patch_apply(patch, base, output, log=None):
            Path(output).write_bytes(b"new-current-rom")
            return True

        result = acquire_current_submission_rom(
            self.processed, self.finalized,
            base_rom_path=self.base_rom, output_dir=self.output,
            participants=(), request_get=self._request_get,
            extract_patches=self._extract, patch_apply=patch_apply,
        )
        Path(result.primary_path).write_bytes(b"tampered-rom")
        with self.assertRaises(CollectionPlanStaleStateError):
            apply_finalized_current_submission_refresh(
                self.processed, result.finalized, manager=self.manager,
                identity_hints=self.hints, participants=(),
            )

    def test_identical_current_download_discards_duplicate_and_keeps_metadata_only_plan(self):
        existing_bytes = self.old_rom.read_bytes()

        def patch_apply(patch, base, output, log=None):
            Path(output).write_bytes(existing_bytes)
            return True

        result = acquire_current_submission_rom(
            self.processed, self.finalized,
            base_rom_path=self.base_rom, output_dir=self.output,
            participants=(), request_get=self._request_get,
            extract_patches=self._extract, patch_apply=patch_apply,
        )
        self.assertTrue(result.identical_to_existing)
        self.assertEqual((), result.created_paths)
        self.assertEqual((), result.finalized.plan.rom_updates)
        self.assertTrue(result.finalized.rom_acquisition_checked)
        self.assertTrue(result.finalized.rom_matches_existing)
        created = list(self.output.rglob("*.sfc"))
        self.assertEqual([], created)


if __name__ == "__main__":
    unittest.main()
