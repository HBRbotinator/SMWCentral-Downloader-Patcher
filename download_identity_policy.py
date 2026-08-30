"""Identity-safe helpers for the legacy download pipeline.

SMWCentral submission IDs identify catalogue submissions.  Their numeric order
must never be used to infer version lineage or obsolescence.  The provider's
explicit obsolete state is authoritative for catalogue status; duplicate titles
are only advisory evidence for the UI/log.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def provider_marks_obsolete(hack: Mapping[str, Any]) -> bool:
    """Return the provider-supplied obsolete flag without inferring lineage."""
    raw_fields = hack.get("raw_fields", {})
    if isinstance(raw_fields, Mapping) and "obsolete" in raw_fields:
        return bool(raw_fields.get("obsolete"))
    return bool(hack.get("obsolete", False))


def same_title_collection_ids(
    processed: Mapping[str, Any],
    current_hack_id: str,
    current_title: str,
) -> tuple[str, ...]:
    """Return other Collection keys with the exact same recorded title.

    This is deliberately non-mutating and makes no claim that any matching
    submission supersedes another one.
    """
    current_key = str(current_hack_id)
    matches: list[str] = []
    for hack_id, hack_data in processed.items():
        if not isinstance(hack_data, Mapping):
            continue
        hack_key = str(hack_id)
        if hack_key == current_key:
            continue
        if hack_data.get("title") == current_title:
            matches.append(hack_key)
    return tuple(matches)
