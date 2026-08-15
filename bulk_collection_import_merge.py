"""Conservative read-only merge planning for bulk Collection imports."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from bulk_collection_import import (
    BulkCollectionImportDocument,
    BulkCollectionImportSourceReference,
)
from bulk_collection_import_preview import (
    BulkCollectionImportPreviewPlan,
)


BULK_COLLECTION_IMPORT_MERGE_SCHEMA = (
    "smwc-bulk-collection-merge-plan"
)
BULK_COLLECTION_IMPORT_MERGE_VERSION = 1

BULK_COLLECTION_IMPORT_MERGE_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "review_required",
)
BULK_COLLECTION_IMPORT_MERGE_VALUE_ACTIONS = (
    "set_new",
    "add_missing",
    "unchanged",
    "review_conflict",
)

BULK_COLLECTION_IMPORT_IDENTITY_REVIEW_REQUIRED_WARNING = (
    "identity_review_required"
)
BULK_COLLECTION_IMPORT_IDENTITY_AMBIGUOUS_WARNING = (
    "identity_ambiguous"
)
BULK_COLLECTION_IMPORT_IDENTITY_CONFLICT_WARNING = (
    "identity_conflict"
)
BULK_COLLECTION_IMPORT_HARD_IDENTITY_CONFLICT_WARNINGS = (
    "source_identity_conflict",
    "duplicate_import_target",
)

BULK_COLLECTION_IMPORT_MERGE_PLAN_KEYS = (
    "schema",
    "version",
    "import_id",
    "summary",
    "items",
    "groups",
)
BULK_COLLECTION_IMPORT_MERGE_SUMMARY_KEYS = (
    "total",
    "create_record",
    "update_record",
    "no_change",
    "review_required",
)
BULK_COLLECTION_IMPORT_MERGE_ITEM_KEYS = (
    "entry_key",
    "action",
    "collection_keys",
    "title_decision",
    "source_reference_additions",
    "attribute_decisions",
    "warnings",
)
BULK_COLLECTION_IMPORT_MERGE_VALUE_DECISION_KEYS = (
    "field",
    "action",
    "existing_value",
    "imported_value",
)
BULK_COLLECTION_IMPORT_MERGE_GROUP_KEYS = (
    "group_key",
    "title",
    "entry_keys",
)

_COLLECTION_RECORD_KEYS = (
    "collection_key",
    "title",
    "source_references",
    "attributes",
    "user_state",
)
_SOURCE_REFERENCE_KEYS = ("source", "external_id")
_COLLECTION_KEY_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)
_SOURCE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,31}$")


class BulkCollectionImportMergeError(ValueError):
    """Raised when a conservative merge plan cannot be built."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportMergeValueDecision:
    """One immutable shared-metadata value decision."""

    field: str
    action: str
    existing_value: Any
    imported_value: Any


@dataclass(frozen=True, slots=True)
class BulkCollectionImportMergeItem:
    """One immutable merge decision for an imported entry."""

    entry_key: str
    action: str
    collection_keys: tuple[str, ...]
    title_decision: BulkCollectionImportMergeValueDecision | None
    source_reference_additions: tuple[
        BulkCollectionImportSourceReference,
        ...,
    ]
    attribute_decisions: tuple[
        BulkCollectionImportMergeValueDecision,
        ...,
    ]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportMergeGroup:
    """One destination-neutral imported group."""

    group_key: str
    title: str
    entry_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportMergePlan:
    """Detached immutable conservative merge plan."""

    schema: str
    version: int
    import_id: str
    summary: Mapping[str, int]
    items: tuple[BulkCollectionImportMergeItem, ...]
    groups: tuple[BulkCollectionImportMergeGroup, ...]


@dataclass(frozen=True, slots=True)
class _CollectionRecord:
    collection_key: str
    title: str
    source_references: tuple[
        BulkCollectionImportSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]


