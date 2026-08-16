"""Write-ready immutable planning for bulk Collection imports."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence


BULK_COLLECTION_IMPORT_APPLICATION_SCHEMA = (
    "smwc-bulk-collection-application-plan"
)
BULK_COLLECTION_IMPORT_APPLICATION_VERSION = 1
BULK_COLLECTION_IMPORT_APPLICATION_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "skip",
)

_RESOLUTION_SCHEMA = "smwc-bulk-collection-resolution-plan"
_RESOLUTION_VERSION = 1
_RESOLUTION_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "review_required",
    "skip",
)
_RESOLUTION_SUMMARY_KEYS = (
    "total",
    *_RESOLUTION_ACTIONS,
)
_RESOLUTION_DOCUMENT_KEYS = (
    "schema",
    "version",
    "import_id",
    "source_sha256",
    "summary",
    "items",
    "groups",
)
_RESOLUTION_ITEM_KEYS = (
    "entry_key",
    "action",
    "collection_key",
    "title_value",
    "source_reference_additions",
    "attributes",
    "attribute_changes",
    "conflicts",
    "warnings",
)
_GROUP_KEYS = (
    "group_key",
    "title",
    "entry_keys",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class BulkCollectionImportApplicationError(ValueError):
    """Raised when a write-ready application plan is unsafe."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportApplicationSourceReference:
    """One shared source identity in an application operation."""

    source: str
    external_id: str


@dataclass(frozen=True, slots=True)
class BulkCollectionImportApplicationAttributeChange:
    """One explicit shared-metadata field update."""

    field: str
    value: Any


@dataclass(frozen=True, slots=True)
class BulkCollectionImportApplicationOperation:
    """One immutable write-ready or no-op outcome."""

    entry_key: str
    action: str
    collection_key: str | None
    expected_shared_sha256: str | None
    title_value: str | None
    source_references: tuple[
        BulkCollectionImportApplicationSourceReference,
        ...,
    ]
    source_reference_additions: tuple[
        BulkCollectionImportApplicationSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]
    attribute_changes: tuple[
        BulkCollectionImportApplicationAttributeChange,
        ...,
    ]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportApplicationGroup:
    """Destination-neutral imported group order."""

    group_key: str
    title: str
    entry_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportApplicationPlan:
    """Detached immutable plan ready for a persistence adapter."""

    schema: str
    version: int
    import_id: str
    source_sha256: str
    summary: Mapping[str, int]
    operations: tuple[
        BulkCollectionImportApplicationOperation,
        ...,
    ]
    groups: tuple[BulkCollectionImportApplicationGroup, ...]


@dataclass(frozen=True, slots=True)
class _CollectionRecord:
    collection_key: str
    title: str
    source_references: tuple[
        BulkCollectionImportApplicationSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]
    shared_sha256: str


def build_bulk_collection_import_application_plan(
    resolution_document: Mapping[str, Any],
    new_collection_keys: Mapping[str, str],
    collection_records: Sequence[Mapping[str, Any]],
) -> BulkCollectionImportApplicationPlan:
    """Build a write-ready plan without mutating Collection data."""

    resolution = _parse_resolution_document(
        resolution_document
    )
    records = _parse_collection_records(collection_records)
    record_index = _index_records(records)

    create_entry_keys = tuple(
        item["entry_key"]
        for item in resolution["items"]
        if item["action"] == "create_record"
    )
    assignments = _parse_new_collection_keys(
        new_collection_keys,
        create_entry_keys,
        records,
    )

    operations = []
    for item in resolution["items"]:
        action = item["action"]
        entry_key = item["entry_key"]

        if action == "create_record":
            operations.append(
                _build_create_operation(
                    item,
                    assignments[entry_key],
                )
            )
        elif action == "update_record":
            record = _require_exact_record(
                record_index,
                item["collection_key"],
            )
            operations.append(
                _build_update_operation(item, record)
            )
        elif action == "no_change":
            record = _require_exact_record(
                record_index,
                item["collection_key"],
            )
            operations.append(
                _build_no_change_operation(item, record)
            )
        elif action == "skip":
            operations.append(
                _build_skip_operation(item)
            )
        else:
            raise BulkCollectionImportApplicationError(
                "Unresolved review rows cannot enter an "
                "application plan."
            )

    summary_values = {
        action: sum(
            operation.action == action
            for operation in operations
        )
        for action in BULK_COLLECTION_IMPORT_APPLICATION_ACTIONS
    }
    summary = MappingProxyType(
        {
            "total": len(operations),
            **summary_values,
        }
    )

    groups = tuple(
        BulkCollectionImportApplicationGroup(
            group_key=group["group_key"],
            title=group["title"],
            entry_keys=tuple(group["entry_keys"]),
        )
        for group in resolution["groups"]
    )

    return BulkCollectionImportApplicationPlan(
        schema=BULK_COLLECTION_IMPORT_APPLICATION_SCHEMA,
        version=BULK_COLLECTION_IMPORT_APPLICATION_VERSION,
        import_id=resolution["import_id"],
        source_sha256=resolution["source_sha256"],
        summary=summary,
        operations=tuple(operations),
        groups=groups,
    )


