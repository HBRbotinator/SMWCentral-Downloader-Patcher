"""Allocate real v5.1 Collection keys for resolved bulk-import creates."""

from __future__ import annotations

import hashlib
import json
import re
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from bulk_collection_import_application import (
    build_bulk_collection_import_application_plan,
)


COLLECTION_IMPORT_LOCAL_KEY_PREFIX = "usr_import_"
COLLECTION_IMPORT_LOCAL_KEY_HEX_LENGTH = 16

_RESOLUTION_SCHEMA = "smwc-bulk-collection-resolution-plan"
_RESOLUTION_VERSION = 1
_RESOLUTION_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "review_required",
    "skip",
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_COLLECTION_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class BulkCollectionImportKeyAllocationError(ValueError):
    """Raised when v5.1 Collection keys cannot be allocated safely."""


def allocate_bulk_collection_import_keys(
    resolution_document: Mapping[str, Any],
    existing_collection_keys: Sequence[str],
) -> Mapping[str, str]:
    """Allocate immutable Collection keys for create_record rows only."""

    resolution = _parse_resolution_header_and_items(
        resolution_document
    )
    existing = _parse_existing_collection_keys(
        existing_collection_keys
    )

    assignments: dict[str, str] = {}
    allocated_values: set[str] = set()

    for item in resolution["items"]:
        if item["action"] != "create_record":
            continue

        collection_key = _allocate_create_key(
            import_id=resolution["import_id"],
            source_sha256=resolution["source_sha256"],
            entry_key=item["entry_key"],
            source_references=item["source_references"],
        )

        if collection_key in existing:
            raise BulkCollectionImportKeyAllocationError(
                f"Allocated Collection key already exists: {collection_key}"
            )
        if collection_key in allocated_values:
            raise BulkCollectionImportKeyAllocationError(
                f"Multiple creates resolve to Collection key: {collection_key}"
            )

        allocated_values.add(collection_key)
        assignments[item["entry_key"]] = collection_key

    return MappingProxyType(assignments)


def bulk_collection_import_key_assignments_to_document(
    assignments: Mapping[str, str],
) -> dict[str, str]:
    """Project immutable assignments to a detached ordered mapping."""

    if not isinstance(assignments, Mapping):
        raise TypeError("assignments must be a mapping")

    result = {}
    for raw_entry_key, raw_collection_key in assignments.items():
        entry_key = _require_text(
            raw_entry_key,
            "assignment entry_key",
        )
        collection_key = _require_collection_key(
            raw_collection_key,
            f"assignment {entry_key}",
        )
        result[entry_key] = collection_key

    return result


