"""Non-mutating identity resolution for bulk Collection imports."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from bulk_collection_import import (
    BULK_COLLECTION_IMPORT_ENTRY_KEY_PATTERN,
    BULK_COLLECTION_IMPORT_ID_PATTERN,
    BULK_COLLECTION_IMPORT_SOURCE_PATTERN,
    BulkCollectionImportDocument,
    BulkCollectionImportSourceReference,
)


BULK_COLLECTION_IDENTITY_PLAN_SCHEMA = (
    "smwc-bulk-collection-identity-plan"
)
BULK_COLLECTION_IDENTITY_PLAN_VERSION = 1

BULK_COLLECTION_IDENTITY_RESOLUTION_STATUSES = (
    "matched_source",
    "matched_metadata",
    "new",
    "ambiguous",
    "conflict",
)

BULK_COLLECTION_IDENTITY_PLAN_KEYS = (
    "schema",
    "version",
    "import_id",
    "resolutions",
)
BULK_COLLECTION_IDENTITY_RESOLUTION_KEYS = (
    "entry_key",
    "status",
    "collection_keys",
    "matched_source_references",
    "proposed_source_references",
    "warnings",
)

_COLLECTION_IDENTITY_KEYS = (
    "collection_key",
    "title",
    "aliases",
    "source_references",
    "attributes",
)
_SOURCE_REFERENCE_KEYS = (
    "source",
    "external_id",
)
_COLLECTION_KEY_PATTERN = re.compile(
    r"^[A-Za-z0-9._:-]{1,128}$"
)


class BulkCollectionIdentityResolutionError(ValueError):
    """Raised when existing Collection identity input is invalid."""


@dataclass(frozen=True, slots=True)
class BulkCollectionIdentityResolution:
    """One immutable import-entry identity decision."""

    entry_key: str
    status: str
    collection_keys: tuple[str, ...]
    matched_source_references: tuple[
        BulkCollectionImportSourceReference,
        ...,
    ]
    proposed_source_references: tuple[
        BulkCollectionImportSourceReference,
        ...,
    ]
    warnings: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionIdentityPlan:
    """Ordered detached identity plan for one import document."""

    schema: str
    version: int
    import_id: str
    resolutions: tuple[
        BulkCollectionIdentityResolution,
        ...,
    ]


@dataclass(frozen=True, slots=True)
class _CollectionIdentity:
    collection_key: str
    title: str
    aliases: tuple[str, ...]
    source_references: tuple[
        BulkCollectionImportSourceReference,
        ...,
    ]
    normalized_titles: frozenset[str]
    normalized_authors: frozenset[str]


def resolve_bulk_collection_identities(
    import_document: BulkCollectionImportDocument,
    collection_identities: Sequence[Mapping[str, Any]],
) -> BulkCollectionIdentityPlan:
    """Resolve imported entries without changing either input."""

    if not isinstance(
        import_document,
        BulkCollectionImportDocument,
    ):
        raise TypeError(
            "import_document must be a BulkCollectionImportDocument"
        )

    identities = _parse_collection_identities(
        collection_identities
    )
    source_index = _build_source_index(identities)

    resolutions = [
        _resolve_entry(
            entry,
            identities,
            source_index,
        )
        for entry in import_document.entries
    ]
    resolutions = _mark_duplicate_import_targets(resolutions)

    return BulkCollectionIdentityPlan(
        schema=BULK_COLLECTION_IDENTITY_PLAN_SCHEMA,
        version=BULK_COLLECTION_IDENTITY_PLAN_VERSION,
        import_id=import_document.import_id,
        resolutions=tuple(resolutions),
    )


def bulk_collection_identity_plan_to_document(
    plan: BulkCollectionIdentityPlan,
) -> dict[str, Any]:
    """Project an identity plan to a detached canonical document."""

    if not isinstance(plan, BulkCollectionIdentityPlan):
        raise TypeError(
            "plan must be a BulkCollectionIdentityPlan"
        )

    return {
        "schema": plan.schema,
        "version": plan.version,
        "import_id": plan.import_id,
        "resolutions": [
            {
                "entry_key": resolution.entry_key,
                "status": resolution.status,
                "collection_keys": list(
                    resolution.collection_keys
                ),
                "matched_source_references": [
                    _source_reference_to_document(reference)
                    for reference
                    in resolution.matched_source_references
                ],
                "proposed_source_references": [
                    _source_reference_to_document(reference)
                    for reference
                    in resolution.proposed_source_references
                ],
                "warnings": list(resolution.warnings),
            }
            for resolution in plan.resolutions
        ],
    }


def serialize_bulk_collection_identity_plan(
    plan: BulkCollectionIdentityPlan,
) -> str:
    """Serialize one plan as deterministic compact JSON."""

    return json.dumps(
        bulk_collection_identity_plan_to_document(plan),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def normalize_bulk_collection_identity_text(value: str) -> str:
    """Normalize title, alias, and author text for safe comparison."""

    if not isinstance(value, str):
        raise TypeError("Identity text must be a string.")

    normalized = unicodedata.normalize("NFKD", value).casefold()
    characters = []
    for character in normalized:
        if unicodedata.combining(character):
            continue
        characters.append(
            character if character.isalnum() else " "
        )
    return " ".join("".join(characters).split())


def _resolve_entry(
    entry: Any,
    identities: tuple[_CollectionIdentity, ...],
    source_index: Mapping[
        tuple[str, str],
        _CollectionIdentity,
    ],
) -> BulkCollectionIdentityResolution:
    matched_references = []
    matched_identities = []

    for reference in entry.source_references:
        identity = source_index.get(
            (reference.source, reference.external_id)
        )
        if identity is None:
            continue
        matched_references.append(reference)
        if identity not in matched_identities:
            matched_identities.append(identity)

    if len(matched_identities) > 1:
        return BulkCollectionIdentityResolution(
            entry_key=entry.entry_key,
            status="conflict",
            collection_keys=tuple(
                identity.collection_key
                for identity in matched_identities
            ),
            matched_source_references=tuple(
                matched_references
            ),
            proposed_source_references=(),
            warnings=("source_identity_conflict",),
        )

    if len(matched_identities) == 1:
        identity = matched_identities[0]
        existing_references = {
            (reference.source, reference.external_id)
            for reference in identity.source_references
        }
        proposed = tuple(
            reference
            for reference in entry.source_references
            if (
                reference.source,
                reference.external_id,
            )
            not in existing_references
        )
        warnings = []
        normalized_title = (
            normalize_bulk_collection_identity_text(
                entry.title
            )
        )
        if normalized_title not in identity.normalized_titles:
            warnings.append("title_mismatch")

        return BulkCollectionIdentityResolution(
            entry_key=entry.entry_key,
            status="matched_source",
            collection_keys=(identity.collection_key,),
            matched_source_references=tuple(
                matched_references
            ),
            proposed_source_references=proposed,
            warnings=tuple(warnings),
        )

    return _resolve_entry_by_metadata(entry, identities)


def _resolve_entry_by_metadata(
    entry: Any,
    identities: tuple[_CollectionIdentity, ...],
) -> BulkCollectionIdentityResolution:
    normalized_title = normalize_bulk_collection_identity_text(
        entry.title
    )
    imported_authors = _normalized_import_authors(
        entry.attributes,
        f"entry {entry.entry_key}",
    )

    title_candidates = tuple(
        identity
        for identity in identities
        if normalized_title in identity.normalized_titles
    )
    metadata_matches = tuple(
        identity
        for identity in title_candidates
        if (
            imported_authors
            and identity.normalized_authors
            and imported_authors
            & identity.normalized_authors
        )
    )

    if len(metadata_matches) == 1:
        return BulkCollectionIdentityResolution(
            entry_key=entry.entry_key,
            status="matched_metadata",
            collection_keys=(
                metadata_matches[0].collection_key,
            ),
            matched_source_references=(),
            proposed_source_references=(),
            warnings=(),
        )

    if title_candidates:
        return BulkCollectionIdentityResolution(
            entry_key=entry.entry_key,
            status="ambiguous",
            collection_keys=tuple(
                identity.collection_key
                for identity in title_candidates
            ),
            matched_source_references=(),
            proposed_source_references=(),
            warnings=(),
        )

    return BulkCollectionIdentityResolution(
        entry_key=entry.entry_key,
        status="new",
        collection_keys=(),
        matched_source_references=(),
        proposed_source_references=(),
        warnings=(),
    )


def _mark_duplicate_import_targets(
    resolutions: list[BulkCollectionIdentityResolution],
) -> list[BulkCollectionIdentityResolution]:
    owners: dict[str, list[int]] = {}

    for index, resolution in enumerate(resolutions):
        if resolution.status not in {
            "matched_source",
            "matched_metadata",
        }:
            continue
        if len(resolution.collection_keys) != 1:
            continue
        owners.setdefault(
            resolution.collection_keys[0],
            [],
        ).append(index)

    duplicate_indexes = {
        index
        for indexes in owners.values()
        if len(indexes) > 1
        for index in indexes
    }
    if not duplicate_indexes:
        return resolutions

    updated = []
    for index, resolution in enumerate(resolutions):
        if index not in duplicate_indexes:
            updated.append(resolution)
            continue
        updated.append(
            BulkCollectionIdentityResolution(
                entry_key=resolution.entry_key,
                status="conflict",
                collection_keys=resolution.collection_keys,
                matched_source_references=(
                    resolution.matched_source_references
                ),
                proposed_source_references=(),
                warnings=("duplicate_import_target",),
            )
        )
    return updated


def _parse_collection_identities(
    value: Sequence[Mapping[str, Any]],
) -> tuple[_CollectionIdentity, ...]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionIdentityResolutionError(
            "collection_identities must be a sequence."
        )

    parsed = []
    collection_keys = set()
    for index, item in enumerate(value):
        label = f"collection_identities[{index}]"
        _require_exact_mapping(
            item,
            _COLLECTION_IDENTITY_KEYS,
            label,
        )

        collection_key = _require_pattern_text(
            item["collection_key"],
            _COLLECTION_KEY_PATTERN,
            f"{label}.collection_key",
        )
        if collection_key in collection_keys:
            raise BulkCollectionIdentityResolutionError(
                f"Duplicate collection_key: {collection_key}"
            )
        collection_keys.add(collection_key)

        title = _require_title(
            item["title"],
            f"{label}.title",
        )
        aliases = _parse_aliases(
            item["aliases"],
            label,
        )
        references = _parse_collection_source_references(
            item["source_references"],
            label,
        )
        authors = _normalized_collection_authors(
            item["attributes"],
            label,
        )
        normalized_titles = frozenset(
            normalize_bulk_collection_identity_text(text)
            for text in (title, *aliases)
        )

        parsed.append(
            _CollectionIdentity(
                collection_key=collection_key,
                title=title,
                aliases=aliases,
                source_references=references,
                normalized_titles=normalized_titles,
                normalized_authors=authors,
            )
        )

    return tuple(parsed)


def _build_source_index(
    identities: Iterable[_CollectionIdentity],
) -> dict[tuple[str, str], _CollectionIdentity]:
    index = {}
    for identity in identities:
        for reference in identity.source_references:
            key = (reference.source, reference.external_id)
            existing = index.get(key)
            if existing is not None:
                raise BulkCollectionIdentityResolutionError(
                    "Collection source identity belongs to more "
                    f"than one record: {reference.source}:"
                    f"{reference.external_id} "
                    f"({existing.collection_key}, "
                    f"{identity.collection_key})"
                )
            index[key] = identity
    return index


def _parse_aliases(
    value: Any,
    identity_label: str,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise BulkCollectionIdentityResolutionError(
            f"{identity_label}.aliases must be a JSON array."
        )

    aliases = []
    seen = set()
    for index, alias_value in enumerate(value):
        alias = _require_title(
            alias_value,
            f"{identity_label}.aliases[{index}]",
        )
        normalized = normalize_bulk_collection_identity_text(
            alias
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        aliases.append(alias)
    return tuple(aliases)


def _parse_collection_source_references(
    value: Any,
    identity_label: str,
) -> tuple[BulkCollectionImportSourceReference, ...]:
    if not isinstance(value, list):
        raise BulkCollectionIdentityResolutionError(
            f"{identity_label}.source_references must be "
            "a JSON array."
        )

    references = []
    seen = set()
    for index, item in enumerate(value):
        label = (
            f"{identity_label}.source_references[{index}]"
        )
        _require_exact_mapping(
            item,
            _SOURCE_REFERENCE_KEYS,
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
        key = (source, external_id)
        if key in seen:
            raise BulkCollectionIdentityResolutionError(
                "Duplicate source reference on Collection "
                f"identity: {source}:{external_id}"
            )
        seen.add(key)
        references.append(
            BulkCollectionImportSourceReference(
                source=source,
                external_id=external_id,
            )
        )
    return tuple(references)


def _normalized_collection_authors(
    value: Any,
    identity_label: str,
) -> frozenset[str]:
    if not isinstance(value, dict):
        raise BulkCollectionIdentityResolutionError(
            f"{identity_label}.attributes must be a JSON object."
        )
    return _normalize_authors(
        value.get("authors"),
        f"{identity_label}.attributes.authors",
        BulkCollectionIdentityResolutionError,
    )


def _normalized_import_authors(
    attributes: Mapping[str, Any],
    label: str,
) -> frozenset[str]:
    return _normalize_authors(
        attributes.get("authors"),
        f"{label}.attributes.authors",
        BulkCollectionIdentityResolutionError,
    )


def _normalize_authors(
    value: Any,
    label: str,
    error_type: type[ValueError],
) -> frozenset[str]:
    if value is None:
        return frozenset()
    if not isinstance(value, (list, tuple)):
        raise error_type(
            f"{label} must be a JSON array when present."
        )

    normalized = set()
    for index, author in enumerate(value):
        if (
            not isinstance(author, str)
            or not author.strip()
            or author != author.strip()
            or len(author) > 512
        ):
            raise error_type(
                f"{label}[{index}] must be a non-empty "
                "trimmed string of at most 512 characters."
            )
        normalized.add(
            normalize_bulk_collection_identity_text(author)
        )
    return frozenset(normalized)


def _source_reference_to_document(
    reference: BulkCollectionImportSourceReference,
) -> dict[str, str]:
    return {
        "source": reference.source,
        "external_id": reference.external_id,
    }


def _require_exact_mapping(
    value: Any,
    expected_keys: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(value, dict):
        raise BulkCollectionIdentityResolutionError(
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
        details.append(
            "unexpected: " + ", ".join(unexpected)
        )
    raise BulkCollectionIdentityResolutionError(
        f"{label} fields must match the identity contract "
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
        raise BulkCollectionIdentityResolutionError(
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
        raise BulkCollectionIdentityResolutionError(
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
        raise BulkCollectionIdentityResolutionError(
            f"{label} must be a non-empty non-whitespace "
            "string of at most 256 characters."
        )
    return value


__all__ = [
    "BULK_COLLECTION_IDENTITY_PLAN_SCHEMA",
    "BULK_COLLECTION_IDENTITY_PLAN_VERSION",
    "BULK_COLLECTION_IDENTITY_RESOLUTION_STATUSES",
    "BULK_COLLECTION_IDENTITY_PLAN_KEYS",
    "BULK_COLLECTION_IDENTITY_RESOLUTION_KEYS",
    "BulkCollectionIdentityResolutionError",
    "BulkCollectionIdentityResolution",
    "BulkCollectionIdentityPlan",
    "resolve_bulk_collection_identities",
    "bulk_collection_identity_plan_to_document",
    "serialize_bulk_collection_identity_plan",
    "normalize_bulk_collection_identity_text",
]
