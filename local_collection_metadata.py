"""Validation helpers for user-owned local Collection metadata."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


LOCAL_DIFFICULTY_CHOICES = (
    "Unknown",
    "No Difficulty",
    "Newcomer",
    "Casual",
    "Intermediate",
    "Advanced",
    "Expert",
    "Master",
    "Grandmaster",
)

LOCAL_HACK_TYPE_CHOICES = (
    "Unknown",
    "Kaizo",
    "Pit",
    "Puzzle",
    "Standard",
    "Tool-Assisted",
)

_TYPE_ALIASES = {
    "kaizo": "kaizo",
    "pit": "pit",
    "puzzle": "puzzle",
    "standard": "standard",
    "tool-assisted": "tool_assisted",
    "tool assisted": "tool_assisted",
    "tool_assisted": "tool_assisted",
    "unknown": "",
}


@dataclass(frozen=True)
class LocalCollectionMetadata:
    """Explicit user-owned metadata for one local/manual Collection record."""

    title: str
    difficulty: str = "Unknown"
    hack_types: tuple[str, ...] = ()
    exits: int = 0


def _clean_title(value) -> str:
    title = " ".join(str(value or "").strip().split())
    if not title:
        raise ValueError("A local hack title is required.")
    return title


def _clean_difficulty(value) -> str:
    difficulty = " ".join(str(value or "").strip().split()) or "Unknown"
    if difficulty.casefold() == "skilled":
        difficulty = "Intermediate"
    known = {item.casefold(): item for item in LOCAL_DIFFICULTY_CHOICES}
    return known.get(difficulty.casefold(), difficulty)


def _iter_type_values(value) -> Iterable[str]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(","))
    try:
        return tuple(str(part).strip() for part in value)
    except TypeError:
        return (str(value).strip(),)


def _clean_hack_types(value) -> tuple[str, ...]:
    result = []
    for raw in _iter_type_values(value):
        if not raw:
            continue
        normalized = _TYPE_ALIASES.get(raw.casefold())
        if normalized is None:
            normalized = raw.casefold().replace("-", "_").replace(" ", "_")
        if not normalized:
            continue
        if normalized not in result:
            result.append(normalized)
    return tuple(result)


def _clean_exits(value) -> int:
    try:
        exits = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Total exits must be a whole number.") from exc
    if exits < 0 or exits > 999:
        raise ValueError("Total exits must be between 0 and 999.")
    return exits


def validate_local_collection_metadata(
    title,
    difficulty="Unknown",
    hack_types=(),
    total_exits=0,
) -> LocalCollectionMetadata:
    """Normalize local metadata without deriving Collection identity from it."""

    return LocalCollectionMetadata(
        title=_clean_title(title),
        difficulty=_clean_difficulty(difficulty),
        hack_types=_clean_hack_types(hack_types),
        exits=_clean_exits(total_exits),
    )


def format_local_hack_types(hack_types) -> str:
    """Return editable display text for normalized local hack types."""

    display = {
        "standard": "Standard",
        "kaizo": "Kaizo",
        "puzzle": "Puzzle",
        "tool_assisted": "Tool-Assisted",
        "pit": "Pit",
    }
    values = [display.get(str(item), str(item).replace("_", " ").title()) for item in hack_types or ()]
    return ", ".join(values) if values else "Unknown"


__all__ = [
    "LOCAL_DIFFICULTY_CHOICES",
    "LOCAL_HACK_TYPE_CHOICES",
    "LocalCollectionMetadata",
    "format_local_hack_types",
    "validate_local_collection_metadata",
]
