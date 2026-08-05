"""Immutable versioned contract for bulk Collection imports."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping


BULK_COLLECTION_IMPORT_SCHEMA = "smwc-bulk-collection-import"
BULK_COLLECTION_IMPORT_VERSION = 1

BULK_COLLECTION_IMPORT_DOCUMENT_KEYS = (
    "schema",
    "version",
    "import_id",
    "title",
    "entries",
    "groups",
)
BULK_COLLECTION_IMPORT_ENTRY_KEYS = (
    "entry_key",
    "title",
    "source_references",
    "attributes",
)
BULK_COLLECTION_IMPORT_SOURCE_REFERENCE_KEYS = (
    "source",
    "external_id",
)
BULK_COLLECTION_IMPORT_GROUP_KEYS = (
    "group_key",
    "title",
    "entry_keys",
)

BULK_COLLECTION_IMPORT_ID_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)
BULK_COLLECTION_IMPORT_ENTRY_KEY_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)
BULK_COLLECTION_IMPORT_GROUP_KEY_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)
BULK_COLLECTION_IMPORT_SOURCE_PATTERN = re.compile(
    r"^[a-z][a-z0-9._-]{0,31}$"
)

BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS = frozenset(
    {
        "completed",
        "completed_date",
        "completion_date",
        "download_paths",
        "notes",
        "personal_rating",
        "planner",
        "planner_state",
        "rom_paths",
        "save_associations",
        "save_paths",
    }
)


class BulkCollectionImportError(ValueError):
    """Raised when a bulk Collection import violates its contract."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportSourceReference:
    """One external identity attached to an imported entry."""

    source: str
    external_id: str


