"""Read-only save-impact review for immutable Collection ROM organization plans.

ROM organization can change directories without changing ROM basenames.  The app
cannot infer an emulator's save-location policy from Save Data Sync settings, so
this module only discovers plausible save relationships.  It never moves, copies,
renames, deletes, creates, or rewrites ROM/save files or Collection/config state.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable, Mapping

from collection_rom_organization_plan import (
    CollectionRomMoveOperation,
    CollectionRomOrganizationPlan,
)
from save_sync import SAVE_EXTENSIONS, association_key, clean_save_associations, clean_save_directories


SOURCE_COLOCATED = "colocated"
SOURCE_CONFIGURED_NAME = "configured_name"
SOURCE_CONFIGURED_ASSOCIATION = "configured_association"


class CollectionRomSaveImpactError(RuntimeError):
    """Raised when save-impact discovery cannot be performed safely."""


@dataclass(frozen=True)
class CollectionRomSaveImpactRow:
    """One discovered save whose relationship to a planned ROM move is reviewable."""

    collection_id: str
    title: str
    rom_source_path: str
    rom_target_path: str
    save_path: str
    save_name: str
    source_kind: str
    source_detail: str
    size_bytes: int
    mtime_ns: int
    possible_target_path: str = ""
    target_occupied: bool = False

    @property
    def colocated(self) -> bool:
        return self.source_kind == SOURCE_COLOCATED


@dataclass(frozen=True)
class CollectionRomSaveImpactReview:
    """Read-only save evidence for one immutable organization plan."""

    plan: CollectionRomOrganizationPlan
    configured_save_directories: tuple[str, ...]
    rows: tuple[CollectionRomSaveImpactRow, ...]

    @property
    def colocated_count(self) -> int:
        return sum(row.colocated for row in self.rows)

    @property
    def external_count(self) -> int:
        return len(self.rows) - self.colocated_count

    @property
    def target_conflict_count(self) -> int:
        return sum(row.target_occupied for row in self.rows)


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _canonical(path: str) -> str:
    return os.path.realpath(_absolute(path))


def _path_identity(path: str) -> str:
    return os.path.normcase(_canonical(path))


def _save_name_matches_rom(save_name: str, rom_path: str) -> bool:
    """Use Save Sync's conservative filename normalization for relationship evidence."""

    return association_key(save_name) == association_key(os.path.basename(rom_path))


def _save_files(directory: str) -> list[str]:
    """List supported regular save files non-recursively without mutating the folder."""

    if not directory or not os.path.isdir(directory):
        return []
    try:
        names = os.listdir(directory)
    except OSError as error:
        raise CollectionRomSaveImpactError(
            f"Cannot inspect save directory {directory!r}: {error}"
        ) from error

    paths: list[str] = []
    for name in names:
        candidate = os.path.join(directory, name)
        if os.path.splitext(name)[1].lower() not in SAVE_EXTENSIONS:
            continue
        if not os.path.isfile(candidate):
            continue
        paths.append(_canonical(candidate))
    return sorted(paths, key=lambda path: os.path.basename(path).casefold())


def _stat_save(path: str) -> tuple[int, int]:
    try:
        stat = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise CollectionRomSaveImpactError(f"Cannot inspect save file {path!r}: {error}") from error
    return stat.st_size, stat.st_mtime_ns


def _colocated_rows(move: CollectionRomMoveOperation) -> list[CollectionRomSaveImpactRow]:
    source_dir = os.path.dirname(move.source_path)
    target_dir = os.path.dirname(move.target_path)
    stem = os.path.splitext(os.path.basename(move.source_path))[0]
    rows: list[CollectionRomSaveImpactRow] = []

    for candidate in _save_files(source_dir):
        if os.path.splitext(os.path.basename(candidate))[0].casefold() != stem.casefold():
            continue
        size_bytes, mtime_ns = _stat_save(candidate)
        possible_target = _canonical(os.path.join(target_dir, os.path.basename(candidate)))
        target_occupied = (
            _path_identity(candidate) != _path_identity(possible_target)
            and os.path.exists(possible_target)
        )
        rows.append(
            CollectionRomSaveImpactRow(
                collection_id=move.collection_id,
                title=move.title,
                rom_source_path=move.source_path,
                rom_target_path=move.target_path,
                save_path=candidate,
                save_name=os.path.basename(candidate),
                source_kind=SOURCE_COLOCATED,
                source_detail=(
                    "Same-basename save is beside the ROM. If the emulator stores saves "
                    "with content, this save may need an explicit migration decision."
                ),
                size_bytes=size_bytes,
                mtime_ns=mtime_ns,
                possible_target_path=possible_target,
                target_occupied=target_occupied,
            )
        )
    return rows


