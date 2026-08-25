from __future__ import annotations

import io
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import zipfile

from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion import IngestionSource
from collection_plan_apply import CollectionPlanStaleStateError
from collection_update_apply import apply_finalized_collection_update
from collection_update_discovery import CollectionUpdateSelection
from collection_update_plan import finalize_collection_update_replacement_plan
from collection_update_rom_acquisition import (
    CollectionUpdateRomAcquisitionError,
    CollectionUpdateRomAcquisitionStaleStateError,
    acquire_collection_update_target_rom,
    finalized_update_has_acquired_target_rom,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffCatalogueProvider, KaizOffDetailSnapshot, KaizOffHackMetadata
from rom_title_matching import CatalogueEntry


SOURCE_ID = "41022"
TARGET_ID = "43123"
DOWNLOAD_URL = f"https://dl.smwcentral.net/{TARGET_ID}/hack.zip"


def _ips_patch(value=b"X"):
    return b"PATCH" + b"\x00\x00\x00" + len(value).to_bytes(2, "big") + value + b"EOF"


def _archive(*patches):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in patches:
            archive.writestr(name, payload)
    return buffer.getvalue()


def _extract_patches(zip_path, extract_to, hack_name="", return_all=False):
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(extract_to)
    paths = sorted(str(path) for path in Path(extract_to).rglob("*.ips"))
    return paths if return_all else (paths[0] if paths else None)


def _patch_apply(patch_path, source_rom_path, output_path, log=None):
    source = bytearray(Path(source_rom_path).read_bytes())
    patch = Path(patch_path).read_bytes()
    if not patch.startswith(b"PATCH") or len(patch) < 11:
        return False
    size = int.from_bytes(patch[8:10], "big")
    data = patch[10 : 10 + size]
    source[: len(data)] = data
    Path(output_path).write_bytes(bytes(source))
    return True


class _Response:
    def __init__(self, payload, url=DOWNLOAD_URL):
        self.payload = payload
        self.url = url
        self.headers = {"Content-Length": str(len(payload))}
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=1):
        for start in range(0, len(self.payload), chunk_size):
            yield self.payload[start : start + chunk_size]

    def close(self):
        self.closed = True


class _Provider(KaizOffCatalogueProvider):
    def __init__(self):
        pass

    def get_hack(self, smwc_submission_id, *, force_refresh=False):
        return KaizOffDetailSnapshot(
            metadata=KaizOffHackMetadata(
                smwc_submission_id=int(smwc_submission_id),
                title="Super Dram World 3 Updated",
                authors=("PangaeaPanga",),
                tags=("kaizo",),
                image_urls=(),
                rating=4.8,
                size_bytes=1234,
                downloads=10,
                download_url=DOWNLOAD_URL,
                release_timestamp=1800000000,
                difficulty="Grandmaster",
                hack_types=("kaizo",),
                exits=30,
                demo=False,
                hall_of_fame=True,
                sa1_compatible=False,
                collaboration=False,
                description="target",
                active=True,
                last_fetched="2026-08-25T00:00:00Z",
                obsoleted_by_submission_id=None,
            ),
            fetched_at=2.0,
            source="test",
            stale=False,
        )


class CollectionUpdateRomAcquisitionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="update_rom_acquisition_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.processed = self.root / "processed.json"
        self.processed.write_text(
            json.dumps(
                {
                    SOURCE_ID: {
                        "title": "Super Dram World 3",
                        "completed": True,
                        "notes": "preserve me",
                    }
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.base_rom = self.root / "clean.smc"
        self.base_rom.write_bytes(b"\x00" * 32)
        self.output_dir = self.root / "roms"
        self.output_dir.mkdir()
        self.manager = HackDataManager(str(self.processed))
        self.hints = CollectionIdentityHintsStore.beside_processed_json(self.processed)
        selection = CollectionUpdateSelection(
            source_collection_key=SOURCE_ID,
            source_entry=CatalogueEntry(int(SOURCE_ID), "Super Dram World 3"),
            target_entry=CatalogueEntry(int(TARGET_ID), "Super Dram World 3 Updated"),
            target_already_in_collection=False,
            catalogue_fetched_at=1.0,
            catalogue_source="test",
            catalogue_stale=False,
        )
        self.finalized = finalize_collection_update_replacement_plan(
            selection,
            self.manager,
            self.hints,
            _Provider(),
            participants=(),
        )

    def _request_get(self, payload):
        def request_get(url, timeout=30, stream=True):
            self.assertEqual(DOWNLOAD_URL, url)
            self.assertEqual(30, timeout)
            self.assertTrue(stream)
            return _Response(payload)

        return request_get

    def test_acquisition_creates_hashed_target_rom_and_enriches_immutable_plan(self):
        archive = _archive(("dram3.ips", _ips_patch()))
        result = acquire_collection_update_target_rom(
            self.processed,
            self.finalized,
            base_rom_path=self.base_rom,
            output_dir=self.output_dir,
            include_smwc_id_in_filename=True,
            participants=(),
            request_get=self._request_get(archive),
            extract_patches=_extract_patches,
            patch_apply=_patch_apply,
        )

        self.assertTrue(finalized_update_has_acquired_target_rom(result.finalized))
        self.assertEqual(1, len(result.created_paths))
        output = Path(result.primary_path)
        self.assertTrue(output.is_file())
        self.assertEqual("Super Dram World 3 Updated [SMWC-ID-43123].smc", output.name)
        self.assertEqual(b"X", output.read_bytes()[:1])
        operation = result.finalized.plan.rom_updates[-1]
        self.assertEqual(TARGET_ID, operation.target_key)
        self.assertEqual(str(output), operation.primary_path)
        asset = operation.assets[0]
        self.assertEqual((IngestionSource.TOOL_PATCH,), asset.sources)
        self.assertEqual(int(TARGET_ID), asset.smwc_submission_id)
        self.assertEqual(len(output.read_bytes()), asset.size_bytes)
        self.assertEqual(SOURCE_ID, next(iter(json.loads(self.processed.read_text()))))

    def test_acquired_plan_applies_target_rom_as_primary_without_network_work(self):
        archive = _archive(("dram3.ips", _ips_patch(b"Y")))
        result = acquire_collection_update_target_rom(
            self.processed,
            self.finalized,
            base_rom_path=self.base_rom,
            output_dir=self.output_dir,
            participants=(),
            request_get=self._request_get(archive),
            extract_patches=_extract_patches,
            patch_apply=_patch_apply,
        )
        apply_finalized_collection_update(
            self.processed,
            result.finalized,
            manager=self.manager,
            identity_hints=self.hints,
            participants=(),
        )
        data = json.loads(self.processed.read_text(encoding="utf-8"))
        self.assertNotIn(SOURCE_ID, data)
        self.assertIn(TARGET_ID, data)
        self.assertEqual("preserve me", data[TARGET_ID]["notes"])
        self.assertEqual(result.primary_path, data[TARGET_ID]["file_path"])
        self.assertTrue(data[TARGET_ID]["files"][0]["primary"])
        self.assertEqual(int(TARGET_ID), data[TARGET_ID]["files"][0]["smwc_submission_id"])

    def test_existing_output_is_never_overwritten(self):
        archive = _archive(("dram3.ips", _ips_patch()))
        target_dir = self.output_dir / "Kaizo" / "07 - Grandmaster"
        target_dir.mkdir(parents=True)
        existing = target_dir / "Super Dram World 3 Updated.smc"
        existing.write_bytes(b"KEEP")

        with self.assertRaises(CollectionUpdateRomAcquisitionError):
            acquire_collection_update_target_rom(
                self.processed,
                self.finalized,
                base_rom_path=self.base_rom,
                output_dir=self.output_dir,
                participants=(),
                request_get=self._request_get(archive),
                extract_patches=_extract_patches,
                patch_apply=_patch_apply,
            )
        self.assertEqual(b"KEEP", existing.read_bytes())

    def test_multiple_patches_require_explicit_selection(self):
        archive = _archive(
            ("v1.ips", _ips_patch(b"A")),
            ("v2.ips", _ips_patch(b"B")),
        )
        with self.assertRaisesRegex(CollectionUpdateRomAcquisitionError, "explicit patch selection"):
            acquire_collection_update_target_rom(
                self.processed,
                self.finalized,
                base_rom_path=self.base_rom,
                output_dir=self.output_dir,
                participants=(),
                request_get=self._request_get(archive),
                extract_patches=_extract_patches,
                patch_apply=_patch_apply,
            )
        self.assertEqual([], list(self.output_dir.rglob("*.smc")))


    def test_multiple_patches_use_explicit_selection_and_primary_choice(self):
        archive = _archive(
            ("v1.ips", _ips_patch(b"A")),
            ("v2.ips", _ips_patch(b"B")),
        )

        def choose(patch_files, hack_name, temp_dir):
            self.assertEqual("Super Dram World 3 Updated", hack_name)
            return [
                {"patch_path": patch_files[0], "output_name": "Dram 3 v1", "primary": False},
                {"patch_path": patch_files[1], "output_name": "Dram 3 v2", "primary": True},
            ]

        result = acquire_collection_update_target_rom(
            self.processed,
            self.finalized,
            base_rom_path=self.base_rom,
            output_dir=self.output_dir,
            participants=(),
            request_get=self._request_get(archive),
            extract_patches=_extract_patches,
            patch_apply=_patch_apply,
            multi_patch_callback=choose,
        )
        self.assertEqual(2, len(result.created_paths))
        self.assertTrue(result.primary_path.endswith("Dram 3 v2.smc"))
        operation = result.finalized.plan.rom_updates[-1]
        self.assertEqual(result.primary_path, operation.primary_path)
        self.assertEqual(2, len(operation.assets))

    def test_existing_target_merge_plan_does_not_offer_post_review_acquisition(self):
        from dataclasses import replace

        reviewed = replace(self.finalized, merge_decision=object())
        archive = _archive(("dram3.ips", _ips_patch()))
        with self.assertRaisesRegex(CollectionUpdateRomAcquisitionError, "already existed"):
            acquire_collection_update_target_rom(
                self.processed,
                reviewed,
                base_rom_path=self.base_rom,
                output_dir=self.output_dir,
                participants=(),
                request_get=self._request_get(archive),
                extract_patches=_extract_patches,
                patch_apply=_patch_apply,
            )

    def test_store_change_during_download_aborts_before_rom_is_published(self):
        archive = _archive(("dram3.ips", _ips_patch()))

        def request_get(url, timeout=30, stream=True):
            data = json.loads(self.processed.read_text(encoding="utf-8"))
            data[SOURCE_ID]["notes"] = "changed during download"
            self.processed.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            return _Response(archive)

        with self.assertRaises(CollectionUpdateRomAcquisitionStaleStateError):
            acquire_collection_update_target_rom(
                self.processed,
                self.finalized,
                base_rom_path=self.base_rom,
                output_dir=self.output_dir,
                participants=(),
                request_get=request_get,
                extract_patches=_extract_patches,
                patch_apply=_patch_apply,
            )
        self.assertEqual([], list(self.output_dir.rglob("*.smc")))

    def test_archive_expansion_is_bounded_before_extraction(self):
        archive = _archive(("dram3.ips", _ips_patch()))
        with patch(
            "collection_update_rom_acquisition.MAX_REPLACEMENT_EXTRACTED_BYTES",
            1,
        ):
            with self.assertRaisesRegex(
                CollectionUpdateRomAcquisitionError,
                "expands beyond the allowed size",
            ):
                acquire_collection_update_target_rom(
                    self.processed,
                    self.finalized,
                    base_rom_path=self.base_rom,
                    output_dir=self.output_dir,
                    participants=(),
                    request_get=self._request_get(archive),
                    extract_patches=_extract_patches,
                    patch_apply=_patch_apply,
                )
        self.assertEqual([], list(self.output_dir.rglob("*.smc")))

    def test_patched_rom_output_size_is_bounded_before_publish(self):
        archive = _archive(("dram3.ips", _ips_patch()))
        with patch("collection_update_rom_acquisition.MAX_PATCHED_ROM_BYTES", 1):
            with self.assertRaisesRegex(
                CollectionUpdateRomAcquisitionError,
                "Patched ROM output exceeds the allowed size",
            ):
                acquire_collection_update_target_rom(
                    self.processed,
                    self.finalized,
                    base_rom_path=self.base_rom,
                    output_dir=self.output_dir,
                    participants=(),
                    request_get=self._request_get(archive),
                    extract_patches=_extract_patches,
                    patch_apply=_patch_apply,
                )
        self.assertEqual([], list(self.output_dir.rglob("*.smc")))

    def test_output_appearing_after_initial_check_is_not_overwritten(self):
        archive = _archive(("dram3.ips", _ips_patch()))
        target = (
            self.output_dir
            / "Kaizo"
            / "07 - Grandmaster"
            / "Super Dram World 3 Updated.smc"
        )

        def patch_with_race(patch_path, source_rom_path, output_path, log=None):
            result = _patch_apply(patch_path, source_rom_path, output_path, log)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"RACE-WINNER")
            return result

        with self.assertRaisesRegex(
            CollectionUpdateRomAcquisitionError,
            "appeared while acquisition was running",
        ):
            acquire_collection_update_target_rom(
                self.processed,
                self.finalized,
                base_rom_path=self.base_rom,
                output_dir=self.output_dir,
                participants=(),
                request_get=self._request_get(archive),
                extract_patches=_extract_patches,
                patch_apply=patch_with_race,
            )
        self.assertEqual(b"RACE-WINNER", target.read_bytes())

    def test_apply_rejects_acquired_rom_if_bytes_change_after_preview(self):
        archive = _archive(("dram3.ips", _ips_patch()))
        result = acquire_collection_update_target_rom(
            self.processed,
            self.finalized,
            base_rom_path=self.base_rom,
            output_dir=self.output_dir,
            participants=(),
            request_get=self._request_get(archive),
            extract_patches=_extract_patches,
            patch_apply=_patch_apply,
        )
        Path(result.primary_path).write_bytes(b"changed")

        with self.assertRaises(CollectionPlanStaleStateError):
            apply_finalized_collection_update(
                self.processed,
                result.finalized,
                manager=self.manager,
                identity_hints=self.hints,
                participants=(),
            )
        data = json.loads(self.processed.read_text(encoding="utf-8"))
        self.assertIn(SOURCE_ID, data)
        self.assertNotIn(TARGET_ID, data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
