"""Transactional Apply for frozen legacy Collection ROM metadata backfill plans.

This boundary writes only Collection metadata. It never moves, renames, copies,
or deletes ROM/save files and never performs provider/network discovery.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from collection_plan_apply import collection_revision_token
from collection_rom_legacy_metadata_plan import (
    LegacyRomMetadataBackfillOperation,
    LegacyRomMetadataModernizationPlan,
)
from collection_transaction import (
    CollectionStaleStateError,
    CollectionTransactionError,
    HackDataManagerCollectionStore,
)
from hack_data_manager import HackDataManager


class LegacyRomMetadataApplyError(RuntimeError):
    """Raised when a frozen legacy metadata plan cannot be applied safely."""


class LegacyRomMetadataApplyStaleStateError(LegacyRomMetadataApplyError):
    """Raised when reviewed Collection or ROM state changed before Apply."""


@dataclass(frozen=True)
class LegacyRomMetadataApplyResult:
    collection_record_count: int


def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _canonical(path: str | Path) -> Path:
    return Path(os.path.realpath(str(_absolute(path))))


def _path_identity(path: str | Path) -> str:
    return os.path.normcase(str(_canonical(path)))


def _stat_identity(path: Path) -> tuple[int, int, int | None, int | None]:
    try:
        stat = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM can no longer be inspected: {path}: {error}"
        ) from error
    if os.path.islink(path) or not os.path.isfile(path):
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM is no longer a regular non-symlink file: {path}"
        )
    return (
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        getattr(stat, "st_dev", None),
        getattr(stat, "st_ino", None),
    )


def _verify_operation_bytes(operation: LegacyRomMetadataBackfillOperation) -> None:
    raw_path = _absolute(operation.legacy_file_path)
    if os.path.islink(raw_path):
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM became a symbolic link: {operation.legacy_file_path}"
        )
    if _path_identity(raw_path) != _path_identity(operation.canonical_path):
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM path changed: {operation.legacy_file_path}"
        )

    canonical = _canonical(operation.canonical_path)
    before = _stat_identity(canonical)
    if before[0] != operation.size_bytes:
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM changed size: {operation.legacy_file_path}"
        )
    if before[1] != operation.source_mtime_ns:
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM modification time changed: {operation.legacy_file_path}"
        )

    digest = hashlib.sha256()
    try:
        with canonical.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM could not be hashed: {operation.legacy_file_path}: {error}"
        ) from error

    after = _stat_identity(canonical)
    if before != after:
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM changed while being verified: {operation.legacy_file_path}"
        )
    if digest.hexdigest() != operation.sha256:
        raise LegacyRomMetadataApplyStaleStateError(
            f"Reviewed legacy ROM bytes no longer match the frozen SHA-256: {operation.legacy_file_path}"
        )


def _validate_exact_record(
    operation: LegacyRomMetadataBackfillOperation,
    collection_data: Mapping[str, Any],
) -> None:
    record = collection_data.get(operation.collection_id)
    if not isinstance(record, Mapping):
        raise LegacyRomMetadataApplyStaleStateError(
            f"Collection record changed after modernization preview: {operation.collection_id}"
        )
    file_path = record.get("file_path")
    if file_path != operation.legacy_file_path:
        raise LegacyRomMetadataApplyStaleStateError(
            f"Legacy file_path changed after modernization preview: {operation.title}"
        )
    files = record.get("files")
    if files is not None and (not isinstance(files, list) or files):
        raise LegacyRomMetadataApplyStaleStateError(
            f"Modern files[] metadata changed after modernization preview: {operation.title}"
        )


def _validate_unique_ownership(
    plan: LegacyRomMetadataModernizationPlan,
    collection_data: Mapping[str, Any],
) -> None:
    planned = {_path_identity(op.canonical_path): op.collection_id for op in plan.operations}
    owners: dict[str, list[str]] = {}
    for raw_id, raw_record in collection_data.items():
        if not isinstance(raw_record, Mapping):
            continue
        path = raw_record.get("file_path")
        if not isinstance(path, str) or not path.strip():
            continue
        identity = _path_identity(path)
        if identity in planned:
            owners.setdefault(identity, []).append(str(raw_id))
    for identity, expected_owner in planned.items():
        if owners.get(identity) != [expected_owner]:
            raise LegacyRomMetadataApplyStaleStateError(
                "Legacy ROM path ownership changed after modernization preview. Run the audit again."
            )


def apply_legacy_rom_metadata_modernization_plan(
    plan: LegacyRomMetadataModernizationPlan,
    manager: HackDataManager,
    *,
    fail_before_replace: bool = False,
) -> LegacyRomMetadataApplyResult:
    """Apply exactly the frozen metadata rows as one atomic processed.json replacement."""
    if not isinstance(plan, LegacyRomMetadataModernizationPlan):
        raise TypeError("plan must be a LegacyRomMetadataModernizationPlan")
    if not isinstance(manager, HackDataManager):
        raise TypeError("manager must be a HackDataManager")

    if collection_revision_token(manager) != plan.collection_revision_token:
        raise LegacyRomMetadataApplyStaleStateError(
            "Collection changed after the modernization preview. Run the legacy metadata audit again."
        )

    store = HackDataManagerCollectionStore(manager)
    transaction = store.begin_transaction()
    try:
        for operation in plan.operations:
            _validate_exact_record(operation, manager.data)
        _validate_unique_ownership(plan, manager.data)
        for operation in plan.operations:
            _verify_operation_bytes(operation)
            transaction.update_record(
                operation.collection_id,
                {"files": [operation.proposed_files_row]},
            )

        # Recheck exact reviewed bytes immediately before the Collection commit.
        for operation in plan.operations:
            _verify_operation_bytes(operation)
        if collection_revision_token(manager) != plan.collection_revision_token:
            raise LegacyRomMetadataApplyStaleStateError(
                "Collection changed while preparing the metadata backfill. Run the audit again."
            )

        transaction.fail_before_replace = bool(fail_before_replace)
        transaction.commit()
    except (LegacyRomMetadataApplyError, CollectionStaleStateError):
        transaction.rollback()
        raise
    except CollectionTransactionError as error:
        transaction.rollback()
        raise LegacyRomMetadataApplyError(
            f"Collection metadata backfill transaction failed: {error}"
        ) from error
    except Exception:
        transaction.rollback()
        raise

    return LegacyRomMetadataApplyResult(collection_record_count=len(plan.operations))


__all__ = [
    "LegacyRomMetadataApplyError",
    "LegacyRomMetadataApplyResult",
    "LegacyRomMetadataApplyStaleStateError",
    "apply_legacy_rom_metadata_modernization_plan",
]
