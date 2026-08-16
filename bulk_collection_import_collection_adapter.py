"""Project the real v5.1 Collection into bulk-import snapshots."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from bulk_collection_import import (
    BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS,
    BULK_COLLECTION_IMPORT_SOURCE_PATTERN,
)


COLLECTION_IMPORT_EXTENSION_KEY = "bulk_collection_import"
COLLECTION_IMPORT_EXTENSION_VERSION = 1
COLLECTION_IMPORT_EXTENSION_KEYS = (
    "version",
    "aliases",
    "source_references",
    "attributes",
)

CORE_SHARED_ATTRIBUTE_KEYS = (
    "authors",
    "difficulty",
    "exit_count",
    "release_date",
)

_COLLECTION_KEY_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)
_EXTENSION_FORBIDDEN_ATTRIBUTE_KEYS = frozenset(
    {
        *BULK_COLLECTION_IMPORT_FORBIDDEN_ATTRIBUTE_KEYS,
        *CORE_SHARED_ATTRIBUTE_KEYS,
        "additional_paths",
        "file_path",
        "files",
        "local_save_entry",
        "provider_extension",
        "save_sync_metadata",
        "time_to_beat",
    }
)


class BulkCollectionImportCollectionProjectionError(ValueError):
    """Raised when v5.1 Collection data cannot be projected safely."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportCollectionSourceReference:
    """One source identity owned by a v5.1 Collection record."""

    source: str
    external_id: str


@dataclass(frozen=True, slots=True)
class BulkCollectionImportCollectionIdentitySnapshot:
    """One immutable identity snapshot for the generic resolver."""

    collection_key: str
    title: str
    aliases: tuple[str, ...]
    source_references: tuple[
        BulkCollectionImportCollectionSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportCollectionRecordSnapshot:
    """One immutable shared-state snapshot for conservative merging."""

    collection_key: str
    title: str
    source_references: tuple[
        BulkCollectionImportCollectionSourceReference,
        ...,
    ]
    attributes: Mapping[str, Any]
    user_state: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportCollectionProjection:
    """Detached ordered v5.1 Collection projection."""

    identities: tuple[
        BulkCollectionImportCollectionIdentitySnapshot,
        ...,
    ]
    records: tuple[
        BulkCollectionImportCollectionRecordSnapshot,
        ...,
    ]


def project_bulk_collection_import_collection(
    collection: Mapping[str, Mapping[str, Any]],
) -> BulkCollectionImportCollectionProjection:
    """Project HackDataManager.data without modifying Collection state."""

    if not isinstance(collection, Mapping):
        raise BulkCollectionImportCollectionProjectionError(
            "Collection data must be a mapping."
        )

    identities = []
    records = []

    for raw_collection_key, raw_record in collection.items():
        collection_key = _require_collection_key(
            raw_collection_key
        )
        if not isinstance(raw_record, Mapping):
            raise BulkCollectionImportCollectionProjectionError(
                f"Collection record {collection_key} must be a mapping."
            )

        title = _require_title(
            raw_record.get("title"),
            f"Collection record {collection_key} title",
        )
        extension = _parse_extension(
            raw_record,
            collection_key,
        )
        source_references = _build_source_references(
            collection_key,
            extension["source_references"],
        )
        attributes = _build_shared_attributes(
            raw_record,
            extension["attributes"],
            collection_key,
        )

        identity = BulkCollectionImportCollectionIdentitySnapshot(
            collection_key=collection_key,
            title=title,
            aliases=extension["aliases"],
            source_references=source_references,
            attributes=attributes,
        )
        record = BulkCollectionImportCollectionRecordSnapshot(
            collection_key=collection_key,
            title=title,
            source_references=source_references,
            attributes=attributes,
            user_state=MappingProxyType({}),
        )

        identities.append(identity)
        records.append(record)

    return BulkCollectionImportCollectionProjection(
        identities=tuple(identities),
        records=tuple(records),
    )


def project_bulk_collection_import_hack_data_manager(
    data_manager: Any,
) -> BulkCollectionImportCollectionProjection:
    """Project the live v5.1 HackDataManager Collection read-only."""

    from hack_data_manager import HackDataManager

    if not isinstance(data_manager, HackDataManager):
        raise TypeError(
            "data_manager must be a HackDataManager"
        )

    return project_bulk_collection_import_collection(
        data_manager.data
    )


def bulk_collection_import_collection_identities_to_documents(
    projection: BulkCollectionImportCollectionProjection,
) -> list[dict[str, Any]]:
    """Return detached identity documents accepted by the resolver."""

    _require_projection(projection)

    return [
        {
            "collection_key": identity.collection_key,
            "title": identity.title,
            "aliases": list(identity.aliases),
            "source_references": [
                _source_reference_to_document(reference)
                for reference in identity.source_references
            ],
            "attributes": {
                field: _thaw_json(value)
                for field, value in identity.attributes.items()
            },
        }
        for identity in projection.identities
    ]


def bulk_collection_import_collection_records_to_documents(
    projection: BulkCollectionImportCollectionProjection,
) -> list[dict[str, Any]]:
    """Return detached Collection documents accepted by merge planning."""

    _require_projection(projection)

    return [
        {
            "collection_key": record.collection_key,
            "title": record.title,
            "source_references": [
                _source_reference_to_document(reference)
                for reference in record.source_references
            ],
            "attributes": {
                field: _thaw_json(value)
                for field, value in record.attributes.items()
            },
            "user_state": {},
        }
        for record in projection.records
    ]


def _parse_extension(
    record: Mapping[str, Any],
    collection_key: str,
) -> Mapping[str, Any]:
    if COLLECTION_IMPORT_EXTENSION_KEY not in record:
        return MappingProxyType(
            {
                "aliases": (),
                "source_references": (),
                "attributes": MappingProxyType({}),
            }
        )

    value = record[COLLECTION_IMPORT_EXTENSION_KEY]
    label = (
        f"Collection record {collection_key}."
        f"{COLLECTION_IMPORT_EXTENSION_KEY}"
    )
    _require_exact_mapping(
        value,
        COLLECTION_IMPORT_EXTENSION_KEYS,
        label,
    )

    version = value["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != COLLECTION_IMPORT_EXTENSION_VERSION
    ):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label}.version is not supported."
        )

    aliases = _parse_aliases(
        value["aliases"],
        f"{label}.aliases",
    )
    references = _parse_source_references(
        value["source_references"],
        f"{label}.source_references",
    )
    attributes = _parse_extension_attributes(
        value["attributes"],
        f"{label}.attributes",
    )

    return MappingProxyType(
        {
            "aliases": aliases,
            "source_references": references,
            "attributes": attributes,
        }
    )