@dataclass(frozen=True, slots=True)
class BulkCollectionImportEntry:
    """One normalized imported hack record."""

    entry_key: str
    title: str
    source_references: tuple[
        BulkCollectionImportSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportGroup:
    """One ordered group of imported entry keys."""

    group_key: str
    title: str
    entry_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportDocument:
    """Detached immutable bulk Collection import document."""

    schema: str
    version: int
    import_id: str
    title: str
    entries: tuple[BulkCollectionImportEntry, ...]
    groups: tuple[BulkCollectionImportGroup, ...]


def parse_bulk_collection_import(
    document: Any,
) -> BulkCollectionImportDocument:
    """Validate and deeply detach one import document."""

    _require_exact_mapping(
        document,
        BULK_COLLECTION_IMPORT_DOCUMENT_KEYS,
        "Bulk Collection import",
    )

    schema = document["schema"]
    if schema != BULK_COLLECTION_IMPORT_SCHEMA:
        raise BulkCollectionImportError(
            "Unsupported bulk Collection import schema."
        )

    version = document["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != BULK_COLLECTION_IMPORT_VERSION
    ):
        raise BulkCollectionImportError(
            "Unsupported bulk Collection import version."
        )

    import_id = _require_pattern_text(
        document["import_id"],
        BULK_COLLECTION_IMPORT_ID_PATTERN,
        "import_id",
    )
    title = _require_title(document["title"], "title")
    entries = _parse_entries(document["entries"])
    groups = _parse_groups(document["groups"])

    _validate_global_source_uniqueness(entries)
    _validate_order_coverage(entries, groups)

    return BulkCollectionImportDocument(
        schema=schema,
        version=version,
        import_id=import_id,
        title=title,
        entries=entries,
        groups=groups,
    )


def bulk_collection_import_to_document(
    import_document: BulkCollectionImportDocument,
) -> dict[str, Any]:
    """Return a detached canonical import document."""

    if not isinstance(
        import_document,
        BulkCollectionImportDocument,
    ):
        raise TypeError(
            "import_document must be a BulkCollectionImportDocument"
        )

    return {
        "schema": import_document.schema,
        "version": import_document.version,
        "import_id": import_document.import_id,
        "title": import_document.title,
        "entries": [
            {
                "entry_key": entry.entry_key,
                "title": entry.title,
                "source_references": [
                    {
                        "source": reference.source,
                        "external_id": reference.external_id,
                    }
                    for reference in entry.source_references
                ],
                "attributes": _thaw_json(entry.attributes),
            }
            for entry in import_document.entries
        ],
        "groups": [
            {
                "group_key": group.group_key,
                "title": group.title,
                "entry_keys": list(group.entry_keys),
            }
            for group in import_document.groups
        ],
    }


def serialize_bulk_collection_import(
    import_document: BulkCollectionImportDocument,
) -> str:
    """Serialize an import document as deterministic compact JSON."""

    return json.dumps(
        bulk_collection_import_to_document(import_document),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _parse_entries(value: Any) -> tuple[BulkCollectionImportEntry, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportError("entries must be a JSON array.")

    parsed = []
    entry_keys = set()
    for index, item in enumerate(value):
        label = f"entries[{index}]"
        _require_exact_mapping(
            item,
            BULK_COLLECTION_IMPORT_ENTRY_KEYS,
            label,
        )

        entry_key = _require_pattern_text(
            item["entry_key"],
            BULK_COLLECTION_IMPORT_ENTRY_KEY_PATTERN,
            f"{label}.entry_key",
        )
        if entry_key in entry_keys:
            raise BulkCollectionImportError(
                f"Duplicate entry_key: {entry_key}"
            )
        entry_keys.add(entry_key)

        parsed.append(
            BulkCollectionImportEntry(
                entry_key=entry_key,
                title=_require_title(
                    item["title"],
                    f"{label}.title",
                ),
                source_references=_parse_source_references(
                    item["source_references"],
                    label,
                ),
                attributes=_parse_attributes(
                    item["attributes"],
                    label,
                ),
            )
        )

    return tuple(parsed)


def _parse_source_references(
    value: Any,
    entry_label: str,
) -> tuple[BulkCollectionImportSourceReference, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportError(
            f"{entry_label}.source_references must be a JSON array."
        )

    parsed = []
    local_pairs = set()
    for index, item in enumerate(value):
        label = f"{entry_label}.source_references[{index}]"
        _require_exact_mapping(
            item,
            BULK_COLLECTION_IMPORT_SOURCE_REFERENCE_KEYS,
            label,
        )

        source = _require_pattern_text(
            item["source"],
            BULK_COLLECTION_IMPORT_SOURCE_PATTERN,
            f"{label}.source",
        )
        external_id = _require_external_id(
            item["external_id"],
            f"{label}.external_id",
        )
        pair = (source, external_id)
        if pair in local_pairs:
            raise BulkCollectionImportError(
                "Duplicate source reference on one entry: "
                f"{source}:{external_id}"
            )
        local_pairs.add(pair)
        parsed.append(
            BulkCollectionImportSourceReference(
                source=source,
                external_id=external_id,
            )
        )

    return tuple(parsed)


def _parse_attributes(
    value: Any,
    entry_label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise BulkCollectionImportError(
            f"{entry_label}.attributes must be a JSON object."
        )

    forbidden = sorted(
        set(value)
        & BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS
    )
    if forbidden:
        raise BulkCollectionImportError(
            "Imported attributes may not contain user-owned "
            "Collection state: "
            + ", ".join(forbidden)
        )

    return _freeze_json(value, f"{entry_label}.attributes")


def _parse_groups(
    value: Any,
) -> tuple[BulkCollectionImportGroup, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportError("groups must be a JSON array.")

    parsed = []
    group_keys = set()
    for index, item in enumerate(value):
        label = f"groups[{index}]"
        _require_exact_mapping(
            item,
            BULK_COLLECTION_IMPORT_GROUP_KEYS,
            label,
        )

        group_key = _require_pattern_text(
            item["group_key"],
            BULK_COLLECTION_IMPORT_GROUP_KEY_PATTERN,
            f"{label}.group_key",
        )
        if group_key in group_keys:
            raise BulkCollectionImportError(
                f"Duplicate group_key: {group_key}"
            )
        group_keys.add(group_key)

        entry_keys_value = item["entry_keys"]
        if not isinstance(entry_keys_value, list):
            raise BulkCollectionImportError(
                f"{label}.entry_keys must be a JSON array."
            )

        entry_keys = []
        for entry_index, entry_key_value in enumerate(
            entry_keys_value
        ):
            entry_keys.append(
                _require_pattern_text(
                    entry_key_value,
                    BULK_COLLECTION_IMPORT_ENTRY_KEY_PATTERN,
                    f"{label}.entry_keys[{entry_index}]",
                )
            )

        parsed.append(
            BulkCollectionImportGroup(
                group_key=group_key,
                title=_require_title(
                    item["title"],
                    f"{label}.title",
                ),
                entry_keys=tuple(entry_keys),
            )
        )

    return tuple(parsed)


def _validate_global_source_uniqueness(
    entries: tuple[BulkCollectionImportEntry, ...],
) -> None:
    owners = {}
    for entry in entries:
        for reference in entry.source_references:
            key = (reference.source, reference.external_id)
            existing = owners.get(key)
            if existing is not None:
                raise BulkCollectionImportError(
                    "Source reference belongs to more than one "
                    f"entry: {reference.source}:"
                    f"{reference.external_id} "
                    f"({existing}, {entry.entry_key})"
                )
            owners[key] = entry.entry_key


def _validate_order_coverage(
    entries: tuple[BulkCollectionImportEntry, ...],
    groups: tuple[BulkCollectionImportGroup, ...],
) -> None:
    expected = {entry.entry_key for entry in entries}
    seen = set()

    for group in groups:
        for entry_key in group.entry_keys:
            if entry_key not in expected:
                raise BulkCollectionImportError(
                    "Ordered group references unknown entry_key: "
                    f"{entry_key}"
                )
            if entry_key in seen:
                raise BulkCollectionImportError(
                    "Imported entry appears more than once in ordered "
                    f"groups: {entry_key}"
                )
            seen.add(entry_key)

    missing = sorted(expected - seen)
    if missing:
        raise BulkCollectionImportError(
            "Every imported entry must appear exactly once in ordered "
            "groups; missing: "
            + ", ".join(missing)
        )


def _require_exact_mapping(
    value: Any,
    expected_keys: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(value, dict):
        raise BulkCollectionImportError(
            f"{label} must be a JSON object."
        )

    expected = set(expected_keys)
    actual = set(value)
    if actual == expected:
        return

    details = []
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unexpected:
        details.append("unexpected: " + ", ".join(unexpected))
    raise BulkCollectionImportError(
        f"{label} fields must match the versioned contract "
        f"({'; '.join(details)})."
    )


def _require_pattern_text(
    value: Any,
    pattern: re.Pattern[str],
    label: str,
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise BulkCollectionImportError(
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
        raise BulkCollectionImportError(
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
        raise BulkCollectionImportError(
            f"{label} must be a non-empty non-whitespace "
            "string of at most 256 characters."
        )
    return value


def _freeze_json(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise BulkCollectionImportError(
                f"{label} contains a non-finite number."
            )
        return value

    if isinstance(value, list):
        return tuple(
            _freeze_json(item, f"{label}[{index}]")
            for index, item in enumerate(value)
        )

    if isinstance(value, dict):
        frozen = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise BulkCollectionImportError(
                    f"{label} contains a non-string object key."
                )
            frozen[key] = _freeze_json(
                item,
                f"{label}.{key}",
            )
        return MappingProxyType(frozen)

    raise BulkCollectionImportError(
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


__all__ = [
    "BULK_COLLECTION_IMPORT_SCHEMA",
    "BULK_COLLECTION_IMPORT_VERSION",
    "BULK_COLLECTION_IMPORT_DOCUMENT_KEYS",
    "BULK_COLLECTION_IMPORT_ENTRY_KEYS",
    "BULK_COLLECTION_IMPORT_SOURCE_REFERENCE_KEYS",
    "BULK_COLLECTION_IMPORT_GROUP_KEYS",
    "BULK_COLLECTION_IMPORT_ID_PATTERN",
    "BULK_COLLECTION_IMPORT_ENTRY_KEY_PATTERN",
    "BULK_COLLECTION_IMPORT_GROUP_KEY_PATTERN",
    "BULK_COLLECTION_IMPORT_SOURCE_PATTERN",
    "BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS",
    "BulkCollectionImportError",
    "BulkCollectionImportSourceReference",
    "BulkCollectionImportEntry",
    "BulkCollectionImportGroup",
    "BulkCollectionImportDocument",
    "parse_bulk_collection_import",
    "bulk_collection_import_to_document",
    "serialize_bulk_collection_import",
]