def _configured_rows(
    move: CollectionRomMoveOperation,
    configured_directories: Iterable[str],
    associations: Mapping[str, str],
    seen_paths: set[str],
    seen_collection_paths: set[tuple[str, str]],
) -> list[CollectionRomSaveImpactRow]:
    rows: list[CollectionRomSaveImpactRow] = []
    for directory in configured_directories:
        for path in _save_files(directory):
            identity = _path_identity(path)
            collection_identity = (move.collection_id, identity)
            if identity in seen_paths or collection_identity in seen_collection_paths:
                continue
            save_name = os.path.basename(path)
            key = association_key(save_name)
            name_match = _save_name_matches_rom(save_name, move.source_path)
            association_match = associations.get(key) == move.collection_id
            if not name_match and not association_match:
                continue

            size_bytes, mtime_ns = _stat_save(path)
            if association_match and not name_match:
                source_kind = SOURCE_CONFIGURED_ASSOCIATION
                detail = (
                    "Configured Save Sync file has an explicit saved filename association "
                    "to this Collection entry. Its emulator storage policy is unknown, so "
                    "no filesystem move is proposed."
                )
            else:
                source_kind = SOURCE_CONFIGURED_NAME
                detail = (
                    "Configured Save Sync file matches the ROM filename. It may be a central "
                    "save-directory copy; no filesystem move is proposed from this evidence."
                )

            rows.append(
                CollectionRomSaveImpactRow(
                    collection_id=move.collection_id,
                    title=move.title,
                    rom_source_path=move.source_path,
                    rom_target_path=move.target_path,
                    save_path=path,
                    save_name=save_name,
                    source_kind=source_kind,
                    source_detail=detail,
                    size_bytes=size_bytes,
                    mtime_ns=mtime_ns,
                )
            )
            seen_paths.add(identity)
            seen_collection_paths.add(collection_identity)
    return rows


def build_collection_rom_save_impact_review(
    plan: CollectionRomOrganizationPlan,
    configured_save_directories: Iterable[str] = (),
    save_associations: Mapping[str, str] | None = None,
) -> CollectionRomSaveImpactReview:
    """Discover plausible save impact without deciding or performing any migration."""

    if not isinstance(plan, CollectionRomOrganizationPlan):
        raise TypeError("plan must be a CollectionRomOrganizationPlan")

    directories = tuple(clean_save_directories(list(configured_save_directories)))
    associations = clean_save_associations(save_associations or {})
    rows: list[CollectionRomSaveImpactRow] = []
    seen_configured_collection_paths: set[tuple[str, str]] = set()

    for move in plan.moves:
        colocated = _colocated_rows(move)
        rows.extend(colocated)
        seen = {_path_identity(row.save_path) for row in colocated}
        rows.extend(
            _configured_rows(
                move,
                directories,
                associations,
                seen,
                seen_configured_collection_paths,
            )
        )

    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                row.title.casefold(),
                row.collection_id,
                row.save_name.casefold(),
                row.save_path.casefold(),
            ),
        )
    )
    return CollectionRomSaveImpactReview(
        plan=plan,
        configured_save_directories=directories,
        rows=ordered,
    )


__all__ = [
    "CollectionRomSaveImpactError",
    "CollectionRomSaveImpactReview",
    "CollectionRomSaveImpactRow",
    "SOURCE_COLOCATED",
    "SOURCE_CONFIGURED_ASSOCIATION",
    "SOURCE_CONFIGURED_NAME",
    "build_collection_rom_save_impact_review",
]
