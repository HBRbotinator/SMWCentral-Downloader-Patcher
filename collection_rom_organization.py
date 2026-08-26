"""Read-only ROM location assessment for explicit Collection organization.

This module deliberately does not create directories or mutate ROM/save files.  It
provides the layout evidence needed by download metadata refreshes today and by a
future explicit organization/reconciliation workflow.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from utils import TYPE_DISPLAY_LOOKUP, get_sorted_folder_name


@dataclass(frozen=True)
class CollectionRomLocationAssessment:
    """Read-only comparison between one recorded ROM and the configured layout."""

    current_path: str
    expected_path: str
    exists: bool
    needs_organization: bool


def _absolute(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path))


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
    record: dict[str, Any],
    output_dir: str,
) -> CollectionRomLocationAssessment | None:
    """Assess the recorded primary ROM location without moving or rewriting it."""

    if not isinstance(record, dict):
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

    current_identity = os.path.normcase(os.path.realpath(current_absolute))
    expected_identity = os.path.normcase(os.path.realpath(expected_path))
    return CollectionRomLocationAssessment(
        current_path=current_absolute,
        expected_path=expected_path,
        exists=os.path.isfile(current_absolute),
        needs_organization=current_identity != expected_identity,
    )
