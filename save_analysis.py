"""Structured, read-only evidence for Save Data Sync parsing.

This module establishes the profile-driven parser boundary used by later Save
Data Sync work. The first profile intentionally preserves the inherited
single-byte behaviour: it records the byte at offset ``0x8C`` without claiming
that the value is universally equivalent to a ROM hack's advertised exits.

Later commits can add checksum-backed standard slots and reusable custom
profiles without changing the matching, collection-update, or UI contracts in
:mod:`save_sync`.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# Inherited raw-counter location. The name deliberately avoids calling the byte
# an exit count: in ordinary SMW saves it is an overworld-event counter.
LEGACY_COUNTER_OFFSET = 0x8C
MIN_LEGACY_SAVE_SIZE = LEGACY_COUNTER_OFFSET + 1
UNINITIALIZED_BYTE = 0xFF

CONFIDENCE_NONE = "none"
CONFIDENCE_LOW = "low"

PROFILE_UNREADABLE = "unreadable"
PROFILE_UNKNOWN = "unknown"
PROFILE_LEGACY_RAW_COUNTER = "legacy_raw_counter"

COUNTER_UNKNOWN = "unknown"
COUNTER_OVERWORLD_EVENTS = "overworld_events"


@dataclass(frozen=True)
class ProfileAttempt:
    """One parser profile decision and the evidence behind it."""

    profile: str
    accepted: bool
    confidence: str
    reason: str
    counter_offset: int | None = None
    counter_kind: str = COUNTER_UNKNOWN
    counter_value: int | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-friendly diagnostic evidence."""

        return {
            "profile": self.profile,
            "accepted": self.accepted,
            "confidence": self.confidence,
            "reason": self.reason,
            "counter_offset": self.counter_offset,
            "counter_kind": self.counter_kind,
            "counter_value": self.counter_value,
        }


@dataclass(frozen=True)
class SaveAnalysis:
    """Read-only parser result for one save file."""

    path: str
    size: int
    profile: str
    confidence: str
    counter_kind: str
    selected_value: int | None
    warnings: tuple[str, ...]
    attempts: tuple[ProfileAttempt, ...]

    @property
    def readable(self) -> bool:
        """Whether the save file itself could be read."""

        return self.profile != PROFILE_UNREADABLE

    @property
    def has_value(self) -> bool:
        """Whether a parser profile exposed a raw counter value."""

        return isinstance(self.selected_value, int)

    def as_dict(self) -> dict[str, Any]:
        """Return stable evidence suitable for diagnostics or persistence."""

        return {
            "path": self.path,
            "size": self.size,
            "profile": self.profile,
            "confidence": self.confidence,
            "counter_kind": self.counter_kind,
            "selected_value": self.selected_value,
            "warnings": list(self.warnings),
            "attempts": [attempt.as_dict() for attempt in self.attempts],
        }


def _absolute(path: os.PathLike[str] | str) -> str:
    return os.path.abspath(os.fspath(path))


def analyze_save(path: os.PathLike[str] | str) -> SaveAnalysis:
    """Read *path* and return structured parser evidence.

    The current accepted profile is deliberately low confidence. It preserves
    the inherited ``0x8C`` read for compatibility while recording that the byte
    is an unvalidated overworld-event counter rather than trusted completion
    progress.
    """

    absolute = _absolute(path)
    try:
        with open(absolute, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        reason = f"Save file could not be read: {exc}"
        attempt = ProfileAttempt(
            profile=PROFILE_LEGACY_RAW_COUNTER,
            accepted=False,
            confidence=CONFIDENCE_NONE,
            reason=reason,
            counter_offset=LEGACY_COUNTER_OFFSET,
            counter_kind=COUNTER_OVERWORLD_EVENTS,
        )
        return SaveAnalysis(
            path=absolute,
            size=0,
            profile=PROFILE_UNREADABLE,
            confidence=CONFIDENCE_NONE,
            counter_kind=COUNTER_UNKNOWN,
            selected_value=None,
            warnings=(reason,),
            attempts=(attempt,),
        )

    size = len(data)
    if size < MIN_LEGACY_SAVE_SIZE:
        reason = (
            f"Save is {size} bytes; at least {MIN_LEGACY_SAVE_SIZE} bytes are "
            "required for the inherited raw counter"
        )
        attempt = ProfileAttempt(
            profile=PROFILE_LEGACY_RAW_COUNTER,
            accepted=False,
            confidence=CONFIDENCE_NONE,
            reason=reason,
            counter_offset=LEGACY_COUNTER_OFFSET,
            counter_kind=COUNTER_OVERWORLD_EVENTS,
        )
        return SaveAnalysis(
            path=absolute,
            size=size,
            profile=PROFILE_UNKNOWN,
            confidence=CONFIDENCE_NONE,
            counter_kind=COUNTER_UNKNOWN,
            selected_value=None,
            warnings=(reason,),
            attempts=(attempt,),
        )

    value = data[LEGACY_COUNTER_OFFSET]
    if value == UNINITIALIZED_BYTE:
        reason = "The inherited raw-counter byte is 0xFF (uninitialized)"
        attempt = ProfileAttempt(
            profile=PROFILE_LEGACY_RAW_COUNTER,
            accepted=False,
            confidence=CONFIDENCE_NONE,
            reason=reason,
            counter_offset=LEGACY_COUNTER_OFFSET,
            counter_kind=COUNTER_OVERWORLD_EVENTS,
            counter_value=value,
        )
        return SaveAnalysis(
            path=absolute,
            size=size,
            profile=PROFILE_UNKNOWN,
            confidence=CONFIDENCE_NONE,
            counter_kind=COUNTER_UNKNOWN,
            selected_value=None,
            warnings=(reason,),
            attempts=(attempt,),
        )

    warning = (
        "Legacy raw counter at 0x8C is not checksum-validated and may not equal "
        "the hack's advertised exits"
    )
    attempt = ProfileAttempt(
        profile=PROFILE_LEGACY_RAW_COUNTER,
        accepted=True,
        confidence=CONFIDENCE_LOW,
        reason="A non-0xFF byte exists at the inherited raw-counter offset",
        counter_offset=LEGACY_COUNTER_OFFSET,
        counter_kind=COUNTER_OVERWORLD_EVENTS,
        counter_value=value,
    )
    return SaveAnalysis(
        path=absolute,
        size=size,
        profile=PROFILE_LEGACY_RAW_COUNTER,
        confidence=CONFIDENCE_LOW,
        counter_kind=COUNTER_OVERWORLD_EVENTS,
        selected_value=value,
        warnings=(warning,),
        attempts=(attempt,),
    )