def _build_source_references(
    collection_key: str,
    explicit_references: Sequence[
        BulkCollectionImportCollectionSourceReference
    ],
) -> tuple[BulkCollectionImportCollectionSourceReference, ...]:
    result = []
    seen = set()

    if collection_key.isdigit():
        smwc_reference = BulkCollectionImportCollectionSourceReference(
            source="smwc",
            external_id=collection_key,
        )
        result.append(smwc_reference)
        seen.add(("smwc", collection_key))

    for reference in explicit_references:
        key = (reference.source, reference.external_id)

        if reference.source == "smwc" and collection_key.isdigit():
            if reference.external_id != collection_key:
                raise BulkCollectionImportCollectionProjectionError(
                    "Numeric Collection keys are authoritative SMWC "
                    "identities and cannot be linked to another "
                    "SMWCentral ID."
                )
            if key in seen:
                continue

        if key in seen:
            raise BulkCollectionImportCollectionProjectionError(
                "Collection import extension contains a duplicate "
                f"source identity: {reference.source}:"
                f"{reference.external_id}"
            )

        seen.add(key)
        result.append(reference)

    return tuple(result)


def _build_shared_attributes(
    record: Mapping[str, Any],
    extension_attributes: Mapping[str, Any],
    collection_key: str,
) -> Mapping[str, Any]:
    attributes: dict[str, Any] = {}

    authors = record.get("authors", [])
    attributes["authors"] = _parse_authors(
        authors,
        f"Collection record {collection_key}.authors",
    )

    difficulty = _optional_shared_text(
        record.get("current_difficulty"),
        f"Collection record {collection_key}.current_difficulty",
    )
    if (
        difficulty is not None
        and difficulty not in ("No Difficulty", "Unknown")
    ):
        attributes["difficulty"] = difficulty

    if "exits" in record:
        exits = record["exits"]
        if (
            isinstance(exits, bool)
            or not isinstance(exits, int)
            or exits < 0
        ):
            raise BulkCollectionImportCollectionProjectionError(
                f"Collection record {collection_key}.exits must be "
                "a non-negative integer."
            )
        attributes["exit_count"] = exits

    release_date = _optional_shared_text(
        record.get("date"),
        f"Collection record {collection_key}.date",
    )
    if release_date is not None:
        attributes["release_date"] = release_date

    for field, value in extension_attributes.items():
        attributes[field] = value

    return MappingProxyType(attributes)


