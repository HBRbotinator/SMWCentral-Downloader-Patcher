"""Detached review for ROM variants that converge on one new Collection target.

This boundary is read-only and provider-free. It exists because separate review
items may legitimately resolve to the same new numeric Collection identity only
after the user makes explicit identity decisions. Their ROM variants must then
be reviewed together so plan finalization never invents a primary ROM.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from collection_ingestion import RomFileEvidence
from collection_reconciliation import (
    IgnoredRomDecision,
    ReconciliationError,
    ReconciliationGroup,
    ReviewAction,
    ReviewDecision,
    RomSelectionDecision,
    resolved_target_key,
    validate_review_decision,
)


class CollectionIngestionConvergenceReviewError(ValueError):
    """Raised when converged ROM review state is incomplete or stale."""


@dataclass(frozen=True)
class ConvergedRomReview:
    """ROM evidence from separate groups that now shares one new target."""

    target_key: str
    group_ids: tuple[str, ...]
    rom_files: tuple[RomFileEvidence, ...]


@dataclass(frozen=True)
class ConvergedRomDecision:
    """One explicit target-level ROM selection across converged review groups."""

    target_key: str
    selection: RomSelectionDecision


def _kept_paths_for_group(
    group: ReconciliationGroup,
    decision: ReviewDecision | None,
) -> tuple[str, ...]:
    if decision is not None and decision.rom_selection is not None:
        return decision.rom_selection.kept_paths
    return tuple(rom.path for rom in group.rom_files)


def _target_for_group(
    group: ReconciliationGroup,
    decision: ReviewDecision | None,
) -> str | None:
    validate_review_decision(group, decision)
    if decision is not None and decision.action in {
        ReviewAction.SKIP,
        ReviewAction.IGNORE,
        ReviewAction.IMPORT_LOCAL,
    }:
        return None
    try:
        return resolved_target_key(group, decision)
    except ReconciliationError as error:
        raise CollectionIngestionConvergenceReviewError(str(error)) from error


def build_converged_rom_reviews(
    groups: Sequence[ReconciliationGroup],
    decisions: Mapping[str, ReviewDecision] | None,
    *,
    existing_collection_keys: Sequence[str] = (),
) -> tuple[ConvergedRomReview, ...]:
    """Return new-target ROM sets that require one combined primary decision."""

    decision_map = dict(decisions or {})
    existing = frozenset(existing_collection_keys)
    grouped: dict[str, list[tuple[ReconciliationGroup, ReviewDecision | None]]] = {}

    for group in groups:
        decision = decision_map.get(group.group_id)
        try:
            target_key = _target_for_group(group, decision)
        except ReconciliationError as error:
            raise CollectionIngestionConvergenceReviewError(str(error)) from error
        if not target_key or target_key in existing:
            continue
        kept_paths = _kept_paths_for_group(group, decision)
        if not kept_paths:
            continue
        grouped.setdefault(target_key, []).append((group, decision))

    reviews = []
    for target_key in sorted(grouped):
        rows = grouped[target_key]
        if len(rows) < 2:
            continue

        by_path: dict[str, RomFileEvidence] = {}
        group_ids = []
        for group, decision in rows:
            kept = frozenset(_kept_paths_for_group(group, decision))
            if not kept:
                continue
            group_ids.append(group.group_id)
            for rom in group.rom_files:
                if rom.path not in kept:
                    continue
                previous = by_path.get(rom.path)
                if previous is not None and previous != rom:
                    raise CollectionIngestionConvergenceReviewError(
                        "Reviewed groups contain conflicting ROM evidence for "
                        f"{rom.path!r}."
                    )
                by_path[rom.path] = rom

        if len(by_path) <= 1:
            continue
        reviews.append(
            ConvergedRomReview(
                target_key=target_key,
                group_ids=tuple(sorted(set(group_ids))),
                rom_files=tuple(by_path[path] for path in sorted(by_path)),
            )
        )

    return tuple(reviews)


def validate_converged_rom_decision(
    review: ConvergedRomReview,
    decision: ConvergedRomDecision,
) -> None:
    """Require an exact path/hash-backed selection for one combined review."""

    if decision.target_key != review.target_key:
        raise CollectionIngestionConvergenceReviewError(
            "Converged ROM decision belongs to another Collection target."
        )
    selection = decision.selection
    available = {rom.path: rom for rom in review.rom_files}
    kept = tuple(dict.fromkeys(selection.kept_paths))
    if kept != selection.kept_paths:
        raise CollectionIngestionConvergenceReviewError(
            "Combined ROM selection cannot repeat retained paths."
        )
    if not kept:
        raise CollectionIngestionConvergenceReviewError(
            "Combined ROM review must keep at least one ROM."
        )
    unknown = set(kept).difference(available)
    if unknown:
        raise CollectionIngestionConvergenceReviewError(
            f"Combined ROM selection references unknown paths: {sorted(unknown)!r}"
        )
    if selection.primary_path not in kept:
        raise CollectionIngestionConvergenceReviewError(
            "Combined primary ROM must be one of the retained paths."
        )

    ignored_paths = set()
    for ignored in selection.ignored:
        rom = available.get(ignored.path)
        if rom is None:
            raise CollectionIngestionConvergenceReviewError(
                "Ignored combined ROM path was not part of this review."
            )
        if rom.sha256 != ignored.sha256:
            raise CollectionIngestionConvergenceReviewError(
                "Ignored combined ROM decision must match path + SHA-256."
            )
        if ignored.path in kept:
            raise CollectionIngestionConvergenceReviewError(
                "A combined ROM cannot be both retained and ignored."
            )
        if ignored.path in ignored_paths:
            raise CollectionIngestionConvergenceReviewError(
                "Ignored combined ROM path cannot be repeated."
            )
        ignored_paths.add(ignored.path)


def decision_map_by_target(
    reviews: Sequence[ConvergedRomReview],
    decisions: Mapping[str, ConvergedRomDecision] | None,
) -> dict[str, ConvergedRomDecision]:
    """Validate and normalize detached combined-ROM decisions by target key."""

    supplied = dict(decisions or {})
    review_map = {review.target_key: review for review in reviews}
    unknown = set(supplied).difference(review_map)
    if unknown:
        raise CollectionIngestionConvergenceReviewError(
            f"Combined ROM decisions contain unknown targets: {sorted(unknown)!r}"
        )
    missing = set(review_map).difference(supplied)
    if missing:
        raise CollectionIngestionConvergenceReviewError(
            "Combined ROM review is required before finalization for: "
            + ", ".join(sorted(missing))
        )
    for target_key, review in review_map.items():
        decision = supplied[target_key]
        if decision.target_key != target_key:
            raise CollectionIngestionConvergenceReviewError(
                "Combined ROM decision key does not match its target."
            )
        validate_converged_rom_decision(review, decision)
    return supplied


__all__ = [
    "CollectionIngestionConvergenceReviewError",
    "ConvergedRomDecision",
    "ConvergedRomReview",
    "build_converged_rom_reviews",
    "decision_map_by_target",
    "validate_converged_rom_decision",
]
