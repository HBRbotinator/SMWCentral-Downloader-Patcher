"""Shared safe download/patch/publish helpers for reviewed SMWC ROM acquisition."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse
import zipfile

import requests

from collection_change_plan import CatalogueMetadataSnapshot, PlannedRomAsset
from collection_ingestion import IngestionSource
from rom_filename_policy import build_patched_rom_filename
from utils import DIFFICULTY_SORTED, TYPE_DISPLAY_LOOKUP


MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2048
MAX_PATCHED_ROM_BYTES = 32 * 1024 * 1024
_DOWNLOAD_CHUNK_BYTES = 256 * 1024
_ALLOWED_ROM_EXTENSIONS = frozenset({".sfc", ".smc"})


class SmwcPatchAcquisitionError(RuntimeError):
    """Raised when reviewed SMWC patch acquisition cannot publish safely."""


@dataclass(frozen=True)
class AcquiredSmwcRomSet:
    assets: tuple[PlannedRomAsset, ...]
    created_paths: tuple[str, ...]
    primary_path: str


def acquire_smwc_rom_assets(
    *,
    submission_id: int,
    metadata: CatalogueMetadataSnapshot,
    download_url: str,
    base_rom_path: str | Path,
    output_dir: str | Path,
    include_smwc_id_in_filename: bool = False,
    multi_patch_callback: Callable | None = None,
    request_get: Callable = requests.get,
    extract_patches: Callable | None = None,
    patch_apply: Callable | None = None,
    before_publish: Callable[[], None] | None = None,
    after_publish: Callable[[], None] | None = None,
    unique_if_occupied: bool = False,
    source_candidate_prefix: str = "smwc-acquisition",
    log=None,
) -> AcquiredSmwcRomSet:
    """Download, patch, hash, and publish reviewed ROM assets without overwriting files."""

    if isinstance(submission_id, bool) or not isinstance(submission_id, int) or submission_id <= 0:
        raise SmwcPatchAcquisitionError("SMWC acquisition requires a positive submission ID.")
    if metadata.submission_id != submission_id:
        raise SmwcPatchAcquisitionError("Acquisition metadata does not match the SMWC submission ID.")

    base_rom = Path(base_rom_path).expanduser().resolve()
    output_root = Path(output_dir).expanduser().resolve()
    if not base_rom.is_file():
        raise SmwcPatchAcquisitionError("Configured base ROM does not exist.")
    extension = base_rom.suffix.lower()
    if extension not in _ALLOWED_ROM_EXTENSIONS:
        raise SmwcPatchAcquisitionError("Configured base ROM must use a .sfc or .smc extension.")
    if not output_root.is_dir():
        raise SmwcPatchAcquisitionError("Configured ROM output directory does not exist.")
    _validate_download_url(download_url)

    if extract_patches is None:
        from api_pipeline import extract_patches_from_zip

        extract_patches = extract_patches_from_zip
    if patch_apply is None:
        from patch_handler import PatchHandler

        patch_apply = PatchHandler.apply_patch

    hack_types = metadata.hack_types or ("standard",)
    difficulty = metadata.difficulty or "No Difficulty"
    normalized_type = str(hack_types[0]).lower().replace("-", "_")
    display_type = TYPE_DISPLAY_LOOKUP.get(normalized_type, "Unknown")
    difficulty_folder = DIFFICULTY_SORTED.get(difficulty, "08 - No Difficulty")
    target_directory = (output_root / display_type / difficulty_folder).resolve()
    try:
        target_directory.relative_to(output_root)
    except ValueError as error:
        raise SmwcPatchAcquisitionError(
            "ROM output resolved outside the configured ROM directory."
        ) from error

    created_paths: list[Path] = []
    selections: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="smwc-reviewed-acquisition-") as temp_name:
        temp_dir = Path(temp_name)
        archive_path = temp_dir / "target.zip"
        _download_archive(download_url, archive_path, request_get=request_get, log=log)
        _validate_patch_archive(archive_path)
        patch_files = extract_patches(
            str(archive_path), str(temp_dir), metadata.title, return_all=True
        )
        if not patch_files:
            raise SmwcPatchAcquisitionError(
                "The selected SMWC download archive does not contain a supported .bps or .ips patch."
            )
        raw_selections = _select_patches(
            patch_files, metadata.title, str(temp_dir), multi_patch_callback
        )
        if raw_selections is None:
            raise SmwcPatchAcquisitionError("ROM patch selection was cancelled.")
        if not raw_selections:
            raise SmwcPatchAcquisitionError("No ROM patch was selected.")
        selections = list(raw_selections)

        staged: list[tuple[Path, Path, bool]] = []
        reserved: set[Path] = set()
        for index, selection in enumerate(selections):
            output_name = selection["output_name"]
            final_name = build_patched_rom_filename(
                output_name,
                extension,
                smwc_id=submission_id,
                include_smwc_id=bool(include_smwc_id_in_filename),
            )
            preferred = (target_directory / final_name).resolve()
            final_path = _available_output_path(
                preferred,
                reserved=reserved,
                unique_if_occupied=unique_if_occupied,
            )
            reserved.add(final_path)

            stage_path = temp_dir / f"patched-{index:03d}{extension}"
            _log(log, f"Patching reviewed SMWC ROM: {output_name}", "Information")
            if not patch_apply(selection["patch_path"], str(base_rom), str(stage_path), log):
                raise SmwcPatchAcquisitionError(f"Patch application failed for {output_name!r}.")
            if not stage_path.is_file() or stage_path.stat().st_size <= 0:
                raise SmwcPatchAcquisitionError(
                    f"Patched ROM output is empty or missing for {output_name!r}."
                )
            if stage_path.stat().st_size > MAX_PATCHED_ROM_BYTES:
                raise SmwcPatchAcquisitionError(
                    f"Patched ROM output exceeds the allowed size for {output_name!r}."
                )
            staged.append((stage_path, final_path, bool(selection["primary"])))

        if not any(primary for _, _, primary in staged):
            stage_path, final_path, _ = staged[0]
            staged[0] = (stage_path, final_path, True)
            selections[0]["primary"] = True

        if before_publish is not None:
            before_publish()
        try:
            for stage_path, final_path, _primary in staged:
                final_path.parent.mkdir(parents=True, exist_ok=True)
                _copy_exclusive(stage_path, final_path)
                created_paths.append(final_path)
            if after_publish is not None:
                after_publish()
        except Exception:
            _remove_created_files(created_paths)
            raise

    assets: list[PlannedRomAsset] = []
    primary_path = ""
    for index, final_path in enumerate(created_paths):
        sha256, size_bytes = hash_file_stable(final_path)
        primary = bool(selections[index]["primary"])
        if primary:
            primary_path = str(final_path)
        assets.append(
            PlannedRomAsset(
                path=str(final_path),
                filename=final_path.name,
                sha256=sha256,
                size_bytes=size_bytes,
                sources=(IngestionSource.TOOL_PATCH,),
                source_candidate_ids=(
                    f"{source_candidate_prefix}:{submission_id}:{index}",
                ),
                smwc_submission_id=submission_id,
            )
        )
    if not primary_path and created_paths:
        primary_path = str(created_paths[0])
    return AcquiredSmwcRomSet(
        assets=tuple(assets),
        created_paths=tuple(str(path) for path in created_paths),
        primary_path=primary_path,
    )


def hash_file_stable(path: str | Path) -> tuple[str, int]:
    source = Path(path)
    before = _stable_stat(source)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise SmwcPatchAcquisitionError(f"Unable to hash ROM: {source}") from error
    after = _stable_stat(source)
    if before != after:
        raise SmwcPatchAcquisitionError(f"ROM changed while hashing: {source}")
    return digest.hexdigest(), before[0]


def _available_output_path(
    preferred: Path,
    *,
    reserved: set[Path],
    unique_if_occupied: bool,
) -> Path:
    if preferred not in reserved and not preferred.exists():
        return preferred
    if not unique_if_occupied:
        raise SmwcPatchAcquisitionError(
            f"Target ROM output already exists and will not be overwritten: {preferred}"
        )
    for number in range(2, 10000):
        candidate = preferred.with_name(f"{preferred.stem} ({number}){preferred.suffix}")
        if candidate not in reserved and not candidate.exists():
            return candidate
    raise SmwcPatchAcquisitionError(
        f"Could not allocate a non-overwriting ROM filename beside: {preferred}"
    )


def _select_patches(patch_files, title, temp_dir, multi_patch_callback):
    if len(patch_files) == 1:
        return [{"patch_path": patch_files[0], "output_name": title, "primary": True}]
    if multi_patch_callback is None:
        raise SmwcPatchAcquisitionError(
            "The selected archive contains multiple patches and requires explicit patch selection."
        )
    result = multi_patch_callback(patch_files, title, temp_dir)
    if result is None:
        return None
    normalized = []
    for raw in result:
        if not isinstance(raw, Mapping):
            raise SmwcPatchAcquisitionError("Patch selection returned invalid data.")
        patch_path = str(raw.get("patch_path") or "")
        output_name = str(raw.get("output_name") or "").strip()
        if patch_path not in patch_files or not output_name:
            raise SmwcPatchAcquisitionError("Patch selection returned invalid data.")
        normalized.append(
            {
                "patch_path": patch_path,
                "output_name": output_name,
                "primary": bool(raw.get("primary")),
            }
        )
    if normalized and sum(1 for item in normalized if item["primary"]) != 1:
        normalized[-1]["primary"] = True
        for item in normalized[:-1]:
            item["primary"] = False
    return normalized


def _download_archive(url: str, destination: Path, *, request_get, log=None) -> None:
    _log(log, "Downloading reviewed SMWCentral patch archive...", "Information")
    response = request_get(url, timeout=30, stream=True)
    try:
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        effective_url = str(getattr(response, "url", url) or url)
        _validate_download_url(effective_url)
        content_length = _content_length(response)
        if content_length is not None and content_length > MAX_ARCHIVE_BYTES:
            raise SmwcPatchAcquisitionError("Patch archive exceeds the allowed download size.")
        total = 0
        with destination.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_ARCHIVE_BYTES:
                    raise SmwcPatchAcquisitionError(
                        "Patch archive exceeds the allowed download size."
                    )
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if total <= 0:
            raise SmwcPatchAcquisitionError("Patch archive download was empty.")
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()


def _validate_patch_archive(path: Path) -> None:
    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_ARCHIVE_MEMBERS:
                raise SmwcPatchAcquisitionError("Patch archive contains too many files.")
            total = 0
            for member in members:
                if member.file_size < 0:
                    raise SmwcPatchAcquisitionError("Patch archive contains an invalid member size.")
                total += member.file_size
                if total > MAX_EXTRACTED_BYTES:
                    raise SmwcPatchAcquisitionError(
                        "Patch archive expands beyond the allowed size."
                    )
    except zipfile.BadZipFile as error:
        raise SmwcPatchAcquisitionError("Patch download is not a valid ZIP archive.") from error


def _validate_download_url(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or parsed.hostname != "dl.smwcentral.net":
        raise SmwcPatchAcquisitionError(
            "ROM acquisition requires the validated SMWCentral download URL from KaizOFF."
        )


def _copy_exclusive(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
    except FileExistsError as error:
        raise SmwcPatchAcquisitionError(
            f"Target ROM output appeared during acquisition and was not overwritten: {destination}"
        ) from error


def _remove_created_files(paths: Sequence[Path]) -> None:
    for path in reversed(tuple(paths)):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def _stable_stat(path: Path) -> tuple[int, int, int | None, int | None]:
    try:
        stat = path.stat()
    except OSError as error:
        raise SmwcPatchAcquisitionError(f"ROM is unavailable: {path}") from error
    if not path.is_file():
        raise SmwcPatchAcquisitionError(f"ROM is not a regular file: {path}")
    return (
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        getattr(stat, "st_dev", None),
        getattr(stat, "st_ino", None),
    )


def _content_length(response) -> int | None:
    headers = getattr(response, "headers", {}) or {}
    value = headers.get("Content-Length") if hasattr(headers, "get") else None
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


def _log(log, message: str, level: str) -> None:
    if log is None:
        return
    try:
        log(message, level)
    except TypeError:
        log(message)


__all__ = [
    "AcquiredSmwcRomSet",
    "MAX_ARCHIVE_BYTES",
    "MAX_ARCHIVE_MEMBERS",
    "MAX_EXTRACTED_BYTES",
    "MAX_PATCHED_ROM_BYTES",
    "SmwcPatchAcquisitionError",
    "acquire_smwc_rom_assets",
    "hash_file_stable",
]
