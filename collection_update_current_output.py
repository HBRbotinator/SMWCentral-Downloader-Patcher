"""Download-location handling for same-ID current-entry ROM downloads."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


ROM_DOWNLOAD_DESTINATION_DEFAULT = "default_output"
ROM_DOWNLOAD_DESTINATION_ALONGSIDE_PRIMARY = "alongside_primary"


class CollectionCurrentOutputError(RuntimeError):
    """Raised when a reviewed ROM download location cannot be used safely."""


def ensure_default_rom_output_directory(configured_output_dir: str | Path) -> Path:
    """Return a usable default ROM output root, creating it when necessary.

    The configured output root is only the default destination for newly created ROMs.
    Existing Collection ROMs may live anywhere and are never required to be beneath it.
    """

    raw = str(configured_output_dir or "").strip()
    if not raw:
        raise CollectionCurrentOutputError(
            "Set a Default ROM Output Folder in Settings before using that download location."
        )

    root = Path(raw).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise CollectionCurrentOutputError(
            f"The configured Default ROM Output Folder could not be created or opened: {root}"
        ) from error

    try:
        resolved = root.resolve()
    except OSError as error:
        raise CollectionCurrentOutputError(
            f"The configured Default ROM Output Folder could not be resolved: {root}"
        ) from error

    if not resolved.is_dir():
        raise CollectionCurrentOutputError(
            f"The configured Default ROM Output Folder is not a directory: {resolved}"
        )
    return resolved


def current_primary_rom_path(record: Mapping | None) -> Path | None:
    """Return one usable current-primary ROM path without inferring a primary.

    Modern ``files[]`` primary state wins. ``file_path`` is accepted as the
    compatibility projection only when it agrees with modern rows, or when the
    record has no modern ROM rows yet. Ambiguous/disagreeing state fails closed.
    """

    if not isinstance(record, Mapping):
        return None

    rows = record.get("files", [])
    valid_rows: list[str] = []
    primary_rows: list[str] = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            raw_path = str(row.get("path") or "").strip()
            if not raw_path:
                continue
            valid_rows.append(raw_path)
            if row.get("primary") is True:
                primary_rows.append(raw_path)

    if len(primary_rows) > 1:
        return None

    projected = str(record.get("file_path") or "").strip()
    candidate = ""
    if len(primary_rows) == 1:
        candidate = primary_rows[0]
        if projected and not _same_path(projected, candidate):
            return None
    elif projected:
        if valid_rows:
            matches = [row_path for row_path in valid_rows if _same_path(row_path, projected)]
            if len(matches) != 1:
                return None
            candidate = matches[0]
        else:
            candidate = projected

    if not candidate:
        return None

    path = Path(candidate).expanduser()
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return path.resolve()
    except OSError:
        return None


def current_primary_rom_directory(record: Mapping | None) -> Path | None:
    """Return the directory containing the explicit usable current primary ROM."""

    primary = current_primary_rom_path(record)
    if primary is None:
        return None
    parent = primary.parent
    try:
        resolved = parent.resolve()
    except OSError:
        return None
    return resolved if resolved.is_dir() else None


def resolve_current_rom_download_directory(
    configured_output_dir: str | Path,
    current_record: Mapping | None,
    destination: str,
) -> Path:
    """Resolve the explicit pre-download destination without moving existing ROMs."""

    choice = str(destination or "").strip()
    if choice == ROM_DOWNLOAD_DESTINATION_DEFAULT:
        return ensure_default_rom_output_directory(configured_output_dir)
    if choice == ROM_DOWNLOAD_DESTINATION_ALONGSIDE_PRIMARY:
        directory = current_primary_rom_directory(current_record)
        if directory is None:
            raise CollectionCurrentOutputError(
                "The current primary ROM no longer has a usable folder. Choose the Default ROM "
                "Output Folder or reopen the update after repairing the primary ROM path."
            )
        return directory
    raise CollectionCurrentOutputError("Choose where the downloaded ROM should be saved.")


def _same_path(left: str | Path, right: str | Path) -> bool:
    try:
        left_value = os.path.normcase(str(Path(left).expanduser().resolve()))
        right_value = os.path.normcase(str(Path(right).expanduser().resolve()))
    except OSError:
        left_value = os.path.normcase(os.path.abspath(os.path.expanduser(str(left))))
        right_value = os.path.normcase(os.path.abspath(os.path.expanduser(str(right))))
    return left_value == right_value


__all__ = [
    "CollectionCurrentOutputError",
    "ROM_DOWNLOAD_DESTINATION_ALONGSIDE_PRIMARY",
    "ROM_DOWNLOAD_DESTINATION_DEFAULT",
    "current_primary_rom_directory",
    "current_primary_rom_path",
    "ensure_default_rom_output_directory",
    "resolve_current_rom_download_directory",
]
