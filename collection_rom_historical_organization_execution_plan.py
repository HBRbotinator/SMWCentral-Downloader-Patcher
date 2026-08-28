"""Final immutable execution previews for historical-provenance ROM organization.

This boundary combines an immutable historical ROM move plan with explicit save
choices, re-discovers save evidence, verifies exact ROM/save bytes, and freezes the
last read-only plan before any historical filesystem execution is introduced.
It performs no Collection or filesystem mutation and makes no provider calls.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from collection_rom_historical_organization_plan import (
    HistoricalRomMoveOperation,
    HistoricalRomOrganizationPlan,
)
from collection_rom_organization_execution_plan import (
    CollectionRomSaveLeaveOperation,
    CollectionRomSaveMoveOperation,
)
from collection_rom_save_disposition import (
    CollectionRomSaveDispositionDecision,
    SaveDisposition,
    save_impact_review_fingerprint,
)
from collection_rom_save_impact import (
    SOURCE_COLOCATED,
    build_collection_rom_save_impact_review,
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HistoricalRomOrganizationExecutionPlanError(RuntimeError):
    """Raised when historical ROM/save intent is stale or unsafe to freeze."""


@dataclass(frozen=True)
class HistoricalRomOrganizationExecutionPlan:
    output_dir: str
    collection_revision_token: str
    save_review_fingerprint: str
    rom_moves: tuple[HistoricalRomMoveOperation, ...]
    save_moves: tuple[CollectionRomSaveMoveOperation, ...]
    save_leaves: tuple[CollectionRomSaveLeaveOperation, ...]
    blocked_move_count: int
    external_save_evidence_count: int
    rom_only_acknowledgement_count: int

    @property
    def save_sync_coverage_loss_count(self) -> int:
        return sum(item.save_sync_coverage_loss_acknowledged for item in self.save_moves)

    @property
    def filesystem_move_count(self) -> int:
        return len(self.rom_moves) + len(self.save_moves)

    def __post_init__(self) -> None:
        if not self.output_dir:
            raise HistoricalRomOrganizationExecutionPlanError(
                "Historical execution plan requires output_dir."
            )
        if not self.collection_revision_token.strip():
            raise HistoricalRomOrganizationExecutionPlanError(
                "Historical execution plan requires a Collection revision precondition."
            )
        if not self.save_review_fingerprint.startswith("sha256:"):
            raise HistoricalRomOrganizationExecutionPlanError(
                "Historical execution plan requires the reviewed save-evidence fingerprint."
            )
        if not self.rom_moves:
            raise HistoricalRomOrganizationExecutionPlanError(
                "No approved historical ROM moves remain after save-disposition review."
            )
        if min(
            self.blocked_move_count,
            self.external_save_evidence_count,
            self.rom_only_acknowledgement_count,
        ) < 0:
            raise HistoricalRomOrganizationExecutionPlanError(
                "Historical execution-plan summary counts cannot be negative."
            )
        targets = [_path_identity(item.target_path) for item in self.rom_moves]
        targets.extend(_path_identity(item.target_path) for item in self.save_moves)
        if len(targets) != len(set(targets)):
            raise HistoricalRomOrganizationExecutionPlanError(
                "Historical execution plan has two filesystem operations targeting the same path."
            )
        for target in targets:
            if not _is_within_root(target, self.output_dir):
                raise HistoricalRomOrganizationExecutionPlanError(
                    "Historical execution-plan target escapes the configured output directory."
                )


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _canonical(path: str) -> str:
    return os.path.realpath(_absolute(path))


def _path_identity(path: str) -> str:
    return os.path.normcase(_canonical(path))


def _is_within_root(path: str, root: str) -> bool:
    try:
        root_identity = _path_identity(root)
        return os.path.commonpath((_path_identity(path), root_identity)) == root_identity
    except ValueError:
        return False


def _stat_identity(path: str) -> tuple[int, int, int | None, int | None]:
    try:
        stat = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise HistoricalRomOrganizationExecutionPlanError(
            f"Cannot inspect reviewed historical file {path!r}: {error}"
        ) from error
    if os.path.islink(path) or not os.path.isfile(path):
        raise HistoricalRomOrganizationExecutionPlanError(
            f"Reviewed historical source is no longer a regular non-symlink file: {path}"
        )
    return (
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        getattr(stat, "st_dev", None),
        getattr(stat, "st_ino", None),
    )


def _verified_sha256(
    path: str,
    *,
    expected_size: int,
    expected_mtime_ns: int,
    expected_sha256: str | None = None,
) -> str:
    before = _stat_identity(path)
    if before[0] != expected_size or before[1] != expected_mtime_ns:
        raise HistoricalRomOrganizationExecutionPlanError(
            f"Reviewed historical source changed before final planning: {path}"
        )
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise HistoricalRomOrganizationExecutionPlanError(
            f"Cannot hash reviewed historical file {path!r}: {error}"
        ) from error
    after = _stat_identity(path)
    if before != after:
        raise HistoricalRomOrganizationExecutionPlanError(
            f"Reviewed historical source changed while final-plan hashing was in progress: {path}"
        )
    actual = digest.hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise HistoricalRomOrganizationExecutionPlanError(
            f"Reviewed historical ROM bytes no longer match the frozen SHA-256: {path}"
        )
    if _SHA256_RE.fullmatch(actual) is None:
        raise HistoricalRomOrganizationExecutionPlanError("Invalid SHA-256 result.")
    return actual


def build_historical_rom_organization_execution_plan(
    plan: HistoricalRomOrganizationPlan,
    decision: CollectionRomSaveDispositionDecision,
    *,
    current_collection_revision_token: str,
    configured_save_directories: Iterable[str] = (),
    save_associations: Mapping[str, str] | None = None,
) -> HistoricalRomOrganizationExecutionPlan:
    """Revalidate historical ROM/save review and freeze exact future operations."""

    if not isinstance(plan, HistoricalRomOrganizationPlan):
        raise TypeError("plan must be a HistoricalRomOrganizationPlan")
    if not isinstance(decision, CollectionRomSaveDispositionDecision):
        raise TypeError("decision must be a CollectionRomSaveDispositionDecision")
    current_revision = str(current_collection_revision_token or "").strip()
    if not current_revision:
        raise HistoricalRomOrganizationExecutionPlanError(
            "Current Collection revision token is required for final historical planning."
        )
    if (
        plan.collection_revision_token != current_revision
        or decision.collection_revision_token != current_revision
    ):
        raise HistoricalRomOrganizationExecutionPlanError(
            "Collection changed after historical ROM/save review. Run the organization audit again."
        )

    fresh_review = build_collection_rom_save_impact_review(
        plan,
        configured_save_directories=configured_save_directories,
        save_associations=save_associations,
    )
    fresh_fingerprint = save_impact_review_fingerprint(fresh_review)
    if fresh_fingerprint != decision.review_fingerprint:
        raise HistoricalRomOrganizationExecutionPlanError(
            "Save evidence or historical plan identity changed after disposition review. Review save dispositions again."
        )

    expected_keys = {
        (move.collection_id, _path_identity(move.source_path)) for move in plan.moves
    }
    decisions = {}
    for item in decision.move_decisions:
        key = (item.collection_id, _path_identity(item.rom_source_path))
        if key in decisions:
            raise HistoricalRomOrganizationExecutionPlanError(
                "Historical save disposition contains duplicate ROM move decisions."
            )
        decisions[key] = item
    if set(decisions) != expected_keys:
        raise HistoricalRomOrganizationExecutionPlanError(
            "Historical save disposition no longer covers exactly the immutable move plan."
        )

    colocated: dict[tuple[str, str], dict[str, object]] = {}
    for row in fresh_review.rows:
        if row.source_kind != SOURCE_COLOCATED:
            continue
        key = (row.collection_id, _path_identity(row.rom_source_path))
        by_path = colocated.setdefault(key, {})
        save_key = _path_identity(row.save_path)
        if save_key in by_path:
            raise HistoricalRomOrganizationExecutionPlanError(
                "Fresh historical save review contains duplicate colocated save identity."
            )
        by_path[save_key] = row

    output_root = _canonical(plan.output_dir)
    approved_roms: list[HistoricalRomMoveOperation] = []
    save_moves: list[CollectionRomSaveMoveOperation] = []
    save_leaves: list[CollectionRomSaveLeaveOperation] = []

    for move in plan.moves:
        key = (move.collection_id, _path_identity(move.source_path))
        move_decision = decisions[key]
        if move_decision.blocks_rom_move:
            continue

        source = _canonical(move.source_path)
        target = _canonical(move.target_path)
        if not _is_within_root(target, output_root):
            raise HistoricalRomOrganizationExecutionPlanError(
                f"Reviewed historical ROM target escapes output_dir: {target}"
            )
        if os.path.lexists(target):
            raise HistoricalRomOrganizationExecutionPlanError(
                f"Reviewed historical ROM target became occupied before final planning: {target}"
            )
        _verified_sha256(
            source,
            expected_size=move.size_bytes,
            expected_mtime_ns=move.source_mtime_ns,
            expected_sha256=move.sha256,
        )
        approved_roms.append(move)

        rows = colocated.get(key, {})
        expected_companions = {_path_identity(item.save_path) for item in move_decision.companions}
        if expected_companions != set(rows):
            raise HistoricalRomOrganizationExecutionPlanError(
                "Colocated save evidence no longer matches the reviewed historical disposition set."
            )
        if rows and move_decision.proceed_without_colocated_save:
            raise HistoricalRomOrganizationExecutionPlanError(
                "Historical ROM move cannot acknowledge no save while colocated saves exist."
            )
        if not rows and not move_decision.proceed_without_colocated_save:
            raise HistoricalRomOrganizationExecutionPlanError(
                "Historical ROM move is missing the explicit no-colocated-save acknowledgement."
            )

        for companion in move_decision.companions:
            row = rows[_path_identity(companion.save_path)]
            if companion.disposition is SaveDisposition.MIGRATE_WITH_ROM:
                if row.save_sync_coverage_lost != companion.save_sync_coverage_loss_acknowledged:
                    if row.save_sync_coverage_lost:
                        raise HistoricalRomOrganizationExecutionPlanError(
                            "Historical save migration would leave Save Sync coverage without acknowledgement."
                        )
                    raise HistoricalRomOrganizationExecutionPlanError(
                        "Historical Save Sync coverage acknowledgement no longer matches current evidence."
                    )
                if not companion.possible_target_path or not row.possible_target_path:
                    raise HistoricalRomOrganizationExecutionPlanError(
                        "Reviewed historical save migration target is missing."
                    )
                save_target = _canonical(companion.possible_target_path)
                if _path_identity(save_target) != _path_identity(row.possible_target_path):
                    raise HistoricalRomOrganizationExecutionPlanError(
                        "Reviewed historical save migration target changed before final planning."
                    )
                if not _is_within_root(save_target, output_root):
                    raise HistoricalRomOrganizationExecutionPlanError(
                        f"Reviewed historical save target escapes output_dir: {save_target}"
                    )
                if row.target_occupied or os.path.lexists(save_target):
                    raise HistoricalRomOrganizationExecutionPlanError(
                        f"Reviewed historical save target became occupied: {save_target}"
                    )
                save_sha = _verified_sha256(
                    row.save_path,
                    expected_size=row.size_bytes,
                    expected_mtime_ns=row.mtime_ns,
                )
                save_moves.append(
                    CollectionRomSaveMoveOperation(
                        collection_id=move.collection_id,
                        title=move.collection_title,
                        rom_source_path=move.source_path,
                        source_path=_canonical(row.save_path),
                        target_path=save_target,
                        sha256=save_sha,
                        size_bytes=row.size_bytes,
                        source_mtime_ns=row.mtime_ns,
                        save_sync_coverage_loss_acknowledged=(
                            companion.save_sync_coverage_loss_acknowledged
                        ),
                    )
                )
            elif companion.disposition is SaveDisposition.LEAVE_IN_PLACE:
                save_leaves.append(
                    CollectionRomSaveLeaveOperation(
                        collection_id=move.collection_id,
                        title=move.collection_title,
                        rom_source_path=move.source_path,
                        save_path=_canonical(row.save_path),
                    )
                )
            else:
                raise HistoricalRomOrganizationExecutionPlanError(
                    "A non-blocked historical ROM move contains a blocking save disposition."
                )

    approved = tuple(sorted(approved_roms, key=lambda item: (
        item.collection_title.casefold(), item.collection_id,
        item.historical_smwc_submission_id, item.asset_name.casefold(),
    )))
    save_moves_tuple = tuple(sorted(save_moves, key=lambda item: (
        item.title.casefold(), item.collection_id, item.source_path.casefold(),
    )))
    save_leaves_tuple = tuple(sorted(save_leaves, key=lambda item: (
        item.title.casefold(), item.collection_id, item.save_path.casefold(),
    )))
    return HistoricalRomOrganizationExecutionPlan(
        output_dir=output_root,
        collection_revision_token=current_revision,
        save_review_fingerprint=fresh_fingerprint,
        rom_moves=approved,
        save_moves=save_moves_tuple,
        save_leaves=save_leaves_tuple,
        blocked_move_count=decision.blocked_move_count,
        external_save_evidence_count=decision.external_evidence_count,
        rom_only_acknowledgement_count=decision.rom_only_acknowledgement_count,
    )


__all__ = [
    "HistoricalRomOrganizationExecutionPlan",
    "HistoricalRomOrganizationExecutionPlanError",
    "build_historical_rom_organization_execution_plan",
]
