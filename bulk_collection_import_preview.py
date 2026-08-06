"""Read-only preview planning for bulk Collection imports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping

from bulk_collection_import import (
    BulkCollectionImportDocument,
    BulkCollectionImportSourceReference,
)
from bulk_collection_import_identity import (
    BulkCollectionIdentityPlan,
    BulkCollectionIdentityResolution,
)


BULK_COLLECTION_IMPORT_PREVIEW_SCHEMA = (
    "smwc-bulk-collection-preview-plan"
)
BULK_COLLECTION_IMPORT_PREVIEW_VERSION = 1

BULK_COLLECTION_IMPORT_PREVIEW_OUTCOMES = (
    "add_new",
    "match_existing",
    "review_required",
)

BULK_COLLECTION_IMPORT_PREVIEW_PLAN_KEYS = (
    "schema",
    "version",
    "import_id",
    "title",
    "summary",
    "items",
    "groups",
)
BULK_COLLECTION_IMPORT_PREVIEW_SUMMARY_KEYS = (
    "total",
    "add_new",
    "match_existing",
    "review_required",
)
BULK_COLLECTION_IMPORT_PREVIEW_ITEM_KEYS = (
    "entry_key",
    "title",
    "outcome",
    "resolution_status",
    "collection_keys",
    "proposed_source_references",
    "warnings",
)
BULK_COLLECTION_IMPORT_PREVIEW_GROUP_KEYS = (
    "group_key",
    "title",
    "entry_keys",
)

_STATUS_TO_OUTCOME = {
    "matched_source": "match_existing",
    "matched_metadata": "match_existing",
    "new": "add_new",
    "ambiguous": "review_required",
    "conflict": "review_required",
}


class BulkCollectionImportPreviewError(ValueError):
    """Raised when an identity plan cannot safely form a preview."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportPreviewItem:
    """One immutable row in an import preview."""

    entry_key: str
    title: str
    outcome: str
    resolution_status: str
    collection_keys: tuple[str, ...]
    proposed_source_references: tuple[
        BulkCollectionImportSourceReference,
        ...,
    ]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportPreviewGroup:
    """One imported display group in the preview."""

    group_key: str
    title: str
    entry_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportPreviewPlan:
    """Detached immutable preview for one import document."""

    schema: str
    version: int
    import_id: str
    title: str
    summary: Mapping[str, int]
    items: tuple[BulkCollectionImportPreviewItem, ...]
    groups: tuple[BulkCollectionImportPreviewGroup, ...]


def build_bulk_collection_import_preview(
    import_document: BulkCollectionImportDocument,
    identity_plan: BulkCollectionIdentityPlan,
) -> BulkCollectionImportPreviewPlan:
    """Build a validated read-only preview from an identity plan."""

    if not isinstance(
        import_document,
        BulkCollectionImportDocument,
    ):
        raise TypeError(
            "import_document must be a BulkCollectionImportDocument"
        )
    if not isinstance(identity_plan, BulkCollectionIdentityPlan):
        raise TypeError(
            "identity_plan must be a BulkCollectionIdentityPlan"
        )
    if import_document.import_id != identity_plan.import_id:
        raise BulkCollectionImportPreviewError(
            "The import document and identity plan use different "
            "import_id values."
        )
    if len(import_document.entries) != len(
        identity_plan.resolutions
    ):
        raise BulkCollectionImportPreviewError(
            "The identity plan must contain exactly one resolution "
            "for every imported entry."
        )

    items = []
    for entry, resolution in zip(
        import_document.entries,
        identity_plan.resolutions,
        strict=True,
    ):
        if entry.entry_key != resolution.entry_key:
            raise BulkCollectionImportPreviewError(
                "Identity resolutions must follow imported entry "
                "order and keys exactly."
            )
        _validate_resolution_semantics(entry, resolution)
        items.append(
            BulkCollectionImportPreviewItem(
                entry_key=entry.entry_key,
                title=entry.title,
                outcome=_STATUS_TO_OUTCOME[
                    resolution.status
                ],
                resolution_status=resolution.status,
                collection_keys=tuple(
                    resolution.collection_keys
                ),
                proposed_source_references=tuple(
                    resolution.proposed_source_references
                ),
                warnings=tuple(resolution.warnings),
            )
        )

    counts = {
        outcome: sum(
            item.outcome == outcome
            for item in items
        )
        for outcome in BULK_COLLECTION_IMPORT_PREVIEW_OUTCOMES
    }
    summary = MappingProxyType(
        {
            "total": len(items),
            "add_new": counts["add_new"],
            "match_existing": counts["match_existing"],
            "review_required": counts["review_required"],
        }
    )
    groups = tuple(
        BulkCollectionImportPreviewGroup(
            group_key=group.group_key,
            title=group.title,
            entry_keys=tuple(group.entry_keys),
        )
        for group in import_document.groups
    )

    return BulkCollectionImportPreviewPlan(
        schema=BULK_COLLECTION_IMPORT_PREVIEW_SCHEMA,
        version=BULK_COLLECTION_IMPORT_PREVIEW_VERSION,
        import_id=import_document.import_id,
        title=import_document.title,
        summary=summary,
        items=tuple(items),
        groups=groups,
    )


