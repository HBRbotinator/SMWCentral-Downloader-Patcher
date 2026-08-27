"""Final immutable execution plans for reviewed Collection ROM organization.

This boundary combines a frozen ROM organization plan with explicit save
choices, re-discovers save evidence, verifies exact file bytes, and produces the
last read-only plan before filesystem execution may exist.  It performs no move,
copy, rename, delete, directory creation, Collection rewrite, or Save Sync write.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Iterable, Mapping

from collection_rom_organization_plan import (
    CollectionRomMoveOperation,
    CollectionRomOrganizationPlan,
)
from collection_rom_save_disposition import (
    CollectionRomMoveSaveDecision,
    CollectionRomSaveDispositionDecision,
    SaveDisposition,
    save_impact_review_fingerprint,
)
from collection_rom_save_impact import (
    CollectionRomSaveImpactReview,
    SOURCE_COLOCATED,
    build_collection_rom_save_impact_review,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CollectionRomOrganizationExecutionPlanError(RuntimeError):
    """Raised when reviewed organization intent is stale or unsafe to freeze."""


@dataclass(frozen=True)
class CollectionRomSaveMoveOperation:
    """One future colocated save move with exact byte/file preconditions."""

    collection_id: str
    title: str
    rom_source_path: str
    source_path: str
    target_path: str
    sha256: str
    size_bytes: int
    source_mtime_ns: int

    def __post_init__(self) -> None:
        if not self.collection_id.strip():
            raise CollectionRomOrganizationExecutionPlanError(
                "Save move requires Collection identity."
            )
        if not self.source_path or not self.target_path:
            raise CollectionRomOrganizationExecutionPlanError(
                "Save move requires source and target paths."
            )
        if _path_identity(self.source_path) == _path_identity(self.target_path):
            raise CollectionRomOrganizationExecutionPlanError(
                "Save move source and target must differ."
            )
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise CollectionRomOrganizationExecutionPlanError(
                "Save move requires a lowercase SHA-256 precondition."
            )
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise CollectionRomOrganizationExecutionPlanError(
                "Save move requires a non-negative byte size."
            )
        if isinstance(self.source_mtime_ns, bool) or self.source_mtime_ns < 0:
            raise CollectionRomOrganizationExecutionPlanError(
                "Save move requires a non-negative source mtime precondition."
            )


@dataclass(frozen=True)
class CollectionRomSaveLeaveOperation:
    """One explicit reviewed choice to leave a colocated save where it is."""

    collection_id: str
    title: str
    rom_source_path: str
    save_path: str

    def __post_init__(self) -> None:
        if not self.collection_id.strip() or not self.save_path:
            raise CollectionRomOrganizationExecutionPlanError(
                "Save leave decision requires Collection identity and save path."
            )


@dataclass(frozen=True)
class CollectionRomOrganizationExecutionPlan:
    """Immutable final preview containing every future filesystem action."""

    output_dir: str
    collection_revision_token: str
    save_review_fingerprint: str
    rom_moves: tuple[CollectionRomMoveOperation, ...]
    save_moves: tuple[CollectionRomSaveMoveOperation, ...]
    save_leaves: tuple[CollectionRomSaveLeaveOperation, ...]
    blocked_move_count: int
    external_save_evidence_count: int
    rom_only_acknowledgement_count: int

    def __post_init__(self) -> None:
        if not self.output_dir:
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution plan requires the configured ROM output directory."
            )
        if not self.collection_revision_token.strip():
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution plan requires a Collection revision precondition."
            )
        if not self.save_review_fingerprint.startswith("sha256:"):
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution plan requires the reviewed save-evidence fingerprint."
            )
        if not self.rom_moves:
            raise CollectionRomOrganizationExecutionPlanError(
                "No approved ROM moves remain after save-disposition review."
            )
        if min(
            self.blocked_move_count,
            self.external_save_evidence_count,
            self.rom_only_acknowledgement_count,
        ) < 0:
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution-plan summary counts cannot be negative."
            )

        rom_sources = [_path_identity(item.source_path) for item in self.rom_moves]
        rom_targets = [_path_identity(item.target_path) for item in self.rom_moves]
        save_sources = [_path_identity(item.source_path) for item in self.save_moves]
        save_targets = [_path_identity(item.target_path) for item in self.save_moves]
        if len(rom_sources) != len(set(rom_sources)):
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution plan contains duplicate ROM sources."
            )
        if len(rom_targets) != len(set(rom_targets)):
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution plan contains duplicate ROM targets."
            )
        if len(save_sources) != len(set(save_sources)):
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution plan contains duplicate save sources."
            )
        if len(save_targets) != len(set(save_targets)):
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution plan contains duplicate save targets."
            )
        all_targets = rom_targets + save_targets
        if len(all_targets) != len(set(all_targets)):
            raise CollectionRomOrganizationExecutionPlanError(
                "Execution plan has two filesystem operations targeting the same path."
            )
        for target in (item.target_path for item in self.rom_moves):
            if not _is_within_root(target, self.output_dir):
                raise CollectionRomOrganizationExecutionPlanError(
                    "Execution-plan ROM target escapes the configured output directory."
                )
        for target in (item.target_path for item in self.save_moves):
            if not _is_within_root(target, self.output_dir):
                raise CollectionRomOrganizationExecutionPlanError(
                    "Execution-plan save target escapes the configured output directory."
                )

    @property
    def filesystem_move_count(self) -> int:
        return len(self.rom_moves) + len(self.save_moves)


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
        raise CollectionRomOrganizationExecutionPlanError(
            f"Cannot inspect reviewed file {path!r}: {error}"
        ) from error
    if os.path.islink(path) or not os.path.isfile(path):
        raise CollectionRomOrganizationExecutionPlanError(
            f"Reviewed source is no longer a regular non-symlink file: {path}"
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
    """Hash a reviewed regular file and reject changes around the read."""

    before = _stat_identity(path)
    if before[0] != expected_size:
        raise CollectionRomOrganizationExecutionPlanError(
            f"Reviewed source size changed before final planning: {path}"
        )
    if before[1] != expected_mtime_ns:
        raise CollectionRomOrganizationExecutionPlanError(
            f"Reviewed source modification time changed before final planning: {path}"
        )

    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as error:
        raise CollectionRomOrganizationExecutionPlanError(
            f"Cannot hash reviewed file {path!r}: {error}"
        ) from error

    after = _stat_identity(path)
    if before != after:
        raise CollectionRomOrganizationExecutionPlanError(
            f"Reviewed source changed while final plan hashing was in progress: {path}"
        )
    actual = digest.hexdigest()
    if expected_sha256 is not None and actual != expected_sha256:
        raise CollectionRomOrganizationExecutionPlanError(
            f"Reviewed ROM bytes no longer match the recorded SHA-256: {path}"
        )
    return actual


def _move_decisions_by_source(
    plan: CollectionRomOrganizationPlan,
    decision: CollectionRomSaveDispositionDecision,
) -> dict[tuple[str, str], CollectionRomMoveSaveDecision]:
    expected = {(move.collection_id, _path_identity(move.source_path)) for move in plan.moves}
    rows: dict[tuple[str, str], CollectionRomMoveSaveDecision] = {}
    for item in decision.move_decisions:
        key = (item.collection_id, _path_identity(item.rom_source_path))
        if key in rows:
            raise CollectionRomOrganizationExecutionPlanError(
                "Save disposition contains duplicate ROM move decisions."
            )
        rows[key] = item
    if set(rows) != expected:
        raise CollectionRomOrganizationExecutionPlanError(
            "Save disposition no longer covers exactly the immutable ROM move plan."
        )
    return rows


def _colocated_rows_by_move(
    review: CollectionRomSaveImpactReview,
) -> dict[tuple[str, str], dict[str, object]]:
    result: dict[tuple[str, str], dict[str, object]] = {}
    for row in review.rows:
        if row.source_kind != SOURCE_COLOCATED:
            continue
        move_key = (row.collection_id, _path_identity(row.rom_source_path))
        by_path = result.setdefault(move_key, {})
        save_identity = _path_identity(row.save_path)
        if save_identity in by_path:
            raise CollectionRomOrganizationExecutionPlanError(
                "Fresh save-impact review contains duplicate colocated save identity."
            )
        by_path[save_identity] = row
    return result


def build_collection_rom_organization_execution_plan(
    plan: CollectionRomOrganizationPlan,
    decision: CollectionRomSaveDispositionDecision,
    *,
    current_collection_revision_token: str,
    configured_save_directories: Iterable[str] = (),
    save_associations: Mapping[str, str] | None = None,
) -> CollectionRomOrganizationExecutionPlan:
    """Revalidate reviewed intent and freeze exact future ROM/save move operations."""

    if not isinstance(plan, CollectionRomOrganizationPlan):
        raise TypeError("plan must be a CollectionRomOrganizationPlan")
    if not isinstance(decision, CollectionRomSaveDispositionDecision):
        raise TypeError("decision must be a CollectionRomSaveDispositionDecision")
    current_revision = str(current_collection_revision_token or "").strip()
    if not current_revision:
        raise CollectionRomOrganizationExecutionPlanError(
            "Current Collection revision token is required for final planning."
        )
    if (
        plan.collection_revision_token != current_revision
        or decision.collection_revision_token != current_revision
    ):
        raise CollectionRomOrganizationExecutionPlanError(
            "Collection changed after ROM/save review. Run the organization audit again."
        )

    fresh_review = build_collection_rom_save_impact_review(
        plan,
        configured_save_directories=configured_save_directories,
        save_associations=save_associations,
    )
    fresh_fingerprint = save_impact_review_fingerprint(fresh_review)
    if fresh_fingerprint != decision.review_fingerprint:
        raise CollectionRomOrganizationExecutionPlanError(
            "Save evidence changed after disposition review. Review save dispositions again."
        )

    move_decisions = _move_decisions_by_source(plan, decision)
    colocated = _colocated_rows_by_move(fresh_review)
    output_root = _canonical(plan.output_dir)
    approved_rom_moves: list[CollectionRomMoveOperation] = []
    save_moves: list[CollectionRomSaveMoveOperation] = []
    save_leaves: list[CollectionRomSaveLeaveOperation] = []

    for move in plan.moves:
        move_key = (move.collection_id, _path_identity(move.source_path))
        move_decision = move_decisions[move_key]
        if move_decision.blocks_rom_move:
            continue

        source = _canonical(move.source_path)
        target = _canonical(move.target_path)
        if not _is_within_root(target, output_root):
            raise CollectionRomOrganizationExecutionPlanError(
                f"Reviewed ROM target escapes the configured output directory: {target}"
            )
        if os.path.exists(target):
            raise CollectionRomOrganizationExecutionPlanError(
                f"Reviewed ROM target became occupied before final planning: {target}"
            )
        _verified_sha256(
            source,
            expected_size=move.size_bytes,
            expected_mtime_ns=move.source_mtime_ns,
            expected_sha256=move.sha256,
        )
        approved_rom_moves.append(move)

        current_rows = colocated.get(move_key, {})
        expected_companion_paths = {
            _path_identity(item.save_path) for item in move_decision.companions
        }
        if expected_companion_paths != set(current_rows):
            raise CollectionRomOrganizationExecutionPlanError(
                "Colocated save evidence no longer matches the reviewed disposition set."
            )
        if current_rows and move_decision.proceed_without_colocated_save:
            raise CollectionRomOrganizationExecutionPlanError(
                "Reviewed ROM move cannot acknowledge no save while colocated saves exist."
            )
        if not current_rows and not move_decision.proceed_without_colocated_save:
            raise CollectionRomOrganizationExecutionPlanError(
                "Reviewed ROM move is missing the explicit no-colocated-save acknowledgement."
            )

        for companion in move_decision.companions:
            row = current_rows[_path_identity(companion.save_path)]
            if companion.disposition is SaveDisposition.MIGRATE_WITH_ROM:
                target_save = _canonical(companion.possible_target_path)
                if _path_identity(target_save) != _path_identity(row.possible_target_path):
                    raise CollectionRomOrganizationExecutionPlanError(
                        "Reviewed save migration target changed before final planning."
                    )
                if not _is_within_root(target_save, output_root):
                    raise CollectionRomOrganizationExecutionPlanError(
                        f"Reviewed save target escapes the configured output directory: {target_save}"
                    )
                if row.target_occupied or os.path.exists(target_save):
                    raise CollectionRomOrganizationExecutionPlanError(
                        f"Reviewed save target became occupied before final planning: {target_save}"
                    )
                save_sha256 = _verified_sha256(
                    row.save_path,
                    expected_size=row.size_bytes,
                    expected_mtime_ns=row.mtime_ns,
                )
                save_moves.append(
                    CollectionRomSaveMoveOperation(
                        collection_id=move.collection_id,
                        title=move.title,
                        rom_source_path=move.source_path,
                        source_path=_canonical(row.save_path),
                        target_path=target_save,
                        sha256=save_sha256,
                        size_bytes=row.size_bytes,
                        source_mtime_ns=row.mtime_ns,
                    )
                )
            elif companion.disposition is SaveDisposition.LEAVE_IN_PLACE:
                save_leaves.append(
                    CollectionRomSaveLeaveOperation(
                        collection_id=move.collection_id,
                        title=move.title,
                        rom_source_path=move.source_path,
                        save_path=_canonical(row.save_path),
                    )
                )
            else:
                raise CollectionRomOrganizationExecutionPlanError(
                    "A non-blocked ROM move contains an unexpected blocking save disposition."
                )

    ordered_roms = tuple(
        sorted(
            approved_rom_moves,
            key=lambda item: (
                item.title.casefold(),
                item.collection_id,
                item.asset_name.casefold(),
                item.source_path.casefold(),
            ),
        )
    )
    ordered_save_moves = tuple(
        sorted(
            save_moves,
            key=lambda item: (
                item.title.casefold(),
                item.collection_id,
                item.source_path.casefold(),
            ),
        )
    )
    ordered_save_leaves = tuple(
        sorted(
            save_leaves,
            key=lambda item: (
                item.title.casefold(),
                item.collection_id,
                item.save_path.casefold(),
            ),
        )
    )
    return CollectionRomOrganizationExecutionPlan(
        output_dir=output_root,
        collection_revision_token=current_revision,
        save_review_fingerprint=fresh_fingerprint,
        rom_moves=ordered_roms,
        save_moves=ordered_save_moves,
        save_leaves=ordered_save_leaves,
        blocked_move_count=decision.blocked_move_count,
        external_save_evidence_count=decision.external_evidence_count,
        rom_only_acknowledgement_count=decision.rom_only_acknowledgement_count,
    )


__all__ = [
    "CollectionRomOrganizationExecutionPlan",
    "CollectionRomOrganizationExecutionPlanError",
    "CollectionRomSaveLeaveOperation",
    "CollectionRomSaveMoveOperation",
    "build_collection_rom_organization_execution_plan",
]
