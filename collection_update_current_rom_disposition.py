"""Reviewed disposition for newly acquired same-ID SMWC ROM assets.

This layer is read-only with respect to Collection and ROM files.  It freezes the
user's explicit choice between keeping all verified ROMs or replacing the current
primary ROM at its existing path.  No version ordering is inferred from IDs,
filenames, or hashes.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import os
from pathlib import Path
from typing import Mapping, Sequence

from collection_change_plan import (
    PlannedRomAsset,
    PrimaryRomSelectionOperation,
    RomAssetsOperation,
    StorePrecondition,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_plan_apply import (
    CollectionIdentityReferenceParticipant,
    collect_store_preconditions,
)
from collection_update_current_refresh import (
    CurrentRomDisposition,
    CurrentRomPrimaryPrecondition,
    CurrentRomReplacementPrecondition,
    FinalizedCurrentSubmissionRefreshPlan,
)
from hack_data_manager import HackDataManager


class CollectionCurrentRomDispositionError(RuntimeError):
    """Raised when an acquired current-ROM choice cannot be finalized safely."""


class CollectionCurrentRomDispositionStaleStateError(CollectionCurrentRomDispositionError):
    """Raised when Collection/filesystem state changed during ROM-disposition review."""


@dataclass(frozen=True)
class CurrentRomChoice:
    path: str
    filename: str
    sha256: str
    size_bytes: int
    mtime_ns: int
    downloaded: bool
    current_primary: bool


@dataclass(frozen=True)
class CurrentRomDispositionReview:
    source_collection_key: str
    choices: tuple[CurrentRomChoice, ...]
    downloaded_default_primary_path: str
    current_primary_path: str
    can_replace_current: bool

    def __post_init__(self) -> None:
        paths = tuple(item.path for item in self.choices)
        if not self.choices or len(paths) != len(set(paths)):
            raise CollectionCurrentRomDispositionError(
                "Current-ROM disposition review requires unique verified ROM choices."
            )
        if self.downloaded_default_primary_path not in paths:
            raise CollectionCurrentRomDispositionError(
                "Downloaded default primary is not present in the reviewed ROM choices."
            )
        if self.can_replace_current and self.current_primary_path not in paths:
            raise CollectionCurrentRomDispositionError(
                "Replace-current review requires the verified current primary ROM."
            )


def build_current_rom_disposition_review(
    processed_json_path: str | Path,
    finalized: FinalizedCurrentSubmissionRefreshPlan,
    *,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants: Sequence[CollectionIdentityReferenceParticipant] | None = None,
) -> CurrentRomDispositionReview:
    """Freeze verified current/downloaded ROM choices without mutating anything."""
    if not isinstance(finalized, FinalizedCurrentSubmissionRefreshPlan):
        raise TypeError("finalized must be FinalizedCurrentSubmissionRefreshPlan")
    if not finalized.rom_acquisition_checked or finalized.rom_matches_existing:
        raise CollectionCurrentRomDispositionError(
            "A distinct downloaded current ROM is required before choosing its disposition."
        )
    finalized = _without_rom_disposition(finalized)
    operation = _single_rom_operation(finalized)
    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = manager or HackDataManager(str(processed))
    if Path(runtime_manager.json_path).expanduser().resolve() != processed:
        raise CollectionCurrentRomDispositionError(
            "Collection manager does not reference the selected processed.json."
        )
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(processed)
    runtime_participants = _runtime_participants(processed, participants)
    _require_preconditions_current(finalized.plan.preconditions, runtime_manager, hints, runtime_participants)

    record = runtime_manager.data.get(finalized.source_collection_key)
    if not isinstance(record, Mapping):
        raise CollectionCurrentRomDispositionStaleStateError(
            "The current Collection entry disappeared before ROM-disposition review."
        )

    existing_rows = _existing_rows(record)
    current_primary_path = _current_primary_path(record, existing_rows)
    choices: list[CurrentRomChoice] = []
    by_path: dict[str, CurrentRomChoice] = {}

    for row in existing_rows:
        path = str(row.get("path") or "")
        sha = str(row.get("sha256") or "").lower()
        size = row.get("size_bytes")
        if not path or len(sha) != 64 or not isinstance(size, int) or isinstance(size, bool) or size < 0:
            continue
        try:
            actual_sha, actual_size, mtime_ns = _hash_file_stable(path)
        except CollectionCurrentRomDispositionStaleStateError:
            continue
        if actual_sha != sha or actual_size != size:
            continue
        choice = CurrentRomChoice(
            path=path,
            filename=os.path.basename(path),
            sha256=sha,
            size_bytes=size,
            mtime_ns=mtime_ns,
            downloaded=False,
            current_primary=(path == current_primary_path),
        )
        choices.append(choice)
        by_path[path] = choice

    for asset in _downloaded_assets_for_review(finalized, operation):
        actual_sha, actual_size, mtime_ns = _hash_file_stable(asset.path)
        if actual_sha != asset.sha256 or actual_size != asset.size_bytes:
            raise CollectionCurrentRomDispositionStaleStateError(
                f"Downloaded reviewed ROM changed before disposition review: {asset.path}"
            )
        choice = CurrentRomChoice(
            path=asset.path,
            filename=asset.filename,
            sha256=asset.sha256,
            size_bytes=asset.size_bytes,
            mtime_ns=mtime_ns,
            downloaded=True,
            current_primary=False,
        )
        if choice.path in by_path:
            raise CollectionCurrentRomDispositionError(
                "Downloaded ROM unexpectedly reuses an existing Collection path."
            )
        choices.append(choice)
        by_path[choice.path] = choice

    downloaded_default = finalized.acquired_default_primary_path or operation.primary_path
    if downloaded_default not in by_path or not by_path[downloaded_default].downloaded:
        raise CollectionCurrentRomDispositionError(
            "Acquired current-ROM plan has no valid downloaded default primary."
        )

    can_replace = bool(
        current_primary_path
        and current_primary_path in by_path
        and not by_path[current_primary_path].downloaded
    )
    return CurrentRomDispositionReview(
        source_collection_key=finalized.source_collection_key,
        choices=tuple(choices),
        downloaded_default_primary_path=downloaded_default,
        current_primary_path=current_primary_path if can_replace else "",
        can_replace_current=can_replace,
    )


def finalize_current_rom_disposition(
    processed_json_path: str | Path,
    finalized: FinalizedCurrentSubmissionRefreshPlan,
    review: CurrentRomDispositionReview,
    disposition: CurrentRomDisposition | str,
    *,
    primary_path: str = "",
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants: Sequence[CollectionIdentityReferenceParticipant] | None = None,
) -> FinalizedCurrentSubmissionRefreshPlan:
    """Freeze one explicit ROM disposition into the immutable same-ID plan."""
    if not isinstance(review, CurrentRomDispositionReview):
        raise TypeError("review must be CurrentRomDispositionReview")
    if isinstance(disposition, str):
        try:
            disposition = CurrentRomDisposition(disposition)
        except ValueError as error:
            raise CollectionCurrentRomDispositionError("Unknown current-ROM disposition.") from error
    if not isinstance(disposition, CurrentRomDisposition):
        raise TypeError("disposition must be CurrentRomDisposition")

    base_finalized = _without_rom_disposition(finalized)
    current_review = build_current_rom_disposition_review(
        processed_json_path,
        base_finalized,
        manager=manager,
        identity_hints=identity_hints,
        participants=participants,
    )
    if current_review != review:
        raise CollectionCurrentRomDispositionStaleStateError(
            "Current ROM choices changed during review. Reopen the ROM choice dialog."
        )
    finalized = base_finalized
    operation = _single_rom_operation(finalized)

    if disposition is CurrentRomDisposition.KEEP_BOTH:
        choices = {item.path for item in review.choices}
        if not primary_path or primary_path not in choices:
            raise CollectionCurrentRomDispositionError(
                "Keep Both requires an explicit primary ROM choice."
            )
        primary_choice = next(item for item in review.choices if item.path == primary_path)
        primary_precondition = CurrentRomPrimaryPrecondition(
            path=primary_choice.path,
            sha256=primary_choice.sha256,
            size_bytes=primary_choice.size_bytes,
            mtime_ns=primary_choice.mtime_ns,
        )
        keep_operation = replace(
            operation,
            primary_path="",
            preserve_existing_primary=True,
        )
        primary_selections = tuple(
            item
            for item in finalized.plan.primary_rom_selections
            if item.target_key != finalized.source_collection_key
        ) + (
            PrimaryRomSelectionOperation(
                target_key=finalized.source_collection_key,
                primary_path=primary_path,
                reason="Explicit same-ID current-ROM Keep Both primary selection",
            ),
        )
        return replace(
            finalized,
            plan=replace(
                finalized.plan,
                rom_updates=(keep_operation,),
                primary_rom_selections=primary_selections,
            ),
            rom_disposition=CurrentRomDisposition.KEEP_BOTH,
            reviewed_primary_path=primary_path,
            reviewed_primary_precondition=primary_precondition,
            rom_replacement=None,
        )

    if not review.can_replace_current or not review.current_primary_path:
        raise CollectionCurrentRomDispositionError(
            "Replace Current ROM is unavailable because no verified current primary ROM exists."
        )
    target = next(item for item in review.choices if item.path == review.current_primary_path)
    source = next(
        item for item in review.choices if item.path == review.downloaded_default_primary_path
    )
    selected_asset = next(
        asset for asset in operation.assets if asset.path == review.downloaded_default_primary_path
    )
    replacement_asset = PlannedRomAsset(
        path=target.path,
        filename=os.path.basename(target.path),
        sha256=selected_asset.sha256,
        size_bytes=selected_asset.size_bytes,
        sources=selected_asset.sources,
        source_candidate_ids=selected_asset.source_candidate_ids,
        smwc_submission_id=selected_asset.smwc_submission_id,
    )
    assets = tuple(
        replacement_asset if asset.path == selected_asset.path else asset
        for asset in operation.assets
    )
    replace_operation = RomAssetsOperation(
        target_key=operation.target_key,
        assets=assets,
        primary_path=target.path,
        preserve_existing_primary=False,
    )
    primary_selections = tuple(
        item
        for item in finalized.plan.primary_rom_selections
        if item.target_key != finalized.source_collection_key
    )
    replacement = CurrentRomReplacementPrecondition(
        source_path=source.path,
        source_sha256=source.sha256,
        source_size_bytes=source.size_bytes,
        source_mtime_ns=source.mtime_ns,
        target_path=target.path,
        target_sha256=target.sha256,
        target_size_bytes=target.size_bytes,
        target_mtime_ns=target.mtime_ns,
    )
    return replace(
        finalized,
        plan=replace(
            finalized.plan,
            rom_updates=(replace_operation,),
            primary_rom_selections=primary_selections,
        ),
        rom_disposition=CurrentRomDisposition.REPLACE_CURRENT,
        reviewed_primary_path=target.path,
        reviewed_primary_precondition=None,
        rom_replacement=replacement,
    )


def _downloaded_assets_for_review(
    finalized: FinalizedCurrentSubmissionRefreshPlan,
    operation: RomAssetsOperation,
) -> tuple[PlannedRomAsset, ...]:
    replacement = finalized.rom_replacement
    if replacement is None:
        return tuple(operation.assets)
    rows = []
    restored = False
    for asset in operation.assets:
        if (
            not restored
            and asset.path == replacement.target_path
            and asset.sha256 == replacement.source_sha256
            and asset.size_bytes == replacement.source_size_bytes
        ):
            rows.append(
                PlannedRomAsset(
                    path=replacement.source_path,
                    filename=os.path.basename(replacement.source_path),
                    sha256=asset.sha256,
                    size_bytes=asset.size_bytes,
                    sources=asset.sources,
                    source_candidate_ids=asset.source_candidate_ids,
                    smwc_submission_id=asset.smwc_submission_id,
                )
            )
            restored = True
        else:
            rows.append(asset)
    if not restored:
        raise CollectionCurrentRomDispositionError(
            "Reviewed replacement no longer identifies its downloaded source asset."
        )
    return tuple(rows)


def _without_rom_disposition(
    finalized: FinalizedCurrentSubmissionRefreshPlan,
) -> FinalizedCurrentSubmissionRefreshPlan:
    if finalized.rom_disposition is None and finalized.rom_replacement is None:
        return finalized
    operation = _single_rom_operation(finalized, require_primary=False)
    downloaded_assets = _downloaded_assets_for_review(finalized, operation)
    default_primary = finalized.acquired_default_primary_path
    if not default_primary:
        raise CollectionCurrentRomDispositionError(
            "Reviewed current-ROM update lost its downloaded default primary path."
        )
    base_operation = RomAssetsOperation(
        target_key=operation.target_key,
        assets=downloaded_assets,
        primary_path=default_primary,
        preserve_existing_primary=False,
    )
    base_selections = tuple(
        item
        for item in finalized.plan.primary_rom_selections
        if item.target_key != finalized.source_collection_key
    )
    return replace(
        finalized,
        plan=replace(
            finalized.plan,
            rom_updates=(base_operation,),
            primary_rom_selections=base_selections,
        ),
        rom_disposition=None,
        reviewed_primary_path="",
        reviewed_primary_precondition=None,
        rom_replacement=None,
    )


def _single_rom_operation(
    finalized: FinalizedCurrentSubmissionRefreshPlan,
    *,
    require_primary: bool = True,
) -> RomAssetsOperation:
    operations = tuple(finalized.plan.rom_updates)
    if len(operations) != 1 or operations[0].target_key != finalized.source_collection_key:
        raise CollectionCurrentRomDispositionError(
            "Current-ROM disposition requires exactly one acquired ROM operation for this Collection entry."
        )
    operation = operations[0]
    if not operation.assets or (require_primary and not operation.primary_path):
        raise CollectionCurrentRomDispositionError(
            "Acquired current-ROM operation has no explicit downloaded primary."
        )
    return operation


def _existing_rows(record: Mapping) -> tuple[Mapping, ...]:
    rows = record.get("files", [])
    if not isinstance(rows, list):
        raise CollectionCurrentRomDispositionStaleStateError(
            "Collection files[] state is invalid during current-ROM disposition review."
        )
    result = []
    for row in rows:
        if not isinstance(row, Mapping):
            raise CollectionCurrentRomDispositionStaleStateError(
                "Collection files[] contains an invalid ROM row."
            )
        result.append(row)
    return tuple(result)


def _current_primary_path(record: Mapping, rows: Sequence[Mapping]) -> str:
    primaries = [str(row.get("path") or "") for row in rows if row.get("primary")]
    primaries = [item for item in primaries if item]
    if len(primaries) > 1:
        raise CollectionCurrentRomDispositionStaleStateError(
            "Collection has multiple primary ROM rows; repair the primary choice first."
        )
    file_path = record.get("file_path")
    projected = file_path if isinstance(file_path, str) and file_path else ""
    if primaries:
        if projected and projected != primaries[0]:
            raise CollectionCurrentRomDispositionStaleStateError(
                "Collection primary ROM metadata disagrees with file_path; repair the primary choice first."
            )
        return primaries[0]
    if projected:
        matches = [row for row in rows if row.get("path") == projected]
        if len(matches) == 1:
            return projected
    return ""


def _hash_file_stable(path_value: str) -> tuple[str, int, int]:
    path = Path(path_value).expanduser()
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as error:
        raise CollectionCurrentRomDispositionStaleStateError(
            f"Reviewed ROM cannot be inspected: {path_value}: {error}"
        ) from error
    if path.is_symlink() or not path.is_file():
        raise CollectionCurrentRomDispositionStaleStateError(
            f"Reviewed ROM is not a regular non-symlink file: {path_value}"
        )
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CollectionCurrentRomDispositionStaleStateError(
            f"Reviewed ROM cannot be hashed: {path_value}: {error}"
        ) from error
    after = path.stat(follow_symlinks=False)
    before_identity = (before.st_size, getattr(before, "st_mtime_ns", int(before.st_mtime * 1e9)))
    after_identity = (after.st_size, getattr(after, "st_mtime_ns", int(after.st_mtime * 1e9)))
    if before_identity != after_identity:
        raise CollectionCurrentRomDispositionStaleStateError(
            f"Reviewed ROM changed while being hashed: {path_value}"
        )
    return digest.hexdigest(), int(after.st_size), int(after_identity[1])


def _runtime_participants(processed: Path, participants):
    if participants is not None:
        return tuple(participants)
    from collection_ingestion_entrypoint import collection_identity_reference_participants
    return tuple(collection_identity_reference_participants(processed))


def _require_preconditions_current(
    expected: Sequence[StorePrecondition],
    manager: HackDataManager,
    hints: CollectionIdentityHintsStore,
    participants: Sequence[CollectionIdentityReferenceParticipant],
) -> None:
    actual = collect_store_preconditions(manager, hints, participants)
    expected_map = _precondition_map(expected)
    actual_map = _precondition_map(actual)
    if expected_map == actual_map:
        return
    changed = sorted(
        key for key in set(expected_map).union(actual_map)
        if expected_map.get(key) != actual_map.get(key)
    )
    raise CollectionCurrentRomDispositionStaleStateError(
        "Collection/dependent state changed during current-ROM disposition review: "
        + (", ".join(changed) if changed else "reviewed stores")
        + ". Restart the update check."
    )


def _precondition_map(items: Sequence[StorePrecondition]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if item.store_name in result:
            raise CollectionCurrentRomDispositionError(
                f"Duplicate reviewed store precondition: {item.store_name!r}."
            )
        result[item.store_name] = item.revision_token
    return result


__all__ = [
    "CollectionCurrentRomDispositionError",
    "CollectionCurrentRomDispositionStaleStateError",
    "CurrentRomChoice",
    "CurrentRomDispositionReview",
    "build_current_rom_disposition_review",
    "finalize_current_rom_disposition",
]