def bulk_collection_import_preview_to_document(
    preview: BulkCollectionImportPreviewPlan,
) -> dict[str, Any]:
    """Project a preview to a detached canonical document."""

    if not isinstance(
        preview,
        BulkCollectionImportPreviewPlan,
    ):
        raise TypeError(
            "preview must be a BulkCollectionImportPreviewPlan"
        )

    return {
        "schema": preview.schema,
        "version": preview.version,
        "import_id": preview.import_id,
        "title": preview.title,
        "summary": {
            key: preview.summary[key]
            for key
            in BULK_COLLECTION_IMPORT_PREVIEW_SUMMARY_KEYS
        },
        "items": [
            {
                "entry_key": item.entry_key,
                "title": item.title,
                "outcome": item.outcome,
                "resolution_status": item.resolution_status,
                "collection_keys": list(
                    item.collection_keys
                ),
                "proposed_source_references": [
                    {
                        "source": reference.source,
                        "external_id": reference.external_id,
                    }
                    for reference
                    in item.proposed_source_references
                ],
                "warnings": list(item.warnings),
            }
            for item in preview.items
        ],
        "groups": [
            {
                "group_key": group.group_key,
                "title": group.title,
                "entry_keys": list(group.entry_keys),
            }
            for group in preview.groups
        ],
    }


def serialize_bulk_collection_import_preview(
    preview: BulkCollectionImportPreviewPlan,
) -> str:
    """Serialize a preview as deterministic compact JSON."""

    return json.dumps(
        bulk_collection_import_preview_to_document(preview),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _validate_resolution_semantics(
    entry: Any,
    resolution: BulkCollectionIdentityResolution,
) -> None:
    status = resolution.status
    collection_count = len(resolution.collection_keys)
    proposed_count = len(
        resolution.proposed_source_references
    )

    if status in {"matched_source", "matched_metadata"}:
        if collection_count != 1:
            raise BulkCollectionImportPreviewError(
                f"{status} must identify exactly one Collection "
                "record."
            )
    elif status == "new":
        if collection_count != 0:
            raise BulkCollectionImportPreviewError(
                "new must not identify a Collection record."
            )
    elif status in {"ambiguous", "conflict"}:
        if collection_count == 0:
            raise BulkCollectionImportPreviewError(
                f"{status} must expose at least one review "
                "candidate."
            )
    else:
        raise BulkCollectionImportPreviewError(
            f"Unsupported identity resolution status: {status}"
        )

    if proposed_count and status != "matched_source":
        raise BulkCollectionImportPreviewError(
            "Proposed source references are only valid for "
            "matched_source."
        )

    imported_references = {
        (reference.source, reference.external_id)
        for reference in entry.source_references
    }
    matched_references = {
        (reference.source, reference.external_id)
        for reference in resolution.matched_source_references
    }
    proposed_references = {
        (reference.source, reference.external_id)
        for reference in resolution.proposed_source_references
    }

    if not matched_references.issubset(imported_references):
        raise BulkCollectionImportPreviewError(
            "Matched source references must belong to the "
            "imported entry."
        )
    if not proposed_references.issubset(imported_references):
        raise BulkCollectionImportPreviewError(
            "Proposed source references must belong to the "
            "imported entry."
        )
    if matched_references & proposed_references:
        raise BulkCollectionImportPreviewError(
            "A source reference cannot be both matched and "
            "proposed."
        )

    if status == "matched_source" and not matched_references:
        raise BulkCollectionImportPreviewError(
            "matched_source requires a matched source reference."
        )
    if status in {
        "matched_metadata",
        "new",
        "ambiguous",
    } and matched_references:
        raise BulkCollectionImportPreviewError(
            f"{status} must not contain matched source "
            "references."
        )


__all__ = [
    "BULK_COLLECTION_IMPORT_PREVIEW_SCHEMA",
    "BULK_COLLECTION_IMPORT_PREVIEW_VERSION",
    "BULK_COLLECTION_IMPORT_PREVIEW_OUTCOMES",
    "BULK_COLLECTION_IMPORT_PREVIEW_PLAN_KEYS",
    "BULK_COLLECTION_IMPORT_PREVIEW_SUMMARY_KEYS",
    "BULK_COLLECTION_IMPORT_PREVIEW_ITEM_KEYS",
    "BULK_COLLECTION_IMPORT_PREVIEW_GROUP_KEYS",
    "BulkCollectionImportPreviewError",
    "BulkCollectionImportPreviewItem",
    "BulkCollectionImportPreviewGroup",
    "BulkCollectionImportPreviewPlan",
    "build_bulk_collection_import_preview",
    "bulk_collection_import_preview_to_document",
    "serialize_bulk_collection_import_preview",
]
