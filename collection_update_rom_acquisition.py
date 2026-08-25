"""Acquire and validate a ROM for an explicitly reviewed Collection replacement.

This boundary may create new ROM files, but it does not mutate Collection/user metadata.
The returned FinalizedCollectionUpdatePlan remains immutable and must still cross the normal
transactional Apply boundary before Collection identity changes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
import shutil
import tempfile
from typing import Callable, Mapping, Sequence
from urllib.parse import urlparse

import requests
import zipfile

from collection_change_plan import PlannedRomAsset, RomAssetsOperation, StorePrecondition
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion import IngestionSource
from collection_plan_apply import (
    CollectionIdentityReferenceParticipant,
    collect_store_preconditions,
)
from collection_update_plan import FinalizedCollectionUpdatePlan
from hack_data_manager import HackDataManager
from rom_filename_policy import build_patched_rom_filename
from utils import DIFFICULTY_SORTED, TYPE_DISPLAY_LOOKUP


MAX_REPLACEMENT_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_REPLACEMENT_EXTRACTED_BYTES = 256 * 1024 * 1024
MAX_REPLACEMENT_ARCHIVE_MEMBERS = 2048
MAX_PATCHED_ROM_BYTES = 32 * 1024 * 1024
_DOWNLOAD_CHUNK_BYTES = 256 * 1024
_ALLOWED_ROM_EXTENSIONS = frozenset({".sfc", ".smc"})


class CollectionUpdateRomAcquisitionError(RuntimeError):
    """Raised when a target ROM cannot be acquired without crossing a safety boundary."""


class CollectionUpdateRomAcquisitionStaleStateError(CollectionUpdateRomAcquisitionError):
    """Raised when reviewed user-owned state changes while a target ROM is acquired."""


@dataclass(frozen=True)
class CollectionUpdateRomAcquisitionResult:
    """New immutable plan plus the newly created target-ROM paths."""

    finalized: FinalizedCollectionUpdatePlan
    created_paths: tuple[str, ...]
    primary_path: str


def acquire_collection_update_target_rom(
    processed_json_path: str | Path,
    finalized: FinalizedCollectionUpdatePlan,
    *,
    base_rom_path: str | Path,
    output_dir: str | Path,
    include_smwc_id_in_filename: bool = False,
    multi_patch_callback: Callable | None = None,
    participants: Sequence[CollectionIdentityReferenceParticipant] | None = None,
    request_get: Callable = requests.get,
    extract_patches: Callable | None = None,
    patch_apply: Callable | None = None,
    log=None,
) -> CollectionUpdateRomAcquisitionResult:
    """Download, patch, hash, and attach a target ROM to an already reviewed plan.

    The newly patched files are created before Collection Apply. Existing files are never
    overwritten. If acquisition fails before a plan is returned, files created by this call
    are removed best-effort.
    """

    if not isinstance(finalized, FinalizedCollectionUpdatePlan):
        raise TypeError("finalized must be FinalizedCollectionUpdatePlan")
    if finalized.merge_decision is not None:
        raise CollectionUpdateRomAcquisitionError(
            "The selected target already existed in Collection. Its existing ROM state was "
            "reviewed separately, so replacement-ROM acquisition is not added after that merge review."
        )

    processed = Path(processed_json_path).expanduser().resolve()
    base_rom = Path(base_rom_path).expanduser().resolve()
    output_root = Path(output_dir).expanduser().resolve()
    if not base_rom.is_file():
        raise CollectionUpdateRomAcquisitionError("Configured base ROM does not exist.")
    extension = base_rom.suffix.lower()
    if extension not in _ALLOWED_ROM_EXTENSIONS:
        raise CollectionUpdateRomAcquisitionError(
            "Configured base ROM must use a .sfc or .smc extension."
        )
    if not output_root.exists() or not output_root.is_dir():
        raise CollectionUpdateRomAcquisitionError("Configured ROM output directory does not exist.")

    target_key = str(finalized.selection.target_entry.smwc_submission_id)
    target_id = int(target_key)
    download_url = str(finalized.target_download_url or "").strip()
    _validate_download_url(download_url)
    if _plan_already_has_target_rom(finalized, target_id):
        raise CollectionUpdateRomAcquisitionError(
            "The finalized replacement plan already contains a ROM for the selected target submission."
        )

    runtime_participants = _runtime_participants(processed, participants)
    _require_plan_preconditions_current(processed, finalized, runtime_participants)

    if extract_patches is None:
        from api_pipeline import extract_patches_from_zip

        extract_patches = extract_patches_from_zip
    if patch_apply is None:
        from patch_handler import PatchHandler

        patch_apply = PatchHandler.apply_patch

    metadata = _target_catalogue_metadata(finalized)
    hack_types = metadata.hack_types or ("standard",)
    difficulty = metadata.difficulty or "No Difficulty"
    normalized_type = str(hack_types[0]).lower().replace("-", "_")
    # Catalogue values are remote metadata. Keep output directory components on the
    # application's finite known-value mappings rather than interpolating unknown text.
    display_type = TYPE_DISPLAY_LOOKUP.get(normalized_type, "Unknown")
    difficulty_folder = DIFFICULTY_SORTED.get(difficulty, "08 - No Difficulty")
    target_directory = (output_root / display_type / difficulty_folder).resolve()
    try:
        target_directory.relative_to(output_root)
    except ValueError as error:
        raise CollectionUpdateRomAcquisitionError(
            "Replacement ROM output resolved outside the configured ROM directory."
        ) from error

    created_paths: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="smwc-replacement-") as temp_name:
        temp_dir = Path(temp_name)
        archive_path = temp_dir / "target.zip"
        _download_archive(download_url, archive_path, request_get=request_get, log=log)
        _validate_patch_archive(archive_path)
        patch_files = extract_patches(
            str(archive_path),
            str(temp_dir),
            metadata.title,
            return_all=True,
        )
        if not patch_files:
            raise CollectionUpdateRomAcquisitionError(
                "The selected SMWC download archive does not contain a supported .bps or .ips patch."
            )

        selections = _select_patches(
            patch_files,
            metadata.title,
            str(temp_dir),
            multi_patch_callback,
        )
        if selections is None:
            raise CollectionUpdateRomAcquisitionError("Target-ROM patch selection was cancelled.")
        if not selections:
            raise CollectionUpdateRomAcquisitionError("No target-ROM patch was selected.")

        staged: list[tuple[Path, Path, bool]] = []
        seen_finals: set[Path] = set()
        for index, selection in enumerate(selections):
            output_name = selection["output_name"]
            final_name = build_patched_rom_filename(
                output_name,
                extension,
                smwc_id=target_id,
                include_smwc_id=bool(include_smwc_id_in_filename),
            )
            final_path = (target_directory / final_name).resolve()
            if final_path in seen_finals:
                raise CollectionUpdateRomAcquisitionError(
                    f"Multiple selected patches resolve to the same output filename: {final_name}"
                )
            seen_finals.add(final_path)
            if final_path.exists():
                raise CollectionUpdateRomAcquisitionError(
                    f"Target ROM output already exists and will not be overwritten: {final_path}"
                )
            stage_path = temp_dir / f"patched-{index:03d}{extension}"
            _log(log, f"Patching target ROM: {output_name}", "Information")
            if not patch_apply(
                selection["patch_path"],
                str(base_rom),
                str(stage_path),
                log,
            ):
                raise CollectionUpdateRomAcquisitionError(
                    f"Patch application failed for {output_name!r}."
                )
            if not stage_path.is_file() or stage_path.stat().st_size <= 0:
                raise CollectionUpdateRomAcquisitionError(
                    f"Patched ROM output is empty or missing for {output_name!r}."
                )
            if stage_path.stat().st_size > MAX_PATCHED_ROM_BYTES:
                raise CollectionUpdateRomAcquisitionError(
                    f"Patched ROM output exceeds the allowed size for {output_name!r}."
                )
            staged.append((stage_path, final_path, bool(selection["primary"])))

        if not any(primary for _, _, primary in staged):
            first = staged[0]
            staged[0] = (first[0], first[1], True)

        # The potentially slow network/patch work is complete. Recheck every reviewed store
        # before publishing any new ROM into the user's output tree.
        _require_plan_preconditions_current(processed, finalized, runtime_participants)

        try:
            for stage_path, final_path, _primary in staged:
                final_path.parent.mkdir(parents=True, exist_ok=True)
                _copy_exclusive(stage_path, final_path)
                created_paths.append(final_path)
            _require_plan_preconditions_current(processed, finalized, runtime_participants)
        except Exception:
            _remove_created_files(created_paths)
            raise

    assets = []
    primary_path = ""
    for index, final_path in enumerate(created_paths):
        sha256, size_bytes = _hash_file(final_path)
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
                    f"collection-update-acquisition:{target_id}:{index}",
                ),
                smwc_submission_id=target_id,
            )
        )
    if not primary_path:
        primary_path = str(created_paths[0])

    rom_operation = RomAssetsOperation(
        target_key=target_key,
        assets=tuple(assets),
        primary_path=primary_path,
    )
    updated_plan = replace(
        finalized.plan,
        rom_updates=tuple(finalized.plan.rom_updates) + (rom_operation,),
    )
    updated = replace(finalized, plan=updated_plan)
    _log(
        log,
        f"Acquired {len(created_paths)} target ROM file(s) for SMWC {target_id}; Collection is still unchanged.",
        "Information",
    )
    return CollectionUpdateRomAcquisitionResult(
        finalized=updated,
        created_paths=tuple(str(path) for path in created_paths),
        primary_path=primary_path,
    )


def finalized_update_has_acquired_target_rom(finalized: FinalizedCollectionUpdatePlan) -> bool:
    """Return whether the finalized plan already contains a tool-patched target ROM."""

    if not isinstance(finalized, FinalizedCollectionUpdatePlan):
        return False
    target_id = int(finalized.selection.target_entry.smwc_submission_id)
    return _plan_already_has_target_rom(finalized, target_id)


def _target_catalogue_metadata(finalized: FinalizedCollectionUpdatePlan):
    target_key = str(finalized.selection.target_entry.smwc_submission_id)
    matches = [
        item.metadata
        for item in finalized.plan.catalogue_updates
        if item.target_key == target_key
    ]
    if len(matches) != 1:
        raise CollectionUpdateRomAcquisitionError(
            "Finalized replacement plan does not contain exactly one target catalogue snapshot."
        )
    return matches[0]


def _select_patches(patch_files, title, temp_dir, multi_patch_callback):
    if len(patch_files) == 1:
        return [
            {
                "patch_path": patch_files[0],
                "output_name": title,
                "primary": True,
            }
        ]
    if multi_patch_callback is None:
        raise CollectionUpdateRomAcquisitionError(
            "The selected archive contains multiple patches and requires explicit patch selection."
        )
    result = multi_patch_callback(patch_files, title, temp_dir)
    if result is None:
        return None
    normalized = []
    for raw in result:
        if not isinstance(raw, Mapping):
            raise CollectionUpdateRomAcquisitionError("Patch selection returned invalid data.")
        patch_path = str(raw.get("patch_path") or "")
        output_name = str(raw.get("output_name") or "").strip()
        if patch_path not in patch_files or not output_name:
            raise CollectionUpdateRomAcquisitionError("Patch selection returned invalid data.")
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
    _log(log, f"Downloading selected replacement archive from SMWCentral...", "Information")
    response = request_get(url, timeout=30, stream=True)
    try:
        if hasattr(response, "raise_for_status"):
            response.raise_for_status()
        effective_url = str(getattr(response, "url", url) or url)
        _validate_download_url(effective_url)
        content_length = _content_length(response)
        if content_length is not None and content_length > MAX_REPLACEMENT_ARCHIVE_BYTES:
            raise CollectionUpdateRomAcquisitionError(
                "Replacement archive exceeds the allowed download size."
            )
        total = 0
        with destination.open("wb") as handle:
            iterator = response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES)
            for chunk in iterator:
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_REPLACEMENT_ARCHIVE_BYTES:
                    raise CollectionUpdateRomAcquisitionError(
                        "Replacement archive exceeds the allowed download size."
                    )
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        if total <= 0:
            raise CollectionUpdateRomAcquisitionError("Replacement archive download was empty.")
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()



def _validate_patch_archive(path: Path) -> None:
    """Reject malformed or expansion-heavy archives before extracting any member."""

    try:
        with zipfile.ZipFile(path, "r") as archive:
            members = archive.infolist()
            if len(members) > MAX_REPLACEMENT_ARCHIVE_MEMBERS:
                raise CollectionUpdateRomAcquisitionError(
                    "Replacement archive contains too many files."
                )
            total = 0
            for member in members:
                if member.file_size < 0:
                    raise CollectionUpdateRomAcquisitionError(
                        "Replacement archive contains an invalid member size."
                    )
                total += member.file_size
                if total > MAX_REPLACEMENT_EXTRACTED_BYTES:
                    raise CollectionUpdateRomAcquisitionError(
                        "Replacement archive expands beyond the allowed size."
                    )
    except zipfile.BadZipFile as error:
        raise CollectionUpdateRomAcquisitionError(
            "Replacement download is not a valid ZIP archive."
        ) from error

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


def _validate_download_url(url: str) -> None:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or parsed.hostname != "dl.smwcentral.net":
        raise CollectionUpdateRomAcquisitionError(
            "Replacement acquisition requires the validated SMWCentral download URL from KaizOFF."
        )


def _copy_exclusive(source: Path, destination: Path) -> None:
    try:
        with source.open("rb") as src, destination.open("xb") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
    except FileExistsError as error:
        raise CollectionUpdateRomAcquisitionError(
            f"Target ROM output appeared while acquisition was running and was not overwritten: {destination}"
        ) from error


def _remove_created_files(paths: Sequence[Path]) -> None:
    failures = []
    for path in reversed(tuple(paths)):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            failures.append(f"{path}: {error}")
    if failures:
        raise CollectionUpdateRomAcquisitionError(
            "Target-ROM acquisition failed and one or more newly created files could not be cleaned up: "
            + "; ".join(failures)
        )


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _plan_already_has_target_rom(finalized: FinalizedCollectionUpdatePlan, target_id: int) -> bool:
    target_key = str(target_id)
    for operation in finalized.plan.rom_updates:
        if operation.target_key != target_key:
            continue
        for asset in operation.assets:
            if asset.smwc_submission_id == target_id:
                return True
    return False


def _runtime_participants(processed: Path, participants):
    if participants is not None:
        return tuple(participants)
    from collection_ingestion_entrypoint import collection_identity_reference_participants

    return tuple(collection_identity_reference_participants(processed))


def _require_plan_preconditions_current(
    processed: Path,
    finalized: FinalizedCollectionUpdatePlan,
    participants: Sequence[CollectionIdentityReferenceParticipant],
) -> None:
    manager = HackDataManager(str(processed))
    hints = CollectionIdentityHintsStore.beside_processed_json(processed)
    current = collect_store_preconditions(manager, hints, participants)
    expected = _precondition_map(finalized.plan.preconditions)
    actual = _precondition_map(current)
    if expected != actual:
        changed = sorted(
            key
            for key in set(expected).union(actual)
            if expected.get(key) != actual.get(key)
        )
        raise CollectionUpdateRomAcquisitionStaleStateError(
            "Collection/dependent state changed during target-ROM acquisition: "
            + (", ".join(changed) if changed else "reviewed stores")
            + ". Restart update discovery."
        )


def _precondition_map(items: Sequence[StorePrecondition]) -> dict[str, str]:
    result = {}
    for item in items:
        if item.store_name in result:
            raise CollectionUpdateRomAcquisitionError(
                f"Duplicate reviewed store precondition: {item.store_name!r}."
            )
        result[item.store_name] = item.revision_token
    return result


def _log(log, message: str, level: str) -> None:
    if log is None:
        return
    try:
        log(message, level)
    except TypeError:
        log(message)


__all__ = [
    "CollectionUpdateRomAcquisitionError",
    "CollectionUpdateRomAcquisitionResult",
    "CollectionUpdateRomAcquisitionStaleStateError",
    "MAX_PATCHED_ROM_BYTES",
    "MAX_REPLACEMENT_ARCHIVE_BYTES",
    "MAX_REPLACEMENT_ARCHIVE_MEMBERS",
    "MAX_REPLACEMENT_EXTRACTED_BYTES",
    "acquire_collection_update_target_rom",
    "finalized_update_has_acquired_target_rom",
]