def build_bulk_collection_import_merge_plan(
    import_document: BulkCollectionImportDocument,
    preview: BulkCollectionImportPreviewPlan,
    collection_records: Sequence[Mapping[str, Any]],
) -> BulkCollectionImportMergePlan:
    """Build a conservative merge plan without modifying inputs."""

    if not isinstance(
        import_document,
        BulkCollectionImportDocument,
    ):
        raise TypeError(
            "import_document must be a BulkCollectionImportDocument"
        )
    if not isinstance(
        preview,
        BulkCollectionImportPreviewPlan,
    ):
        raise TypeError(
            "preview must be a BulkCollectionImportPreviewPlan"
        )

    _validate_preview_correspondence(import_document, preview)
    records = _parse_collection_records(collection_records)
    required_keys = {
        item.collection_keys[0]
        for item in preview.items
        if item.outcome == "match_existing"
    }
    actual_keys = {record.collection_key for record in records}
    if actual_keys != required_keys:
        raise BulkCollectionImportMergeError(
            "Collection records must exactly cover matched preview "
            "targets and no others."
        )
    record_index = {
        record.collection_key: record
        for record in records
    }

    items = []
    for entry, preview_item in zip(
        import_document.entries,
        preview.items,
        strict=True,
    ):
        if preview_item.outcome == "review_required":
            items.append(
                _build_identity_review_item(preview_item)
            )
        elif preview_item.outcome == "add_new":
            items.append(_build_new_item(entry, preview_item))
        elif preview_item.outcome == "match_existing":
            record = record_index[
                preview_item.collection_keys[0]
            ]
            items.append(
                _build_matched_item(
                    entry,
                    preview_item,
                    record,
                )
            )
        else:
            raise BulkCollectionImportMergeError(
                "Unsupported preview outcome."
            )

    counts = {
        action: sum(item.action == action for item in items)
        for action in BULK_COLLECTION_IMPORT_MERGE_ACTIONS
    }
    summary = MappingProxyType(
        {
            "total": len(items),
            "create_record": counts["create_record"],
            "update_record": counts["update_record"],
            "no_change": counts["no_change"],
            "review_required": counts["review_required"],
        }
    )
    groups = tuple(
        BulkCollectionImportMergeGroup(
            group_key=group.group_key,
            title=group.title,
            entry_keys=tuple(group.entry_keys),
        )
        for group in import_document.groups
    )

    return BulkCollectionImportMergePlan(
        schema=BULK_COLLECTION_IMPORT_MERGE_SCHEMA,
        version=BULK_COLLECTION_IMPORT_MERGE_VERSION,
        import_id=import_document.import_id,
        summary=summary,
        items=tuple(items),
        groups=groups,
    )


def bulk_collection_import_merge_plan_to_document(
    plan: BulkCollectionImportMergePlan,
) -> dict[str, Any]:
    """Project a merge plan to a detached canonical document."""

    if not isinstance(
        plan,
        BulkCollectionImportMergePlan,
    ):
        raise TypeError(
            "plan must be a BulkCollectionImportMergePlan"
        )

    return {
        "schema": plan.schema,
        "version": plan.version,
        "import_id": plan.import_id,
        "summary": {
            key: plan.summary[key]
            for key in BULK_COLLECTION_IMPORT_MERGE_SUMMARY_KEYS
        },
        "items": [
            {
                "entry_key": item.entry_key,
                "action": item.action,
                "collection_keys": list(item.collection_keys),
                "title_decision": (
                    None
                    if item.title_decision is None
                    else _decision_to_document(
                        item.title_decision
                    )
                ),
                "source_reference_additions": [
                    {
                        "source": reference.source,
                        "external_id": reference.external_id,
                    }
                    for reference
                    in item.source_reference_additions
                ],
                "attribute_decisions": [
                    _decision_to_document(decision)
                    for decision in item.attribute_decisions
                ],
                "warnings": list(item.warnings),
            }
            for item in plan.items
        ],
        "groups": [
            {
                "group_key": group.group_key,
                "title": group.title,
                "entry_keys": list(group.entry_keys),
            }
            for group in plan.groups
        ],
    }


