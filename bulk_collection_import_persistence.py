"""Atomic execution boundary for bulk Collection import application plans."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence


BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_SCHEMA = (
    "smwc-bulk-collection-persistence-result"
)
BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_VERSION = 1
BULK_COLLECTION_IMPORT_PERSISTENCE_OUTCOMES = (
    "created",
    "updated",
    "unchanged",
    "skipped",
)

_APPLICATION_SCHEMA = "smwc-bulk-collection-application-plan"
_APPLICATION_VERSION = 1
_APPLICATION_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "skip",
)
_APPLICATION_SUMMARY_KEYS = (
    "total",
    *_APPLICATION_ACTIONS,
)
_APPLICATION_DOCUMENT_KEYS = (
    "schema",
    "version",
    "import_id",
    "source_sha256",
    "summary",
    "operations",
    "groups",
)
_APPLICATION_OPERATION_KEYS = (
    "entry_key",
    "action",
    "collection_key",
    "expected_shared_sha256",
    "title_value",
    "source_references",
    "source_reference_additions",
    "attributes",
    "attribute_changes",
    "warnings",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class BulkCollectionImportPersistenceError(RuntimeError):
    """Raised when an application plan cannot be executed atomically."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportPersistenceItem:
    """One ordered persistence outcome."""

    entry_key: str
    outcome: str
    collection_key: str | None
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportPersistenceResult:
    """Immutable result of one committed application plan."""

    schema: str
    version: int
    import_id: str
    source_sha256: str
    summary: Mapping[str, int]
    items: tuple[BulkCollectionImportPersistenceItem, ...]


def execute_bulk_collection_import_application_plan(
    application_plan: Mapping[str, Any],
    store: Any,
) -> BulkCollectionImportPersistenceResult:
    """Preflight and atomically execute one write-ready plan."""

    plan = _parse_application_plan(application_plan)
    _preflight(plan, store)

    transaction = None
    try:
        transaction = store.begin_transaction()

        for operation in plan["operations"]:
            action = operation["action"]
            if action == "create_record":
                transaction.create_record(
                    collection_key=operation["collection_key"],
                    title=operation["title_value"],
                    source_references=[
                        _thaw_json(reference)
                        for reference
                        in operation["source_references"]
                    ],
                    attributes={
                        field: _thaw_json(value)
                        for field, value
                        in operation["attributes"].items()
                    },
                    user_state={},
                )
            elif action == "update_record":
                transaction.update_record(
                    collection_key=operation["collection_key"],
                    title_value=operation["title_value"],
                    source_reference_additions=[
                        _thaw_json(reference)
                        for reference
                        in operation["source_reference_additions"]
                    ],
                    attribute_changes=[
                        {
                            "field": change["field"],
                            "value": _thaw_json(change["value"]),
                        }
                        for change
                        in operation["attribute_changes"]
                    ],
                )

        transaction.commit()
    except Exception as error:
        if transaction is not None:
            try:
                transaction.rollback()
            except Exception:
                pass
        raise BulkCollectionImportPersistenceError(
            "Bulk Collection import transaction failed."
        ) from error

    items = tuple(
        BulkCollectionImportPersistenceItem(
            entry_key=operation["entry_key"],
            outcome=_outcome_for_action(operation["action"]),
            collection_key=operation["collection_key"],
            warnings=operation["warnings"],
        )
        for operation in plan["operations"]
    )
    counts = {
        outcome: sum(
            item.outcome == outcome
            for item in items
        )
        for outcome in BULK_COLLECTION_IMPORT_PERSISTENCE_OUTCOMES
    }

    return BulkCollectionImportPersistenceResult(
        schema=BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_SCHEMA,
        version=BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_VERSION,
        import_id=plan["import_id"],
        source_sha256=plan["source_sha256"],
        summary=MappingProxyType(
            {
                "total": len(items),
                **counts,
            }
        ),
        items=items,
    )


