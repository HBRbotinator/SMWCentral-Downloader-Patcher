"""Immutable read-only plans for modernizing legacy Collection ROM metadata.

Only rows explicitly classified ready by ``collection_rom_legacy_metadata`` may
enter this boundary. The builder revalidates Collection ownership and exact ROM
filesystem state, computes SHA-256 from stable bytes, and freezes the proposed
modern ``files[]`` row without mutating Collection or filesystem state.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from collection_rom_legacy_metadata import (
    LegacyRomMetadataAudit,
    STATUS_READY,
    STATUS_REVIEW_PROVENANCE,
)
from collection_rom_legacy_provenance_review import (
    LegacyRomProvenanceDecision,
    LegacyRomProvenanceReview,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_ROM_SUFFIXES = {".sfc", ".smc"}


class LegacyRomMetadataPlanError(RuntimeError):
    """Raised when ready legacy metadata can no longer be planned safely."""


@dataclass(frozen=True)
class LegacyRomMetadataBackfillOperation:
    """One frozen proposed ``files[]`` primary row and its byte preconditions."""

    collection_id: str
    title: str
    legacy_file_path: str
    canonical_path: str
    asset_name: str
    sha256: str
    size_bytes: int
    source_mtime_ns: int
    smwc_submission_id: int | None
    ingestion_source: str = "legacy_collection_backfill"

    def __post_init__(self) -> None:
        if not self.collection_id.strip():
            raise LegacyRomMetadataPlanError("Backfill operation requires Collection identity.")
        if not self.legacy_file_path or not self.canonical_path or not self.asset_name:
            raise LegacyRomMetadataPlanError("Backfill operation requires an exact ROM path and name.")
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise LegacyRomMetadataPlanError("Backfill operation requires a lowercase SHA-256.")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise LegacyRomMetadataPlanError("Backfill operation requires a non-negative byte size.")
        if isinstance(self.source_mtime_ns, bool) or self.source_mtime_ns < 0:
            raise LegacyRomMetadataPlanError("Backfill operation requires a source mtime precondition.")
        if self.smwc_submission_id is not None and (
            not isinstance(self.smwc_submission_id, int)
            or isinstance(self.smwc_submission_id, bool)
            or self.smwc_submission_id <= 0
        ):
            raise LegacyRomMetadataPlanError(
                "Backfill SMWC provenance must be a positive submission ID when present."
            )
        if not self.ingestion_source.strip():
            raise LegacyRomMetadataPlanError("Backfill operation requires an ingestion source.")

    @property
    def proposed_files_row(self) -> dict[str, Any]:
        """Return a detached modern primary row exactly represented by this plan."""
        row: dict[str, Any] = {
            "path": self.canonical_path,
            "name": self.asset_name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "primary": True,
            "ingestion_sources": [self.ingestion_source],
        }
        if self.smwc_submission_id is not None:
            row["smwc_submission_id"] = self.smwc_submission_id
        return row


@dataclass(frozen=True)
class LegacyRomMetadataModernizationPlan:
    """Immutable read-only preview of safe legacy metadata backfills."""

    collection_revision_token: str
    operations: tuple[LegacyRomMetadataBackfillOperation, ...]
    audit_row_count: int
    excluded_blocking_count: int

    def __post_init__(self) -> None:
        if not self.collection_revision_token.strip():
            raise LegacyRomMetadataPlanError(
                "Modernization plan requires a Collection revision precondition."
            )
        if not self.operations:
            raise LegacyRomMetadataPlanError(
                "Modernization plan requires at least one audit-ready legacy ROM."
            )
        if min(self.audit_row_count, self.excluded_blocking_count) < 0:
            raise LegacyRomMetadataPlanError("Modernization plan counts cannot be negative.")
        ids = [operation.collection_id for operation in self.operations]
        if len(ids) != len(set(ids)):
            raise LegacyRomMetadataPlanError("Modernization plan has duplicate Collection IDs.")
        paths = [_path_identity(operation.canonical_path) for operation in self.operations]
        if len(paths) != len(set(paths)):
            raise LegacyRomMetadataPlanError("Modernization plan has duplicate ROM paths.")


@dataclass(frozen=True)
class ReviewedLegacyRomMetadataModernizationPlan:
    """Immutable preview created only from explicit ambiguous provenance decisions."""

    collection_revision_token: str
    operations: tuple[LegacyRomMetadataBackfillOperation, ...]
    reviewed_row_count: int

    def __post_init__(self) -> None:
        if not self.collection_revision_token.strip():
            raise LegacyRomMetadataPlanError(
                "Reviewed modernization plan requires a Collection revision precondition."
            )
        if not self.operations:
            raise LegacyRomMetadataPlanError(
                "Reviewed modernization plan requires at least one explicit provenance decision."
            )
        if self.reviewed_row_count != len(self.operations):
            raise LegacyRomMetadataPlanError(
                "Reviewed modernization plan must contain every reviewed provenance row exactly once."
            )
        ids = [operation.collection_id for operation in self.operations]
        if len(ids) != len(set(ids)):
            raise LegacyRomMetadataPlanError(
                "Reviewed modernization plan has duplicate Collection IDs."
            )
        paths = [_path_identity(operation.canonical_path) for operation in self.operations]
        if len(paths) != len(set(paths)):
            raise LegacyRomMetadataPlanError(
                "Reviewed modernization plan has duplicate ROM paths."
            )


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _canonical(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def _path_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(_absolute(path)))


def _stat_fingerprint(stat_result: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        stat_result.st_dev,
        stat_result.st_ino,
        stat_result.st_size,
        stat_result.st_mtime_ns,
        stat_result.st_ctime_ns,
    )


def _hash_stable_regular_file(path: str) -> tuple[str, int, int]:
    """Hash one regular non-symlink ROM and reject changes during hashing."""
    if os.path.islink(path):
        raise LegacyRomMetadataPlanError(
            f"Legacy ROM became a symbolic link after the audit: {path}"
        )
    if not os.path.isfile(path):
        raise LegacyRomMetadataPlanError(
            f"Legacy ROM disappeared or is no longer a regular file: {path}"
        )

    before = os.stat(path, follow_symlinks=False)
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = os.stat(path, follow_symlinks=False)

    if _stat_fingerprint(before) != _stat_fingerprint(after):
        raise LegacyRomMetadataPlanError(
            f"Legacy ROM changed while SHA-256 was being computed: {path}"
        )
    return digest.hexdigest(), after.st_size, after.st_mtime_ns


def _validate_exact_legacy_record(
    row,
    collection_data: Mapping[str, Any],
) -> Mapping[str, Any]:
    raw_record = collection_data.get(row.collection_id)
    if not isinstance(raw_record, Mapping):
        raise LegacyRomMetadataPlanError(
            f"Collection record {row.collection_id!r} changed after the legacy audit."
        )

    current_file_path = raw_record.get("file_path")
    if not isinstance(current_file_path, str) or not current_file_path.strip():
        raise LegacyRomMetadataPlanError(
            f"Legacy file_path for {row.title!r} changed after the audit."
        )
    if os.path.islink(_absolute(current_file_path)):
        raise LegacyRomMetadataPlanError(
            f"Legacy ROM became a symbolic link after the audit: {current_file_path}"
        )
    if _path_identity(current_file_path) != _path_identity(row.current_path):
        raise LegacyRomMetadataPlanError(
            f"Legacy file_path ownership for {row.title!r} changed after the audit."
        )

    files = raw_record.get("files")
    if files is not None:
        if not isinstance(files, list) or files:
            raise LegacyRomMetadataPlanError(
                f"Modern files[] metadata for {row.title!r} changed after the audit."
            )

    suffix = Path(current_file_path).suffix.lower()
    if suffix not in _SUPPORTED_ROM_SUFFIXES:
        raise LegacyRomMetadataPlanError(
            f"Legacy ROM extension for {row.title!r} is no longer supported."
        )
    return raw_record


def _reject_duplicate_current_ownership(
    candidate_paths: Mapping[str, str],
    collection_data: Mapping[str, Any],
) -> None:
    owners: dict[str, list[str]] = {}
    for raw_collection_id, raw_record in collection_data.items():
        if not isinstance(raw_record, Mapping):
            continue
        path = raw_record.get("file_path")
        if not isinstance(path, str) or not path.strip():
            continue
        identity = _path_identity(path)
        if identity in candidate_paths:
            owners.setdefault(identity, []).append(str(raw_collection_id))

    for identity, collection_ids in owners.items():
        expected_owner = candidate_paths[identity]
        if collection_ids != [expected_owner]:
            raise LegacyRomMetadataPlanError(
                "Legacy ROM path ownership changed after the audit; run the audit again."
            )


def build_legacy_rom_metadata_modernization_plan(
    audit: LegacyRomMetadataAudit,
    collection_data: Mapping[str, Any],
    collection_revision_token: str,
) -> LegacyRomMetadataModernizationPlan:
    """Hash and freeze only audit-ready legacy ROM metadata without writing it."""
    if not isinstance(audit, LegacyRomMetadataAudit):
        raise TypeError("audit must be a LegacyRomMetadataAudit")
    if not isinstance(collection_data, Mapping):
        raise TypeError("Collection data must be a mapping.")
    revision = str(collection_revision_token or "").strip()
    if not revision:
        raise LegacyRomMetadataPlanError(
            "Collection revision token is required before previewing modernization."
        )
    audited_revision = str(audit.collection_revision_token or "").strip()
    if not audited_revision:
        raise LegacyRomMetadataPlanError(
            "The legacy metadata audit has no Collection revision precondition. Run the audit again."
        )
    if audited_revision != revision:
        raise LegacyRomMetadataPlanError(
            "Collection changed after the legacy metadata audit. Run the audit again."
        )

    ready_rows = [row for row in audit.rows if row.status == STATUS_READY]
    if not ready_rows:
        raise LegacyRomMetadataPlanError(
            "The legacy metadata audit has no ready ROMs to modernize."
        )

    candidate_paths: dict[str, str] = {}
    for row in ready_rows:
        _validate_exact_legacy_record(row, collection_data)
        identity = _path_identity(row.current_path)
        if identity in candidate_paths:
            raise LegacyRomMetadataPlanError(
                "The legacy metadata audit contains duplicate ready ROM paths."
            )
        candidate_paths[identity] = row.collection_id
    _reject_duplicate_current_ownership(candidate_paths, collection_data)

    operations: list[LegacyRomMetadataBackfillOperation] = []
    for row in ready_rows:
        record = _validate_exact_legacy_record(row, collection_data)
        current_file_path = str(record["file_path"])
        canonical = _canonical(current_file_path)
        if _path_identity(canonical) != _path_identity(row.current_path):
            raise LegacyRomMetadataPlanError(
                f"Legacy ROM target for {row.title!r} changed after the audit."
            )

        sha256, size_bytes, mtime_ns = _hash_stable_regular_file(canonical)
        if row.size_bytes is not None and size_bytes != row.size_bytes:
            raise LegacyRomMetadataPlanError(
                f"Legacy ROM size for {row.title!r} changed after the audit."
            )

        operations.append(
            LegacyRomMetadataBackfillOperation(
                collection_id=row.collection_id,
                title=row.title,
                legacy_file_path=current_file_path,
                canonical_path=canonical,
                asset_name=os.path.basename(canonical),
                sha256=sha256,
                size_bytes=size_bytes,
                source_mtime_ns=mtime_ns,
                smwc_submission_id=row.proposed_smwc_submission_id,
                ingestion_source=row.proposed_ingestion_source,
            )
        )

    ordered = tuple(
        sorted(
            operations,
            key=lambda operation: (
                operation.title.casefold(),
                operation.collection_id,
                operation.canonical_path.casefold(),
            ),
        )
    )
    return LegacyRomMetadataModernizationPlan(
        collection_revision_token=revision,
        operations=ordered,
        audit_row_count=len(audit.rows),
        excluded_blocking_count=audit.blocking_count,
    )


def build_reviewed_legacy_rom_metadata_modernization_plan(
    audit: LegacyRomMetadataAudit,
    review: LegacyRomProvenanceReview,
    decision: LegacyRomProvenanceDecision,
    collection_data: Mapping[str, Any],
    collection_revision_token: str,
) -> ReviewedLegacyRomMetadataModernizationPlan:
    """Hash/freeze ambiguous legacy ROMs only after explicit recorded-ID provenance choices."""
    if not isinstance(audit, LegacyRomMetadataAudit):
        raise TypeError("audit must be a LegacyRomMetadataAudit")
    if not isinstance(review, LegacyRomProvenanceReview):
        raise TypeError("review must be a LegacyRomProvenanceReview")
    if not isinstance(decision, LegacyRomProvenanceDecision):
        raise TypeError("decision must be a LegacyRomProvenanceDecision")
    if not isinstance(collection_data, Mapping):
        raise TypeError("Collection data must be a mapping.")

    revision = str(collection_revision_token or "").strip()
    if not revision:
        raise LegacyRomMetadataPlanError(
            "Collection revision token is required before previewing reviewed modernization."
        )
    revisions = {
        str(audit.collection_revision_token or "").strip(),
        str(review.collection_revision_token or "").strip(),
        str(decision.collection_revision_token or "").strip(),
        revision,
    }
    if "" in revisions or len(revisions) != 1:
        raise LegacyRomMetadataPlanError(
            "Collection or provenance review changed before modernization planning. Run the legacy metadata audit again."
        )

    audit_rows = {
        row.collection_id: row
        for row in audit.rows
        if row.status == STATUS_REVIEW_PROVENANCE
    }
    review_rows = {row.collection_id: row for row in review.rows}
    selected = dict(decision.selections)
    if set(review_rows) != set(selected):
        raise LegacyRomMetadataPlanError(
            "The saved provenance decision no longer covers the exact reviewed legacy ROM set."
        )

    candidate_paths: dict[str, str] = {}
    for collection_id, review_row in review_rows.items():
        audit_row = audit_rows.get(collection_id)
        if audit_row is None:
            raise LegacyRomMetadataPlanError(
                "The saved provenance review no longer matches the legacy metadata audit."
            )
        chosen = selected[collection_id]
        if chosen not in review_row.candidate_smwc_submission_ids:
            raise LegacyRomMetadataPlanError(
                f"Selected SMWC provenance for {review_row.title!r} is no longer an allowed recorded identity."
            )
        _validate_exact_legacy_record(audit_row, collection_data)
        identity = _path_identity(audit_row.current_path)
        if identity in candidate_paths:
            raise LegacyRomMetadataPlanError(
                "The reviewed provenance set contains duplicate legacy ROM paths."
            )
        candidate_paths[identity] = collection_id
    _reject_duplicate_current_ownership(candidate_paths, collection_data)

    operations: list[LegacyRomMetadataBackfillOperation] = []
    for collection_id, review_row in review_rows.items():
        audit_row = audit_rows[collection_id]
        record = _validate_exact_legacy_record(audit_row, collection_data)
        current_file_path = str(record["file_path"])
        canonical = _canonical(current_file_path)
        if _path_identity(canonical) != _path_identity(audit_row.current_path):
            raise LegacyRomMetadataPlanError(
                f"Legacy ROM target for {audit_row.title!r} changed after provenance review."
            )
        sha256, size_bytes, mtime_ns = _hash_stable_regular_file(canonical)
        if audit_row.size_bytes is not None and size_bytes != audit_row.size_bytes:
            raise LegacyRomMetadataPlanError(
                f"Legacy ROM size for {audit_row.title!r} changed after provenance review."
            )
        operations.append(
            LegacyRomMetadataBackfillOperation(
                collection_id=collection_id,
                title=audit_row.title,
                legacy_file_path=current_file_path,
                canonical_path=canonical,
                asset_name=os.path.basename(canonical),
                sha256=sha256,
                size_bytes=size_bytes,
                source_mtime_ns=mtime_ns,
                smwc_submission_id=selected[collection_id],
                ingestion_source="legacy_collection_backfill_reviewed_provenance",
            )
        )

    ordered = tuple(
        sorted(
            operations,
            key=lambda operation: (
                operation.title.casefold(),
                operation.collection_id,
                operation.canonical_path.casefold(),
            ),
        )
    )
    return ReviewedLegacyRomMetadataModernizationPlan(
        collection_revision_token=revision,
        operations=ordered,
        reviewed_row_count=len(review_rows),
    )


__all__ = [
    "LegacyRomMetadataBackfillOperation",
    "LegacyRomMetadataModernizationPlan",
    "ReviewedLegacyRomMetadataModernizationPlan",
    "LegacyRomMetadataPlanError",
    "build_legacy_rom_metadata_modernization_plan",
    "build_reviewed_legacy_rom_metadata_modernization_plan",
]
