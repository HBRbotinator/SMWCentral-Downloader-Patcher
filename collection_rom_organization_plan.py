"""Immutable read-only plans for explicit Collection ROM organization.

This module turns only the audit's already-safe ``Would move`` rows into a frozen
move plan.  It performs no filesystem mutation.  The plan captures Collection and
source/target preconditions so a later execution boundary can fail closed rather
than re-deciding organization semantics.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

from collection_rom_assets import CollectionRomAssetError, collection_rom_asset_views
from collection_rom_organization import (
    CollectionRomOrganizationAudit,
    STATUS_NEEDS_ORGANIZATION,
    expected_collection_rom_path,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CollectionRomOrganizationPlanError(RuntimeError):
    """Raised when an audit cannot safely become an immutable move plan."""


@dataclass(frozen=True)
class CollectionRomMoveOperation:
    """One future ROM move with exact reviewed source/target preconditions."""

    collection_id: str
    title: str
    asset_name: str
    source_path: str
    target_path: str
    sha256: str
    size_bytes: int
    source_mtime_ns: int
    primary: bool
    smwc_submission_id: int | None

    def __post_init__(self) -> None:
        if not self.collection_id.strip():
            raise CollectionRomOrganizationPlanError("ROM move requires Collection identity.")
        if not self.source_path or not self.target_path:
            raise CollectionRomOrganizationPlanError("ROM move requires source and target paths.")
        if _path_identity(self.source_path) == _path_identity(self.target_path):
            raise CollectionRomOrganizationPlanError("ROM move source and target must differ.")
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise CollectionRomOrganizationPlanError(
                "ROM move requires a recorded lowercase SHA-256 precondition."
            )
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise CollectionRomOrganizationPlanError(
                "ROM move requires a non-negative recorded byte size."
            )
        if isinstance(self.source_mtime_ns, bool) or self.source_mtime_ns < 0:
            raise CollectionRomOrganizationPlanError(
                "ROM move requires a non-negative source mtime precondition."
            )
        if self.smwc_submission_id is not None and (
            not isinstance(self.smwc_submission_id, int)
            or isinstance(self.smwc_submission_id, bool)
            or self.smwc_submission_id <= 0
        ):
            raise CollectionRomOrganizationPlanError(
                "ROM move SMWC provenance must be a positive submission ID when present."
            )


@dataclass(frozen=True)
class CollectionRomOrganizationPlan:
    """Immutable preview of safe ROM moves derived from one Collection audit."""

    output_dir: str
    collection_revision_token: str
    moves: tuple[CollectionRomMoveOperation, ...]
    audit_row_count: int
    in_place_count: int
    excluded_blocking_count: int

    def __post_init__(self) -> None:
        if not self.output_dir:
            raise CollectionRomOrganizationPlanError("Organization plan requires output_dir.")
        if not self.collection_revision_token.strip():
            raise CollectionRomOrganizationPlanError(
                "Organization plan requires a Collection revision precondition."
            )
        if not self.moves:
            raise CollectionRomOrganizationPlanError(
                "Organization plan requires at least one safe ROM move."
            )
        if min(self.audit_row_count, self.in_place_count, self.excluded_blocking_count) < 0:
            raise CollectionRomOrganizationPlanError("Organization plan counts cannot be negative.")

        sources = [_path_identity(move.source_path) for move in self.moves]
        targets = [_path_identity(move.target_path) for move in self.moves]
        if len(sources) != len(set(sources)):
            raise CollectionRomOrganizationPlanError("Organization plan has duplicate sources.")
        if len(targets) != len(set(targets)):
            raise CollectionRomOrganizationPlanError("Organization plan has duplicate targets.")


@dataclass(frozen=True)
class _CurrentAsset:
    path: str
    sha256: str
    size_bytes: int
    primary: bool
    smwc_submission_id: int | None


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _canonical(path: str) -> str:
    return os.path.realpath(_absolute(path))


def _path_identity(path: str) -> str:
    return os.path.normcase(_canonical(path))


def _is_within_root(path: str, root: str) -> bool:
    try:
        return os.path.commonpath((_path_identity(path), _path_identity(root))) == _path_identity(root)
    except ValueError:
        return False


def _current_asset(record: Mapping[str, Any], expected_path: str) -> _CurrentAsset:
    try:
        views = collection_rom_asset_views(record)
    except CollectionRomAssetError as error:
        raise CollectionRomOrganizationPlanError(
            f"Collection ROM metadata changed after the audit: {error}"
        ) from error

    matching = [view for view in views if _path_identity(view.path) == _path_identity(expected_path)]
    if len(matching) != 1:
        raise CollectionRomOrganizationPlanError(
            "A move candidate no longer resolves to exactly one modern Collection ROM asset."
        )
    view = matching[0]
    if _SHA256_RE.fullmatch(view.sha256 or "") is None:
        raise CollectionRomOrganizationPlanError(
            f"ROM asset {view.name!r} has no valid recorded SHA-256; exact byte identity is required."
        )
    if view.size_bytes is None:
        raise CollectionRomOrganizationPlanError(
            f"ROM asset {view.name!r} has no recorded byte size; exact file preconditions are required."
        )
    return _CurrentAsset(
        path=_canonical(view.path),
        sha256=view.sha256,
        size_bytes=view.size_bytes,
        primary=view.primary,
        smwc_submission_id=view.smwc_submission_id,
    )


def build_collection_rom_organization_plan(
    audit: CollectionRomOrganizationAudit,
    collection_data: Mapping[str, Any],
    collection_revision_token: str,
) -> CollectionRomOrganizationPlan:
    """Freeze audit-safe move candidates without moving or rewriting anything.

    The audit remains the semantic decision boundary.  This function rechecks the
    live Collection metadata and filesystem facts needed to ensure the preview has
    not already gone stale, then captures those facts as immutable preconditions.
    """

    if not isinstance(audit, CollectionRomOrganizationAudit):
        raise TypeError("audit must be a CollectionRomOrganizationAudit")
    if not isinstance(collection_data, Mapping):
        raise TypeError("Collection data must be a mapping.")
    if not str(collection_revision_token or "").strip():
        raise CollectionRomOrganizationPlanError(
            "Collection revision token is required before previewing a move plan."
        )

    output_root = _canonical(audit.output_dir)
    candidates = [row for row in audit.rows if row.status == STATUS_NEEDS_ORGANIZATION]
    if not candidates:
        raise CollectionRomOrganizationPlanError(
            "The audit has no safe ROM move candidates to preview."
        )

    moves: list[CollectionRomMoveOperation] = []
    for row in candidates:
        raw_record = collection_data.get(row.collection_id)
        if not isinstance(raw_record, Mapping):
            raise CollectionRomOrganizationPlanError(
                f"Collection record {row.collection_id!r} changed after the audit."
            )
        record = raw_record
        asset = _current_asset(record, row.current_path)

        expected_now = expected_collection_rom_path(
            output_root,
            str(record.get("hack_type", "standard") or "standard"),
            str(record.get("current_difficulty", "Unknown") or "Unknown"),
            os.path.basename(asset.path),
        )
        if _path_identity(expected_now) != _path_identity(row.expected_path):
            raise CollectionRomOrganizationPlanError(
                f"The expected ROM layout for {row.title!r} changed after the audit. Run the audit again."
            )
        if not _is_within_root(expected_now, output_root):
            raise CollectionRomOrganizationPlanError(
                "A planned ROM target escapes the configured output directory."
            )
        if os.path.islink(asset.path):
            raise CollectionRomOrganizationPlanError(
                f"ROM asset {row.asset_name!r} is a symbolic link and requires explicit review."
            )
        if not os.path.isfile(asset.path):
            raise CollectionRomOrganizationPlanError(
                f"ROM source disappeared after the audit: {asset.path}"
            )
        if os.path.exists(expected_now):
            raise CollectionRomOrganizationPlanError(
                f"ROM target became occupied after the audit: {expected_now}"
            )

        stat = os.stat(asset.path, follow_symlinks=False)
        if stat.st_size != asset.size_bytes:
            raise CollectionRomOrganizationPlanError(
                f"ROM source size changed after it was recorded: {asset.path}"
            )

        if row.primary != asset.primary or row.smwc_submission_id != asset.smwc_submission_id:
            raise CollectionRomOrganizationPlanError(
                f"ROM metadata for {row.asset_name!r} changed after the audit. Run the audit again."
            )

        moves.append(
            CollectionRomMoveOperation(
                collection_id=row.collection_id,
                title=row.title,
                asset_name=row.asset_name,
                source_path=asset.path,
                target_path=_canonical(expected_now),
                sha256=asset.sha256,
                size_bytes=asset.size_bytes,
                source_mtime_ns=stat.st_mtime_ns,
                primary=asset.primary,
                smwc_submission_id=asset.smwc_submission_id,
            )
        )

    ordered = tuple(
        sorted(
            moves,
            key=lambda move: (
                move.title.casefold(),
                move.collection_id,
                move.asset_name.casefold(),
                move.source_path.casefold(),
            ),
        )
    )
    return CollectionRomOrganizationPlan(
        output_dir=output_root,
        collection_revision_token=str(collection_revision_token),
        moves=ordered,
        audit_row_count=len(audit.rows),
        in_place_count=audit.in_place_count,
        excluded_blocking_count=audit.blocking_count,
    )


__all__ = [
    "CollectionRomMoveOperation",
    "CollectionRomOrganizationPlan",
    "CollectionRomOrganizationPlanError",
    "build_collection_rom_organization_plan",
]
