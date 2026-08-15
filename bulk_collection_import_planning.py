"""Read-only orchestration for bulk Collection import planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from bulk_collection_import import BulkCollectionImportDocument
from bulk_collection_import_identity import (
    BulkCollectionIdentityPlan,
    resolve_bulk_collection_identities,
)
from bulk_collection_import_json import (
    BulkCollectionImportJsonLoadResult,
    load_bulk_collection_import_json,
)
from bulk_collection_import_merge import (
    BulkCollectionImportMergePlan,
    build_bulk_collection_import_merge_plan,
)
from bulk_collection_import_preview import (
    BulkCollectionImportPreviewPlan,
    build_bulk_collection_import_preview,
)


BULK_COLLECTION_IMPORT_PLANNING_STAGES = (
    "load",
    "identity",
    "preview",
    "merge",
)


class BulkCollectionImportPlanningError(ValueError):
    """Raised when one named planning stage cannot complete."""

    def __init__(self, stage: str, message: str):
        if stage not in BULK_COLLECTION_IMPORT_PLANNING_STAGES:
            raise ValueError(
                "Bulk Collection import planning stage is invalid."
            )
        self.stage = stage
        super().__init__(
            f"Bulk Collection import planning failed during "
            f"{stage}: {message}"
        )


@dataclass(frozen=True, slots=True)
class BulkCollectionImportPlanningSession:
    """Detached immutable result of one read-only planning pass."""

    source_name: str
    byte_count: int
    sha256: str
    document: BulkCollectionImportDocument
    identity_plan: BulkCollectionIdentityPlan
    preview_plan: BulkCollectionImportPreviewPlan
    merge_plan: BulkCollectionImportMergePlan


def plan_bulk_collection_import_file(
    path: str | Path,
    collection_identities: Sequence[Mapping[str, Any]],
    collection_records: Sequence[Mapping[str, Any]],
) -> BulkCollectionImportPlanningSession:
    """Compose load, identity, preview, and merge planning stages."""

    loaded = _run_stage(
        "load",
        lambda: load_bulk_collection_import_json(path),
    )
    identity_plan = _run_stage(
        "identity",
        lambda: resolve_bulk_collection_identities(
            loaded.document,
            collection_identities,
        ),
    )
    preview_plan = _run_stage(
        "preview",
        lambda: build_bulk_collection_import_preview(
            loaded.document,
            identity_plan,
        ),
    )
    matched_records = _run_stage(
        "merge",
        lambda: _select_matched_collection_records(
            preview_plan,
            collection_records,
        ),
    )
    merge_plan = _run_stage(
        "merge",
        lambda: build_bulk_collection_import_merge_plan(
            loaded.document,
            preview_plan,
            matched_records,
        ),
    )

    return _build_session(
        loaded,
        identity_plan,
        preview_plan,
        merge_plan,
    )


def _select_matched_collection_records(
    preview_plan: BulkCollectionImportPreviewPlan,
    collection_records: Sequence[Mapping[str, Any]],
) -> tuple[Mapping[str, Any], ...]:
    """Select only records required by match_existing preview items."""

    if (
        isinstance(
            collection_records,
            (str, bytes, bytearray),
        )
        or not isinstance(collection_records, Sequence)
    ):
        raise TypeError(
            "collection_records must be a sequence."
        )

    required_keys = {
        item.collection_keys[0]
        for item in preview_plan.items
        if item.outcome == "match_existing"
    }
    if not required_keys:
        return ()

    selected = []
    for record in collection_records:
        if not isinstance(record, Mapping):
            continue
        collection_key = record.get("collection_key")
        if collection_key in required_keys:
            selected.append(record)

    return tuple(selected)


def _run_stage(stage: str, operation: Any) -> Any:
    try:
        return operation()
    except BulkCollectionImportPlanningError:
        raise
    except Exception as error:
        raise BulkCollectionImportPlanningError(
            stage,
            str(error) or error.__class__.__name__,
        ) from error


def _build_session(
    loaded: BulkCollectionImportJsonLoadResult,
    identity_plan: BulkCollectionIdentityPlan,
    preview_plan: BulkCollectionImportPreviewPlan,
    merge_plan: BulkCollectionImportMergePlan,
) -> BulkCollectionImportPlanningSession:
    return BulkCollectionImportPlanningSession(
        source_name=loaded.source_name,
        byte_count=loaded.byte_count,
        sha256=loaded.sha256,
        document=loaded.document,
        identity_plan=identity_plan,
        preview_plan=preview_plan,
        merge_plan=merge_plan,
    )


__all__ = [
    "BULK_COLLECTION_IMPORT_PLANNING_STAGES",
    "BulkCollectionImportPlanningError",
    "BulkCollectionImportPlanningSession",
    "plan_bulk_collection_import_file",
]
