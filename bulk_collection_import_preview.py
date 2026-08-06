"""Read-only preview planning for bulk Collection imports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping
import re

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

_IMPORT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_ENTRY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_GROUP_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_COLLECTION_KEY_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)
_SOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")
_WARNING_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SOURCE_REFERENCE_KEYS = ("source", "external_id")


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


def parse_bulk_collection_import_preview(
    document: Any,
) -> BulkCollectionImportPreviewPlan:
    """Parse and deeply detach one serialized preview plan."""

    _require_exact_mapping(
        document,
        BULK_COLLECTION_IMPORT_PREVIEW_PLAN_KEYS,
        "Bulk Collection import preview",
    )

    schema = document["schema"]
    if schema != BULK_COLLECTION_IMPORT_PREVIEW_SCHEMA:
        raise BulkCollectionImportPreviewError(
            "Unsupported bulk Collection preview schema."
        )

    version = document["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != BULK_COLLECTION_IMPORT_PREVIEW_VERSION
    ):
        raise BulkCollectionImportPreviewError(
            "Unsupported bulk Collection preview version."
        )

    import_id = _require_pattern_text(
        document["import_id"],
        _IMPORT_ID_PATTERN,
        "import_id",
    )
    title = _require_title(document["title"], "title")
    items = _parse_preview_items(document["items"])
    groups = _parse_preview_groups(document["groups"])
    summary = _parse_preview_summary(
        document["summary"],
        items,
    )
    _validate_preview_group_coverage(items, groups)

    return BulkCollectionImportPreviewPlan(
        schema=schema,
        version=version,
        import_id=import_id,
        title=title,
        summary=summary,
        items=items,
        groups=groups,
    )


def _parse_preview_items(
    value: Any,
) -> tuple[BulkCollectionImportPreviewItem, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportPreviewError(
            "items must be a JSON array."
        )

    items = []
    entry_keys = set()
    for index, item in enumerate(value):
        label = f"items[{index}]"
        _require_exact_mapping(
            item,
            BULK_COLLECTION_IMPORT_PREVIEW_ITEM_KEYS,
            label,
        )
        entry_key = _require_pattern_text(
            item["entry_key"],
            _ENTRY_KEY_PATTERN,
            f"{label}.entry_key",
        )
        if entry_key in entry_keys:
            raise BulkCollectionImportPreviewError(
                f"Duplicate preview entry_key: {entry_key}"
            )
        entry_keys.add(entry_key)

        outcome = item["outcome"]
        if outcome not in BULK_COLLECTION_IMPORT_PREVIEW_OUTCOMES:
            raise BulkCollectionImportPreviewError(
                f"{label}.outcome is unsupported."
            )
        resolution_status = item["resolution_status"]
        expected_outcome = _STATUS_TO_OUTCOME.get(
            resolution_status
        )
        if expected_outcome != outcome:
            raise BulkCollectionImportPreviewError(
                f"{label} outcome does not match resolution status."
            )

        items.append(
            BulkCollectionImportPreviewItem(
                entry_key=entry_key,
                title=_require_title(
                    item["title"],
                    f"{label}.title",
                ),
                outcome=outcome,
                resolution_status=resolution_status,
                collection_keys=_parse_preview_collection_keys(
                    item["collection_keys"],
                    label,
                ),
                proposed_source_references=(
                    _parse_preview_source_references(
                        item["proposed_source_references"],
                        f"{label}.proposed_source_references",
                    )
                ),
                warnings=_parse_preview_warnings(
                    item["warnings"],
                    label,
                ),
            )
        )

    return tuple(items)


def _parse_preview_groups(
    value: Any,
) -> tuple[BulkCollectionImportPreviewGroup, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportPreviewError(
            "groups must be a JSON array."
        )

    groups = []
    group_keys = set()
    for index, item in enumerate(value):
        label = f"groups[{index}]"
        _require_exact_mapping(
            item,
            BULK_COLLECTION_IMPORT_PREVIEW_GROUP_KEYS,
            label,
        )
        group_key = _require_pattern_text(
            item["group_key"],
            _GROUP_KEY_PATTERN,
            f"{label}.group_key",
        )
        if group_key in group_keys:
            raise BulkCollectionImportPreviewError(
                f"Duplicate preview group_key: {group_key}"
            )
        group_keys.add(group_key)

        entry_keys_value = item["entry_keys"]
        if not isinstance(entry_keys_value, list):
            raise BulkCollectionImportPreviewError(
                f"{label}.entry_keys must be a JSON array."
            )
        entry_keys = tuple(
            _require_pattern_text(
                entry_key,
                _ENTRY_KEY_PATTERN,
                f"{label}.entry_keys[{entry_index}]",
            )
            for entry_index, entry_key in enumerate(
                entry_keys_value
            )
        )
        groups.append(
            BulkCollectionImportPreviewGroup(
                group_key=group_key,
                title=_require_title(
                    item["title"],
                    f"{label}.title",
                ),
                entry_keys=entry_keys,
            )
        )

    return tuple(groups)


def _parse_preview_summary(
    value: Any,
    items: tuple[BulkCollectionImportPreviewItem, ...],
) -> Mapping[str, int]:
    _require_exact_mapping(
        value,
        BULK_COLLECTION_IMPORT_PREVIEW_SUMMARY_KEYS,
        "summary",
    )
    counts = {
        outcome: sum(item.outcome == outcome for item in items)
        for outcome in BULK_COLLECTION_IMPORT_PREVIEW_OUTCOMES
    }
    expected = {
        "total": len(items),
        "add_new": counts["add_new"],
        "match_existing": counts["match_existing"],
        "review_required": counts["review_required"],
    }

    for key, expected_value in expected.items():
        actual = value[key]
        if (
            isinstance(actual, bool)
            or not isinstance(actual, int)
            or actual < 0
            or actual != expected_value
        ):
            raise BulkCollectionImportPreviewError(
                f"summary.{key} does not match preview items."
            )

    return MappingProxyType(expected)


def _parse_preview_collection_keys(
    value: Any,
    item_label: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportPreviewError(
            f"{item_label}.collection_keys must be a JSON array."
        )

    keys = []
    seen = set()
    for index, item in enumerate(value):
        key = _require_pattern_text(
            item,
            _COLLECTION_KEY_PATTERN,
            f"{item_label}.collection_keys[{index}]",
        )
        if key in seen:
            raise BulkCollectionImportPreviewError(
                f"{item_label}.collection_keys contains a duplicate."
            )
        seen.add(key)
        keys.append(key)
    return tuple(keys)


def _parse_preview_source_references(
    value: Any,
    label: str,
) -> tuple[BulkCollectionImportSourceReference, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportPreviewError(
            f"{label} must be a JSON array."
        )

    references = []
    seen = set()
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        _require_exact_mapping(
            item,
            _SOURCE_REFERENCE_KEYS,
            item_label,
        )
        source = _require_pattern_text(
            item["source"],
            _SOURCE_PATTERN,
            f"{item_label}.source",
        )
        external_id = _require_external_id(
            item["external_id"],
            f"{item_label}.external_id",
        )
        key = (source, external_id)
        if key in seen:
            raise BulkCollectionImportPreviewError(
                f"{label} contains a duplicate source reference."
            )
        seen.add(key)
        references.append(
            BulkCollectionImportSourceReference(
                source=source,
                external_id=external_id,
            )
        )
    return tuple(references)


def _parse_preview_warnings(
    value: Any,
    item_label: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportPreviewError(
            f"{item_label}.warnings must be a JSON array."
        )

    warnings = []
    seen = set()
    for index, warning in enumerate(value):
        if (
            not isinstance(warning, str)
            or _WARNING_PATTERN.fullmatch(warning) is None
        ):
            raise BulkCollectionImportPreviewError(
                f"{item_label}.warnings[{index}] is invalid."
            )
        if warning in seen:
            raise BulkCollectionImportPreviewError(
                f"{item_label}.warnings contains a duplicate."
            )
        seen.add(warning)
        warnings.append(warning)
    return tuple(warnings)


def _validate_preview_group_coverage(
    items: tuple[BulkCollectionImportPreviewItem, ...],
    groups: tuple[BulkCollectionImportPreviewGroup, ...],
) -> None:
    expected = {item.entry_key for item in items}
    seen = set()
    for group in groups:
        for entry_key in group.entry_keys:
            if entry_key not in expected:
                raise BulkCollectionImportPreviewError(
                    "Preview group references an unknown entry_key."
                )
            if entry_key in seen:
                raise BulkCollectionImportPreviewError(
                    "Preview entry appears more than once in groups."
                )
            seen.add(entry_key)

    if seen != expected:
        raise BulkCollectionImportPreviewError(
            "Every preview item must appear exactly once in groups."
        )


def _require_exact_mapping(
    value: Any,
    expected_keys: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(value, dict):
        raise BulkCollectionImportPreviewError(
            f"{label} must be a JSON object."
        )
    expected = set(expected_keys)
    actual = set(value)
    if actual == expected:
        return

    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unexpected:
        details.append("unexpected: " + ", ".join(unexpected))
    raise BulkCollectionImportPreviewError(
        f"{label} fields must match the preview contract "
        f"({'; '.join(details)})."
    )


def _require_pattern_text(
    value: Any,
    pattern: re.Pattern[str],
    label: str,
) -> str:
    if (
        not isinstance(value, str)
        or pattern.fullmatch(value) is None
    ):
        raise BulkCollectionImportPreviewError(
            f"{label} has an invalid identifier format."
        )
    return value


def _require_title(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 512
    ):
        raise BulkCollectionImportPreviewError(
            f"{label} must be a non-empty trimmed string "
            "of at most 512 characters."
        )
    return value


def _require_external_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
        or len(value) > 256
    ):
        raise BulkCollectionImportPreviewError(
            f"{label} must be a non-empty non-whitespace "
            "string of at most 256 characters."
        )
    return value


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
    "parse_bulk_collection_import_preview",
    "build_bulk_collection_import_preview",
    "bulk_collection_import_preview_to_document",
    "serialize_bulk_collection_import_preview",
]
