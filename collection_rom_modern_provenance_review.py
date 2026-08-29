"""Read-only explicit provenance decisions for modern ROM assets missing SMWC ownership.

Numeric Collection records can contain otherwise-valid modern ``files[]`` rows whose
``smwc_submission_id`` is absent.  Organization must not borrow the record's current
catalogue metadata until the user explicitly chooses which already-recorded numeric
Collection identity owns each ROM asset.  This module performs only detached review;
it never calls providers, hashes ROMs, writes Collection state, or touches files.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from collection_rom_assets import CollectionRomAssetError, collection_rom_asset_views
from collection_rom_organization import (
    CollectionRomOrganizationAudit,
    CollectionRomOrganizationRow,
    STATUS_REVIEW_PROVENANCE,
)
from collection_rom_provenance_history import (
    positive_smwc_submission_id,
    recorded_collection_smwc_submission_ids,
)


class ModernRomProvenanceReviewError(RuntimeError):
    """Raised when a missing-provenance modern ROM review is stale or invalid."""


@dataclass(frozen=True)
class ModernRomProvenanceChoiceRow:
    collection_id: str
    title: str
    asset_name: str
    current_path: str
    candidate_smwc_submission_ids: tuple[int, ...]
    current_smwc_submission_id: int
    primary: bool
    sha256: str
    size_bytes: int | None

    @property
    def decision_key(self) -> tuple[str, str]:
        return (self.collection_id, self.current_path)


@dataclass(frozen=True)
class ModernRomProvenanceReview:
    collection_revision_token: str
    rows: tuple[ModernRomProvenanceChoiceRow, ...]

    def __post_init__(self) -> None:
        if not self.collection_revision_token.strip():
            raise ModernRomProvenanceReviewError(
                "Modern ROM provenance review requires a Collection revision."
            )
        if not self.rows:
            raise ModernRomProvenanceReviewError(
                "No modern ROM assets with missing SMWC provenance are eligible for review."
            )


@dataclass(frozen=True)
class ModernRomProvenanceDecision:
    collection_revision_token: str
    selections: tuple[tuple[str, str, int], ...]

    def __post_init__(self) -> None:
        keys = [(collection_id, path) for collection_id, path, _ in self.selections]
        if len(keys) != len(set(keys)):
            raise ModernRomProvenanceReviewError(
                "Modern ROM provenance decision contains duplicate asset keys."
            )
        for collection_id, path, submission_id in self.selections:
            if (
                not collection_id
                or not path
                or isinstance(submission_id, bool)
                or submission_id <= 0
            ):
                raise ModernRomProvenanceReviewError(
                    "Modern ROM provenance decisions require exact asset paths and positive SMWC IDs."
                )


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _path_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(_absolute(path)))


def _is_missing_provenance_row(row: CollectionRomOrganizationRow) -> bool:
    return (
        row.status == STATUS_REVIEW_PROVENANCE
        and positive_smwc_submission_id(row.collection_id) is not None
        and row.smwc_submission_id is None
        and bool(row.current_path)
    )


def missing_modern_provenance_audit_rows(
    audit: CollectionRomOrganizationAudit,
) -> tuple[CollectionRomOrganizationRow, ...]:
    if not isinstance(audit, CollectionRomOrganizationAudit):
        raise TypeError("audit must be a CollectionRomOrganizationAudit")
    return tuple(row for row in audit.rows if _is_missing_provenance_row(row))


def _find_exact_missing_asset(
    record: Mapping[str, Any],
    audit_row: CollectionRomOrganizationRow,
):
    try:
        views = collection_rom_asset_views(record)
    except CollectionRomAssetError as error:
        raise ModernRomProvenanceReviewError(
            f"Modern ROM metadata changed for {audit_row.title}: {error}"
        ) from error

    matches = [
        view
        for view in views
        if _path_identity(view.path) == _path_identity(audit_row.current_path)
    ]
    if len(matches) != 1:
        raise ModernRomProvenanceReviewError(
            f"ROM asset ownership changed after the organization audit: {audit_row.asset_name}"
        )
    view = matches[0]
    if view.smwc_submission_id is not None:
        raise ModernRomProvenanceReviewError(
            f"ROM provenance changed after the organization audit: {audit_row.asset_name}"
        )
    if (
        view.primary != audit_row.primary
        or view.sha256 != audit_row.sha256
        or view.size_bytes != audit_row.size_bytes
    ):
        raise ModernRomProvenanceReviewError(
            f"ROM asset metadata changed after the organization audit: {audit_row.asset_name}"
        )
    return view


def build_modern_rom_provenance_review(
    audit: CollectionRomOrganizationAudit,
    collection_data: Mapping[str, Any],
    collection_revision_token: str,
) -> ModernRomProvenanceReview:
    """Build detached choices only for numeric modern assets missing provenance."""

    revision = str(collection_revision_token or "").strip()
    if not revision:
        raise ModernRomProvenanceReviewError("Collection revision is required.")

    rows: list[ModernRomProvenanceChoiceRow] = []
    for audit_row in missing_modern_provenance_audit_rows(audit):
        record = collection_data.get(audit_row.collection_id)
        if not isinstance(record, Mapping):
            raise ModernRomProvenanceReviewError(
                f"Collection record {audit_row.collection_id!r} changed after the organization audit."
            )
        current = positive_smwc_submission_id(audit_row.collection_id)
        if current is None:
            continue
        candidates = recorded_collection_smwc_submission_ids(audit_row.collection_id, record)
        if not candidates:
            continue
        view = _find_exact_missing_asset(record, audit_row)
        rows.append(
            ModernRomProvenanceChoiceRow(
                collection_id=audit_row.collection_id,
                title=audit_row.title,
                asset_name=view.name,
                current_path=_absolute(view.path),
                candidate_smwc_submission_ids=candidates,
                current_smwc_submission_id=current,
                primary=view.primary,
                sha256=view.sha256,
                size_bytes=view.size_bytes,
            )
        )

    rows.sort(key=lambda row: (row.title.casefold(), row.collection_id, row.current_path.casefold()))
    return ModernRomProvenanceReview(collection_revision_token=revision, rows=tuple(rows))


def build_modern_rom_provenance_decision(
    review: ModernRomProvenanceReview,
    selections: Mapping[tuple[str, str], int],
) -> ModernRomProvenanceDecision:
    frozen: list[tuple[str, str, int]] = []
    for row in review.rows:
        selected = selections.get(row.decision_key)
        if selected is None:
            raise ModernRomProvenanceReviewError(
                f"Choose provenance for {row.title!r} / {row.asset_name!r} before saving the review."
            )
        if selected not in row.candidate_smwc_submission_ids:
            raise ModernRomProvenanceReviewError(
                f"Selected SMWC provenance for {row.asset_name!r} is not recorded in Collection history."
            )
        frozen.append((row.collection_id, row.current_path, selected))
    return ModernRomProvenanceDecision(
        collection_revision_token=review.collection_revision_token,
        selections=tuple(frozen),
    )


__all__ = [
    "ModernRomProvenanceChoiceRow",
    "ModernRomProvenanceDecision",
    "ModernRomProvenanceReview",
    "ModernRomProvenanceReviewError",
    "build_modern_rom_provenance_decision",
    "build_modern_rom_provenance_review",
    "missing_modern_provenance_audit_rows",
]
