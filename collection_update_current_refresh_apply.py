"""Transactional Apply for finalized same-SMWC-ID Collection refresh plans."""
from __future__ import annotations

import hashlib
from pathlib import Path

from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion import IngestionSource
from collection_plan_apply import (
    CollectionPlanApplyResult,
    CollectionPlanStaleStateError,
    apply_collection_change_plan,
)
from collection_update_current_refresh import (
    CurrentRomDisposition,
    FinalizedCurrentSubmissionRefreshPlan,
)
from hack_data_manager import HackDataManager


class CollectionCurrentRefreshApplyError(RuntimeError):
    """Raised when a current-submission refresh Apply request is structurally invalid."""


def apply_finalized_current_submission_refresh(
    processed_json_path: str | Path,
    finalized: FinalizedCurrentSubmissionRefreshPlan,
    *,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants=None,
) -> CollectionPlanApplyResult:
    """Apply only the frozen same-ID metadata/ROM plan; never rediscover or download."""

    if not isinstance(finalized, FinalizedCurrentSubmissionRefreshPlan):
        raise CollectionCurrentRefreshApplyError(
            "Current-submission refresh Apply requires a finalized refresh plan."
        )
    plan = finalized.plan
    if plan.identity_migrations or plan.reference_migrations:
        raise CollectionCurrentRefreshApplyError(
            "Current-submission refresh must not contain identity/reference migrations."
        )
    if len(plan.record_intents) != 1 or plan.record_intents[0].target_key != finalized.source_collection_key:
        raise CollectionCurrentRefreshApplyError(
            "Current-submission refresh plan does not target exactly the selected Collection entry."
        )

    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = manager or HackDataManager(str(processed))
    if Path(runtime_manager.json_path).expanduser().resolve() != processed:
        raise CollectionCurrentRefreshApplyError(
            "Collection manager does not reference the selected processed.json."
        )
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(processed)
    if participants is None:
        from collection_ingestion_entrypoint import collection_identity_reference_participants

        runtime_participants = tuple(collection_identity_reference_participants(processed))
    else:
        runtime_participants = tuple(participants)

    if (
        finalized.rom_acquisition_checked
        and not finalized.rom_matches_existing
        and plan.rom_updates
        and finalized.rom_disposition is None
    ):
        raise CollectionCurrentRefreshApplyError(
            "Downloaded current ROM requires an explicit Replace Current ROM or Keep Both decision before Apply."
        )
    if finalized.rom_disposition is CurrentRomDisposition.REPLACE_CURRENT:
        from collection_update_current_rom_replace_apply import apply_current_rom_replacement
        return apply_current_rom_replacement(
            processed,
            finalized,
            manager=runtime_manager,
            identity_hints=hints,
            participants=runtime_participants,
        )

    if finalized.rom_disposition is CurrentRomDisposition.KEEP_BOTH:
        _validate_reviewed_primary_rom(finalized)
    _validate_acquired_roms(plan, finalized.source_collection_key)
    return apply_collection_change_plan(
        plan,
        runtime_manager,
        hints,
        reference_participants=runtime_participants,
    )


def _validate_reviewed_primary_rom(finalized: FinalizedCurrentSubmissionRefreshPlan) -> None:
    frozen = finalized.reviewed_primary_precondition
    if frozen is None or frozen.path != finalized.reviewed_primary_path:
        raise CollectionCurrentRefreshApplyError(
            "Keep Both requires exact reviewed primary-ROM byte preconditions before Apply."
        )
    path = Path(frozen.path).expanduser()
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as error:
        raise CollectionPlanStaleStateError(
            f"Reviewed primary ROM is missing before Apply: {frozen.path}"
        ) from error
    if path.is_symlink() or not path.is_file():
        raise CollectionPlanStaleStateError(
            f"Reviewed primary ROM is not a regular file before Apply: {frozen.path}"
        )
    before_mtime_ns = getattr(before, "st_mtime_ns", int(before.st_mtime * 1e9))
    if before.st_size != frozen.size_bytes or int(before_mtime_ns) != frozen.mtime_ns:
        raise CollectionPlanStaleStateError(
            f"Reviewed primary ROM changed before Apply: {frozen.path}"
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    try:
        after = path.stat(follow_symlinks=False)
    except OSError as error:
        raise CollectionPlanStaleStateError(
            f"Reviewed primary ROM changed before Apply: {frozen.path}"
        ) from error
    after_mtime_ns = getattr(after, "st_mtime_ns", int(after.st_mtime * 1e9))
    if (
        after.st_size != frozen.size_bytes
        or int(after_mtime_ns) != frozen.mtime_ns
        or digest.hexdigest() != frozen.sha256
    ):
        raise CollectionPlanStaleStateError(
            f"Reviewed primary ROM changed before Apply: {frozen.path}"
        )

def _validate_acquired_roms(plan, source_key: str) -> None:


    for operation in plan.rom_updates:
        if operation.target_key != source_key:
            raise CollectionCurrentRefreshApplyError(
                "Current-submission refresh contains a ROM operation for a different Collection key."
            )
        for asset in operation.assets:
            if asset.smwc_submission_id != int(source_key):
                raise CollectionCurrentRefreshApplyError(
                    "Refreshed ROM provenance does not match the current Collection SMWC ID."
                )
            if IngestionSource.TOOL_PATCH not in asset.sources:
                continue
            path = Path(asset.path).expanduser()
            if not path.is_file():
                raise CollectionPlanStaleStateError(
                    f"Reviewed refreshed ROM is missing before Apply: {asset.path}"
                )
            stat = path.stat()
            if stat.st_size != asset.size_bytes:
                raise CollectionPlanStaleStateError(
                    f"Reviewed refreshed ROM changed size before Apply: {asset.path}"
                )
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != asset.sha256:
                raise CollectionPlanStaleStateError(
                    f"Reviewed refreshed ROM changed contents before Apply: {asset.path}"
                )


__all__ = [
    "CollectionCurrentRefreshApplyError",
    "apply_finalized_current_submission_refresh",
]
