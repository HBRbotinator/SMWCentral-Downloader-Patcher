"""Acquire current SMWC submission ROM bytes for an immutable same-ID refresh plan."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Mapping, Sequence

import requests

from collection_change_plan import RomAssetsOperation, StorePrecondition
from collection_identity_hints import CollectionIdentityHintsStore
from collection_plan_apply import (
    CollectionIdentityReferenceParticipant,
    collect_store_preconditions,
)
from collection_update_current_refresh import FinalizedCurrentSubmissionRefreshPlan
from hack_data_manager import HackDataManager
from smwc_patch_acquisition import (
    SmwcPatchAcquisitionError,
    acquire_smwc_rom_assets,
    hash_file_stable,
)


class CollectionCurrentRefreshAcquisitionError(RuntimeError):
    """Raised when current-submission ROM acquisition cannot complete safely."""


class CollectionCurrentRefreshAcquisitionStaleStateError(
    CollectionCurrentRefreshAcquisitionError
):
    """Raised when reviewed state changes while the current ROM is acquired."""


@dataclass(frozen=True)
class CollectionCurrentRefreshAcquisitionResult:
    finalized: FinalizedCurrentSubmissionRefreshPlan
    created_paths: tuple[str, ...]
    primary_path: str
    identical_to_existing: bool = False


def acquire_current_submission_rom(
    processed_json_path: str | Path,
    finalized: FinalizedCurrentSubmissionRefreshPlan,
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
) -> CollectionCurrentRefreshAcquisitionResult:
    """Download/patch the current SMWC submission without mutating Collection state.

    Existing files are never overwritten. A filename collision receives a deterministic
    numbered suffix. If every newly patched asset is byte-identical to an already verified
    modern asset for the same Collection record, the temporary new copies are removed and
    the metadata-only immutable plan is returned instead.
    """

    if not isinstance(finalized, FinalizedCurrentSubmissionRefreshPlan):
        raise TypeError("finalized must be FinalizedCurrentSubmissionRefreshPlan")
    if finalized.plan.rom_updates:
        raise CollectionCurrentRefreshAcquisitionError(
            "The current-submission refresh plan already contains acquired ROM assets."
        )

    processed = Path(processed_json_path).expanduser().resolve()
    runtime_participants = _runtime_participants(processed, participants)
    _require_plan_preconditions_current(processed, finalized, runtime_participants)

    source_key = finalized.source_collection_key
    metadata = _current_catalogue_metadata(finalized)
    try:
        acquired = acquire_smwc_rom_assets(
            submission_id=int(source_key),
            metadata=metadata,
            download_url=finalized.download_url,
            base_rom_path=base_rom_path,
            output_dir=output_dir,
            include_smwc_id_in_filename=include_smwc_id_in_filename,
            multi_patch_callback=multi_patch_callback,
            request_get=request_get,
            extract_patches=extract_patches,
            patch_apply=patch_apply,
            before_publish=lambda: _require_plan_preconditions_current(
                processed, finalized, runtime_participants
            ),
            after_publish=lambda: _require_plan_preconditions_current(
                processed, finalized, runtime_participants
            ),
            unique_if_occupied=True,
            source_candidate_prefix="current-submission-refresh-acquisition",
            log=log,
        )
    except SmwcPatchAcquisitionError as error:
        raise CollectionCurrentRefreshAcquisitionError(str(error)) from error

    if _acquired_assets_already_present(processed, source_key, acquired.assets):
        _remove_created_paths(acquired.created_paths)
        _log(
            log,
            f"Current SMWC {source_key} download matches existing verified ROM bytes; no new ROM was retained.",
            "Information",
        )
        checked = replace(
            finalized,
            rom_acquisition_checked=True,
            rom_matches_existing=True,
        )
        return CollectionCurrentRefreshAcquisitionResult(
            finalized=checked,
            created_paths=(),
            primary_path="",
            identical_to_existing=True,
        )

    operation = RomAssetsOperation(
        target_key=source_key,
        assets=acquired.assets,
        primary_path=acquired.primary_path,
    )
    updated = replace(
        finalized,
        plan=replace(
            finalized.plan,
            rom_updates=tuple(finalized.plan.rom_updates) + (operation,),
        ),
        rom_acquisition_checked=True,
        rom_matches_existing=False,
    )
    _log(
        log,
        f"Acquired {len(acquired.created_paths)} refreshed ROM file(s) for current SMWC {source_key}; Collection is still unchanged.",
        "Information",
    )
    return CollectionCurrentRefreshAcquisitionResult(
        finalized=updated,
        created_paths=acquired.created_paths,
        primary_path=acquired.primary_path,
        identical_to_existing=False,
    )


def finalized_current_refresh_has_acquired_rom(
    finalized: FinalizedCurrentSubmissionRefreshPlan,
) -> bool:
    if not isinstance(finalized, FinalizedCurrentSubmissionRefreshPlan):
        return False
    return bool(finalized.plan.rom_updates)


def finalized_current_refresh_rom_checked(
    finalized: FinalizedCurrentSubmissionRefreshPlan,
) -> bool:
    return bool(
        isinstance(finalized, FinalizedCurrentSubmissionRefreshPlan)
        and finalized.rom_acquisition_checked
    )


def _acquired_assets_already_present(processed: Path, source_key: str, assets) -> bool:
    manager = HackDataManager(str(processed))
    record = manager.data.get(source_key)
    if not isinstance(record, Mapping):
        return False
    rows = record.get("files", [])
    if not isinstance(rows, list) or not assets:
        return False

    verified_hashes: set[tuple[str, int]] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        sha = str(row.get("sha256") or "").lower()
        size = row.get("size_bytes")
        path = row.get("path")
        if len(sha) != 64 or not isinstance(size, int) or not isinstance(path, str):
            continue
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            continue
        try:
            actual_sha, actual_size = hash_file_stable(candidate)
        except SmwcPatchAcquisitionError:
            continue
        if actual_sha == sha and actual_size == size:
            verified_hashes.add((sha, size))
    return all((asset.sha256, asset.size_bytes) in verified_hashes for asset in assets)


def _current_catalogue_metadata(finalized: FinalizedCurrentSubmissionRefreshPlan):
    matches = [
        item.metadata
        for item in finalized.plan.catalogue_updates
        if item.target_key == finalized.source_collection_key
    ]
    if len(matches) != 1:
        raise CollectionCurrentRefreshAcquisitionError(
            "Current-submission refresh plan does not contain exactly one catalogue snapshot."
        )
    return matches[0]


def _runtime_participants(processed: Path, participants):
    if participants is not None:
        return tuple(participants)
    from collection_ingestion_entrypoint import collection_identity_reference_participants

    return tuple(collection_identity_reference_participants(processed))


def _require_plan_preconditions_current(
    processed: Path,
    finalized: FinalizedCurrentSubmissionRefreshPlan,
    participants: Sequence[CollectionIdentityReferenceParticipant],
) -> None:
    manager = HackDataManager(str(processed))
    hints = CollectionIdentityHintsStore.beside_processed_json(processed)
    current = collect_store_preconditions(manager, hints, participants)
    expected = _precondition_map(finalized.plan.preconditions)
    actual = _precondition_map(current)
    if expected == actual:
        return
    changed = sorted(
        key
        for key in set(expected).union(actual)
        if expected.get(key) != actual.get(key)
    )
    raise CollectionCurrentRefreshAcquisitionStaleStateError(
        "Collection/dependent state changed during current-submission ROM acquisition: "
        + (", ".join(changed) if changed else "reviewed stores")
        + ". Restart the update check."
    )


def _precondition_map(items: Sequence[StorePrecondition]) -> dict[str, str]:
    result = {}
    for item in items:
        if item.store_name in result:
            raise CollectionCurrentRefreshAcquisitionError(
                f"Duplicate reviewed store precondition: {item.store_name!r}."
            )
        result[item.store_name] = item.revision_token
    return result


def _remove_created_paths(paths: Sequence[str]) -> None:
    for raw in reversed(tuple(paths)):
        try:
            Path(raw).unlink(missing_ok=True)
        except OSError:
            pass


def _log(log, message: str, level: str) -> None:
    if log is None:
        return
    try:
        log(message, level)
    except TypeError:
        log(message)


__all__ = [
    "CollectionCurrentRefreshAcquisitionError",
    "CollectionCurrentRefreshAcquisitionResult",
    "CollectionCurrentRefreshAcquisitionStaleStateError",
    "acquire_current_submission_rom",
    "finalized_current_refresh_has_acquired_rom",
    "finalized_current_refresh_rom_checked",
]
