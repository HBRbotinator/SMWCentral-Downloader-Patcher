"""Transactional metadata-only repair for reviewed modern ROM provenance decisions."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from typing import Any, Mapping

from collection_plan_apply import collection_revision_token
from collection_rom_modern_provenance_review import (
    ModernRomProvenanceDecision,
    ModernRomProvenanceReview,
    ModernRomProvenanceReviewError,
)
from collection_rom_provenance_history import recorded_collection_smwc_submission_ids
from collection_transaction import (
    CollectionStaleStateError,
    CollectionTransactionError,
    HackDataManagerCollectionStore,
)
from hack_data_manager import HackDataManager


class ModernRomProvenanceApplyError(RuntimeError):
    """Raised when reviewed modern provenance cannot be repaired safely."""


class ModernRomProvenanceApplyStaleStateError(ModernRomProvenanceApplyError):
    """Raised when Collection/files[] state changed after provenance review."""


@dataclass(frozen=True)
class ModernRomProvenanceApplyResult:
    collection_record_count: int
    asset_count: int


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _path_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(_absolute(path)))


def _selection_map(decision: ModernRomProvenanceDecision) -> dict[tuple[str, str], int]:
    return {(collection_id, _path_identity(path)): sid for collection_id, path, sid in decision.selections}


def apply_modern_rom_provenance_decision(
    review: ModernRomProvenanceReview,
    decision: ModernRomProvenanceDecision,
    manager: HackDataManager,
    *,
    fail_before_replace: bool = False,
) -> ModernRomProvenanceApplyResult:
    """Atomically write only reviewed missing per-ROM ``smwc_submission_id`` values."""
    if not isinstance(review, ModernRomProvenanceReview):
        raise TypeError("review must be a ModernRomProvenanceReview")
    if not isinstance(decision, ModernRomProvenanceDecision):
        raise TypeError("decision must be a ModernRomProvenanceDecision")
    if not isinstance(manager, HackDataManager):
        raise TypeError("manager must be a HackDataManager")
    if decision.collection_revision_token != review.collection_revision_token:
        raise ModernRomProvenanceApplyStaleStateError(
            "The saved provenance decision does not belong to the active review."
        )
    if collection_revision_token(manager) != review.collection_revision_token:
        raise ModernRomProvenanceApplyStaleStateError(
            "Collection changed after the provenance review. Run the ROM organization audit again."
        )

    selections = _selection_map(decision)
    expected_keys = {(row.collection_id, _path_identity(row.current_path)) for row in review.rows}
    if set(selections) != expected_keys:
        raise ModernRomProvenanceApplyStaleStateError(
            "The saved provenance decisions no longer match the reviewed ROM asset set."
        )

    updates: dict[str, list[dict[str, Any]]] = {}
    updated_assets = 0
    for row in review.rows:
        record = manager.data.get(row.collection_id)
        if not isinstance(record, Mapping):
            raise ModernRomProvenanceApplyStaleStateError(
                f"Collection record changed after provenance review: {row.collection_id}"
            )
        selected = selections[(row.collection_id, _path_identity(row.current_path))]
        if selected not in recorded_collection_smwc_submission_ids(row.collection_id, record):
            raise ModernRomProvenanceApplyStaleStateError(
                f"Selected SMWC provenance is no longer recorded for {row.title!r}."
            )
        raw_files = updates.get(row.collection_id, record.get("files"))
        if not isinstance(raw_files, list):
            raise ModernRomProvenanceApplyStaleStateError(
                f"Modern files[] metadata changed after provenance review: {row.title}"
            )
        files = copy.deepcopy(raw_files)
        matches = []
        for index, asset in enumerate(files):
            if not isinstance(asset, Mapping):
                continue
            path = asset.get("path")
            if isinstance(path, str) and path.strip() and _path_identity(path) == _path_identity(row.current_path):
                matches.append((index, asset))
        if len(matches) != 1:
            raise ModernRomProvenanceApplyStaleStateError(
                f"ROM asset ownership changed after provenance review: {row.asset_name}"
            )
        index, asset = matches[0]
        if asset.get("smwc_submission_id") is not None:
            raise ModernRomProvenanceApplyStaleStateError(
                f"ROM provenance changed after provenance review: {row.asset_name}"
            )
        if (
            bool(asset.get("primary")) != row.primary
            or str(asset.get("sha256", "") or "") != row.sha256
            or asset.get("size_bytes") != row.size_bytes
        ):
            raise ModernRomProvenanceApplyStaleStateError(
                f"ROM asset metadata changed after provenance review: {row.asset_name}"
            )
        updated = dict(asset)
        updated["smwc_submission_id"] = selected
        files[index] = updated
        updates[row.collection_id] = files
        updated_assets += 1

    store = HackDataManagerCollectionStore(manager)
    transaction = store.begin_transaction()
    try:
        for collection_id, files in updates.items():
            transaction.update_record(collection_id, {"files": files})
        if collection_revision_token(manager) != review.collection_revision_token:
            raise ModernRomProvenanceApplyStaleStateError(
                "Collection changed while preparing provenance repair. Run the audit again."
            )
        transaction.fail_before_replace = bool(fail_before_replace)
        transaction.commit()
    except (ModernRomProvenanceApplyError, CollectionStaleStateError):
        transaction.rollback()
        raise
    except CollectionTransactionError as error:
        transaction.rollback()
        raise ModernRomProvenanceApplyError(
            f"Collection provenance repair transaction failed: {error}"
        ) from error
    except Exception:
        transaction.rollback()
        raise

    return ModernRomProvenanceApplyResult(
        collection_record_count=len(updates),
        asset_count=updated_assets,
    )


__all__ = [
    "ModernRomProvenanceApplyError",
    "ModernRomProvenanceApplyResult",
    "ModernRomProvenanceApplyStaleStateError",
    "apply_modern_rom_provenance_decision",
]
