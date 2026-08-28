"""Read-only audit for legacy Collection ROM metadata modernization.

Legacy Collection records may still carry only ``file_path`` without the modern
``files[]`` asset structure. This module identifies which of those records can be
modernized safely in a later explicit planning/apply boundary. It performs no
hashing and never mutates Collection or filesystem state.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping


STATUS_READY = "ready"
STATUS_MISSING_SOURCE = "missing_source"
STATUS_REVIEW_PROVENANCE = "review_provenance"
STATUS_REVIEW_METADATA = "review_metadata"
STATUS_DUPLICATE_PATH = "duplicate_path"
STATUS_SYMLINK = "symlink"

BLOCKING_STATUSES = {
    STATUS_MISSING_SOURCE,
    STATUS_REVIEW_PROVENANCE,
    STATUS_REVIEW_METADATA,
    STATUS_DUPLICATE_PATH,
    STATUS_SYMLINK,
}

_SUPPORTED_ROM_SUFFIXES = {".sfc", ".smc"}


@dataclass(frozen=True)
class LegacyRomMetadataAuditRow:
    """One existing legacy ``file_path`` record and its proposed modernization facts."""

    collection_id: str
    title: str
    current_path: str
    status: str
    detail: str
    size_bytes: int | None
    proposed_smwc_submission_id: int | None
    proposed_ingestion_source: str = "legacy_collection_backfill"

    @property
    def blocking(self) -> bool:
        return self.status in BLOCKING_STATUSES


@dataclass(frozen=True)
class LegacyRomMetadataAudit:
    """Immutable read-only aggregate for legacy ROM metadata modernization."""

    rows: tuple[LegacyRomMetadataAuditRow, ...]

    @property
    def ready_count(self) -> int:
        return sum(row.status == STATUS_READY for row in self.rows)

    @property
    def blocking_count(self) -> int:
        return sum(row.blocking for row in self.rows)


class LegacyRomMetadataAuditError(RuntimeError):
    """Raised when legacy Collection state cannot be audited safely."""


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _canonical(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _path_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(_absolute(path)))


def _numeric_collection_id(collection_id: str) -> int | None:
    text = str(collection_id or "").strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


def _has_identity_migration_provenance(record: Mapping[str, Any]) -> bool:
    prior = record.get("prior_smwc_submission_ids", [])
    history = record.get("identity_migration_history", [])
    return bool(prior) or bool(history)


def _legacy_row(
    collection_id: str,
    record: Mapping[str, Any],
) -> LegacyRomMetadataAuditRow | None:
    files = record.get("files")
    if files is not None:
        if not isinstance(files, list):
            path = str(record.get("file_path", "") or "").strip()
            if not path:
                return None
            return LegacyRomMetadataAuditRow(
                collection_id=collection_id,
                title=str(record.get("title", "") or f"Collection {collection_id}"),
                current_path=_absolute(path),
                status=STATUS_REVIEW_METADATA,
                detail="Collection files metadata is malformed and must be repaired first.",
                size_bytes=None,
                proposed_smwc_submission_id=None,
            )
        if files:
            return None

    path = str(record.get("file_path", "") or "").strip()
    if not path:
        return None

    title = str(record.get("title", "") or f"Collection {collection_id}")
    absolute = _absolute(path)
    suffix = Path(absolute).suffix.lower()
    if suffix not in _SUPPORTED_ROM_SUFFIXES:
        return LegacyRomMetadataAuditRow(
            collection_id=collection_id,
            title=title,
            current_path=absolute,
            status=STATUS_REVIEW_METADATA,
            detail=(
                "Legacy file_path does not reference a supported .sfc/.smc ROM. "
                "No modern files[] row is proposed."
            ),
            size_bytes=None,
            proposed_smwc_submission_id=None,
        )

    if os.path.islink(absolute):
        return LegacyRomMetadataAuditRow(
            collection_id=collection_id,
            title=title,
            current_path=absolute,
            status=STATUS_SYMLINK,
            detail=(
                "Legacy ROM path is a symbolic link. Resolve the real file explicitly before "
                "modernizing Collection ROM metadata."
            ),
            size_bytes=None,
            proposed_smwc_submission_id=None,
        )

    if not os.path.exists(absolute):
        return LegacyRomMetadataAuditRow(
            collection_id=collection_id,
            title=title,
            current_path=absolute,
            status=STATUS_MISSING_SOURCE,
            detail="The legacy ROM file does not currently exist.",
            size_bytes=None,
            proposed_smwc_submission_id=None,
        )

    if not os.path.isfile(absolute):
        return LegacyRomMetadataAuditRow(
            collection_id=collection_id,
            title=title,
            current_path=absolute,
            status=STATUS_REVIEW_METADATA,
            detail="Legacy file_path is not a regular ROM file.",
            size_bytes=None,
            proposed_smwc_submission_id=None,
        )

    numeric_id = _numeric_collection_id(collection_id)
    if numeric_id is not None and _has_identity_migration_provenance(record):
        return LegacyRomMetadataAuditRow(
            collection_id=collection_id,
            title=title,
            current_path=_canonical(absolute),
            status=STATUS_REVIEW_PROVENANCE,
            detail=(
                "This numeric Collection record has prior submission/migration provenance. "
                "The legacy file_path cannot be assigned to the current SMWC ID without an "
                "explicit provenance decision."
            ),
            size_bytes=os.path.getsize(absolute),
            proposed_smwc_submission_id=None,
        )

    if numeric_id is None and not collection_id.startswith("usr_"):
        return LegacyRomMetadataAuditRow(
            collection_id=collection_id,
            title=title,
            current_path=_canonical(absolute),
            status=STATUS_REVIEW_PROVENANCE,
            detail=(
                "Collection identity is neither a numeric SMWC submission ID nor an opaque "
                "usr_* local ID. ROM provenance requires review before modernization."
            ),
            size_bytes=os.path.getsize(absolute),
            proposed_smwc_submission_id=None,
        )

    proposed_id = numeric_id
    provenance_text = (
        f"SMWC {numeric_id}" if numeric_id is not None else "local/user-owned provenance"
    )
    return LegacyRomMetadataAuditRow(
        collection_id=collection_id,
        title=title,
        current_path=_canonical(absolute),
        status=STATUS_READY,
        detail=(
            "Ready for a later explicit modernization plan. The existing ROM would remain in "
            f"place; its modern primary files[] row would use {provenance_text}. Exact SHA-256 "
            "must still be computed and revalidated before any Collection write."
        ),
        size_bytes=os.path.getsize(absolute),
        proposed_smwc_submission_id=proposed_id,
    )


def _mark_duplicate_paths(
    rows: list[LegacyRomMetadataAuditRow],
) -> tuple[LegacyRomMetadataAuditRow, ...]:
    indexes: dict[str, list[int]] = {}
    for index, row in enumerate(rows):
        if not row.current_path:
            continue
        indexes.setdefault(_path_identity(row.current_path), []).append(index)

    duplicates = {
        index
        for group in indexes.values()
        if len(group) > 1
        for index in group
    }
    if not duplicates:
        return tuple(rows)

    result: list[LegacyRomMetadataAuditRow] = []
    for index, row in enumerate(rows):
        if index not in duplicates:
            result.append(row)
            continue
        result.append(
            replace(
                row,
                status=STATUS_DUPLICATE_PATH,
                detail=(
                    "The same legacy ROM path is referenced by multiple Collection records. "
                    "Modernization requires an explicit ownership decision first."
                ),
                proposed_smwc_submission_id=None,
            )
        )
    return tuple(result)


def build_legacy_rom_metadata_audit(
    collection_data: Mapping[str, Any],
) -> LegacyRomMetadataAudit:
    """Return a deterministic read-only audit of legacy ``file_path`` records."""

    if not isinstance(collection_data, Mapping):
        raise TypeError("Collection data must be a mapping.")

    rows: list[LegacyRomMetadataAuditRow] = []
    for raw_collection_id, raw_record in collection_data.items():
        if not isinstance(raw_record, Mapping):
            continue
        row = _legacy_row(str(raw_collection_id), raw_record)
        if row is not None:
            rows.append(row)

    rows_with_collisions = _mark_duplicate_paths(rows)
    ordered = tuple(
        sorted(
            rows_with_collisions,
            key=lambda row: (
                row.status != STATUS_READY,
                row.title.casefold(),
                row.collection_id,
                row.current_path.casefold(),
            ),
        )
    )
    return LegacyRomMetadataAudit(rows=ordered)


__all__ = [
    "LegacyRomMetadataAudit",
    "LegacyRomMetadataAuditError",
    "LegacyRomMetadataAuditRow",
    "STATUS_DUPLICATE_PATH",
    "STATUS_MISSING_SOURCE",
    "STATUS_READY",
    "STATUS_REVIEW_METADATA",
    "STATUS_REVIEW_PROVENANCE",
    "STATUS_SYMLINK",
    "build_legacy_rom_metadata_audit",
]
