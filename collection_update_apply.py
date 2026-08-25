"""Apply a finalized explicit SMWC replacement plan without rediscovery or network work."""
from __future__ import annotations

from pathlib import Path
import hashlib

from collection_identity_hints import CollectionIdentityHintsStore
from collection_plan_apply import (
    COLLECTION_APPLY_JOURNAL_FILENAME,
    CollectionPlanApplyResult,
    CollectionPlanStaleStateError,
    apply_collection_change_plan,
    recover_interrupted_collection_apply,
)
from collection_reconciliation import IdentityMigrationKind
from collection_ingestion import IngestionSource
from collection_update_plan import FinalizedCollectionUpdatePlan
from hack_data_manager import HackDataManager


class CollectionUpdateApplyError(RuntimeError):
    """Raised when the replacement Apply boundary receives invalid finalized state."""


def apply_finalized_collection_update(
    processed_json_path: str | Path,
    finalized: FinalizedCollectionUpdatePlan,
    *,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants=None,
) -> CollectionPlanApplyResult:
    """Apply only the already-finalized immutable replacement plan."""

    if not isinstance(finalized, FinalizedCollectionUpdatePlan):
        raise CollectionUpdateApplyError(
            "SMWC replacement Apply requires a finalized replacement plan."
        )
    plan = finalized.plan
    migrations = tuple(plan.identity_migrations)
    if len(migrations) != 1 or migrations[0].kind != IdentityMigrationKind.SUBMISSION_REPLACEMENT:
        raise CollectionUpdateApplyError(
            "Finalized SMWC replacement plan must contain exactly one reviewed submission replacement."
        )
    migration = migrations[0]
    source_key = str(finalized.selection.source_collection_key)
    target_key = str(finalized.selection.target_entry.smwc_submission_id)
    if migration.source_key != source_key or migration.target_key != target_key:
        raise CollectionUpdateApplyError(
            "Finalized replacement plan does not match the explicitly selected SMWC relationship."
        )

    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = manager or HackDataManager(str(processed))
    if Path(runtime_manager.json_path).expanduser().resolve() != processed:
        raise CollectionUpdateApplyError(
            "Collection manager does not reference the selected processed.json."
        )
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(processed)

    if participants is None:
        from collection_ingestion_entrypoint import collection_identity_reference_participants

        runtime_participants = collection_identity_reference_participants(processed)
    else:
        runtime_participants = tuple(participants)

    _validate_acquired_target_roms(plan)
    return apply_collection_change_plan(
        plan,
        runtime_manager,
        hints,
        reference_participants=tuple(runtime_participants),
    )


def _validate_acquired_target_roms(plan) -> None:
    """Fail closed if a tool-patched ROM changed after the reviewed preview."""

    for operation in plan.rom_updates:
        for asset in operation.assets:
            if IngestionSource.TOOL_PATCH not in asset.sources:
                continue
            path = Path(asset.path).expanduser()
            if not path.is_file():
                raise CollectionPlanStaleStateError(
                    f"Reviewed acquired ROM is missing before Apply: {asset.path}"
                )
            stat = path.stat()
            if stat.st_size != asset.size_bytes:
                raise CollectionPlanStaleStateError(
                    f"Reviewed acquired ROM changed size before Apply: {asset.path}"
                )
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != asset.sha256:
                raise CollectionPlanStaleStateError(
                    f"Reviewed acquired ROM changed contents before Apply: {asset.path}"
                )


def collection_update_apply_recovery_pending(processed_json_path: str | Path) -> bool:
    """Return whether a coordinated Collection transaction journal needs attention."""

    processed = Path(processed_json_path).expanduser().resolve()
    return (processed.parent / COLLECTION_APPLY_JOURNAL_FILENAME).exists()


def recover_collection_update_apply(processed_json_path: str | Path) -> bool:
    """Recover/clean an abandoned coordinated Apply after caller confirmation."""

    processed = Path(processed_json_path).expanduser().resolve()
    return recover_interrupted_collection_apply(processed.parent)


__all__ = [
    "CollectionUpdateApplyError",
    "apply_finalized_collection_update",
    "collection_update_apply_recovery_pending",
    "recover_collection_update_apply",
]
