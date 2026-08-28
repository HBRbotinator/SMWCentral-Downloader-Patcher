"""Immutable read-only plans for historical-provenance ROM organization.

This boundary consumes only ``Ready for plan`` rows from the detached historical
provenance review. It revalidates Collection ownership, exact recorded ROM identity,
the historical metadata that justified each target, and current filesystem facts,
then freezes those facts into a historical move plan. It never mutates Collection,
ROM, save, Planner, or Save Sync state.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from typing import Any, Mapping

from collection_rom_assets import CollectionRomAssetError, collection_rom_asset_views
from collection_rom_historical_provenance import (
    HistoricalRomProvenanceReview,
    HistoricalRomProvenanceRow,
    STATUS_READY,
)


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class HistoricalRomOrganizationPlanError(RuntimeError):
    """Raised when a reviewed historical ROM move can no longer be frozen safely."""


@dataclass(frozen=True)
class HistoricalRomMoveOperation:
    collection_id: str
    collection_title: str
    asset_name: str
    source_path: str
    target_path: str
    sha256: str
    size_bytes: int
    source_mtime_ns: int
    primary: bool
    historical_smwc_submission_id: int
    historical_title: str
    historical_hack_type: str
    historical_difficulty: str

    def __post_init__(self) -> None:
        if not self.collection_id.strip():
            raise HistoricalRomOrganizationPlanError(
                "Historical ROM move requires Collection identity."
            )
        if not self.source_path or not self.target_path:
            raise HistoricalRomOrganizationPlanError(
                "Historical ROM move requires source and target paths."
            )
        if _path_identity(self.source_path) == _path_identity(self.target_path):
            raise HistoricalRomOrganizationPlanError(
                "Historical ROM move source and target must differ."
            )
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise HistoricalRomOrganizationPlanError(
                "Historical ROM move requires an exact lowercase SHA-256."
            )
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise HistoricalRomOrganizationPlanError(
                "Historical ROM move requires a non-negative byte size."
            )
        if isinstance(self.source_mtime_ns, bool) or self.source_mtime_ns < 0:
            raise HistoricalRomOrganizationPlanError(
                "Historical ROM move requires a non-negative source mtime."
            )
        if (
            not isinstance(self.historical_smwc_submission_id, int)
            or isinstance(self.historical_smwc_submission_id, bool)
            or self.historical_smwc_submission_id <= 0
        ):
            raise HistoricalRomOrganizationPlanError(
                "Historical ROM move requires positive recorded SMWC provenance."
            )
        if not self.historical_hack_type.strip() or not self.historical_difficulty.strip():
            raise HistoricalRomOrganizationPlanError(
                "Historical ROM move requires the reviewed historical layout metadata."
            )


@dataclass(frozen=True)
class HistoricalRomOrganizationPlan:
    output_dir: str
    collection_revision_token: str
    moves: tuple[HistoricalRomMoveOperation, ...]
    review_row_count: int
    in_place_count: int
    excluded_blocking_count: int

    def __post_init__(self) -> None:
        if not self.output_dir:
            raise HistoricalRomOrganizationPlanError(
                "Historical organization plan requires output_dir."
            )
        if not self.collection_revision_token.strip():
            raise HistoricalRomOrganizationPlanError(
                "Historical organization plan requires a Collection revision precondition."
            )
        if not self.moves:
            raise HistoricalRomOrganizationPlanError(
                "Historical provenance review has no ready ROM moves to preview."
            )
        if min(self.review_row_count, self.in_place_count, self.excluded_blocking_count) < 0:
            raise HistoricalRomOrganizationPlanError(
                "Historical organization plan counts cannot be negative."
            )
        sources = [_path_identity(move.source_path) for move in self.moves]
        targets = [_path_identity(move.target_path) for move in self.moves]
        if len(sources) != len(set(sources)):
            raise HistoricalRomOrganizationPlanError(
                "Historical organization plan contains duplicate ROM sources."
            )
        if len(targets) != len(set(targets)):
            raise HistoricalRomOrganizationPlanError(
                "Historical organization plan contains duplicate ROM targets."
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
        raise HistoricalRomOrganizationPlanError(
            f"Cannot inspect reviewed historical ROM {path!r}: {error}"
        ) from error
    if os.path.islink(path) or not os.path.isfile(path):
        raise HistoricalRomOrganizationPlanError(
            f"Reviewed historical ROM is no longer a regular non-symlink file: {path}"
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
    expected_sha256: str,
) -> tuple[str, int]:
    before = _stat_identity(path)
    if before[0] != expected_size:
        raise HistoricalRomOrganizationPlanError(
            f"Historical ROM size changed after provenance review: {path}"
        )
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise HistoricalRomOrganizationPlanError(
            f"Cannot hash reviewed historical ROM {path!r}: {error}"
        ) from error
    after = _stat_identity(path)
    if before != after:
        raise HistoricalRomOrganizationPlanError(
            f"Historical ROM changed while SHA-256 was being computed: {path}"
        )
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise HistoricalRomOrganizationPlanError(
            f"Historical ROM SHA-256 no longer matches recorded files[] identity: {path}"
        )
    return actual, before[1]


def _find_exact_asset(
    record: Mapping[str, Any],
    row: HistoricalRomProvenanceRow,
):
    try:
        views = collection_rom_asset_views(record)
    except CollectionRomAssetError as error:
        raise HistoricalRomOrganizationPlanError(
            f"Modern ROM metadata changed after historical review: {error}"
        ) from error

    matches = [
        view for view in views
        if _path_identity(view.path) == _path_identity(row.current_path)
    ]
    if len(matches) != 1:
        raise HistoricalRomOrganizationPlanError(
            f"Historical ROM asset ownership changed after review: {row.asset_name}"
        )
    return matches[0]


def build_historical_rom_organization_plan(
    review: HistoricalRomProvenanceReview,
    collection_data: Mapping[str, Any],
    collection_revision_token: str,
) -> HistoricalRomOrganizationPlan:
    """Freeze only historical-review rows already classified ``Ready for plan``."""

    if not isinstance(review, HistoricalRomProvenanceReview):
        raise TypeError("review must be a HistoricalRomProvenanceReview")
    if not isinstance(collection_data, Mapping):
        raise TypeError("Collection data must be a mapping.")

    revision = str(collection_revision_token or "").strip()
    if not revision:
        raise HistoricalRomOrganizationPlanError(
            "Collection revision token is required before previewing a historical plan."
        )
    if revision != review.collection_revision_token:
        raise HistoricalRomOrganizationPlanError(
            "Collection changed after historical provenance review. Run the ROM organization audit again."
        )

    ready_rows = [row for row in review.rows if row.status == STATUS_READY]
    if not ready_rows:
        raise HistoricalRomOrganizationPlanError(
            "Historical provenance review has no ready ROM moves to preview."
        )

    output_root = _canonical(review.output_dir)
    moves: list[HistoricalRomMoveOperation] = []
    for row in ready_rows:
        raw_record = collection_data.get(row.collection_id)
        if not isinstance(raw_record, Mapping):
            raise HistoricalRomOrganizationPlanError(
                f"Collection record {row.collection_id!r} changed after historical review."
            )

        asset = _find_exact_asset(raw_record, row)
        if (
            asset.name != row.asset_name
            or asset.primary != row.primary
            or asset.smwc_submission_id != row.historical_smwc_submission_id
            or asset.sha256 != row.sha256
            or asset.size_bytes != row.size_bytes
        ):
            raise HistoricalRomOrganizationPlanError(
                f"Historical ROM metadata changed after review: {row.asset_name}"
            )
        if _SHA256_RE.fullmatch(asset.sha256 or "") is None or asset.size_bytes is None:
            raise HistoricalRomOrganizationPlanError(
                f"Historical ROM {row.asset_name!r} no longer has exact files[] byte identity."
            )

        source = _absolute(asset.path)
        target = _canonical(row.expected_path)
        if os.path.islink(source):
            raise HistoricalRomOrganizationPlanError(
                f"Historical ROM became a symbolic link after review: {source}"
            )
        if not os.path.isfile(source):
            raise HistoricalRomOrganizationPlanError(
                f"Historical ROM source disappeared after review: {source}"
            )
        if not _is_within_root(target, output_root):
            raise HistoricalRomOrganizationPlanError(
                "A reviewed historical ROM target escapes the configured output directory."
            )
        if _path_identity(source) == _path_identity(target):
            raise HistoricalRomOrganizationPlanError(
                "A reviewed historical ROM is already at its planned target."
            )
        if os.path.exists(target):
            raise HistoricalRomOrganizationPlanError(
                f"Historical ROM target became occupied after review: {target}"
            )

        actual_sha256, mtime_ns = _verified_sha256(
            source,
            expected_size=asset.size_bytes,
            expected_sha256=asset.sha256,
        )
        moves.append(
            HistoricalRomMoveOperation(
                collection_id=row.collection_id,
                collection_title=row.collection_title,
                asset_name=row.asset_name,
                source_path=_canonical(source),
                target_path=target,
                sha256=actual_sha256,
                size_bytes=asset.size_bytes,
                source_mtime_ns=mtime_ns,
                primary=asset.primary,
                historical_smwc_submission_id=row.historical_smwc_submission_id,
                historical_title=row.historical_title,
                historical_hack_type=row.historical_hack_type,
                historical_difficulty=row.historical_difficulty,
            )
        )

    ordered = tuple(
        sorted(
            moves,
            key=lambda move: (
                move.collection_title.casefold(),
                move.collection_id,
                move.historical_smwc_submission_id,
                move.asset_name.casefold(),
                move.source_path.casefold(),
            ),
        )
    )
    return HistoricalRomOrganizationPlan(
        output_dir=output_root,
        collection_revision_token=revision,
        moves=ordered,
        review_row_count=len(review.rows),
        in_place_count=review.in_place_count,
        excluded_blocking_count=review.blocking_count,
    )


__all__ = [
    "HistoricalRomMoveOperation",
    "HistoricalRomOrganizationPlan",
    "HistoricalRomOrganizationPlanError",
    "build_historical_rom_organization_plan",
]
