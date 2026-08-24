"""Read-only discovery of possible related SMWC submissions for Collection entries.

This module intentionally does not infer version lineage. It ranks catalogue rows that may
be worth reviewing and freezes an explicit user selection for a later acquisition/migration
boundary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from kaizoff_provider import KaizOffIndexSnapshot
from rom_title_matching import CatalogueEntry, CatalogueMatcher, RankedCatalogueMatch


class CollectionUpdateDiscoveryError(ValueError):
    """Raised when a read-only update/replacement discovery request is invalid."""


@dataclass(frozen=True)
class RelatedSubmissionCandidate:
    """One catalogue row surfaced as potentially related, never as proven lineage."""

    entry: CatalogueEntry
    title_score: float
    reasons: tuple[str, ...]
    cautions: tuple[str, ...]
    already_in_collection: bool


@dataclass(frozen=True)
class CollectionUpdateDiscovery:
    """Frozen Index-backed discovery state for one existing numeric Collection entry."""

    source_collection_key: str
    source_entry: CatalogueEntry
    catalogue_entries: tuple[CatalogueEntry, ...]
    suggestions: tuple[RelatedSubmissionCandidate, ...]
    existing_numeric_collection_ids: frozenset[int]
    catalogue_fetched_at: float
    catalogue_source: str
    catalogue_stale: bool


@dataclass(frozen=True)
class CollectionUpdateSelection:
    """Detached explicit choice of a possible replacement target.

    The selection is not a migration plan and does not assert that the target is newer.
    """

    source_collection_key: str
    source_entry: CatalogueEntry
    target_entry: CatalogueEntry
    target_already_in_collection: bool
    catalogue_fetched_at: float
    catalogue_source: str
    catalogue_stale: bool


_NUMERIC_SEARCH = re.compile(r"(?i)^\s*(?:smwc(?:\s*-?\s*id)?\s*[-:#]?\s*)?(\d+)\s*$")


def build_collection_update_discovery(
    source_collection_key: str | int,
    source_record: Mapping[str, Any],
    index_snapshot: KaizOffIndexSnapshot,
    *,
    existing_collection_keys: Iterable[str | int] = (),
    suggestion_limit: int = 20,
) -> CollectionUpdateDiscovery:
    """Build a frozen, read-only related-submission discovery snapshot."""

    source_id = _numeric_collection_id(source_collection_key)
    if not isinstance(source_record, Mapping):
        raise CollectionUpdateDiscoveryError("Selected Collection record is invalid.")
    if not isinstance(index_snapshot, KaizOffIndexSnapshot):
        raise CollectionUpdateDiscoveryError("KaizOFF Index snapshot is invalid.")

    source_entry = _collection_record_catalogue_entry(source_id, source_record)
    catalogue_entries = tuple(index_snapshot.entries)
    if not catalogue_entries:
        raise CollectionUpdateDiscoveryError("KaizOFF Index contains no catalogue entries.")

    existing_numeric_ids = frozenset(
        identifier
        for raw_key in existing_collection_keys
        for identifier in [_try_numeric_collection_id(raw_key)]
        if identifier is not None
    )
    suggestions = _rank_related_submissions(
        source_entry,
        catalogue_entries,
        existing_numeric_ids,
        limit=suggestion_limit,
    )
    return CollectionUpdateDiscovery(
        source_collection_key=str(source_id),
        source_entry=source_entry,
        catalogue_entries=catalogue_entries,
        suggestions=suggestions,
        existing_numeric_collection_ids=existing_numeric_ids,
        catalogue_fetched_at=float(index_snapshot.fetched_at),
        catalogue_source=str(index_snapshot.source or "unknown"),
        catalogue_stale=bool(index_snapshot.stale),
    )


def search_collection_update_catalogue(
    discovery: CollectionUpdateDiscovery,
    query: str,
    *,
    limit: int = 50,
) -> tuple[CatalogueEntry, ...]:
    """Search the frozen discovery Index by exact ID or local title matching."""

    if not isinstance(discovery, CollectionUpdateDiscovery):
        raise CollectionUpdateDiscoveryError("Update discovery state is invalid.")
    text = str(query or "").strip()
    if not text:
        return tuple(item.entry for item in discovery.suggestions[: max(1, int(limit))])

    numeric_match = _NUMERIC_SEARCH.match(text)
    if numeric_match:
        identifier = int(numeric_match.group(1))
        if identifier == int(discovery.source_collection_key):
            return ()
        return tuple(
            entry
            for entry in discovery.catalogue_entries
            if entry.smwc_submission_id == identifier
        )[:1]

    source_id = int(discovery.source_collection_key)
    pool = tuple(
        entry
        for entry in discovery.catalogue_entries
        if entry.smwc_submission_id != source_id
    )
    query_folded = text.casefold()
    substring_matches = sorted(
        (entry for entry in pool if query_folded in entry.title.casefold()),
        key=lambda entry: (entry.title.casefold().find(query_folded), entry.title.casefold()),
    )

    matcher = CatalogueMatcher(pool)
    ranked = matcher.rank(text, limit=max(20, int(limit) * 2))
    ordered: list[CatalogueEntry] = []
    seen: set[int] = set()
    for entry in [*substring_matches, *(item.entry for item in ranked)]:
        if entry.smwc_submission_id in seen:
            continue
        seen.add(entry.smwc_submission_id)
        ordered.append(entry)
        if len(ordered) >= max(1, int(limit)):
            break
    return tuple(ordered)


def select_possible_collection_replacement(
    discovery: CollectionUpdateDiscovery,
    target_submission_id: int | str,
) -> CollectionUpdateSelection:
    """Freeze an explicit related-submission choice without writing or planning migration."""

    if not isinstance(discovery, CollectionUpdateDiscovery):
        raise CollectionUpdateDiscoveryError("Update discovery state is invalid.")
    target_id = _numeric_collection_id(target_submission_id)
    source_id = int(discovery.source_collection_key)
    if target_id == source_id:
        raise CollectionUpdateDiscoveryError(
            "The current SMWC submission cannot replace itself."
        )
    target = next(
        (
            entry
            for entry in discovery.catalogue_entries
            if entry.smwc_submission_id == target_id
        ),
        None,
    )
    if target is None:
        raise CollectionUpdateDiscoveryError(
            "Selected SMWC submission is not present in the frozen KaizOFF Index."
        )
    return CollectionUpdateSelection(
        source_collection_key=discovery.source_collection_key,
        source_entry=discovery.source_entry,
        target_entry=target,
        target_already_in_collection=target_id in discovery.existing_numeric_collection_ids,
        catalogue_fetched_at=discovery.catalogue_fetched_at,
        catalogue_source=discovery.catalogue_source,
        catalogue_stale=discovery.catalogue_stale,
    )


def _rank_related_submissions(
    source_entry: CatalogueEntry,
    catalogue_entries: Sequence[CatalogueEntry],
    existing_numeric_ids: frozenset[int],
    *,
    limit: int,
) -> tuple[RelatedSubmissionCandidate, ...]:
    pool = tuple(
        entry
        for entry in catalogue_entries
        if entry.smwc_submission_id != source_entry.smwc_submission_id
    )
    if not pool:
        return ()

    matcher = CatalogueMatcher(pool)
    ranked = matcher.rank(
        source_entry.title,
        difficulty_hint=source_entry.difficulty,
        limit=max(40, int(limit) * 4),
    )
    candidates: list[RelatedSubmissionCandidate] = []
    for match in ranked:
        # Suggested rows need an actual title anchor. Generic metadata such as the
        # same difficulty/type is supporting evidence only and must never manufacture
        # a relationship between otherwise unrelated submissions. Manual search still
        # exposes the complete frozen Index when the user knows what to look for.
        title_anchor = bool(
            match.exact
            or match.core_exact
            or match.articleless_exact
            or match.abbreviation_match
            or match.matched_distinctive_tokens
        )
        if not title_anchor or match.score < 0.62:
            continue
        reasons = _candidate_reasons(source_entry, match)
        cautions = _candidate_cautions(match)
        candidates.append(
            RelatedSubmissionCandidate(
                entry=match.entry,
                title_score=round(match.score, 4),
                reasons=reasons,
                cautions=cautions,
                already_in_collection=(
                    match.entry.smwc_submission_id in existing_numeric_ids
                ),
            )
        )
        if len(candidates) >= max(1, int(limit)):
            break
    return tuple(candidates)


def _candidate_reasons(
    source: CatalogueEntry,
    match: RankedCatalogueMatch,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if match.exact:
        reasons.append("Same normalized title")
    elif match.core_exact or match.articleless_exact:
        reasons.append("Same core title")
    elif match.matched_distinctive_tokens:
        reasons.append(
            "Shared distinctive title terms: "
            + ", ".join(match.matched_distinctive_tokens[:4])
        )
    else:
        reasons.append(f"Similar title ({match.score:.0%})")

    if _equal_text(source.difficulty, match.entry.difficulty):
        reasons.append("Same difficulty")
    if _type_tokens(source.hack_type) and _type_tokens(source.hack_type) == _type_tokens(
        match.entry.hack_type
    ):
        reasons.append("Same type")
    if source.exits is not None and source.exits == match.entry.exits:
        reasons.append("Same exit count")
    return tuple(reasons)


def _candidate_cautions(match: RankedCatalogueMatch) -> tuple[str, ...]:
    cautions: list[str] = []
    if match.number_conflict:
        cautions.append("Title numbers differ")
    if match.qualifier_conflict:
        cautions.append("Demo/Beta/Alpha qualifiers differ")
    if match.short_guard:
        cautions.append("Short/generic title needs extra care")
    if match.abbreviation_match:
        cautions.append("Acronym-style title match")
    if match.phrase_match:
        cautions.append("Partial-title relationship only")
    return tuple(cautions)


def _collection_record_catalogue_entry(
    source_id: int,
    record: Mapping[str, Any],
) -> CatalogueEntry:
    title = str(record.get("title") or "").strip()
    if not title:
        raise CollectionUpdateDiscoveryError(
            "Selected Collection record has no title to search from."
        )
    raw_types = record.get("hack_types")
    if isinstance(raw_types, (list, tuple)):
        hack_type = ", ".join(
            str(item).strip() for item in raw_types if str(item).strip()
        )
    else:
        hack_type = str(record.get("hack_type") or "").strip()

    exits = record.get("exits")
    if isinstance(exits, bool):
        exits = None
    elif exits is not None:
        try:
            exits = int(exits)
        except (TypeError, ValueError):
            exits = None

    raw_authors = record.get("authors") or ()
    authors: tuple[str, ...]
    if isinstance(raw_authors, str):
        authors = tuple(
            item.strip() for item in raw_authors.split(",") if item.strip()
        )
    elif isinstance(raw_authors, (list, tuple)):
        authors = tuple(str(item).strip() for item in raw_authors if str(item).strip())
    else:
        authors = ()

    return CatalogueEntry(
        smwc_submission_id=source_id,
        title=title,
        difficulty=str(record.get("current_difficulty") or record.get("difficulty") or "").strip(),
        hack_type=hack_type,
        exits=exits,
        authors=authors,
    )


def _numeric_collection_id(value: str | int) -> int:
    identifier = _try_numeric_collection_id(value)
    if identifier is None:
        raise CollectionUpdateDiscoveryError(
            "Update/replacement discovery is available only for known numeric SMWC Collection entries."
        )
    return identifier


def _try_numeric_collection_id(value: str | int) -> int | None:
    if isinstance(value, bool):
        return None
    text = str(value or "").strip()
    if not text.isdigit():
        return None
    identifier = int(text)
    return identifier if identifier > 0 else None


def _equal_text(left: str, right: str) -> bool:
    return bool(left and right and left.strip().casefold() == right.strip().casefold())


def _type_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token.strip().casefold()
        for token in re.split(r"[,;/]", str(value or ""))
        if token.strip()
    )


__all__ = [
    "CollectionUpdateDiscovery",
    "CollectionUpdateDiscoveryError",
    "CollectionUpdateSelection",
    "RelatedSubmissionCandidate",
    "build_collection_update_discovery",
    "search_collection_update_catalogue",
    "select_possible_collection_replacement",
]
