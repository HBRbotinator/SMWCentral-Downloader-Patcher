"""Read-only historical-provenance assistance for Collection ROM organization.

Modern ``files[]`` rows may legitimately retain per-ROM SMWC provenance that differs
from the Collection record's current numeric submission ID after an explicit
replacement.  Those assets must not borrow the current record's type/difficulty
metadata when deriving an organization target.  This module consumes the existing
organization audit plus rich metadata for each ROM's own recorded SMWC submission
and produces a detached, immutable review only.  It never writes Collection state or
touches ROM/save bytes.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Sequence

from collection_rom_assets import CollectionRomAssetError, collection_rom_asset_views
from collection_rom_organization import (
    CollectionRomOrganizationAudit,
    CollectionRomOrganizationRow,
    STATUS_REVIEW_PROVENANCE,
    STATUS_NEEDS_ORGANIZATION,
    expected_collection_rom_path,
)


STATUS_READY = "ready"
STATUS_IN_PLACE = "in_place"
STATUS_MISSING_SOURCE = "missing_source"
STATUS_TARGET_OCCUPIED = "target_occupied"
STATUS_TARGET_COLLISION = "target_collision"
STATUS_REVIEW_METADATA = "review_metadata"

BLOCKING_STATUSES = {
    STATUS_MISSING_SOURCE,
    STATUS_TARGET_OCCUPIED,
    STATUS_TARGET_COLLISION,
    STATUS_REVIEW_METADATA,
}


class HistoricalRomProvenanceReviewError(RuntimeError):
    """Raised when historical ROM provenance cannot be reviewed safely."""


@dataclass(frozen=True)
class HistoricalRomProvenanceRow:
    collection_id: str
    collection_title: str
    asset_name: str
    current_path: str
    expected_path: str
    historical_smwc_submission_id: int
    historical_title: str
    historical_difficulty: str
    historical_hack_type: str
    status: str
    detail: str
    primary: bool
    sha256: str
    size_bytes: int | None

    @property
    def blocking(self) -> bool:
        return self.status in BLOCKING_STATUSES

    @property
    def ready_for_planning(self) -> bool:
        return self.status == STATUS_READY


@dataclass(frozen=True)
class HistoricalRomProvenanceReview:
    output_dir: str
    collection_revision_token: str
    rows: tuple[HistoricalRomProvenanceRow, ...]
    excluded_unknown_provenance_count: int = 0

    @property
    def ready_count(self) -> int:
        return sum(row.status == STATUS_READY for row in self.rows)

    @property
    def in_place_count(self) -> int:
        return sum(row.status == STATUS_IN_PLACE for row in self.rows)

    @property
    def blocking_count(self) -> int:
        return sum(row.blocking for row in self.rows)


@dataclass(frozen=True)
class _HistoricalMetadata:
    smwc_submission_id: int
    title: str
    difficulty: str
    hack_types: tuple[str, ...]


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _path_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(_absolute(path)))


def _numeric_collection_id(collection_id: str) -> int | None:
    text = str(collection_id or "").strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


def _is_known_historical_row(row: CollectionRomOrganizationRow) -> bool:
    current_id = _numeric_collection_id(row.collection_id)
    provenance = row.smwc_submission_id
    return (
        row.status == STATUS_REVIEW_PROVENANCE
        and current_id is not None
        and isinstance(provenance, int)
        and not isinstance(provenance, bool)
        and provenance > 0
        and provenance != current_id
    )


def historical_provenance_audit_rows(
    audit: CollectionRomOrganizationAudit,
) -> tuple[CollectionRomOrganizationRow, ...]:
    """Return only modern audit rows with explicit historical SMWC provenance."""

    if not isinstance(audit, CollectionRomOrganizationAudit):
        raise TypeError("audit must be a CollectionRomOrganizationAudit")
    return tuple(row for row in audit.rows if _is_known_historical_row(row))


def required_historical_submission_ids(
    audit: CollectionRomOrganizationAudit,
) -> tuple[int, ...]:
    """Return distinct recorded historical submission IDs required for review."""

    return tuple(
        sorted({int(row.smwc_submission_id) for row in historical_provenance_audit_rows(audit)})
    )


def _metadata_from_detail(detail: Any) -> _HistoricalMetadata:
    value = getattr(detail, "metadata", detail)
    identifier = getattr(value, "smwc_submission_id", None)
    if not isinstance(identifier, int) or isinstance(identifier, bool) or identifier <= 0:
        raise HistoricalRomProvenanceReviewError(
            "Historical SMWC metadata is missing a valid submission ID."
        )
    raw_types = getattr(value, "hack_types", ())
    if raw_types is None:
        raw_types = ()
    if not isinstance(raw_types, (tuple, list)):
        raise HistoricalRomProvenanceReviewError(
            f"Historical SMWC {identifier} hack type metadata is malformed."
        )
    hack_types = tuple(str(item).strip() for item in raw_types if str(item).strip())
    return _HistoricalMetadata(
        smwc_submission_id=identifier,
        title=str(getattr(value, "title", "") or "").strip(),
        difficulty=str(getattr(value, "difficulty", "") or "").strip(),
        hack_types=hack_types,
    )


def _detail_map(details: Sequence[Any]) -> dict[int, _HistoricalMetadata]:
    result: dict[int, _HistoricalMetadata] = {}
    for detail in details:
        metadata = _metadata_from_detail(detail)
        if metadata.smwc_submission_id in result and result[metadata.smwc_submission_id] != metadata:
            raise HistoricalRomProvenanceReviewError(
                f"Conflicting metadata was supplied for SMWC {metadata.smwc_submission_id}."
            )
        result[metadata.smwc_submission_id] = metadata
    return result


def _find_exact_asset(record: Mapping[str, Any], row: CollectionRomOrganizationRow):
    try:
        views = collection_rom_asset_views(record)
    except CollectionRomAssetError as error:
        raise HistoricalRomProvenanceReviewError(
            f"Modern ROM metadata changed for {row.title}: {error}"
        ) from error
    matches = [view for view in views if _path_identity(view.path) == _path_identity(row.current_path)]
    if len(matches) != 1:
        raise HistoricalRomProvenanceReviewError(
            f"Historical ROM asset ownership changed after the organization audit: {row.asset_name}"
        )
    return matches[0]


def _initial_review_rows(
    audit: CollectionRomOrganizationAudit,
    collection_data: Mapping[str, Any],
    details: Mapping[int, _HistoricalMetadata],
) -> list[HistoricalRomProvenanceRow]:
    rows: list[HistoricalRomProvenanceRow] = []
    for audit_row in historical_provenance_audit_rows(audit):
        raw_record = collection_data.get(audit_row.collection_id)
        if not isinstance(raw_record, Mapping):
            raise HistoricalRomProvenanceReviewError(
                f"Collection record {audit_row.collection_id!r} changed after the organization audit."
            )
        view = _find_exact_asset(raw_record, audit_row)
        if (
            view.smwc_submission_id != audit_row.smwc_submission_id
            or view.primary != audit_row.primary
            or view.sha256 != audit_row.sha256
            or view.size_bytes != audit_row.size_bytes
        ):
            raise HistoricalRomProvenanceReviewError(
                f"Historical ROM metadata changed after the organization audit: {audit_row.asset_name}"
            )

        historical_id = int(audit_row.smwc_submission_id)
        metadata = details.get(historical_id)
        if metadata is None:
            raise HistoricalRomProvenanceReviewError(
                f"Rich metadata for historical SMWC {historical_id} was not supplied."
            )

        hack_type = metadata.hack_types[0] if metadata.hack_types else "unknown"
        difficulty = metadata.difficulty or "Unknown"
        expected = expected_collection_rom_path(
            audit.output_dir,
            hack_type,
            difficulty,
            os.path.basename(audit_row.current_path),
        )
        current = _absolute(audit_row.current_path)

        if os.path.islink(current):
            status = STATUS_REVIEW_METADATA
            detail = "Symbolic-link ROM assets require explicit review before organization."
        elif not os.path.isfile(current):
            status = STATUS_MISSING_SOURCE
            detail = "The historical ROM file no longer exists."
        elif not audit_row.sha256 or audit_row.size_bytes is None:
            status = STATUS_REVIEW_METADATA
            detail = "Exact recorded SHA-256 and byte size are required before organization planning."
        elif os.path.getsize(current) != audit_row.size_bytes:
            status = STATUS_REVIEW_METADATA
            detail = "The historical ROM byte size no longer matches its recorded files[] identity."
        elif _path_identity(current) == _path_identity(expected):
            status = STATUS_IN_PLACE
            detail = (
                f"This retained ROM is already in the layout derived from its own SMWC {historical_id} metadata."
            )
        elif os.path.exists(expected):
            status = STATUS_TARGET_OCCUPIED
            detail = (
                "The historical-metadata target already exists. No overwrite or implicit deduplication is permitted."
            )
        else:
            status = STATUS_READY
            detail = (
                f"SMWC {historical_id} metadata provides an explicit historical type/difficulty layout. "
                "A later immutable plan may use this target without borrowing current Collection metadata."
            )

        rows.append(
            HistoricalRomProvenanceRow(
                collection_id=audit_row.collection_id,
                collection_title=audit_row.title,
                asset_name=audit_row.asset_name,
                current_path=current,
                expected_path=expected,
                historical_smwc_submission_id=historical_id,
                historical_title=metadata.title or f"SMWC {historical_id}",
                historical_difficulty=difficulty,
                historical_hack_type=hack_type,
                status=status,
                detail=detail,
                primary=audit_row.primary,
                sha256=audit_row.sha256,
                size_bytes=audit_row.size_bytes,
            )
        )
    return rows


def _mark_target_collisions(
    rows: Iterable[HistoricalRomProvenanceRow],
    audit: CollectionRomOrganizationAudit,
) -> tuple[HistoricalRomProvenanceRow, ...]:
    materialized = list(rows)
    targets: dict[str, list[int]] = {}
    for index, row in enumerate(materialized):
        if row.status != STATUS_READY:
            continue
        targets.setdefault(_path_identity(row.expected_path), []).append(index)
    reserved_by_normal_audit = {
        _path_identity(row.expected_path)
        for row in audit.rows
        if row.status == STATUS_NEEDS_ORGANIZATION and row.expected_path
    }
    collision_indexes = {
        index
        for identity, indexes in targets.items()
        if len(indexes) > 1 or identity in reserved_by_normal_audit
        for index in indexes
    }
    if not collision_indexes:
        return tuple(materialized)
    return tuple(
        replace(
            row,
            status=STATUS_TARGET_COLLISION,
            detail=(
                "Multiple historical ROM assets resolve to the same target path. "
                "Organization requires explicit conflict review."
            ),
        )
        if index in collision_indexes
        else row
        for index, row in enumerate(materialized)
    )


def build_historical_rom_provenance_review(
    audit: CollectionRomOrganizationAudit,
    collection_data: Mapping[str, Any],
    collection_revision_token: str,
    catalogue_details: Sequence[Any],
) -> HistoricalRomProvenanceReview:
    """Build an immutable read-only historical-layout review from exact provenance metadata."""

    if not isinstance(audit, CollectionRomOrganizationAudit):
        raise TypeError("audit must be a CollectionRomOrganizationAudit")
    if not isinstance(collection_data, Mapping):
        raise TypeError("Collection data must be a mapping.")
    revision = str(collection_revision_token or "").strip()
    if not revision:
        raise HistoricalRomProvenanceReviewError(
            "Collection revision token is required for historical provenance review."
        )

    historical_rows = historical_provenance_audit_rows(audit)
    if not historical_rows:
        raise HistoricalRomProvenanceReviewError(
            "The organization audit has no explicit historical-provenance ROM assets to review."
        )

    details = _detail_map(catalogue_details)
    required = required_historical_submission_ids(audit)
    missing = [identifier for identifier in required if identifier not in details]
    if missing:
        raise HistoricalRomProvenanceReviewError(
            "Missing rich metadata for historical SMWC submission(s): "
            + ", ".join(str(identifier) for identifier in missing)
        )

    rows = _mark_target_collisions(_initial_review_rows(audit, collection_data, details), audit)
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                row.status == STATUS_IN_PLACE,
                row.collection_title.casefold(),
                row.collection_id,
                row.historical_smwc_submission_id,
                row.asset_name.casefold(),
            ),
        )
    )
    unknown_count = sum(
        row.status == STATUS_REVIEW_PROVENANCE and not _is_known_historical_row(row)
        for row in audit.rows
    )
    return HistoricalRomProvenanceReview(
        output_dir=_absolute(audit.output_dir),
        collection_revision_token=revision,
        rows=ordered,
        excluded_unknown_provenance_count=unknown_count,
    )


__all__ = [
    "HistoricalRomProvenanceReview",
    "HistoricalRomProvenanceReviewError",
    "HistoricalRomProvenanceRow",
    "STATUS_IN_PLACE",
    "STATUS_MISSING_SOURCE",
    "STATUS_READY",
    "STATUS_REVIEW_METADATA",
    "STATUS_TARGET_COLLISION",
    "STATUS_TARGET_OCCUPIED",
    "build_historical_rom_provenance_review",
    "historical_provenance_audit_rows",
    "required_historical_submission_ids",
]