def serialize_bulk_collection_import_key_assignments(
    assignments: Mapping[str, str],
) -> str:
    """Serialize assignments as stable compact JSON."""

    return json.dumps(
        bulk_collection_import_key_assignments_to_document(
            assignments
        ),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def build_v5_1_bulk_collection_import_application_plan(
    resolution_document: Mapping[str, Any],
    collection_records: Sequence[Mapping[str, Any]],
):
    """Allocate v5.1 create keys and feed them into the generic app planner."""

    existing_keys = tuple(
        _require_collection_key(
            record.get("collection_key")
            if isinstance(record, Mapping)
            else None,
            "collection record key",
        )
        for record in collection_records
    )

    assignments = allocate_bulk_collection_import_keys(
        resolution_document,
        existing_keys,
    )

    return build_bulk_collection_import_application_plan(
        resolution_document,
        assignments,
        collection_records,
    )


def _allocate_create_key(
    *,
    import_id: str,
    source_sha256: str,
    entry_key: str,
    source_references: tuple[tuple[str, str], ...],
) -> str:
    smwc_ids = {
        external_id
        for source, external_id in source_references
        if source == "smwc"
    }

    if len(smwc_ids) > 1:
        raise BulkCollectionImportKeyAllocationError(
            "A create row cannot contain multiple distinct SMWCentral IDs."
        )

    if smwc_ids:
        raw_smwc_id = next(iter(smwc_ids))
        if not raw_smwc_id.isdecimal():
            raise BulkCollectionImportKeyAllocationError(
                "SMWCentral external IDs must be decimal."
            )

        canonical = str(int(raw_smwc_id, 10))
        if canonical == "0":
            raise BulkCollectionImportKeyAllocationError(
                "SMWCentral external ID must be greater than zero."
            )
        return canonical

    if source_references:
        canonical_sources = [
            {
                "source": source,
                "external_id": external_id,
            }
            for source, external_id in sorted(source_references)
        ]
        seed = {
            "kind": "source_identity",
            "source_references": canonical_sources,
        }
    else:
        seed = {
            "kind": "import_entry",
            "import_id": import_id,
            "source_sha256": source_sha256,
            "entry_key": entry_key,
        }

    payload = json.dumps(
        seed,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()[
        :COLLECTION_IMPORT_LOCAL_KEY_HEX_LENGTH
    ]
    return f"{COLLECTION_IMPORT_LOCAL_KEY_PREFIX}{digest}"


def _parse_resolution_header_and_items(
    value: Mapping[str, Any],
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportKeyAllocationError(
            "resolution_document must be a mapping."
        )

    if value.get("schema") != _RESOLUTION_SCHEMA:
        raise BulkCollectionImportKeyAllocationError(
            "Resolution schema is not supported."
        )
    if value.get("version") != _RESOLUTION_VERSION:
        raise BulkCollectionImportKeyAllocationError(
            "Resolution version is not supported."
        )

    import_id = _require_text(
        value.get("import_id"),
        "resolution import_id",
    )
    source_sha256 = _require_sha256(
        value.get("source_sha256"),
        "resolution source_sha256",
    )

    raw_items = value.get("items")
    if (
        isinstance(raw_items, (str, bytes, bytearray))
        or not isinstance(raw_items, Sequence)
    ):
        raise BulkCollectionImportKeyAllocationError(
            "Resolution items must be a sequence."
        )

    items = []
    seen_entry_keys = set()
    for index, raw_item in enumerate(raw_items):
        if not isinstance(raw_item, Mapping):
            raise BulkCollectionImportKeyAllocationError(
                f"Resolution item {index} must be a mapping."
            )

        entry_key = _require_text(
            raw_item.get("entry_key"),
            f"resolution item {index} entry_key",
        )
        if entry_key in seen_entry_keys:
            raise BulkCollectionImportKeyAllocationError(
                "Resolution entry keys must be unique."
            )
        seen_entry_keys.add(entry_key)

        action = raw_item.get("action")
        if action not in _RESOLUTION_ACTIONS:
            raise BulkCollectionImportKeyAllocationError(
                f"Unsupported resolution action: {action}"
            )
        if action == "review_required":
            raise BulkCollectionImportKeyAllocationError(
                "Unresolved review rows block Collection key allocation."
            )

        references = _parse_source_references(
            raw_item.get("source_reference_additions", ()),
            f"resolution item {index} source references",
        )

        items.append(
            MappingProxyType(
                {
                    "entry_key": entry_key,
                    "action": action,
                    "source_references": references,
                }
            )
        )

    _validate_summary(value.get("summary"), tuple(items))

    return MappingProxyType(
        {
            "import_id": import_id,
            "source_sha256": source_sha256,
            "items": tuple(items),
        }
    )


def _validate_summary(
    value: Any,
    items: tuple[Mapping[str, Any], ...],
) -> None:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportKeyAllocationError(
            "Resolution summary must be a mapping."
        )

    expected_keys = ("total", *_RESOLUTION_ACTIONS)
    if set(value) != set(expected_keys):
        raise BulkCollectionImportKeyAllocationError(
            "Resolution summary fields do not match the contract."
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

    for key in expected_keys:
        actual = value[key]
        if (
            type(actual) is not int
            or actual < 0
            or actual != expected[key]
        ):
            raise BulkCollectionImportKeyAllocationError(
                "Resolution summary does not match its items."
            )


def _parse_source_references(
    value: Any,
    label: str,
) -> tuple[tuple[str, str], ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportKeyAllocationError(
            f"{label} must be a sequence."
        )

    references = []
    seen = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise BulkCollectionImportKeyAllocationError(
                f"{label}[{index}] must be a mapping."
            )
        if set(raw) != {"source", "external_id"}:
            raise BulkCollectionImportKeyAllocationError(
                f"{label}[{index}] fields are invalid."
            )

        source = _require_text(
            raw["source"],
            f"{label}[{index}].source",
        )
        external_id = _require_text(
            raw["external_id"],
            f"{label}[{index}].external_id",
        )
        pair = (source, external_id)
        if pair in seen:
            continue
        seen.add(pair)
        references.append(pair)

    return tuple(references)


def _parse_existing_collection_keys(
    values: Sequence[str],
) -> frozenset[str]:
    if (
        isinstance(values, (str, bytes, bytearray))
        or not isinstance(values, Sequence)
    ):
        raise BulkCollectionImportKeyAllocationError(
            "existing_collection_keys must be a sequence."
        )

    keys = []
    for index, raw in enumerate(values):
        keys.append(
            _require_collection_key(
                raw,
                f"existing_collection_keys[{index}]",
            )
        )

    if len(set(keys)) != len(keys):
        raise BulkCollectionImportKeyAllocationError(
            "Existing Collection keys must be unique."
        )

    return frozenset(keys)


def _require_collection_key(
    value: Any,
    label: str,
) -> str:
    text = _require_text(value, label)
    if _COLLECTION_KEY_PATTERN.fullmatch(text) is None:
        raise BulkCollectionImportKeyAllocationError(
            f"{label} is not a valid v5.1 Collection key."
        )
    return text


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportKeyAllocationError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


def _require_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA256_PATTERN.fullmatch(value) is None
    ):
        raise BulkCollectionImportKeyAllocationError(
            f"{label} must be a lowercase 64-character SHA-256."
        )
    return value


__all__ = [
    "COLLECTION_IMPORT_LOCAL_KEY_PREFIX",
    "COLLECTION_IMPORT_LOCAL_KEY_HEX_LENGTH",
    "BulkCollectionImportKeyAllocationError",
    "allocate_bulk_collection_import_keys",
    "bulk_collection_import_key_assignments_to_document",
    "serialize_bulk_collection_import_key_assignments",
    "build_v5_1_bulk_collection_import_application_plan",
]
