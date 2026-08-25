"""Collection-facing helpers for inspecting and selecting modern ROM assets.

The Collection ``files[]`` array is the authoritative multi-ROM structure. This module
provides detached helpers for presenting those rows and changing only the selected primary
asset. It never moves, renames, deletes, hashes, or otherwise mutates ROM files on disk.
"""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from typing import Any, Mapping


class CollectionRomAssetError(RuntimeError):
    """Raised when Collection ROM asset state cannot be interpreted safely."""


@dataclass(frozen=True)
class CollectionRomAssetView:
    """Read-only presentation facts for one Collection ``files[]`` row."""

    path: str
    name: str
    sha256: str
    size_bytes: int | None
    primary: bool
    smwc_submission_id: int | None
    ingestion_sources: tuple[str, ...]
    exists: bool


def collection_rom_asset_views(record: Mapping[str, Any]) -> tuple[CollectionRomAssetView, ...]:
    """Return validated read-only views for the modern ROM rows in *record*."""

    raw_rows = record.get("files", [])
    if raw_rows is None:
        return ()
    if not isinstance(raw_rows, list):
        raise CollectionRomAssetError("Collection files field must be an array.")

    seen_paths: set[str] = set()
    views: list[CollectionRomAssetView] = []
    for raw in raw_rows:
        if not isinstance(raw, Mapping):
            raise CollectionRomAssetError("Collection ROM file entry must be an object.")

        path = raw.get("path")
        if not isinstance(path, str) or not path.strip():
            raise CollectionRomAssetError("Collection ROM file entry requires a path.")
        if path in seen_paths:
            raise CollectionRomAssetError(f"Collection ROM file path is duplicated: {path}")
        seen_paths.add(path)

        sha256 = raw.get("sha256", "")
        if sha256 is None:
            sha256 = ""
        if not isinstance(sha256, str):
            raise CollectionRomAssetError("Collection ROM SHA-256 must be text when present.")

        size_bytes = raw.get("size_bytes")
        if size_bytes is not None:
            if (
                not isinstance(size_bytes, int)
                or isinstance(size_bytes, bool)
                or size_bytes < 0
            ):
                raise CollectionRomAssetError(
                    "Collection ROM size_bytes must be a non-negative integer when present."
                )

        submission_id = raw.get("smwc_submission_id")
        if submission_id is not None:
            if (
                not isinstance(submission_id, int)
                or isinstance(submission_id, bool)
                or submission_id <= 0
            ):
                raise CollectionRomAssetError(
                    "Collection ROM smwc_submission_id must be a positive integer when present."
                )

        sources = raw.get("ingestion_sources", [])
        if sources is None:
            sources = []
        if not isinstance(sources, list) or any(
            not isinstance(source, str) or not source.strip() for source in sources
        ):
            raise CollectionRomAssetError(
                "Collection ROM ingestion_sources must be an array of non-empty strings."
            )

        name = raw.get("name")
        if not isinstance(name, str) or not name.strip():
            name = os.path.basename(path)

        views.append(
            CollectionRomAssetView(
                path=path,
                name=name,
                sha256=sha256,
                size_bytes=size_bytes,
                primary=bool(raw.get("primary", False)),
                smwc_submission_id=submission_id,
                ingestion_sources=tuple(sources),
                exists=os.path.exists(path),
            )
        )

    return tuple(views)


def current_primary_rom_path(record: Mapping[str, Any]) -> str | None:
    """Return the current primary modern ROM path without modifying the record."""

    views = collection_rom_asset_views(record)
    if not views:
        return None

    explicit = [view.path for view in views if view.primary]
    if len(explicit) > 1:
        raise CollectionRomAssetError("Collection record has multiple primary ROM assets.")
    if explicit:
        return explicit[0]

    compatibility_path = record.get("file_path")
    if isinstance(compatibility_path, str) and compatibility_path:
        if any(view.path == compatibility_path for view in views):
            return compatibility_path

    return None


def build_primary_rom_updates(
    record: Mapping[str, Any],
    selected_path: str,
) -> tuple[list[dict[str, Any]], str]:
    """Return detached ``files[]`` + ``file_path`` values for a primary selection.

    Only an already-recorded modern ROM asset may be selected. Unknown per-row fields are
    preserved. The input mapping and its ``files[]`` rows are never mutated.
    """

    if not isinstance(selected_path, str) or not selected_path:
        raise CollectionRomAssetError("A primary ROM path must be selected.")

    views = collection_rom_asset_views(record)
    if not views:
        raise CollectionRomAssetError("Collection record has no modern ROM assets.")
    if selected_path not in {view.path for view in views}:
        raise CollectionRomAssetError(
            "Primary ROM must reference an existing Collection files[] row."
        )

    raw_rows = record.get("files", [])
    updated_rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        row = copy.deepcopy(dict(raw))
        row["primary"] = row.get("path") == selected_path
        updated_rows.append(row)

    return updated_rows, selected_path


def format_rom_asset_size(size_bytes: int | None) -> str:
    """Return a compact human-readable byte count for Collection UI presentation."""

    if size_bytes is None:
        return "size unknown"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KiB"
    return f"{size_bytes / (1024 * 1024):.2f} MiB"
