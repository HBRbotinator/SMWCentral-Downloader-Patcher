"""Read-only explicit provenance decisions for ambiguous legacy ROM records.

This boundary consumes legacy metadata audit rows already classified
``review_provenance`` because a numeric Collection record has recorded identity
migration history.  It offers only SMWC submission IDs already present in the
Collection record (current identity plus recorded prior/history IDs).  It never
calls providers and never mutates Collection or filesystem state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from collection_rom_legacy_metadata import LegacyRomMetadataAudit, STATUS_REVIEW_PROVENANCE


class LegacyRomProvenanceReviewError(RuntimeError):
    """Raised when detached legacy provenance review can no longer be built safely."""


@dataclass(frozen=True)
class LegacyRomProvenanceChoiceRow:
    collection_id: str
    title: str
    current_path: str
    candidate_smwc_submission_ids: tuple[int, ...]
    current_smwc_submission_id: int


@dataclass(frozen=True)
class LegacyRomProvenanceReview:
    collection_revision_token: str
    rows: tuple[LegacyRomProvenanceChoiceRow, ...]

    def __post_init__(self) -> None:
        if not self.collection_revision_token.strip():
            raise LegacyRomProvenanceReviewError("Legacy provenance review requires a Collection revision.")
        if not self.rows:
            raise LegacyRomProvenanceReviewError("No ambiguous legacy provenance rows are eligible for review.")


@dataclass(frozen=True)
class LegacyRomProvenanceDecision:
    collection_revision_token: str
    selections: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        ids = [collection_id for collection_id, _ in self.selections]
        if len(ids) != len(set(ids)):
            raise LegacyRomProvenanceReviewError("Legacy provenance decision contains duplicate Collection IDs.")
        for collection_id, submission_id in self.selections:
            if not collection_id or isinstance(submission_id, bool) or submission_id <= 0:
                raise LegacyRomProvenanceReviewError("Legacy provenance decisions require positive SMWC IDs.")


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def recorded_legacy_rom_provenance_ids(collection_id: str, record: Mapping[str, Any]) -> tuple[int, ...]:
    current = _positive_int(collection_id)
    if current is None:
        return ()
    candidates = {current}
    prior = record.get("prior_smwc_submission_ids", [])
    if isinstance(prior, list):
        for value in prior:
            parsed = _positive_int(value)
            if parsed is not None:
                candidates.add(parsed)
    history = record.get("identity_migration_history", [])
    if isinstance(history, list):
        for event in history:
            if not isinstance(event, Mapping):
                continue
            for key in ("source_key", "target_key"):
                parsed = _positive_int(event.get(key))
                if parsed is not None:
                    candidates.add(parsed)
    return tuple(sorted(candidates))


def build_legacy_rom_provenance_review(
    audit: LegacyRomMetadataAudit,
    collection_data: Mapping[str, Any],
    collection_revision_token: str,
) -> LegacyRomProvenanceReview:
    if audit.collection_revision_token != collection_revision_token:
        raise LegacyRomProvenanceReviewError(
            "Collection changed after the legacy metadata audit. Run the audit again."
        )
    rows: list[LegacyRomProvenanceChoiceRow] = []
    for audit_row in audit.rows:
        if audit_row.status != STATUS_REVIEW_PROVENANCE:
            continue
        current = _positive_int(audit_row.collection_id)
        record = collection_data.get(audit_row.collection_id)
        if current is None or not isinstance(record, Mapping):
            continue
        candidates = recorded_legacy_rom_provenance_ids(audit_row.collection_id, record)
        # A useful decision requires at least one recorded alternative to current identity.
        if len(candidates) < 2:
            continue
        current_path = str(record.get("file_path", "") or "").strip()
        if not current_path or current_path != audit_row.current_path:
            # The audit stores canonical paths for these rows; compare canonicalized text lazily
            # through the audit boundary by requiring the currently displayed path to remain owned.
            import os
            from pathlib import Path
            if not current_path or str(Path(current_path).expanduser().resolve()) != audit_row.current_path:
                raise LegacyRomProvenanceReviewError(
                    f"Legacy file_path for {audit_row.title!r} changed after the audit."
                )
        rows.append(
            LegacyRomProvenanceChoiceRow(
                collection_id=audit_row.collection_id,
                title=audit_row.title,
                current_path=audit_row.current_path,
                candidate_smwc_submission_ids=candidates,
                current_smwc_submission_id=current,
            )
        )
    return LegacyRomProvenanceReview(
        collection_revision_token=collection_revision_token,
        rows=tuple(rows),
    )


def build_legacy_rom_provenance_decision(
    review: LegacyRomProvenanceReview,
    selections: Mapping[str, int],
) -> LegacyRomProvenanceDecision:
    frozen: list[tuple[str, int]] = []
    for row in review.rows:
        selected = selections.get(row.collection_id)
        if selected is None:
            raise LegacyRomProvenanceReviewError(
                f"Choose provenance for {row.title!r} before saving the review."
            )
        if selected not in row.candidate_smwc_submission_ids:
            raise LegacyRomProvenanceReviewError(
                f"Selected SMWC provenance for {row.title!r} is not recorded in Collection history."
            )
        frozen.append((row.collection_id, selected))
    return LegacyRomProvenanceDecision(
        collection_revision_token=review.collection_revision_token,
        selections=tuple(frozen),
    )


__all__ = [
    "LegacyRomProvenanceChoiceRow",
    "LegacyRomProvenanceDecision",
    "LegacyRomProvenanceReview",
    "LegacyRomProvenanceReviewError",
    "build_legacy_rom_provenance_decision",
    "recorded_legacy_rom_provenance_ids",
    "build_legacy_rom_provenance_review",
]
