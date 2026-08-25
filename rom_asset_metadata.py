"""Helpers for persisting modern Collection ROM asset facts."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Iterable, Mapping


class RomAssetMetadataError(RuntimeError):
    """Raised when a patched ROM cannot be recorded safely."""


def build_tool_patch_rom_asset(
    path: str,
    *,
    smwc_submission_id: int,
    primary: bool,
) -> dict[str, Any]:
    """Return a modern Collection files[] row for one freshly patched ROM."""

    if not isinstance(path, str) or not path.strip():
        raise RomAssetMetadataError("Patched ROM path is required.")
    if (
        not isinstance(smwc_submission_id, int)
        or isinstance(smwc_submission_id, bool)
        or smwc_submission_id <= 0
    ):
        raise RomAssetMetadataError("Patched ROM requires a positive SMWC submission ID.")

    normalized_path = str(Path(path).expanduser().resolve())
    before = _stable_stat(normalized_path)
    digest = hashlib.sha256()
    try:
        with open(normalized_path, "rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as error:
        raise RomAssetMetadataError(
            f"Unable to hash patched ROM: {normalized_path}"
        ) from error
    after = _stable_stat(normalized_path)
    if before != after:
        raise RomAssetMetadataError(
            f"Patched ROM changed while hashing: {normalized_path}"
        )

    return {
        "path": normalized_path,
        "name": os.path.basename(normalized_path),
        "sha256": digest.hexdigest(),
        "size_bytes": before[0],
        "primary": bool(primary),
        "smwc_submission_id": smwc_submission_id,
        "ingestion_sources": ["tool_patch"],
    }


def merge_collection_rom_assets(
    existing_rows: object,
    new_rows: Iterable[Mapping[str, Any]],
    *,
    primary_path: str,
) -> list[dict[str, Any]]:
    """Merge freshly patched assets without discarding existing modern ROM rows."""

    if existing_rows is None:
        existing_rows = []
    if not isinstance(existing_rows, list):
        raise RomAssetMetadataError("Collection files field must be an array.")

    by_path: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for raw in existing_rows:
        if not isinstance(raw, Mapping):
            raise RomAssetMetadataError("Collection ROM file entry must be an object.")
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            raise RomAssetMetadataError("Collection ROM file entry requires path.")
        if path in by_path:
            continue
        by_path[path] = dict(raw)
        order.append(path)

    added = False
    for raw in new_rows:
        if not isinstance(raw, Mapping):
            raise RomAssetMetadataError("New ROM asset must be an object.")
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            raise RomAssetMetadataError("New ROM asset requires path.")
        row = by_path.get(path, {})
        row.update(dict(raw))
        by_path[path] = row
        if path not in order:
            order.append(path)
        added = True

    if not added:
        raise RomAssetMetadataError("At least one newly patched ROM asset is required.")
    if not isinstance(primary_path, str) or primary_path not in by_path:
        raise RomAssetMetadataError("Primary patched ROM must exist in files[].")

    result: list[dict[str, Any]] = []
    for path in order:
        row = by_path[path]
        row["primary"] = path == primary_path
        result.append(row)
    return result


def _stable_stat(path: str) -> tuple[int, int, int | None, int | None]:
    try:
        stat = os.stat(path)
    except OSError as error:
        raise RomAssetMetadataError(f"Patched ROM is unavailable: {path}") from error
    if not os.path.isfile(path):
        raise RomAssetMetadataError(f"Patched ROM is not a regular file: {path}")
    return (
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        getattr(stat, "st_dev", None),
        getattr(stat, "st_ino", None),
    )


__all__ = [
    "RomAssetMetadataError",
    "build_tool_patch_rom_asset",
    "merge_collection_rom_assets",
]
