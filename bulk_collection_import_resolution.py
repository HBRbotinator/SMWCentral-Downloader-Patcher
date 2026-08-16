"""Immutable post-review planning for bulk Collection imports."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence


BULK_COLLECTION_IMPORT_RESOLUTION_SCHEMA = (
    "smwc-bulk-collection-resolution-plan"
)
BULK_COLLECTION_IMPORT_RESOLUTION_VERSION = 1
BULK_COLLECTION_IMPORT_RESOLUTION_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "review_required",
    "skip",
)

_HARD_IDENTITY_CONFLICT_WARNINGS = (
    "source_identity_conflict",
    "duplicate_import_target",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class BulkCollectionImportResolutionError(ValueError):
    """Raised when post-review resolution cannot be planned safely."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportResolutionSourceReference:
    """One source identity carried by a resolution item."""

    source: str
    external_id: str


@dataclass(frozen=True, slots=True)
class BulkCollectionImportResolutionAttributeChange:
    """One explicit shared-metadata change."""

    field: str
    value: Any


@dataclass(frozen=True, slots=True)
class BulkCollectionImportResolutionConflict:
    """One shared-metadata conflict exposed during resolution."""

    field: str
    existing_value: Any
    imported_value: Any


@dataclass(frozen=True, slots=True)
class BulkCollectionImportResolutionItem:
    """One immutable post-review outcome."""

    entry_key: str
    action: str
    collection_key: str | None
    title_value: str | None
    source_reference_additions: tuple[
        BulkCollectionImportResolutionSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]
    attribute_changes: tuple[
        BulkCollectionImportResolutionAttributeChange,
        ...,
    ]
    conflicts: tuple[
        BulkCollectionImportResolutionConflict,
        ...,
    ]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportResolutionGroup:
    """Destination-neutral imported group order."""

    group_key: str
    title: str
    entry_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportResolutionPlan:
    """Detached immutable result after one review round."""

    schema: str
    version: int
    import_id: str
    source_sha256: str
    summary: Mapping[str, int]
    items: tuple[BulkCollectionImportResolutionItem, ...]
    groups: tuple[BulkCollectionImportResolutionGroup, ...]