def serialize_bulk_collection_import_merge_plan(
    plan: BulkCollectionImportMergePlan,
) -> str:
    """Serialize a merge plan as deterministic compact JSON."""

    return json.dumps(
        bulk_collection_import_merge_plan_to_document(plan),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def bulk_collection_import_identity_review_warnings(
    resolution_status: str,
    preview_warnings: Sequence[str],
) -> tuple[str, ...]:
    """Preserve the reason and source warnings for identity review."""

    if resolution_status == "ambiguous":
        reason = (
            BULK_COLLECTION_IMPORT_IDENTITY_AMBIGUOUS_WARNING
        )
    elif resolution_status == "conflict":
        reason = (
            BULK_COLLECTION_IMPORT_IDENTITY_CONFLICT_WARNING
        )
    else:
        raise BulkCollectionImportMergeError(
            "Identity review requires ambiguous or conflict status."
        )

    if (
        isinstance(preview_warnings, (str, bytes, bytearray))
        or not isinstance(preview_warnings, Sequence)
    ):
        raise BulkCollectionImportMergeError(
            "Identity review warnings must be a sequence."
        )

    warnings = [
        BULK_COLLECTION_IMPORT_IDENTITY_REVIEW_REQUIRED_WARNING,
        reason,
    ]
    for warning in preview_warnings:
        if not isinstance(warning, str) or not warning:
            raise BulkCollectionImportMergeError(
                "Identity review warning codes must be "
                "non-empty strings."
            )
        if warning not in warnings:
            warnings.append(warning)

    hard_conflicts = {
        warning
        for warning in warnings
        if warning
        in BULK_COLLECTION_IMPORT_HARD_IDENTITY_CONFLICT_WARNINGS
    }
    if resolution_status == "ambiguous" and hard_conflicts:
        raise BulkCollectionImportMergeError(
            "Ambiguous identity review cannot contain a hard "
            "identity-conflict warning."
        )
    if resolution_status == "conflict" and not hard_conflicts:
        raise BulkCollectionImportMergeError(
            "Conflicting identity review requires a known hard "
            "identity-conflict warning."
        )

    return tuple(warnings)


def _build_identity_review_item(
    preview_item: Any,
) -> BulkCollectionImportMergeItem:
    return BulkCollectionImportMergeItem(
        entry_key=preview_item.entry_key,
        action="review_required",
        collection_keys=tuple(
            preview_item.collection_keys
        ),
        title_decision=None,
        source_reference_additions=(),
        attribute_decisions=(),
        warnings=bulk_collection_import_identity_review_warnings(
            preview_item.resolution_status,
            preview_item.warnings,
        ),
    )


def _build_new_item(
    entry: Any,
    preview_item: Any,
) -> BulkCollectionImportMergeItem:
    return BulkCollectionImportMergeItem(
        entry_key=entry.entry_key,
        action="create_record",
        collection_keys=(),
        title_decision=BulkCollectionImportMergeValueDecision(
            field="title",
            action="set_new",
            existing_value=None,
            imported_value=entry.title,
        ),
        source_reference_additions=tuple(
            entry.source_references
        ),
        attribute_decisions=tuple(
            BulkCollectionImportMergeValueDecision(
                field=field,
                action="set_new",
                existing_value=None,
                imported_value=_freeze_json(
                    value,
                    f"entry {entry.entry_key}.{field}",
                ),
            )
            for field, value in entry.attributes.items()
        ),
        warnings=tuple(preview_item.warnings),
    )


def _build_matched_item(
    entry: Any,
    preview_item: Any,
    record: _CollectionRecord,
) -> BulkCollectionImportMergeItem:
    title_decision = _compare_value(
        "title",
        record.title,
        entry.title,
    )
    attribute_decisions = tuple(
        _compare_attribute(
            field,
            record.attributes,
            imported_value,
        )
        for field, imported_value in entry.attributes.items()
    )

    existing_references = {
        (reference.source, reference.external_id)
        for reference in record.source_references
    }
    imported_references = {
        (reference.source, reference.external_id)
        for reference in entry.source_references
    }
    additions = tuple(
        reference
        for reference
        in preview_item.proposed_source_references
        if (
            reference.source,
            reference.external_id,
        )
        not in existing_references
    )
    proposed_keys = {
        (reference.source, reference.external_id)
        for reference in preview_item.proposed_source_references
    }
    if not proposed_keys.issubset(imported_references):
        raise BulkCollectionImportMergeError(
            "Proposed source additions must belong to the "
            "imported entry."
        )
    if proposed_keys & existing_references:
        raise BulkCollectionImportMergeError(
            "Preview proposed a source identity already present "
            "on the Collection record."
        )

    has_conflict = (
        title_decision.action == "review_conflict"
        or any(
            decision.action == "review_conflict"
            for decision in attribute_decisions
        )
    )
    has_update = bool(additions) or any(
        decision.action == "add_missing"
        for decision in attribute_decisions
    )

    warnings = list(preview_item.warnings)
    if has_conflict and "metadata_conflict" not in warnings:
        warnings.append("metadata_conflict")

    if has_conflict:
        action = "review_required"
    elif has_update:
        action = "update_record"
    else:
        action = "no_change"

    return BulkCollectionImportMergeItem(
        entry_key=entry.entry_key,
        action=action,
        collection_keys=(record.collection_key,),
        title_decision=title_decision,
        source_reference_additions=additions,
        attribute_decisions=attribute_decisions,
        warnings=tuple(warnings),
    )


def _compare_value(
    field: str,
    existing_value: Any,
    imported_value: Any,
) -> BulkCollectionImportMergeValueDecision:
    existing = _freeze_json(existing_value, f"{field}.existing")
    imported = _freeze_json(imported_value, f"{field}.imported")
    action = (
        "unchanged"
        if existing == imported
        else "review_conflict"
    )
    return BulkCollectionImportMergeValueDecision(
        field=field,
        action=action,
        existing_value=existing,
        imported_value=imported,
    )


def _compare_attribute(
    field: str,
    existing_attributes: Mapping[str, Any],
    imported_value: Any,
) -> BulkCollectionImportMergeValueDecision:
    imported = _freeze_json(
        imported_value,
        f"attribute {field}.imported",
    )
    if (
        field not in existing_attributes
        or existing_attributes[field] is None
    ):
        return BulkCollectionImportMergeValueDecision(
            field=field,
            action="add_missing",
            existing_value=None,
            imported_value=imported,
        )

    existing = _freeze_json(
        existing_attributes[field],
        f"attribute {field}.existing",
    )
    action = (
        "unchanged"
        if existing == imported
        else "review_conflict"
    )
    return BulkCollectionImportMergeValueDecision(
        field=field,
        action=action,
        existing_value=existing,
        imported_value=imported,
    )


def _validate_preview_correspondence(
    import_document: BulkCollectionImportDocument,
    preview: BulkCollectionImportPreviewPlan,
) -> None:
    if import_document.import_id != preview.import_id:
        raise BulkCollectionImportMergeError(
            "Preview import_id does not match the import document."
        )
    if import_document.title != preview.title:
        raise BulkCollectionImportMergeError(
            "Preview title does not match the import document."
        )
    if len(import_document.entries) != len(preview.items):
        raise BulkCollectionImportMergeError(
            "Preview item count does not match imported entries."
        )
    for entry, item in zip(
        import_document.entries,
        preview.items,
        strict=True,
    ):
        if (
            entry.entry_key != item.entry_key
            or entry.title != item.title
        ):
            raise BulkCollectionImportMergeError(
                "Preview items must exactly follow imported entries."
            )

    import_groups = tuple(
        (group.group_key, group.title, tuple(group.entry_keys))
        for group in import_document.groups
    )
    preview_groups = tuple(
        (group.group_key, group.title, tuple(group.entry_keys))
        for group in preview.groups
    )
    if import_groups != preview_groups:
        raise BulkCollectionImportMergeError(
            "Preview groups do not match imported group structure."
        )

    for item in preview.items:
        if item.outcome == "match_existing":
            if len(item.collection_keys) != 1:
                raise BulkCollectionImportMergeError(
                    "Matched preview items require exactly one "
                    "Collection target."
                )
        elif item.outcome == "add_new":
            if item.collection_keys:
                raise BulkCollectionImportMergeError(
                    "New preview items must not identify a "
                    "Collection target."
                )


def _parse_collection_records(
    value: Sequence[Mapping[str, Any]],
) -> tuple[_CollectionRecord, ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportMergeError(
            "collection_records must be a sequence."
        )

    records = []
    keys = set()
    source_owners = {}
    for index, item in enumerate(value):
        label = f"collection_records[{index}]"
        _require_exact_mapping(
            item,
            _COLLECTION_RECORD_KEYS,
            label,
        )
        collection_key = _require_pattern_text(
            item["collection_key"],
            _COLLECTION_KEY_PATTERN,
            f"{label}.collection_key",
        )
        if collection_key in keys:
            raise BulkCollectionImportMergeError(
                f"Duplicate collection_key: {collection_key}"
            )
        keys.add(collection_key)

        references = _parse_source_references(
            item["source_references"],
            label,
        )
        for reference in references:
            source_key = (
                reference.source,
                reference.external_id,
            )
            owner = source_owners.get(source_key)
            if owner is not None:
                raise BulkCollectionImportMergeError(
                    "Collection source identity belongs to more "
                    f"than one record: {owner}, {collection_key}"
                )
            source_owners[source_key] = collection_key

        attributes = item["attributes"]
        if not isinstance(attributes, dict):
            raise BulkCollectionImportMergeError(
                f"{label}.attributes must be a JSON object."
            )
        user_state = item["user_state"]
        if not isinstance(user_state, dict):
            raise BulkCollectionImportMergeError(
                f"{label}.user_state must be a JSON object."
            )
        _freeze_json(user_state, f"{label}.user_state")

        records.append(
            _CollectionRecord(
                collection_key=collection_key,
                title=_require_title(
                    item["title"],
                    f"{label}.title",
                ),
                source_references=references,
                attributes=_freeze_json(
                    attributes,
                    f"{label}.attributes",
                ),
            )
        )

    return tuple(records)


def _parse_source_references(
    value: Any,
    record_label: str,
) -> tuple[BulkCollectionImportSourceReference, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportMergeError(
            f"{record_label}.source_references must be "
            "a JSON array."
        )

    references = []
    seen = set()
    for index, item in enumerate(value):
        label = f"{record_label}.source_references[{index}]"
        _require_exact_mapping(
            item,
            _SOURCE_REFERENCE_KEYS,
            label,
        )
        source = _require_pattern_text(
            item["source"],
            _SOURCE_PATTERN,
            f"{label}.source",
        )
        external_id = _require_external_id(
            item["external_id"],
            f"{label}.external_id",
        )
        key = (source, external_id)
        if key in seen:
            raise BulkCollectionImportMergeError(
                f"{record_label} contains a duplicate source "
                "reference."
            )
        seen.add(key)
        references.append(
            BulkCollectionImportSourceReference(
                source=source,
                external_id=external_id,
            )
        )
    return tuple(references)


def _decision_to_document(
    decision: BulkCollectionImportMergeValueDecision,
) -> dict[str, Any]:
    return {
        "field": decision.field,
        "action": decision.action,
        "existing_value": _thaw_json(
            decision.existing_value
        ),
        "imported_value": _thaw_json(
            decision.imported_value
        ),
    }


def _freeze_json(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BulkCollectionImportMergeError(
                f"{label} contains a non-finite number."
            )
        return value
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{label}[{index}]")
            for index, item in enumerate(value)
        )
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise BulkCollectionImportMergeError(
                    f"{label} contains a non-string object key."
                )
            frozen[key] = _freeze_json(
                item,
                f"{label}.{key}",
            )
        return MappingProxyType(frozen)
    raise BulkCollectionImportMergeError(
        f"{label} contains a value that is not JSON-compatible."
    )


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _thaw_json(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _require_exact_mapping(
    value: Any,
    expected_keys: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(value, dict):
        raise BulkCollectionImportMergeError(
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
    raise BulkCollectionImportMergeError(
        f"{label} fields must match the merge contract "
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
        raise BulkCollectionImportMergeError(
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
        raise BulkCollectionImportMergeError(
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
        raise BulkCollectionImportMergeError(
            f"{label} must be a non-empty non-whitespace "
            "string of at most 256 characters."
        )
    return value


__all__ = [
    "BULK_COLLECTION_IMPORT_MERGE_SCHEMA",
    "BULK_COLLECTION_IMPORT_MERGE_VERSION",
    "BULK_COLLECTION_IMPORT_MERGE_ACTIONS",
    "BULK_COLLECTION_IMPORT_MERGE_VALUE_ACTIONS",
    "BULK_COLLECTION_IMPORT_IDENTITY_REVIEW_REQUIRED_WARNING",
    "BULK_COLLECTION_IMPORT_IDENTITY_AMBIGUOUS_WARNING",
    "BULK_COLLECTION_IMPORT_IDENTITY_CONFLICT_WARNING",
    "BULK_COLLECTION_IMPORT_HARD_IDENTITY_CONFLICT_WARNINGS",
    "BULK_COLLECTION_IMPORT_MERGE_PLAN_KEYS",
    "BULK_COLLECTION_IMPORT_MERGE_SUMMARY_KEYS",
    "BULK_COLLECTION_IMPORT_MERGE_ITEM_KEYS",
    "BULK_COLLECTION_IMPORT_MERGE_VALUE_DECISION_KEYS",
    "BULK_COLLECTION_IMPORT_MERGE_GROUP_KEYS",
    "BulkCollectionImportMergeError",
    "BulkCollectionImportMergeValueDecision",
    "BulkCollectionImportMergeItem",
    "BulkCollectionImportMergeGroup",
    "BulkCollectionImportMergePlan",
    "build_bulk_collection_import_merge_plan",
    "bulk_collection_import_identity_review_warnings",
    "bulk_collection_import_merge_plan_to_document",
    "serialize_bulk_collection_import_merge_plan",
]
