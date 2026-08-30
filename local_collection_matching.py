"""Conservative matching against existing opaque local Collection records."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from collection_reconciliation import is_local_collection_key
from rom_title_matching import CatalogueEntry, CatalogueMatcher


@dataclass(frozen=True)
class LocalCollectionEntry:
    """Immutable review snapshot of one existing usr_* Collection record."""

    target_key: str
    title: str
    difficulty: str = ""
    hack_types: tuple[str, ...] = ()
    exits: int | None = None


@dataclass(frozen=True)
class LocalCollectionMatch:
    """One non-authoritative local record suggestion requiring user confirmation."""

    target_key: str
    title: str
    difficulty: str
    hack_types: tuple[str, ...]
    exits: int | None
    confidence: float


def snapshot_local_collection_entries(
    records: Mapping[str, object] | None,
) -> tuple[LocalCollectionEntry, ...]:
    """Freeze valid usr_* records without deriving identity from their metadata."""

    result = []
    for raw_key, raw_record in dict(records or {}).items():
        key = str(raw_key)
        if not is_local_collection_key(key) or not isinstance(raw_record, Mapping):
            continue
        title = str(raw_record.get("title") or "").strip()
        if not title:
            continue
        raw_types = raw_record.get("hack_types")
        if isinstance(raw_types, (list, tuple)):
            hack_types = tuple(
                str(value).strip()
                for value in raw_types
                if str(value).strip()
            )
        else:
            single = str(raw_record.get("hack_type") or "").strip()
            hack_types = (single,) if single else ()
        exits = raw_record.get("exits")
        if isinstance(exits, bool):
            exits = None
        elif exits is not None:
            try:
                exits = int(exits)
            except (TypeError, ValueError):
                exits = None
            if exits is not None and exits < 0:
                exits = None
        result.append(
            LocalCollectionEntry(
                target_key=key,
                title=title,
                difficulty=str(raw_record.get("current_difficulty") or "").strip(),
                hack_types=hack_types,
                exits=exits,
            )
        )
    return tuple(sorted(result, key=lambda item: (item.title.casefold(), item.target_key)))


def find_local_collection_matches(
    title_hints: str | Sequence[str],
    entries: Sequence[LocalCollectionEntry],
    *,
    limit: int = 5,
    minimum_confidence: float = 0.68,
) -> tuple[LocalCollectionMatch, ...]:
    """Rank plausible local records while never treating similarity as identity."""

    if isinstance(title_hints, str):
        queries = (title_hints,)
    else:
        queries = tuple(str(value) for value in title_hints)
    queries = tuple(value.strip() for value in queries if value.strip())
    frozen = tuple(entries)
    if not queries or not frozen:
        return ()
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
        raise ValueError("Local Collection match limit must be a positive integer.")

    surrogate_to_entry: dict[int, LocalCollectionEntry] = {}
    catalogue = []
    for index, entry in enumerate(frozen, start=1):
        surrogate_to_entry[index] = entry
        catalogue.append(
            CatalogueEntry(
                smwc_submission_id=index,
                title=entry.title,
                difficulty=entry.difficulty,
                hack_type=", ".join(entry.hack_types),
                exits=entry.exits,
            )
        )
    matcher = CatalogueMatcher(catalogue)

    best: dict[str, float] = {}
    for query in queries:
        for ranked in matcher.rank(query, limit=min(len(catalogue), max(limit * 3, 12))):
            if ranked.score < minimum_confidence:
                continue
            entry = surrogate_to_entry[ranked.entry.smwc_submission_id]
            best[entry.target_key] = max(best.get(entry.target_key, 0.0), ranked.score)

    ordered = sorted(
        (
            LocalCollectionMatch(
                target_key=entry.target_key,
                title=entry.title,
                difficulty=entry.difficulty,
                hack_types=entry.hack_types,
                exits=entry.exits,
                confidence=best[entry.target_key],
            )
            for entry in frozen
            if entry.target_key in best
        ),
        key=lambda item: (-item.confidence, item.title.casefold(), item.target_key),
    )
    return tuple(ordered[:limit])


__all__ = [
    "LocalCollectionEntry",
    "LocalCollectionMatch",
    "find_local_collection_matches",
    "snapshot_local_collection_entries",
]
