"""Shared read-only helpers for recorded Collection SMWC identity provenance."""
from __future__ import annotations

from typing import Any, Mapping


def positive_smwc_submission_id(value: Any) -> int | None:
    """Return a positive numeric SMWC submission ID, or ``None`` when invalid."""

    if isinstance(value, bool):
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def recorded_collection_smwc_submission_ids(
    collection_id: str,
    record: Mapping[str, Any],
) -> tuple[int, ...]:
    """Return current + explicitly recorded prior numeric SMWC identities only."""

    current = positive_smwc_submission_id(collection_id)
    if current is None:
        return ()

    candidates = {current}
    prior = record.get("prior_smwc_submission_ids", [])
    if isinstance(prior, list):
        for value in prior:
            parsed = positive_smwc_submission_id(value)
            if parsed is not None:
                candidates.add(parsed)

    history = record.get("identity_migration_history", [])
    if isinstance(history, list):
        for event in history:
            if not isinstance(event, Mapping):
                continue
            for key in ("source_key", "target_key"):
                parsed = positive_smwc_submission_id(event.get(key))
                if parsed is not None:
                    candidates.add(parsed)

    return tuple(sorted(candidates))


__all__ = [
    "positive_smwc_submission_id",
    "recorded_collection_smwc_submission_ids",
]
