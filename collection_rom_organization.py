"""Read-only ROM organization assessment for Collection assets.

The organizer surface is intentionally split into audit/preview and later execution
boundaries.  This module performs only read-only filesystem inspection; it never
creates directories, moves, copies, renames, deletes, hashes, or rewrites ROM/save
files or Collection state.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from collection_rom_assets import CollectionRomAssetError, collection_rom_asset_views
from utils import TYPE_DISPLAY_LOOKUP, get_sorted_folder_name


STATUS_IN_PLACE = "in_place"
STATUS_NEEDS_ORGANIZATION = "needs_organization"
STATUS_MISSING_SOURCE = "missing_source"
STATUS_TARGET_OCCUPIED = "target_occupied"
STATUS_TARGET_COLLISION = "target_collision"
STATUS_REVIEW_PROVENANCE = "review_provenance"
STATUS_LEGACY_PATH = "legacy_path"
STATUS_REVIEW_METADATA = "review_metadata"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


BLOCKING_STATUSES = {
    STATUS_MISSING_SOURCE,
    STATUS_TARGET_OCCUPIED,
    STATUS_TARGET_COLLISION,
    STATUS_REVIEW_PROVENANCE,
    STATUS_LEGACY_PATH,
    STATUS_REVIEW_METADATA,
}


@dataclass(frozen=True)
class CollectionRomLocationAssessment:
    """Read-only comparison between one recorded ROM and the configured layout."""

    current_path: str
    expected_path: str
    exists: bool
    needs_organization: bool


@dataclass(frozen=True)
class CollectionRomOrganizationRow:
    """One immutable audit row for an existing Collection ROM reference."""

    collection_id: str
    title: str
    asset_name: str
    current_path: str
    expected_path: str
    status: str
    detail: str
    primary: bool
    smwc_submission_id: int | None
    sha256: str = ""
    size_bytes: int | None = None

    @property
    def blocking(self) -> bool:
        return self.status in BLOCKING_STATUSES

    @property
    def needs_action(self) -> bool:
        return self.status != STATUS_IN_PLACE


@dataclass(frozen=True)
class CollectionRomOrganizationAudit:
    """Immutable aggregate preview for the explicit Collection organizer."""

    output_dir: str
    rows: tuple[CollectionRomOrganizationRow, ...]

    @property
    def in_place_count(self) -> int:
        return sum(row.status == STATUS_IN_PLACE for row in self.rows)

    @property
    def move_candidate_count(self) -> int:
        return sum(row.status == STATUS_NEEDS_ORGANIZATION for row in self.rows)

    @property
    def blocking_count(self) -> int:
        return sum(row.blocking for row in self.rows)

    @property
    def attention_count(self) -> int:
        return sum(row.needs_action for row in self.rows)

    @property
    def legacy_path_count(self) -> int:
        return sum(row.status == STATUS_LEGACY_PATH for row in self.rows)

    @property
    def historical_provenance_count(self) -> int:
        return sum(
            row.status == STATUS_REVIEW_PROVENANCE
            and row.smwc_submission_id is not None
            and _numeric_collection_id(row.collection_id) is not None
            and row.smwc_submission_id != _numeric_collection_id(row.collection_id)
            for row in self.rows
        )

    @property
    def missing_provenance_count(self) -> int:
        return sum(
            row.status == STATUS_REVIEW_PROVENANCE
            and row.smwc_submission_id is None
            and _numeric_collection_id(row.collection_id) is not None
            for row in self.rows
        )


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


def _path_identity(path: str) -> str:
    return os.path.normcase(os.path.realpath(_absolute(path)))


def _numeric_collection_id(collection_id: str) -> int | None:
    text = str(collection_id or "").strip()
    if not text.isdigit():
        return None
    value = int(text)
    return value if value > 0 else None


def expected_collection_rom_path(
    output_dir: str,
    hack_type: str,
    display_difficulty: str,
    filename: str,
) -> str:
    """Return the configured canonical-style output path without touching disk."""

    if not output_dir or not filename:
        return ""

    normalized_type = (hack_type or "standard").lower().replace("-", "_")
    display_type = TYPE_DISPLAY_LOOKUP.get(
        normalized_type,
        hack_type or "Standard",
    )
    difficulty_folder = get_sorted_folder_name(display_difficulty or "Unknown")
    return _absolute(
        os.path.join(output_dir, display_type, difficulty_folder, filename)
    )


def assess_collection_rom_location(
    record: Mapping[str, Any],
    output_dir: str,
) -> CollectionRomLocationAssessment | None:
    """Assess the recorded primary ROM location without moving or rewriting it."""

    if not isinstance(record, Mapping):
        return None

    current_path = str(record.get("file_path", "") or "").strip()
    if not current_path:
        return None

    current_absolute = _absolute(current_path)
    expected_path = expected_collection_rom_path(
        output_dir,
        str(record.get("hack_type", "standard") or "standard"),
        str(record.get("current_difficulty", "Unknown") or "Unknown"),
        os.path.basename(current_absolute),
    )
    if not expected_path:
        return None

    return CollectionRomLocationAssessment(
        current_path=current_absolute,
        expected_path=expected_path,
        exists=os.path.isfile(current_absolute),
        needs_organization=_path_identity(current_absolute)
        != _path_identity(expected_path),
    )


def _modern_asset_rows(
    collection_id: str,
    record: Mapping[str, Any],
) -> list[dict[str, Any]]:
    views = collection_rom_asset_views(record)
    return [
        {
            "path": _absolute(view.path),
            "name": view.name,
            "primary": view.primary,
            "smwc_submission_id": view.smwc_submission_id,
            "sha256": view.sha256,
            "size_bytes": view.size_bytes,
            "collection_id": collection_id,
        }
        for view in views
    ]


def _legacy_file_path_row(
    collection_id: str,
    record: Mapping[str, Any],
) -> dict[str, Any] | None:
    path = str(record.get("file_path", "") or "").strip()
    if not path:
        return None
    return {
        "path": _absolute(path),
        "name": os.path.basename(path),
        "primary": True,
        "smwc_submission_id": None,
        "sha256": "",
        "size_bytes": None,
        "collection_id": collection_id,
    }


def _eligible_expected_path(
    collection_id: str,
    record: Mapping[str, Any],
    asset: Mapping[str, Any],
    output_dir: str,
) -> tuple[str, str | None]:
    numeric_id = _numeric_collection_id(collection_id)
    provenance = asset.get("smwc_submission_id")

    if numeric_id is not None:
        if not isinstance(provenance, int) or isinstance(provenance, bool):
            return "", (
                "Per-ROM SMWC provenance is missing, so this numeric record cannot be "
                "organized automatically without deciding which submission metadata owns "
                "the retained ROM."
            )
        if provenance != numeric_id:
            return "", (
                f"This ROM is recorded as SMWC {provenance}, while the Collection record "
                f"currently represents SMWC {numeric_id}. Its target layout requires review."
            )

    expected = expected_collection_rom_path(
        output_dir,
        str(record.get("hack_type", "standard") or "standard"),
        str(record.get("current_difficulty", "Unknown") or "Unknown"),
        os.path.basename(str(asset.get("path", "") or "")),
    )
    return expected, None


def _initial_rows(
    collection_data: Mapping[str, Any],
    output_dir: str,
) -> list[CollectionRomOrganizationRow]:
    rows: list[CollectionRomOrganizationRow] = []
    for raw_collection_id, raw_record in collection_data.items():
        collection_id = str(raw_collection_id)
        if not isinstance(raw_record, Mapping):
            continue
        record = raw_record
        title = str(record.get("title", "") or f"Collection {collection_id}")
        try:
            modern = _modern_asset_rows(collection_id, record)
        except CollectionRomAssetError as error:
            legacy_path = str(record.get("file_path", "") or "").strip()
            rows.append(
                CollectionRomOrganizationRow(
                    collection_id=collection_id,
                    title=title,
                    asset_name="Invalid files[] metadata",
                    current_path=_absolute(legacy_path) if legacy_path else "",
                    expected_path="",
                    status=STATUS_REVIEW_METADATA,
                    detail=f"Modern Collection ROM metadata requires review: {error}",
                    primary=False,
                    smwc_submission_id=None,
                    sha256="",
                    size_bytes=None,
                )
            )
            continue
        legacy_only = not modern
        assets = modern
        if legacy_only:
            legacy = _legacy_file_path_row(collection_id, record)
            assets = [legacy] if legacy is not None else []

        for asset in assets:
            current_path = str(asset["path"])
            exists = os.path.isfile(current_path)
            provenance = asset.get("smwc_submission_id")
            provenance_value = (
                provenance
                if isinstance(provenance, int) and not isinstance(provenance, bool)
                else None
            )

            if legacy_only:
                rows.append(
                    CollectionRomOrganizationRow(
                        collection_id=collection_id,
                        title=title,
                        asset_name=str(asset["name"]),
                        current_path=current_path,
                        expected_path="",
                        status=STATUS_LEGACY_PATH,
                        detail=(
                            "Legacy file_path-only ROM references are audit-visible but are "
                            "not move candidates until they have modern files[] identity."
                        ),
                        primary=True,
                        smwc_submission_id=None,
                        sha256="",
                        size_bytes=None,
                    )
                )
                continue

            expected_path, provenance_review = _eligible_expected_path(
                collection_id,
                record,
                asset,
                output_dir,
            )
            if provenance_review is not None:
                rows.append(
                    CollectionRomOrganizationRow(
                        collection_id=collection_id,
                        title=title,
                        asset_name=str(asset["name"]),
                        current_path=current_path,
                        expected_path="",
                        status=STATUS_REVIEW_PROVENANCE,
                        detail=provenance_review,
                        primary=bool(asset["primary"]),
                        smwc_submission_id=provenance_value,
                        sha256=str(asset.get("sha256", "") or ""),
                        size_bytes=asset.get("size_bytes"),
                    )
                )
                continue

            sha256 = str(asset.get("sha256", "") or "")
            size_bytes = asset.get("size_bytes")
            same_path = _path_identity(current_path) == _path_identity(expected_path)
            if not exists:
                status = STATUS_MISSING_SOURCE
                detail = "The recorded ROM file does not currently exist."
            elif same_path:
                status = STATUS_IN_PLACE
                detail = "Already in the configured Collection ROM layout."
            elif os.path.islink(current_path):
                status = STATUS_REVIEW_METADATA
                detail = (
                    "Symbolic-link ROM assets require explicit review before organization."
                )
            elif _SHA256_RE.fullmatch(sha256) is None or size_bytes is None:
                status = STATUS_REVIEW_METADATA
                detail = (
                    "Exact recorded ROM SHA-256 and byte size are required before a filesystem "
                    "move can become an immutable organization plan."
                )
            elif os.path.getsize(current_path) != size_bytes:
                status = STATUS_REVIEW_METADATA
                detail = (
                    "The current ROM byte size no longer matches its recorded files[] identity."
                )
            elif os.path.exists(expected_path):
                status = STATUS_TARGET_OCCUPIED
                detail = (
                    "The expected target path already exists. No overwrite or implicit "
                    "deduplication is permitted."
                )
            else:
                status = STATUS_NEEDS_ORGANIZATION
                detail = "Existing ROM differs from the configured type/difficulty layout."

            rows.append(
                CollectionRomOrganizationRow(
                    collection_id=collection_id,
                    title=title,
                    asset_name=str(asset["name"]),
                    current_path=current_path,
                    expected_path=expected_path,
                    status=status,
                    detail=detail,
                    primary=bool(asset["primary"]),
                    smwc_submission_id=provenance_value,
                    sha256=str(asset.get("sha256", "") or ""),
                    size_bytes=asset.get("size_bytes"),
                )
            )
    return rows


def _mark_target_collisions(
    rows: Iterable[CollectionRomOrganizationRow],
) -> tuple[CollectionRomOrganizationRow, ...]:
    materialized = list(rows)
    targets: dict[str, list[int]] = {}
    for index, row in enumerate(materialized):
        if row.status != STATUS_NEEDS_ORGANIZATION or not row.expected_path:
            continue
        targets.setdefault(_path_identity(row.expected_path), []).append(index)

    collision_indexes = {
        index
        for indexes in targets.values()
        if len(indexes) > 1
        for index in indexes
    }
    if not collision_indexes:
        return tuple(materialized)

    updated: list[CollectionRomOrganizationRow] = []
    for index, row in enumerate(materialized):
        if index not in collision_indexes:
            updated.append(row)
            continue
        updated.append(
            CollectionRomOrganizationRow(
                collection_id=row.collection_id,
                title=row.title,
                asset_name=row.asset_name,
                current_path=row.current_path,
                expected_path=row.expected_path,
                status=STATUS_TARGET_COLLISION,
                detail=(
                    "Multiple recorded ROM assets resolve to this same target path. "
                    "Organization requires explicit conflict review."
                ),
                primary=row.primary,
                smwc_submission_id=row.smwc_submission_id,
                sha256=row.sha256,
                size_bytes=row.size_bytes,
            )
        )
    return tuple(updated)


def build_collection_rom_organization_audit(
    collection_data: Mapping[str, Any],
    output_dir: str,
) -> CollectionRomOrganizationAudit:
    """Build a deterministic read-only organization audit for Collection ROM assets."""

    if not isinstance(collection_data, Mapping):
        raise TypeError("Collection data must be a mapping.")

    output = str(output_dir or "").strip()
    if not output:
        raise ValueError("Configure an output directory before auditing ROM organization.")

    rows = _mark_target_collisions(_initial_rows(collection_data, output))
    ordered = tuple(
        sorted(
            rows,
            key=lambda row: (
                row.status == STATUS_IN_PLACE,
                row.title.casefold(),
                row.collection_id,
                row.asset_name.casefold(),
                row.current_path.casefold(),
            ),
        )
    )
    return CollectionRomOrganizationAudit(
        output_dir=_absolute(output),
        rows=ordered,
    )