@dataclass(frozen=True, slots=True)
class _ImportedEntry:
    entry_key: str
    title: str
    source_references: tuple[
        BulkCollectionImportResolutionSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class _CollectionRecord:
    collection_key: str
    title: str
    source_references: tuple[
        BulkCollectionImportResolutionSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]


def build_bulk_collection_import_resolution_plan(
    import_entries: Mapping[str, Mapping[str, Any]],
    merge_items: Sequence[Mapping[str, Any]],
    review_decisions: Sequence[Mapping[str, Any]],
    collection_records: Sequence[Mapping[str, Any]],
    groups: Sequence[Mapping[str, Any]],
    import_id: str,
    source_sha256: str,
) -> BulkCollectionImportResolutionPlan:
    """Build a detached plan without modifying Collection data."""

    normalized_import_id = _require_text(import_id, "import_id")
    normalized_sha256 = _require_sha256(source_sha256)

    entries = _parse_import_entries(import_entries)
    merges = _parse_sequence_of_mappings(
        merge_items,
        "merge_items",
    )
    reviews = _parse_sequence_of_mappings(
        review_decisions,
        "review_decisions",
    )
    records = _parse_collection_records(collection_records)
    parsed_groups = _parse_groups(groups, tuple(entries))

    merge_keys = tuple(
        _require_text(item.get("entry_key"), "merge entry_key")
        for item in merges
    )
    entry_keys = tuple(entries)
    if merge_keys != entry_keys:
        raise BulkCollectionImportResolutionError(
            "Merge items must exactly match import entry order."
        )

    review_items = tuple(
        item
        for item in merges
        if item.get("action") == "review_required"
    )
    expected_review_keys = tuple(
        item["entry_key"] for item in review_items
    )
    actual_review_keys = tuple(
        _require_text(
            item.get("entry_key"),
            "review decision entry_key",
        )
        for item in reviews
    )
    if actual_review_keys != expected_review_keys:
        raise BulkCollectionImportResolutionError(
            "Review decisions must exactly cover review-required "
            "rows in merge-plan order."
        )

    record_index = _index_records(records)
    review_index = {
        item["entry_key"]: item
        for item in reviews
    }

    resolved_items = []
    for entry_key, merge_item in zip(
        entry_keys,
        merges,
        strict=True,
    ):
        entry = entries[entry_key]
        action = merge_item.get("action")

        if action == "create_record":
            resolved = _create_item(
                entry,
                tuple(merge_item.get("warnings", ())),
            )
        elif action == "update_record":
            resolved = _safe_update_item(
                entry,
                merge_item,
            )
        elif action == "no_change":
            resolved = _no_change_item(
                entry,
                merge_item,
            )
        elif action == "review_required":
            resolved = _resolve_review_item(
                entry,
                merge_item,
                review_index[entry_key],
                record_index,
            )
        else:
            raise BulkCollectionImportResolutionError(
                f"Unsupported merge action for {entry_key}."
            )

        resolved_items.append(resolved)

    summary_values = {
        action: sum(
            item.action == action
            for item in resolved_items
        )
        for action in BULK_COLLECTION_IMPORT_RESOLUTION_ACTIONS
    }
    summary = MappingProxyType(
        {
            "total": len(resolved_items),
            **summary_values,
        }
    )

    return BulkCollectionImportResolutionPlan(
        schema=BULK_COLLECTION_IMPORT_RESOLUTION_SCHEMA,
        version=BULK_COLLECTION_IMPORT_RESOLUTION_VERSION,
        import_id=normalized_import_id,
        source_sha256=normalized_sha256,
        summary=summary,
        items=tuple(resolved_items),
        groups=parsed_groups,
    )


def bulk_collection_import_resolution_plan_to_document(
    plan: BulkCollectionImportResolutionPlan,
) -> dict[str, Any]:
    """Project a resolution plan to detached canonical JSON data."""

    if not isinstance(
        plan,
        BulkCollectionImportResolutionPlan,
    ):
        raise TypeError(
            "plan must be BulkCollectionImportResolutionPlan"
        )

    return {
        "schema": plan.schema,
        "version": plan.version,
        "import_id": plan.import_id,
        "source_sha256": plan.source_sha256,
        "summary": {
            "total": plan.summary["total"],
            **{
                action: plan.summary[action]
                for action
                in BULK_COLLECTION_IMPORT_RESOLUTION_ACTIONS
            },
        },
        "items": [
            {
                "entry_key": item.entry_key,
                "action": item.action,
                "collection_key": item.collection_key,
                "title_value": item.title_value,
                "source_reference_additions": [
                    {
                        "source": reference.source,
                        "external_id": reference.external_id,
                    }
                    for reference
                    in item.source_reference_additions
                ],
                "attributes": {
                    field: _thaw_json(value)
                    for field, value in item.attributes.items()
                },
                "attribute_changes": [
                    {
                        "field": change.field,
                        "value": _thaw_json(change.value),
                    }
                    for change in item.attribute_changes
                ],
                "conflicts": [
                    {
                        "field": conflict.field,
                        "existing_value": _thaw_json(
                            conflict.existing_value
                        ),
                        "imported_value": _thaw_json(
                            conflict.imported_value
                        ),
                    }
                    for conflict in item.conflicts
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


def serialize_bulk_collection_import_resolution_plan(
    plan: BulkCollectionImportResolutionPlan,
) -> str:
    """Serialize a resolution plan as stable compact JSON."""

    return json.dumps(
        bulk_collection_import_resolution_plan_to_document(plan),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _resolve_review_item(
    entry: _ImportedEntry,
    merge_item: Mapping[str, Any],
    decision: Mapping[str, Any],
    record_index: Mapping[str, tuple[_CollectionRecord, ...]],
) -> BulkCollectionImportResolutionItem:
    action = decision.get("action")
    warnings = _parse_warnings(merge_item.get("warnings", ()))

    if action == "skip":
        return BulkCollectionImportResolutionItem(
            entry_key=entry.entry_key,
            action="skip",
            collection_key=None,
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=warnings,
        )

    if action == "create_new":
        if "identity_ambiguous" not in warnings:
            raise BulkCollectionImportResolutionError(
                "create_new is only valid for ambiguous identity "
                "review."
            )
        return _create_item(entry, warnings)

    if action == "resolve_metadata":
        return _resolve_metadata_review(
            entry,
            merge_item,
            decision,
        )

    if action == "select_existing":
        if "identity_ambiguous" not in warnings:
            raise BulkCollectionImportResolutionError(
                "select_existing is only valid for ambiguous "
                "identity review."
            )
        selected_key = _require_text(
            decision.get("selected_collection_key"),
            "selected_collection_key",
        )
        candidates = tuple(
            _require_text(value, "identity candidate")
            for value in merge_item.get("collection_keys", ())
        )
        if selected_key not in candidates:
            raise BulkCollectionImportResolutionError(
                "Selected Collection record is not an identity "
                "candidate."
            )
        record = _require_exact_record(
            record_index,
            selected_key,
        )
        return _replan_selected_record(entry, record)

    raise BulkCollectionImportResolutionError(
        f"Unsupported review action for {entry.entry_key}."
    )


def _resolve_metadata_review(
    entry: _ImportedEntry,
    merge_item: Mapping[str, Any],
    decision: Mapping[str, Any],
) -> BulkCollectionImportResolutionItem:
    keys = tuple(
        _require_text(value, "metadata Collection key")
        for value in merge_item.get("collection_keys", ())
    )
    if len(keys) != 1:
        raise BulkCollectionImportResolutionError(
            "Metadata review must target exactly one Collection "
            "record."
        )
    selected_key = _require_text(
        decision.get("selected_collection_key"),
        "selected_collection_key",
    )
    if selected_key != keys[0]:
        raise BulkCollectionImportResolutionError(
            "Metadata resolution must preserve the matched "
            "Collection record."
        )

    title_value = None
    title_decision = merge_item.get("title_decision")
    if isinstance(title_decision, Mapping):
        title_action = title_decision.get("action")
        if title_action == "review_conflict":
            choice = decision.get("title_choice")
            if choice == "use_imported":
                title_value = _require_text(
                    title_decision.get("imported_value"),
                    "imported title",
                )
            elif choice != "keep_existing":
                raise BulkCollectionImportResolutionError(
                    "Conflicting title requires an explicit choice."
                )

    choice_map = _attribute_choice_map(
        decision.get("attribute_choices", ())
    )
    changes = []
    expected_conflicts = []

    for value_decision in _parse_sequence_of_mappings(
        merge_item.get("attribute_decisions", ()),
        "attribute_decisions",
    ):
        field = _require_text(
            value_decision.get("field"),
            "attribute decision field",
        )
        value_action = value_decision.get("action")
        imported = _freeze_json(
            value_decision.get("imported_value"),
            f"attribute {field}",
        )

        if value_action == "add_missing":
            changes.append(
                BulkCollectionImportResolutionAttributeChange(
                    field=field,
                    value=imported,
                )
            )
        elif value_action == "review_conflict":
            expected_conflicts.append(field)
            choice = choice_map.get(field)
            if choice == "use_imported":
                changes.append(
                    BulkCollectionImportResolutionAttributeChange(
                        field=field,
                        value=imported,
                    )
                )
            elif choice != "keep_existing":
                raise BulkCollectionImportResolutionError(
                    f"Conflict {field} requires an explicit choice."
                )
        elif value_action not in ("unchanged",):
            raise BulkCollectionImportResolutionError(
                f"Unsupported metadata decision action: "
                f"{value_action}"
            )

    if tuple(choice_map) != tuple(expected_conflicts):
        raise BulkCollectionImportResolutionError(
            "Metadata choices must exactly cover conflicting "
            "attributes in plan order."
        )

    additions = _parse_source_references(
        merge_item.get("source_reference_additions", ()),
        "source_reference_additions",
    )
    has_update = bool(
        title_value is not None
        or additions
        or changes
    )

    return BulkCollectionImportResolutionItem(
        entry_key=entry.entry_key,
        action="update_record" if has_update else "no_change",
        collection_key=selected_key,
        title_value=title_value,
        source_reference_additions=additions,
        attributes=MappingProxyType({}),
        attribute_changes=tuple(changes),
        conflicts=(),
        warnings=(),
    )


def _replan_selected_record(
    entry: _ImportedEntry,
    record: _CollectionRecord,
) -> BulkCollectionImportResolutionItem:
    conflicts = []
    changes = []

    if entry.title != record.title:
        conflicts.append(
            BulkCollectionImportResolutionConflict(
                field="title",
                existing_value=record.title,
                imported_value=entry.title,
            )
        )

    for field, imported in entry.attributes.items():
        if field not in record.attributes:
            changes.append(
                BulkCollectionImportResolutionAttributeChange(
                    field=field,
                    value=imported,
                )
            )
            continue

        existing = record.attributes[field]
        if existing != imported:
            conflicts.append(
                BulkCollectionImportResolutionConflict(
                    field=field,
                    existing_value=existing,
                    imported_value=imported,
                )
            )

    existing_references = {
        (reference.source, reference.external_id)
        for reference in record.source_references
    }
    additions = tuple(
        reference
        for reference in entry.source_references
        if (
            reference.source,
            reference.external_id,
        )
        not in existing_references
    )

    if conflicts:
        return BulkCollectionImportResolutionItem(
            entry_key=entry.entry_key,
            action="review_required",
            collection_key=record.collection_key,
            title_value=None,
            source_reference_additions=additions,
            attributes=MappingProxyType({}),
            attribute_changes=tuple(changes),
            conflicts=tuple(conflicts),
            warnings=("metadata_conflict",),
        )

    has_update = bool(additions or changes)
    return BulkCollectionImportResolutionItem(
        entry_key=entry.entry_key,
        action="update_record" if has_update else "no_change",
        collection_key=record.collection_key,
        title_value=None,
        source_reference_additions=additions,
        attributes=MappingProxyType({}),
        attribute_changes=tuple(changes),
        conflicts=(),
        warnings=(),
    )


def _safe_update_item(
    entry: _ImportedEntry,
    merge_item: Mapping[str, Any],
) -> BulkCollectionImportResolutionItem:
    keys = tuple(
        _require_text(value, "update Collection key")
        for value in merge_item.get("collection_keys", ())
    )
    if len(keys) != 1:
        raise BulkCollectionImportResolutionError(
            "Safe update must target exactly one Collection record."
        )

    changes = []
    for decision in _parse_sequence_of_mappings(
        merge_item.get("attribute_decisions", ()),
        "attribute_decisions",
    ):
        if decision.get("action") == "add_missing":
            field = _require_text(
                decision.get("field"),
                "attribute decision field",
            )
            changes.append(
                BulkCollectionImportResolutionAttributeChange(
                    field=field,
                    value=_freeze_json(
                        decision.get("imported_value"),
                        f"attribute {field}",
                    ),
                )
            )
        elif decision.get("action") not in ("unchanged",):
            raise BulkCollectionImportResolutionError(
                "Safe update contains a non-safe metadata action."
            )

    return BulkCollectionImportResolutionItem(
        entry_key=entry.entry_key,
        action="update_record",
        collection_key=keys[0],
        title_value=None,
        source_reference_additions=_parse_source_references(
            merge_item.get("source_reference_additions", ()),
            "source_reference_additions",
        ),
        attributes=MappingProxyType({}),
        attribute_changes=tuple(changes),
        conflicts=(),
        warnings=_parse_warnings(
            merge_item.get("warnings", ())
        ),
    )


def _no_change_item(
    entry: _ImportedEntry,
    merge_item: Mapping[str, Any],
) -> BulkCollectionImportResolutionItem:
    keys = tuple(
        _require_text(value, "no-change Collection key")
        for value in merge_item.get("collection_keys", ())
    )
    if len(keys) != 1:
        raise BulkCollectionImportResolutionError(
            "No-change item must target exactly one Collection "
            "record."
        )

    return BulkCollectionImportResolutionItem(
        entry_key=entry.entry_key,
        action="no_change",
        collection_key=keys[0],
        title_value=None,
        source_reference_additions=(),
        attributes=MappingProxyType({}),
        attribute_changes=(),
        conflicts=(),
        warnings=_parse_warnings(
            merge_item.get("warnings", ())
        ),
    )


def _create_item(
    entry: _ImportedEntry,
    warnings: Sequence[str],
) -> BulkCollectionImportResolutionItem:
    return BulkCollectionImportResolutionItem(
        entry_key=entry.entry_key,
        action="create_record",
        collection_key=None,
        title_value=entry.title,
        source_reference_additions=tuple(
            entry.source_references
        ),
        attributes=entry.attributes,
        attribute_changes=(),
        conflicts=(),
        warnings=_parse_warnings(warnings),
    )


def _parse_import_entries(
    value: Mapping[str, Mapping[str, Any]],
) -> dict[str, _ImportedEntry]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportResolutionError(
            "import_entries must be a mapping."
        )

    result = {}
    for key, raw in value.items():
        entry_key = _require_text(key, "import entry key")
        if not isinstance(raw, Mapping):
            raise BulkCollectionImportResolutionError(
                f"Import entry {entry_key} must be a mapping."
            )
        if raw.get("entry_key") != entry_key:
            raise BulkCollectionImportResolutionError(
                "Import entry mapping key must equal entry_key."
            )
        attributes_value = raw.get("attributes", {})
        if not isinstance(attributes_value, Mapping):
            raise BulkCollectionImportResolutionError(
                f"Import entry {entry_key} attributes must be a "
                "mapping."
            )
        attributes = MappingProxyType(
            {
                _require_text(field, "attribute field"): _freeze_json(
                    attribute_value,
                    f"entry {entry_key}.{field}",
                )
                for field, attribute_value
                in attributes_value.items()
            }
        )
        result[entry_key] = _ImportedEntry(
            entry_key=entry_key,
            title=_require_text(
                raw.get("title"),
                f"entry {entry_key} title",
            ),
            source_references=_parse_source_references(
                raw.get("source_references", ()),
                f"entry {entry_key} source_references",
            ),
            attributes=attributes,
        )

    return result


def _parse_collection_records(
    value: Sequence[Mapping[str, Any]],
) -> tuple[_CollectionRecord, ...]:
    raw_records = _parse_sequence_of_mappings(
        value,
        "collection_records",
    )
    records = []
    for raw in raw_records:
        key = _require_text(
            raw.get("collection_key"),
            "collection_key",
        )
        attributes_value = raw.get("attributes", {})
        if not isinstance(attributes_value, Mapping):
            raise BulkCollectionImportResolutionError(
                f"Collection record {key} attributes must be a "
                "mapping."
            )
        records.append(
            _CollectionRecord(
                collection_key=key,
                title=_require_text(
                    raw.get("title"),
                    f"Collection record {key} title",
                ),
                source_references=_parse_source_references(
                    raw.get("source_references", ()),
                    f"Collection record {key} source_references",
                ),
                attributes=MappingProxyType(
                    {
                        _require_text(
                            field,
                            "Collection attribute field",
                        ): _freeze_json(
                            attribute_value,
                            f"Collection record {key}.{field}",
                        )
                        for field, attribute_value
                        in attributes_value.items()
                    }
                ),
            )
        )
    return tuple(records)


def _index_records(
    records: Sequence[_CollectionRecord],
) -> Mapping[str, tuple[_CollectionRecord, ...]]:
    index = {}
    for record in records:
        index.setdefault(record.collection_key, []).append(record)
    return {
        key: tuple(values)
        for key, values in index.items()
    }


def _require_exact_record(
    index: Mapping[str, tuple[_CollectionRecord, ...]],
    collection_key: str,
) -> _CollectionRecord:
    matches = index.get(collection_key, ())
    if len(matches) != 1:
        raise BulkCollectionImportResolutionError(
            "Selected Collection record must appear exactly once "
            "in the supplied snapshot."
        )
    return matches[0]


def _parse_groups(
    value: Sequence[Mapping[str, Any]],
    entry_keys: tuple[str, ...],
) -> tuple[BulkCollectionImportResolutionGroup, ...]:
    raw_groups = _parse_sequence_of_mappings(value, "groups")
    groups = []
    flattened = []
    seen_group_keys = set()

    for raw in raw_groups:
        group_key = _require_text(
            raw.get("group_key"),
            "group_key",
        )
        if group_key in seen_group_keys:
            raise BulkCollectionImportResolutionError(
                "Group keys must be unique."
            )
        seen_group_keys.add(group_key)

        raw_entry_keys = raw.get("entry_keys")
        if (
            isinstance(raw_entry_keys, (str, bytes, bytearray))
            or not isinstance(raw_entry_keys, Sequence)
        ):
            raise BulkCollectionImportResolutionError(
                "Group entry_keys must be a sequence."
            )
        group_entry_keys = tuple(
            _require_text(item, "group entry_key")
            for item in raw_entry_keys
        )
        flattened.extend(group_entry_keys)
        groups.append(
            BulkCollectionImportResolutionGroup(
                group_key=group_key,
                title=_require_text(raw.get("title"), "group title"),
                entry_keys=group_entry_keys,
            )
        )

    if tuple(flattened) != entry_keys:
        raise BulkCollectionImportResolutionError(
            "Groups must cover every imported entry exactly once "
            "and preserve import order."
        )

    return tuple(groups)


def _parse_source_references(
    value: Any,
    label: str,
) -> tuple[BulkCollectionImportResolutionSourceReference, ...]:
    raw_references = _parse_sequence_of_mappings(value, label)
    result = []
    seen = set()
    for raw in raw_references:
        source = _require_text(raw.get("source"), f"{label} source")
        external_id = _require_text(
            raw.get("external_id"),
            f"{label} external_id",
        )
        key = (source, external_id)
        if key in seen:
            raise BulkCollectionImportResolutionError(
                f"{label} contains a duplicate source identity."
            )
        seen.add(key)
        result.append(
            BulkCollectionImportResolutionSourceReference(
                source=source,
                external_id=external_id,
            )
        )
    return tuple(result)


def _attribute_choice_map(value: Any) -> Mapping[str, str]:
    raw_choices = _parse_sequence_of_mappings(
        value,
        "attribute_choices",
    )
    result = {}
    for raw in raw_choices:
        field = _require_text(
            raw.get("field"),
            "attribute choice field",
        )
        choice = raw.get("choice")
        if choice not in ("keep_existing", "use_imported"):
            raise BulkCollectionImportResolutionError(
                f"Unsupported conflict choice for {field}."
            )
        if field in result:
            raise BulkCollectionImportResolutionError(
                "Attribute conflict choices must be unique."
            )
        result[field] = choice
    return result


def _parse_warnings(value: Any) -> tuple[str, ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportResolutionError(
            "warnings must be a sequence."
        )
    result = []
    for warning in value:
        code = _require_text(warning, "warning")
        if code not in result:
            result.append(code)
    return tuple(result)


def _parse_sequence_of_mappings(
    value: Any,
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportResolutionError(
            f"{label} must be a sequence."
        )
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise BulkCollectionImportResolutionError(
                f"{label}[{index}] must be a mapping."
            )
        result.append(item)
    return tuple(result)


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportResolutionError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


def _require_sha256(value: Any) -> str:
    if (
        not isinstance(value, str)
        or _SHA256_PATTERN.fullmatch(value) is None
    ):
        raise BulkCollectionImportResolutionError(
            "source_sha256 must be a lowercase 64-character "
            "SHA-256."
        )
    return value


def _freeze_json(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BulkCollectionImportResolutionError(
                f"{label} contains a non-finite number."
            )
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _require_text(key, f"{label} key"): _freeze_json(
                    item,
                    f"{label}.{key}",
                )
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{label}[{index}]")
            for index, item in enumerate(value)
        )
    raise BulkCollectionImportResolutionError(
        f"{label} contains a non-JSON value."
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


__all__ = [
    "BULK_COLLECTION_IMPORT_RESOLUTION_SCHEMA",
    "BULK_COLLECTION_IMPORT_RESOLUTION_VERSION",
    "BULK_COLLECTION_IMPORT_RESOLUTION_ACTIONS",
    "BulkCollectionImportResolutionError",
    "BulkCollectionImportResolutionSourceReference",
    "BulkCollectionImportResolutionAttributeChange",
    "BulkCollectionImportResolutionConflict",
    "BulkCollectionImportResolutionItem",
    "BulkCollectionImportResolutionGroup",
    "BulkCollectionImportResolutionPlan",
    "build_bulk_collection_import_resolution_plan",
    "bulk_collection_import_resolution_plan_to_document",
    "serialize_bulk_collection_import_resolution_plan",
]