def bulk_collection_import_shared_record_sha256(
    record: Mapping[str, Any],
) -> str:
    """Fingerprint canonical shared Collection state only."""

    shared = _parse_shared_record(record)
    document = {
        "collection_key": shared["collection_key"],
        "title": shared["title"],
        "source_references": [
            {
                "source": reference.source,
                "external_id": reference.external_id,
            }
            for reference in shared["source_references"]
        ],
        "attributes": {
            field: _thaw_json(value)
            for field, value in shared["attributes"].items()
        },
    }
    payload = json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def bulk_collection_import_application_plan_to_document(
    plan: BulkCollectionImportApplicationPlan,
) -> dict[str, Any]:
    """Project an application plan to detached canonical JSON."""

    if not isinstance(
        plan,
        BulkCollectionImportApplicationPlan,
    ):
        raise TypeError(
            "plan must be BulkCollectionImportApplicationPlan"
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
                in BULK_COLLECTION_IMPORT_APPLICATION_ACTIONS
            },
        },
        "operations": [
            {
                "entry_key": operation.entry_key,
                "action": operation.action,
                "collection_key": operation.collection_key,
                "expected_shared_sha256": (
                    operation.expected_shared_sha256
                ),
                "title_value": operation.title_value,
                "source_references": [
                    {
                        "source": reference.source,
                        "external_id": reference.external_id,
                    }
                    for reference
                    in operation.source_references
                ],
                "source_reference_additions": [
                    {
                        "source": reference.source,
                        "external_id": reference.external_id,
                    }
                    for reference
                    in operation.source_reference_additions
                ],
                "attributes": {
                    field: _thaw_json(value)
                    for field, value
                    in operation.attributes.items()
                },
                "attribute_changes": [
                    {
                        "field": change.field,
                        "value": _thaw_json(change.value),
                    }
                    for change in operation.attribute_changes
                ],
                "warnings": list(operation.warnings),
            }
            for operation in plan.operations
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


def serialize_bulk_collection_import_application_plan(
    plan: BulkCollectionImportApplicationPlan,
) -> str:
    """Serialize an application plan as deterministic compact JSON."""

    return json.dumps(
        bulk_collection_import_application_plan_to_document(plan),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _build_create_operation(
    item: Mapping[str, Any],
    collection_key: str,
) -> BulkCollectionImportApplicationOperation:
    if item["collection_key"] is not None:
        raise BulkCollectionImportApplicationError(
            "create_record resolution rows cannot already have "
            "a Collection key."
        )
    if item["conflicts"]:
        raise BulkCollectionImportApplicationError(
            "create_record resolution rows cannot contain "
            "conflicts."
        )
    if item["attribute_changes"]:
        raise BulkCollectionImportApplicationError(
            "create_record resolution rows cannot contain "
            "attribute changes."
        )

    title_value = _require_text(
        item["title_value"],
        "create title_value",
    )

    return BulkCollectionImportApplicationOperation(
        entry_key=item["entry_key"],
        action="create_record",
        collection_key=collection_key,
        expected_shared_sha256=None,
        title_value=title_value,
        source_references=item["source_reference_additions"],
        source_reference_additions=(),
        attributes=item["attributes"],
        attribute_changes=(),
        warnings=item["warnings"],
    )


def _build_update_operation(
    item: Mapping[str, Any],
    record: _CollectionRecord,
) -> BulkCollectionImportApplicationOperation:
    if item["conflicts"]:
        raise BulkCollectionImportApplicationError(
            "update_record resolution rows cannot contain "
            "conflicts."
        )
    if item["attributes"]:
        raise BulkCollectionImportApplicationError(
            "update_record resolution rows cannot contain "
            "create attributes."
        )

    title_value = _optional_text(
        item["title_value"],
        "update title_value",
    )

    return BulkCollectionImportApplicationOperation(
        entry_key=item["entry_key"],
        action="update_record",
        collection_key=record.collection_key,
        expected_shared_sha256=record.shared_sha256,
        title_value=title_value,
        source_references=(),
        source_reference_additions=(
            item["source_reference_additions"]
        ),
        attributes=MappingProxyType({}),
        attribute_changes=item["attribute_changes"],
        warnings=item["warnings"],
    )


def _build_no_change_operation(
    item: Mapping[str, Any],
    record: _CollectionRecord,
) -> BulkCollectionImportApplicationOperation:
    if (
        item["title_value"] is not None
        or item["source_reference_additions"]
        or item["attributes"]
        or item["attribute_changes"]
        or item["conflicts"]
    ):
        raise BulkCollectionImportApplicationError(
            "no_change resolution rows cannot contain changes."
        )

    return BulkCollectionImportApplicationOperation(
        entry_key=item["entry_key"],
        action="no_change",
        collection_key=record.collection_key,
        expected_shared_sha256=record.shared_sha256,
        title_value=None,
        source_references=(),
        source_reference_additions=(),
        attributes=MappingProxyType({}),
        attribute_changes=(),
        warnings=item["warnings"],
    )


def _build_skip_operation(
    item: Mapping[str, Any],
) -> BulkCollectionImportApplicationOperation:
    if (
        item["collection_key"] is not None
        or item["title_value"] is not None
        or item["source_reference_additions"]
        or item["attributes"]
        or item["attribute_changes"]
        or item["conflicts"]
    ):
        raise BulkCollectionImportApplicationError(
            "skip resolution rows cannot contain a write target "
            "or changes."
        )

    return BulkCollectionImportApplicationOperation(
        entry_key=item["entry_key"],
        action="skip",
        collection_key=None,
        expected_shared_sha256=None,
        title_value=None,
        source_references=(),
        source_reference_additions=(),
        attributes=MappingProxyType({}),
        attribute_changes=(),
        warnings=item["warnings"],
    )


def _parse_resolution_document(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    _require_exact_mapping(
        value,
        _RESOLUTION_DOCUMENT_KEYS,
        "resolution document",
    )

    if value["schema"] != _RESOLUTION_SCHEMA:
        raise BulkCollectionImportApplicationError(
            "Resolution document schema is not supported."
        )
    if (
        type(value["version"]) is not int
        or value["version"] != _RESOLUTION_VERSION
    ):
        raise BulkCollectionImportApplicationError(
            "Resolution document version is not supported."
        )

    import_id = _require_text(
        value["import_id"],
        "resolution import_id",
    )
    source_sha256 = _require_sha256(
        value["source_sha256"],
        "resolution source_sha256",
    )

    raw_items = _parse_sequence_of_mappings(
        value["items"],
        "resolution items",
    )
    items = tuple(
        _parse_resolution_item(item, index)
        for index, item in enumerate(raw_items)
    )

    entry_keys = tuple(item["entry_key"] for item in items)
    if len(set(entry_keys)) != len(entry_keys):
        raise BulkCollectionImportApplicationError(
            "Resolution entry keys must be unique."
        )

    summary = _parse_resolution_summary(
        value["summary"],
        items,
    )
    if summary["review_required"] != 0:
        raise BulkCollectionImportApplicationError(
            "A write-ready application plan cannot contain "
            "review_required rows."
        )

    groups = _parse_groups(value["groups"], entry_keys)

    return {
        "import_id": import_id,
        "source_sha256": source_sha256,
        "summary": summary,
        "items": items,
        "groups": groups,
    }


def _parse_resolution_item(
    value: Mapping[str, Any],
    index: int,
) -> Mapping[str, Any]:
    label = f"resolution items[{index}]"
    _require_exact_mapping(
        value,
        _RESOLUTION_ITEM_KEYS,
        label,
    )

    action = value["action"]
    if action not in _RESOLUTION_ACTIONS:
        raise BulkCollectionImportApplicationError(
            f"{label}.action is not supported."
        )

    collection_key = _optional_text(
        value["collection_key"],
        f"{label}.collection_key",
    )
    title_value = _optional_text(
        value["title_value"],
        f"{label}.title_value",
    )

    attributes_value = value["attributes"]
    if not isinstance(attributes_value, Mapping):
        raise BulkCollectionImportApplicationError(
            f"{label}.attributes must be a mapping."
        )
    attributes = MappingProxyType(
        {
            _require_text(
                field,
                f"{label} attribute field",
            ): _freeze_json(
                item,
                f"{label}.attributes.{field}",
            )
            for field, item in attributes_value.items()
        }
    )

    changes = _parse_attribute_changes(
        value["attribute_changes"],
        f"{label}.attribute_changes",
    )
    conflicts = _parse_sequence_of_mappings(
        value["conflicts"],
        f"{label}.conflicts",
    )
    warnings = _parse_warnings(
        value["warnings"],
        f"{label}.warnings",
    )

    return MappingProxyType(
        {
            "entry_key": _require_text(
                value["entry_key"],
                f"{label}.entry_key",
            ),
            "action": action,
            "collection_key": collection_key,
            "title_value": title_value,
            "source_reference_additions": (
                _parse_source_references(
                    value["source_reference_additions"],
                    f"{label}.source_reference_additions",
                )
            ),
            "attributes": attributes,
            "attribute_changes": changes,
            "conflicts": conflicts,
            "warnings": warnings,
        }
    )


def _parse_resolution_summary(
    value: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
) -> Mapping[str, int]:
    _require_exact_mapping(
        value,
        _RESOLUTION_SUMMARY_KEYS,
        "resolution summary",
    )

    expected = {
        "total": len(items),
        **{
            action: sum(
                item["action"] == action
                for item in items
            )
            for action in _RESOLUTION_ACTIONS
        },
    }

    for key in _RESOLUTION_SUMMARY_KEYS:
        if type(value[key]) is not int or value[key] < 0:
            raise BulkCollectionImportApplicationError(
                f"resolution summary {key} must be a "
                "non-negative integer."
            )
        if value[key] != expected[key]:
            raise BulkCollectionImportApplicationError(
                "Resolution summary does not match its items."
            )

    return MappingProxyType(expected)


def _parse_new_collection_keys(
    value: Mapping[str, str],
    create_entry_keys: tuple[str, ...],
    records: Sequence[_CollectionRecord],
) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportApplicationError(
            "new_collection_keys must be a mapping."
        )

    assignments = {
        _require_text(
            entry_key,
            "new Collection key entry",
        ): _require_text(
            collection_key,
            f"new Collection key for {entry_key}",
        )
        for entry_key, collection_key in value.items()
    }

    if set(assignments) != set(create_entry_keys):
        raise BulkCollectionImportApplicationError(
            "New Collection key assignments must exactly cover "
            "create_record rows."
        )

    assigned_values = tuple(
        assignments[entry_key]
        for entry_key in create_entry_keys
    )
    if len(set(assigned_values)) != len(assigned_values):
        raise BulkCollectionImportApplicationError(
            "New Collection keys must be unique."
        )

    existing_keys = {
        record.collection_key
        for record in records
    }
    collisions = existing_keys.intersection(assigned_values)
    if collisions:
        raise BulkCollectionImportApplicationError(
            "New Collection keys cannot collide with existing "
            "Collection records."
        )

    return MappingProxyType(
        {
            entry_key: assignments[entry_key]
            for entry_key in create_entry_keys
        }
    )


def _parse_collection_records(
    value: Sequence[Mapping[str, Any]],
) -> tuple[_CollectionRecord, ...]:
    raw_records = _parse_sequence_of_mappings(
        value,
        "collection_records",
    )
    records = []

    for raw in raw_records:
        shared = _parse_shared_record(raw)
        records.append(
            _CollectionRecord(
                collection_key=shared["collection_key"],
                title=shared["title"],
                source_references=shared[
                    "source_references"
                ],
                attributes=shared["attributes"],
                shared_sha256=(
                    bulk_collection_import_shared_record_sha256(
                        raw
                    )
                ),
            )
        )

    return tuple(records)


def _parse_shared_record(
    record: Mapping[str, Any],
) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        raise BulkCollectionImportApplicationError(
            "Collection record must be a mapping."
        )

    collection_key = _require_text(
        record.get("collection_key"),
        "Collection record collection_key",
    )
    title = _require_text(
        record.get("title"),
        f"Collection record {collection_key} title",
    )
    references = _parse_source_references(
        record.get("source_references", ()),
        f"Collection record {collection_key} source_references",
    )

    attributes_value = record.get("attributes", {})
    if not isinstance(attributes_value, Mapping):
        raise BulkCollectionImportApplicationError(
            f"Collection record {collection_key} attributes "
            "must be a mapping."
        )
    attributes = MappingProxyType(
        {
            _require_text(
                field,
                "Collection attribute field",
            ): _freeze_json(
                value,
                f"Collection record {collection_key}.{field}",
            )
            for field, value in attributes_value.items()
        }
    )

    return MappingProxyType(
        {
            "collection_key": collection_key,
            "title": title,
            "source_references": references,
            "attributes": attributes,
        }
    )


def _index_records(
    records: Sequence[_CollectionRecord],
) -> Mapping[str, tuple[_CollectionRecord, ...]]:
    index: dict[str, list[_CollectionRecord]] = {}
    for record in records:
        index.setdefault(
            record.collection_key,
            [],
        ).append(record)

    return MappingProxyType(
        {
            key: tuple(values)
            for key, values in index.items()
        }
    )


def _require_exact_record(
    index: Mapping[str, tuple[_CollectionRecord, ...]],
    collection_key: str | None,
) -> _CollectionRecord:
    key = _require_text(
        collection_key,
        "existing Collection target",
    )
    matches = index.get(key, ())
    if len(matches) != 1:
        raise BulkCollectionImportApplicationError(
            "Existing application targets must appear exactly "
            "once in the supplied Collection snapshot."
        )
    return matches[0]


def _parse_groups(
    value: Sequence[Mapping[str, Any]],
    entry_keys: tuple[str, ...],
) -> tuple[Mapping[str, Any], ...]:
    raw_groups = _parse_sequence_of_mappings(value, "groups")
    groups = []
    flattened = []
    seen = set()

    for index, raw in enumerate(raw_groups):
        label = f"groups[{index}]"
        _require_exact_mapping(raw, _GROUP_KEYS, label)
        group_key = _require_text(
            raw["group_key"],
            f"{label}.group_key",
        )
        if group_key in seen:
            raise BulkCollectionImportApplicationError(
                "Group keys must be unique."
            )
        seen.add(group_key)

        raw_entry_keys = raw["entry_keys"]
        if (
            isinstance(
                raw_entry_keys,
                (str, bytes, bytearray),
            )
            or not isinstance(raw_entry_keys, Sequence)
        ):
            raise BulkCollectionImportApplicationError(
                f"{label}.entry_keys must be a sequence."
            )
        group_entry_keys = tuple(
            _require_text(
                item,
                f"{label}.entry_key",
            )
            for item in raw_entry_keys
        )
        flattened.extend(group_entry_keys)

        groups.append(
            MappingProxyType(
                {
                    "group_key": group_key,
                    "title": _require_text(
                        raw["title"],
                        f"{label}.title",
                    ),
                    "entry_keys": group_entry_keys,
                }
            )
        )

    if tuple(flattened) != entry_keys:
        raise BulkCollectionImportApplicationError(
            "Groups must cover every resolution row exactly "
            "once and preserve operation order."
        )

    return tuple(groups)


def _parse_source_references(
    value: Any,
    label: str,
) -> tuple[BulkCollectionImportApplicationSourceReference, ...]:
    raw_references = _parse_sequence_of_mappings(
        value,
        label,
    )
    result = []
    seen = set()

    for index, raw in enumerate(raw_references):
        reference_label = f"{label}[{index}]"
        source = _require_text(
            raw.get("source"),
            f"{reference_label}.source",
        )
        external_id = _require_text(
            raw.get("external_id"),
            f"{reference_label}.external_id",
        )
        key = (source, external_id)
        if key in seen:
            raise BulkCollectionImportApplicationError(
                f"{label} contains a duplicate source identity."
            )
        seen.add(key)
        result.append(
            BulkCollectionImportApplicationSourceReference(
                source=source,
                external_id=external_id,
            )
        )

    return tuple(result)


def _parse_attribute_changes(
    value: Any,
    label: str,
) -> tuple[BulkCollectionImportApplicationAttributeChange, ...]:
    raw_changes = _parse_sequence_of_mappings(value, label)
    result = []
    seen = set()

    for index, raw in enumerate(raw_changes):
        if set(raw) != {"field", "value"}:
            raise BulkCollectionImportApplicationError(
                f"{label}[{index}] must contain field and value."
            )
        field = _require_text(
            raw["field"],
            f"{label}[{index}].field",
        )
        if field in seen:
            raise BulkCollectionImportApplicationError(
                f"{label} contains a duplicate field."
            )
        seen.add(field)
        result.append(
            BulkCollectionImportApplicationAttributeChange(
                field=field,
                value=_freeze_json(
                    raw["value"],
                    f"{label}[{index}].value",
                ),
            )
        )

    return tuple(result)


def _parse_warnings(
    value: Any,
    label: str,
) -> tuple[str, ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportApplicationError(
            f"{label} must be a sequence."
        )

    warnings = []
    for warning in value:
        code = _require_text(warning, f"{label} warning")
        if code not in warnings:
            warnings.append(code)

    return tuple(warnings)


def _parse_sequence_of_mappings(
    value: Any,
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportApplicationError(
            f"{label} must be a sequence."
        )

    result = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise BulkCollectionImportApplicationError(
                f"{label}[{index}] must be a mapping."
            )
        result.append(item)

    return tuple(result)


def _require_exact_mapping(
    value: Any,
    expected_keys: Sequence[str],
    label: str,
) -> None:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportApplicationError(
            f"{label} must be a mapping."
        )
    if set(value) != set(expected_keys):
        raise BulkCollectionImportApplicationError(
            f"{label} fields do not match the expected contract."
        )


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportApplicationError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_text(value, label)


def _require_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA256_PATTERN.fullmatch(value) is None
    ):
        raise BulkCollectionImportApplicationError(
            f"{label} must be a lowercase 64-character SHA-256."
        )
    return value


def _freeze_json(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BulkCollectionImportApplicationError(
                f"{label} contains a non-finite number."
            )
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _require_text(
                    key,
                    f"{label} key",
                ): _freeze_json(
                    item,
                    f"{label}.{key}",
                )
                for key, item in value.items()
            }
        )
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(
                item,
                f"{label}[{index}]",
            )
            for index, item in enumerate(value)
        )

    raise BulkCollectionImportApplicationError(
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
    "BULK_COLLECTION_IMPORT_APPLICATION_SCHEMA",
    "BULK_COLLECTION_IMPORT_APPLICATION_VERSION",
    "BULK_COLLECTION_IMPORT_APPLICATION_ACTIONS",
    "BulkCollectionImportApplicationError",
    "BulkCollectionImportApplicationSourceReference",
    "BulkCollectionImportApplicationAttributeChange",
    "BulkCollectionImportApplicationOperation",
    "BulkCollectionImportApplicationGroup",
    "BulkCollectionImportApplicationPlan",
    "build_bulk_collection_import_application_plan",
    "bulk_collection_import_shared_record_sha256",
    "bulk_collection_import_application_plan_to_document",
    "serialize_bulk_collection_import_application_plan",
]
