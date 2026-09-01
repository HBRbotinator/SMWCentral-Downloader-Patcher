"""Default output-root handling for same-ID current-entry ROM downloads."""
from __future__ import annotations

from pathlib import Path


class CollectionCurrentOutputError(RuntimeError):
    """Raised when the configured default ROM output root cannot be used safely."""


def ensure_default_rom_output_directory(configured_output_dir: str | Path) -> Path:
    """Return a usable default ROM output root, creating it when necessary.

    The configured output root is only the default destination for newly created ROMs.
    Existing Collection ROMs may live anywhere and are never required to be beneath it.
    """

    raw = str(configured_output_dir or "").strip()
    if not raw:
        raise CollectionCurrentOutputError(
            "Set a Default ROM Output Folder in Settings before downloading a ROM."
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


__all__ = [
    "CollectionCurrentOutputError",
    "ensure_default_rom_output_directory",
]
