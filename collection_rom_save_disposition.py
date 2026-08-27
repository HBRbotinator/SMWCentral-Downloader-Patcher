"""Detached explicit save dispositions for Collection ROM organization.

This boundary records user choices made against a read-only save-impact review.  It
never moves, copies, renames, deletes, creates, hashes, or rewrites ROM/save files,
Collection data, or Save Sync configuration.  A later planning boundary must
re-discover save evidence and compare the frozen review fingerprint before it may
turn these choices into filesystem operations.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping

from collection_rom_save_impact import (
    CollectionRomSaveImpactReview,
    SOURCE_COLOCATED,
)


class CollectionRomSaveDispositionError(RuntimeError):
    """Raised when a save-disposition review is incomplete or unsafe."""


class SaveDisposition(str, Enum):
    """Explicit user choice for one detected colocated save companion."""

    MIGRATE_WITH_ROM = "migrate_with_rom"
    LEAVE_IN_PLACE = "leave_in_place"
    BLOCK_ROM_MOVE = "block_rom_move"


@dataclass(frozen=True)
class CollectionRomSaveCompanionDisposition:
    """One explicit decision for one colocated save/ROM relationship."""

    collection_id: str
    rom_source_path: str
    save_path: str
    disposition: SaveDisposition
    possible_target_path: str
    save_sync_coverage_loss_acknowledged: bool = False


@dataclass(frozen=True)
class CollectionRomMoveSaveDecision:
    """Complete reviewed save disposition for one immutable ROM move."""

    collection_id: str
    rom_source_path: str
    companions: tuple[CollectionRomSaveCompanionDisposition, ...]
    proceed_without_colocated_save: bool

    @property
    def blocks_rom_move(self) -> bool:
        return any(
            item.disposition is SaveDisposition.BLOCK_ROM_MOVE for item in self.companions
        )

    @property
    def migrate_save_count(self) -> int:
        return sum(
            item.disposition is SaveDisposition.MIGRATE_WITH_ROM for item in self.companions
        )

    @property
    def leave_save_count(self) -> int:
        return sum(
            item.disposition is SaveDisposition.LEAVE_IN_PLACE for item in self.companions
        )


@dataclass(frozen=True)
class CollectionRomSaveDispositionDecision:
    """Detached immutable result of a complete save-disposition review."""

    collection_revision_token: str
    review_fingerprint: str
    move_decisions: tuple[CollectionRomMoveSaveDecision, ...]
    external_evidence_count: int

    @property
    def blocked_move_count(self) -> int:
        return sum(item.blocks_rom_move for item in self.move_decisions)

    @property
    def approved_move_count(self) -> int:
        return len(self.move_decisions) - self.blocked_move_count

    @property
    def migrate_save_count(self) -> int:
        return sum(item.migrate_save_count for item in self.move_decisions)

    @property
    def leave_save_count(self) -> int:
        return sum(item.leave_save_count for item in self.move_decisions)

    @property
    def rom_only_acknowledgement_count(self) -> int:
        return sum(item.proceed_without_colocated_save for item in self.move_decisions)


def _companion_key(collection_id: str, rom_source_path: str, save_path: str) -> str:
    """Stable opaque mapping key used by the UI/finalizer boundary."""

    payload = json.dumps(
        [collection_id, rom_source_path, save_path],
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def companion_disposition_key(collection_id: str, rom_source_path: str, save_path: str) -> str:
    """Public stable key for supplying a disposition for one colocated save row."""

    return _companion_key(collection_id, rom_source_path, save_path)


def save_impact_review_fingerprint(review: CollectionRomSaveImpactReview) -> str:
    """Hash the exact immutable plan + discovered save evidence reviewed by the user."""

    if not isinstance(review, CollectionRomSaveImpactReview):
        raise TypeError("review must be a CollectionRomSaveImpactReview")

    plan = review.plan
    payload = {
        "collection_revision_token": plan.collection_revision_token,
        "output_dir": plan.output_dir,
        "moves": [
            {
                "collection_id": move.collection_id,
                "source_path": move.source_path,
                "target_path": move.target_path,
                "sha256": move.sha256,
                "size_bytes": move.size_bytes,
                "source_mtime_ns": move.source_mtime_ns,
                "primary": move.primary,
                "smwc_submission_id": move.smwc_submission_id,
            }
            for move in plan.moves
        ],
        "configured_save_directories": list(review.configured_save_directories),
        "rows": [
            {
                "collection_id": row.collection_id,
                "rom_source_path": row.rom_source_path,
                "rom_target_path": row.rom_target_path,
                "save_path": row.save_path,
                "save_name": row.save_name,
                "source_kind": row.source_kind,
                "size_bytes": row.size_bytes,
                "mtime_ns": row.mtime_ns,
                "possible_target_path": row.possible_target_path,
                "target_occupied": row.target_occupied,
                "save_sync_source_covered": row.save_sync_source_covered,
                "save_sync_target_covered": row.save_sync_target_covered,
            }
            for row in review.rows
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def finalize_collection_rom_save_disposition_decision(
    review: CollectionRomSaveImpactReview,
    *,
    companion_dispositions: Mapping[str, SaveDisposition | str],
    rom_only_acknowledgements: Iterable[str] = (),
    save_sync_coverage_loss_acknowledgements: Iterable[str] = (),
) -> CollectionRomSaveDispositionDecision:
    """Validate a complete explicit review and return detached immutable intent.

    ``rom_only_acknowledgements`` contains ROM source paths for plan moves where no
    colocated save was detected.  This is intentionally an acknowledgement rather
    than a claim that no emulator save exists elsewhere.
    """

    if not isinstance(review, CollectionRomSaveImpactReview):
        raise TypeError("review must be a CollectionRomSaveImpactReview")
    if not isinstance(companion_dispositions, Mapping):
        raise TypeError("companion_dispositions must be a mapping")

    colocated_by_move: dict[tuple[str, str], list] = {}
    expected_keys: dict[str, object] = {}
    for row in review.rows:
        if row.source_kind != SOURCE_COLOCATED:
            continue
        move_key = (row.collection_id, row.rom_source_path)
        colocated_by_move.setdefault(move_key, []).append(row)
        key = _companion_key(row.collection_id, row.rom_source_path, row.save_path)
        if key in expected_keys:
            raise CollectionRomSaveDispositionError(
                "Save-impact review contains duplicate colocated relationship identity."
            )
        expected_keys[key] = row

    supplied_keys = set(companion_dispositions)
    missing = set(expected_keys).difference(supplied_keys)
    unknown = supplied_keys.difference(expected_keys)
    if missing:
        raise CollectionRomSaveDispositionError(
            "Choose a disposition for every detected colocated save before saving the review."
        )
    if unknown:
        raise CollectionRomSaveDispositionError(
            "Save disposition contains rows that are not part of this review."
        )

    coverage_loss_keys = {
        key
        for key, row in expected_keys.items()
        if getattr(row, "save_sync_coverage_lost", False)
    }
    coverage_acknowledgements = {
        str(key)
        for key in save_sync_coverage_loss_acknowledgements
        if str(key)
    }
    unknown_coverage_acknowledgements = coverage_acknowledgements.difference(coverage_loss_keys)
    if unknown_coverage_acknowledgements:
        raise CollectionRomSaveDispositionError(
            "Save Sync coverage acknowledgement contains rows that do not lose configured coverage."
        )

    acknowledgements = {str(path) for path in rom_only_acknowledgements if str(path)}
    move_sources = {move.source_path for move in review.plan.moves}
    if not acknowledgements.issubset(move_sources):
        raise CollectionRomSaveDispositionError(
            "Save disposition contains an acknowledgement for an unknown ROM move."
        )

    decisions: list[CollectionRomMoveSaveDecision] = []
    for move in review.plan.moves:
        move_key = (move.collection_id, move.source_path)
        colocated_rows = colocated_by_move.get(move_key, [])
        companion_decisions: list[CollectionRomSaveCompanionDisposition] = []

        if colocated_rows:
            if move.source_path in acknowledgements:
                raise CollectionRomSaveDispositionError(
                    "A ROM move with detected colocated saves cannot use the no-colocated-save acknowledgement."
                )
            for row in colocated_rows:
                key = _companion_key(row.collection_id, row.rom_source_path, row.save_path)
                raw = companion_dispositions[key]
                try:
                    disposition = (
                        raw if isinstance(raw, SaveDisposition) else SaveDisposition(str(raw))
                    )
                except ValueError as error:
                    raise CollectionRomSaveDispositionError(
                        f"Invalid save disposition for {row.save_name!r}: {raw!r}"
                    ) from error
                coverage_loss_acknowledged = False
                if disposition is SaveDisposition.MIGRATE_WITH_ROM:
                    if not row.possible_target_path:
                        raise CollectionRomSaveDispositionError(
                            f"Save {row.save_name!r} has no reviewed colocated migration target."
                        )
                    if row.target_occupied:
                        raise CollectionRomSaveDispositionError(
                            f"Save {row.save_name!r} cannot migrate because its reviewed target is occupied."
                        )
                    if row.save_sync_coverage_lost:
                        if key not in coverage_acknowledgements:
                            raise CollectionRomSaveDispositionError(
                                f"Acknowledge that migrating {row.save_name!r} will move it out of configured Save Sync coverage."
                            )
                        coverage_loss_acknowledged = True
                companion_decisions.append(
                    CollectionRomSaveCompanionDisposition(
                        collection_id=row.collection_id,
                        rom_source_path=row.rom_source_path,
                        save_path=row.save_path,
                        disposition=disposition,
                        possible_target_path=row.possible_target_path,
                        save_sync_coverage_loss_acknowledged=coverage_loss_acknowledged,
                    )
                )
            proceed_without = False
        else:
            if move.source_path not in acknowledgements:
                raise CollectionRomSaveDispositionError(
                    "Explicitly acknowledge every ROM move for which no colocated save was detected."
                )
            proceed_without = True

        decisions.append(
            CollectionRomMoveSaveDecision(
                collection_id=move.collection_id,
                rom_source_path=move.source_path,
                companions=tuple(companion_decisions),
                proceed_without_colocated_save=proceed_without,
            )
        )

    return CollectionRomSaveDispositionDecision(
        collection_revision_token=review.plan.collection_revision_token,
        review_fingerprint=save_impact_review_fingerprint(review),
        move_decisions=tuple(decisions),
        external_evidence_count=review.external_count,
    )


__all__ = [
    "CollectionRomMoveSaveDecision",
    "CollectionRomSaveCompanionDisposition",
    "CollectionRomSaveDispositionDecision",
    "CollectionRomSaveDispositionError",
    "SaveDisposition",
    "companion_disposition_key",
    "finalize_collection_rom_save_disposition_decision",
    "save_impact_review_fingerprint",
]