def _parse_extension_attributes(
    value: Any,
    label: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} must be a JSON object."
        )

    forbidden = (
        set(value)
        & _EXTENSION_FORBIDDEN_ATTRIBUTE_KEYS
    )
    if forbidden:
        joined = ", ".join(sorted(forbidden))
        raise BulkCollectionImportCollectionProjectionError(
            "Bulk Collection import extension attributes cannot "
            f"contain reserved/local fields: {joined}"
        )

    return MappingProxyType(
        {
            _require_attribute_field(
                field,
                label,
            ): _freeze_json(
                item,
                f"{label}.{field}",
            )
            for field, item in value.items()
        }
    )


def _parse_aliases(
    value: Any,
    label: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} must be a JSON array."
        )

    aliases = []
    seen = set()
    for index, raw_alias in enumerate(value):
        alias = _require_title(
            raw_alias,
            f"{label}[{index}]",
        )
        if alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)

    return tuple(aliases)


def _parse_source_references(
    value: Any,
    label: str,
) -> tuple[BulkCollectionImportCollectionSourceReference, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} must be a JSON array."
        )

    references = []
    for index, item in enumerate(value):
        item_label = f"{label}[{index}]"
        _require_exact_mapping(
            item,
            ("source", "external_id"),
            item_label,
        )

        source = item["source"]
        if (
            not isinstance(source, str)
            or BULK_COLLECTION_IMPORT_SOURCE_PATTERN.fullmatch(
                source
            )
            is None
        ):
            raise BulkCollectionImportCollectionProjectionError(
                f"{item_label}.source is invalid."
            )

        external_id = _require_external_id(
            item["external_id"],
            f"{item_label}.external_id",
        )
        references.append(
            BulkCollectionImportCollectionSourceReference(
                source=source,
                external_id=external_id,
            )
        )

    return tuple(references)


def _parse_authors(
    value: Any,
    label: str,
) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} must be a JSON array."
        )

    authors = []
    for index, raw_author in enumerate(value):
        author = _require_title(
            raw_author,
            f"{label}[{index}]",
        )
        authors.append(author)

    return tuple(authors)


def _optional_shared_text(
    value: Any,
    label: str,
) -> str | None:
    if value is None or value == "":
        return None
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
    ):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} must be blank or a trimmed string."
        )
    return value


def _require_collection_key(value: Any) -> str:
    if (
        not isinstance(value, str)
        or _COLLECTION_KEY_PATTERN.fullmatch(value) is None
    ):
        raise BulkCollectionImportCollectionProjectionError(
            "Collection keys must use the v5.1 stable ID format."
        )
    return value


def _require_title(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
    ):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


def _require_external_id(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 512
    ):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


def _require_attribute_field(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 128
    ):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} contains an invalid attribute field."
        )
    return value


def _require_exact_mapping(
    value: Any,
    keys: Sequence[str],
    label: str,
) -> None:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} must be a JSON object."
        )
    if set(value) != set(keys):
        raise BulkCollectionImportCollectionProjectionError(
            f"{label} fields do not match the expected contract."
        )


def _freeze_json(value: Any, label: str) -> Any:
    if value is None or isinstance(value, (str, bool)):
        return value
    if type(value) is int:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BulkCollectionImportCollectionProjectionError(
                f"{label} contains a non-finite number."
            )
        return value
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                _require_attribute_field(
                    key,
                    label,
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

    raise BulkCollectionImportCollectionProjectionError(
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


def _source_reference_to_document(
    reference: BulkCollectionImportCollectionSourceReference,
) -> dict[str, str]:
    return {
        "source": reference.source,
        "external_id": reference.external_id,
    }


def _require_projection(
    value: Any,
) -> None:
    if not isinstance(
        value,
        BulkCollectionImportCollectionProjection,
    ):
        raise TypeError(
            "projection must be "
            "BulkCollectionImportCollectionProjection"
        )


__all__ = [
    "COLLECTION_IMPORT_EXTENSION_KEY",
    "COLLECTION_IMPORT_EXTENSION_VERSION",
    "COLLECTION_IMPORT_EXTENSION_KEYS",
    "CORE_SHARED_ATTRIBUTE_KEYS",
    "BulkCollectionImportCollectionProjectionError",
    "BulkCollectionImportCollectionSourceReference",
    "BulkCollectionImportCollectionIdentitySnapshot",
    "BulkCollectionImportCollectionRecordSnapshot",
    "BulkCollectionImportCollectionProjection",
    "project_bulk_collection_import_collection",
    "project_bulk_collection_import_hack_data_manager",
    "bulk_collection_import_collection_identities_to_documents",
    "bulk_collection_import_collection_records_to_documents",
]