def bulk_collection_import_persistence_result_to_document(
    result: BulkCollectionImportPersistenceResult,
) -> dict[str, Any]:
    """Project a persistence result to detached canonical JSON."""

    if not isinstance(
        result,
        BulkCollectionImportPersistenceResult,
    ):
        raise TypeError(
            "result must be BulkCollectionImportPersistenceResult"
        )

    return {
        "schema": result.schema,
        "version": result.version,
        "import_id": result.import_id,
        "source_sha256": result.source_sha256,
        "summary": {
            "total": result.summary["total"],
            **{
                outcome: result.summary[outcome]
                for outcome
                in BULK_COLLECTION_IMPORT_PERSISTENCE_OUTCOMES
            },
        },
        "items": [
            {
                "entry_key": item.entry_key,
                "outcome": item.outcome,
                "collection_key": item.collection_key,
                "warnings": list(item.warnings),
            }
            for item in result.items
        ],
    }


def serialize_bulk_collection_import_persistence_result(
    result: BulkCollectionImportPersistenceResult,
) -> str:
    """Serialize a persistence result as deterministic compact JSON."""

    return json.dumps(
        bulk_collection_import_persistence_result_to_document(
            result
        ),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _preflight(
    plan: Mapping[str, Any],
    store: Any,
) -> None:
    """Validate every write precondition before beginning a transaction."""

    for operation in plan["operations"]:
        action = operation["action"]
        collection_key = operation["collection_key"]

        if action == "create_record":
            try:
                exists = store.record_exists(collection_key)
            except Exception as error:
                raise BulkCollectionImportPersistenceError(
                    "Could not preflight a new Collection key."
                ) from error
            if exists:
                raise BulkCollectionImportPersistenceError(
                    "A create_record Collection key already exists."
                )

        elif action in ("update_record", "no_change"):
            try:
                actual_sha256 = store.shared_sha256(
                    collection_key
                )
            except Exception as error:
                raise BulkCollectionImportPersistenceError(
                    "Could not preflight existing Collection state."
                ) from error

            if (
                actual_sha256
                != operation["expected_shared_sha256"]
            ):
                raise BulkCollectionImportPersistenceError(
                    "Existing Collection shared state changed after "
                    "application planning."
                )


def _parse_application_plan(
    value: Mapping[str, Any],
) -> Mapping[str, Any]:
    _require_exact_mapping(
        value,
        _APPLICATION_DOCUMENT_KEYS,
        "application plan",
    )

    if value["schema"] != _APPLICATION_SCHEMA:
        raise BulkCollectionImportPersistenceError(
            "Application plan schema is not supported."
        )
    if (
        type(value["version"]) is not int
        or value["version"] != _APPLICATION_VERSION
    ):
        raise BulkCollectionImportPersistenceError(
            "Application plan version is not supported."
        )

    import_id = _require_text(
        value["import_id"],
        "application import_id",
    )
    source_sha256 = _require_sha256(
        value["source_sha256"],
        "application source_sha256",
    )

    raw_operations = _parse_sequence_of_mappings(
        value["operations"],
        "application operations",
    )
    operations = tuple(
        _parse_operation(operation, index)
        for index, operation in enumerate(raw_operations)
    )

    entry_keys = tuple(
        operation["entry_key"]
        for operation in operations
    )
    if len(set(entry_keys)) != len(entry_keys):
        raise BulkCollectionImportPersistenceError(
            "Application operation entry keys must be unique."
        )

    _validate_summary(value["summary"], operations)
    _validate_group_coverage(value["groups"], entry_keys)

    create_keys = tuple(
        operation["collection_key"]
        for operation in operations
        if operation["action"] == "create_record"
    )
    if len(set(create_keys)) != len(create_keys):
        raise BulkCollectionImportPersistenceError(
            "Application create Collection keys must be unique."
        )

    return MappingProxyType(
        {
            "import_id": import_id,
            "source_sha256": source_sha256,
            "operations": operations,
        }
    )


def _parse_operation(
    value: Mapping[str, Any],
    index: int,
) -> Mapping[str, Any]:
    label = f"application operations[{index}]"
    _require_exact_mapping(
        value,
        _APPLICATION_OPERATION_KEYS,
        label,
    )

    action = value["action"]
    if action not in _APPLICATION_ACTIONS:
        raise BulkCollectionImportPersistenceError(
            f"{label}.action is not supported."
        )

    collection_key = _optional_text(
        value["collection_key"],
        f"{label}.collection_key",
    )
    expected_sha256 = value["expected_shared_sha256"]
    title_value = _optional_text(
        value["title_value"],
        f"{label}.title_value",
    )

    source_references = _parse_source_references(
        value["source_references"],
        f"{label}.source_references",
    )
    source_reference_additions = _parse_source_references(
        value["source_reference_additions"],
        f"{label}.source_reference_additions",
    )
    attributes = _parse_attributes(
        value["attributes"],
        f"{label}.attributes",
    )
    changes = _parse_attribute_changes(
        value["attribute_changes"],
        f"{label}.attribute_changes",
    )
    warnings = _parse_warnings(
        value["warnings"],
        f"{label}.warnings",
    )

    if action == "create_record":
        if collection_key is None or expected_sha256 is not None:
            raise BulkCollectionImportPersistenceError(
                "create_record requires a target key and no "
                "existing-state fingerprint."
            )
        if title_value is None:
            raise BulkCollectionImportPersistenceError(
                "create_record requires a title."
            )
        if source_reference_additions or changes:
            raise BulkCollectionImportPersistenceError(
                "create_record cannot contain update-only fields."
            )

    elif action == "update_record":
        if collection_key is None:
            raise BulkCollectionImportPersistenceError(
                "update_record requires a Collection target."
            )
        _require_sha256(
            expected_sha256,
            f"{label}.expected_shared_sha256",
        )
        if source_references or attributes:
            raise BulkCollectionImportPersistenceError(
                "update_record cannot contain create-only fields."
            )

    elif action == "no_change":
        if collection_key is None:
            raise BulkCollectionImportPersistenceError(
                "no_change requires a Collection target."
            )
        _require_sha256(
            expected_sha256,
            f"{label}.expected_shared_sha256",
        )
        if (
            title_value is not None
            or source_references
            or source_reference_additions
            or attributes
            or changes
        ):
            raise BulkCollectionImportPersistenceError(
                "no_change cannot contain write data."
            )

    elif action == "skip":
        if (
            collection_key is not None
            or expected_sha256 is not None
            or title_value is not None
            or source_references
            or source_reference_additions
            or attributes
            or changes
        ):
            raise BulkCollectionImportPersistenceError(
                "skip cannot contain a target, fingerprint, or "
                "write data."
            )

    return MappingProxyType(
        {
            "entry_key": _require_text(
                value["entry_key"],
                f"{label}.entry_key",
            ),
            "action": action,
            "collection_key": collection_key,
            "expected_shared_sha256": expected_sha256,
            "title_value": title_value,
            "source_references": source_references,
            "source_reference_additions": (
                source_reference_additions
            ),
            "attributes": attributes,
            "attribute_changes": changes,
            "warnings": warnings,
        }
    )


def _validate_summary(
    value: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
) -> None:
    _require_exact_mapping(
        value,
        _APPLICATION_SUMMARY_KEYS,
        "application summary",
    )

    expected = {
        "total": len(operations),
        **{
            action: sum(
                operation["action"] == action
                for operation in operations
            )
            for action in _APPLICATION_ACTIONS
        },
    }

    for key in _APPLICATION_SUMMARY_KEYS:
        actual = value[key]
        if (
            type(actual) is not int
            or actual < 0
            or actual != expected[key]
        ):
            raise BulkCollectionImportPersistenceError(
                "Application summary does not match its operations."
            )


def _validate_group_coverage(
    value: Sequence[Mapping[str, Any]],
    entry_keys: tuple[str, ...],
) -> None:
    groups = _parse_sequence_of_mappings(value, "application groups")
    flattened = []
    seen = set()

    for index, group in enumerate(groups):
        label = f"application groups[{index}]"
        _require_exact_mapping(
            group,
            ("group_key", "title", "entry_keys"),
            label,
        )
        group_key = _require_text(
            group["group_key"],
            f"{label}.group_key",
        )
        if group_key in seen:
            raise BulkCollectionImportPersistenceError(
                "Application group keys must be unique."
            )
        seen.add(group_key)
        _require_text(
            group["title"],
            f"{label}.title",
        )

        raw_entry_keys = group["entry_keys"]
        if (
            isinstance(
                raw_entry_keys,
                (str, bytes, bytearray),
            )
            or not isinstance(raw_entry_keys, Sequence)
        ):
            raise BulkCollectionImportPersistenceError(
                f"{label}.entry_keys must be a sequence."
            )
        flattened.extend(
            _require_text(
                entry_key,
                f"{label}.entry_key",
            )
            for entry_key in raw_entry_keys
        )

    if tuple(flattened) != entry_keys:
        raise BulkCollectionImportPersistenceError(
            "Application groups must cover operations exactly "
            "once and preserve order."
        )


def _parse_source_references(
    value: Any,
    label: str,
) -> tuple[Mapping[str, str], ...]:
    references = _parse_sequence_of_mappings(value, label)
    result = []
    seen = set()

    for index, reference in enumerate(references):
        if set(reference) != {"source", "external_id"}:
            raise BulkCollectionImportPersistenceError(
                f"{label}[{index}] fields are invalid."
            )
        source = _require_text(
            reference["source"],
            f"{label}[{index}].source",
        )
        external_id = _require_text(
            reference["external_id"],
            f"{label}[{index}].external_id",
        )
        key = (source, external_id)
        if key in seen:
            raise BulkCollectionImportPersistenceError(
                f"{label} contains a duplicate source identity."
            )
        seen.add(key)
        result.append(
            MappingProxyType(
                {
                    "source": source,
                    "external_id": external_id,
                }
            )
        )

    return tuple(result)


def _parse_attributes(
    value: Mapping[str, Any],
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportPersistenceError(
            f"{label} must be a mapping."
        )

    return MappingProxyType(
        {
            _require_text(
                field,
                f"{label} field",
            ): _freeze_json(
                item,
                f"{label}.{field}",
            )
            for field, item in value.items()
        }
    )


def _parse_attribute_changes(
    value: Any,
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    changes = _parse_sequence_of_mappings(value, label)
    result = []
    seen = set()

    for index, change in enumerate(changes):
        if set(change) != {"field", "value"}:
            raise BulkCollectionImportPersistenceError(
                f"{label}[{index}] fields are invalid."
            )
        field = _require_text(
            change["field"],
            f"{label}[{index}].field",
        )
        if field in seen:
            raise BulkCollectionImportPersistenceError(
                f"{label} contains a duplicate field."
            )
        seen.add(field)
        result.append(
            MappingProxyType(
                {
                    "field": field,
                    "value": _freeze_json(
                        change["value"],
                        f"{label}[{index}].value",
                    ),
                }
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
        raise BulkCollectionImportPersistenceError(
            f"{label} must be a sequence."
        )

    result = []
    for warning in value:
        code = _require_text(warning, f"{label} warning")
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
        raise BulkCollectionImportPersistenceError(
            f"{label} must be a sequence."
        )

    result = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            raise BulkCollectionImportPersistenceError(
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
        raise BulkCollectionImportPersistenceError(
            f"{label} must be a mapping."
        )
    if set(value) != set(expected_keys):
        raise BulkCollectionImportPersistenceError(
            f"{label} fields do not match the expected contract."
        )


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportPersistenceError(
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
        raise BulkCollectionImportPersistenceError(
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
            raise BulkCollectionImportPersistenceError(
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

    raise BulkCollectionImportPersistenceError(
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


def _outcome_for_action(action: str) -> str:
    return {
        "create_record": "created",
        "update_record": "updated",
        "no_change": "unchanged",
        "skip": "skipped",
    }[action]


__all__ = [
    "BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_SCHEMA",
    "BULK_COLLECTION_IMPORT_PERSISTENCE_RESULT_VERSION",
    "BULK_COLLECTION_IMPORT_PERSISTENCE_OUTCOMES",
    "BulkCollectionImportPersistenceError",
    "BulkCollectionImportPersistenceItem",
    "BulkCollectionImportPersistenceResult",
    "execute_bulk_collection_import_application_plan",
    "bulk_collection_import_persistence_result_to_document",
    "serialize_bulk_collection_import_persistence_result",
]
