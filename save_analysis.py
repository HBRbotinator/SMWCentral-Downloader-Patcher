"""Structured, read-only evidence for Save Data Sync parsing.

The parser first looks for checksum-valid standard Super Mario World save
slots. A standard SRAM region contains three 143-byte slots and a backup copy
of each slot. The final two bytes of every copy store a checksum complement for
the preceding 141 bytes.

When no usable standard slot can be proven, smaller saves fall back to the
inherited single-byte read at offset ``0x8C``. Expanded SRAM images instead fail
closed because that byte commonly belongs to an unrelated SA-1/BW-RAM layout.
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

# Standard SMW SRAM uses three 143-byte slots followed by three backup copies.
STANDARD_SLOT_DATA_SIZE = 0x8D
STANDARD_SLOT_SIZE = 0x8F
STANDARD_EVENT_COUNTER_OFFSET = 0x8C
STANDARD_CHECKSUM_OFFSET = 0x8D
STANDARD_CHECKSUM_SEED = 0x5A5A
STANDARD_SRAM_SIZE = 0x35A

# SA-1/BW-RAM and other expanded SRAM images are commonly 64 KiB or larger.
# A raw byte at the vanilla 0x8C offset is not meaningful unless a supported
# layout validates it, so the legacy fallback is suppressed at this boundary.
EXPANDED_SRAM_MIN_SIZE = 0x10000

STANDARD_SLOT_OFFSETS = (
    ("A", 0x000, 0x1AD),
    ("B", 0x08F, 0x23C),
    ("C", 0x11E, 0x2CB),
)

CONFIDENCE_NONE = "none"
CONFIDENCE_LOW = "low"
CONFIDENCE_MEDIUM = "medium"

PROFILE_UNREADABLE = "unreadable"
PROFILE_UNKNOWN = "unknown"
PROFILE_STANDARD_SMW_SLOTS = "standard_smw_slots"
PROFILE_EXPANDED_SRAM_UNKNOWN = "expanded_sram_unknown"
PROFILE_LEGACY_RAW_COUNTER = "legacy_raw_counter"

COUNTER_UNKNOWN = "unknown"
COUNTER_OVERWORLD_EVENTS = "overworld_events"

COPY_PRIMARY = "primary"
COPY_BACKUP = "backup"


@dataclass(frozen=True)
class ProfileAttempt:
    """One parser-profile decision and the evidence behind it."""

    profile: str
    accepted: bool
    confidence: str
    reason: str
    counter_offset: int | None = None
    counter_kind: str = COUNTER_UNKNOWN
    counter_value: int | None = None
    slot: str | None = None
    copy_kind: str | None = None
    checksum_valid: bool | None = None
    stored_checksum: int | None = None
    expected_checksum: int | None = None

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
            "slot": self.slot,
            "copy_kind": self.copy_kind,
            "checksum_valid": self.checksum_valid,
            "stored_checksum": self.stored_checksum,
            "expected_checksum": self.expected_checksum,
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
    selected_slot: str | None = None
    selected_copy: str | None = None
    valid_slots: tuple[str, ...] = ()

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
            "selected_slot": self.selected_slot,
            "selected_copy": self.selected_copy,
            "valid_slots": list(self.valid_slots),
            "warnings": list(self.warnings),
            "attempts": [attempt.as_dict() for attempt in self.attempts],
        }


def _absolute(path: os.PathLike[str] | str) -> str:
    return os.path.abspath(os.fspath(path))


def calculate_standard_checksum(slot_data: bytes) -> int:
    """Return the standard SMW checksum complement for 141 data bytes."""

    if len(slot_data) != STANDARD_SLOT_DATA_SIZE:
        raise ValueError(
            f"Expected {STANDARD_SLOT_DATA_SIZE} slot-data bytes, "
            f"received {len(slot_data)}"
        )
    return (STANDARD_CHECKSUM_SEED - sum(slot_data)) & 0xFFFF


def _standard_copy_attempt(
    data: bytes,
    *,
    slot: str,
    copy_kind: str,
    offset: int,
) -> ProfileAttempt:
    slot_bytes = data[offset : offset + STANDARD_SLOT_SIZE]
    slot_data = slot_bytes[:STANDARD_SLOT_DATA_SIZE]
    stored_checksum = int.from_bytes(
        slot_bytes[STANDARD_CHECKSUM_OFFSET:STANDARD_SLOT_SIZE],
        "little",
    )
    expected_checksum = calculate_standard_checksum(slot_data)
    checksum_valid = stored_checksum == expected_checksum
    counter_value = slot_data[STANDARD_EVENT_COUNTER_OFFSET]
    counter_offset = offset + STANDARD_EVENT_COUNTER_OFFSET

    if not checksum_valid:
        reason = (
            f"Slot {slot} {copy_kind} checksum mismatch: stored "
            f"0x{stored_checksum:04X}, expected 0x{expected_checksum:04X}"
        )
        accepted = False
        confidence = CONFIDENCE_NONE
    elif counter_value == UNINITIALIZED_BYTE:
        reason = f"Slot {slot} {copy_kind} is checksum-valid but uninitialized"
        accepted = False
        confidence = CONFIDENCE_NONE
    else:
        reason = f"Slot {slot} {copy_kind} has a valid standard SMW checksum"
        accepted = True
        confidence = CONFIDENCE_MEDIUM

    return ProfileAttempt(
        profile=PROFILE_STANDARD_SMW_SLOTS,
        accepted=accepted,
        confidence=confidence,
        reason=reason,
        counter_offset=counter_offset,
        counter_kind=COUNTER_OVERWORLD_EVENTS,
        counter_value=counter_value,
        slot=slot,
        copy_kind=copy_kind,
        checksum_valid=checksum_valid,
        stored_checksum=stored_checksum,
        expected_checksum=expected_checksum,
    )


def _analyze_standard_slots(
    absolute: str,
    data: bytes,
) -> tuple[SaveAnalysis | None, tuple[ProfileAttempt, ...]]:
    if len(data) < STANDARD_SRAM_SIZE:
        return None, ()

    attempts: list[ProfileAttempt] = []
    for slot, primary_offset, backup_offset in STANDARD_SLOT_OFFSETS:
        attempts.append(
            _standard_copy_attempt(
                data,
                slot=slot,
                copy_kind=COPY_PRIMARY,
                offset=primary_offset,
            )
        )
        attempts.append(
            _standard_copy_attempt(
                data,
                slot=slot,
                copy_kind=COPY_BACKUP,
                offset=backup_offset,
            )
        )

    accepted = [attempt for attempt in attempts if attempt.accepted]
    if not accepted:
        return None, tuple(attempts)

    slot_order = {slot: index for index, (slot, _, _) in enumerate(STANDARD_SLOT_OFFSETS)}
    selected = max(
        accepted,
        key=lambda attempt: (
            attempt.counter_value if attempt.counter_value is not None else -1,
            attempt.copy_kind == COPY_PRIMARY,
            -slot_order.get(attempt.slot or "", len(slot_order)),
        ),
    )

    warnings = [
        "Checksum-valid standard SMW slot data was found, but the selected "
        "overworld-event counter may not equal the hack's advertised exits"
    ]
    for slot, _, _ in STANDARD_SLOT_OFFSETS:
        copies = [attempt for attempt in attempts if attempt.slot == slot]
        usable = [attempt for attempt in copies if attempt.accepted]
        if len(usable) == 2 and usable[0].counter_value != usable[1].counter_value:
            warnings.append(
                f"Slot {slot} primary and backup counters differ; the higher "
                "checksum-valid value was selected"
            )
        elif len(usable) == 1:
            other = next(attempt for attempt in copies if attempt is not usable[0])
            if other.counter_value != UNINITIALIZED_BYTE:
                warnings.append(
                    f"Slot {slot} has only one usable checksum-valid copy"
                )

    valid_slots = tuple(
        slot
        for slot, _, _ in STANDARD_SLOT_OFFSETS
        if any(attempt.accepted and attempt.slot == slot for attempt in attempts)
    )
    analysis = SaveAnalysis(
        path=absolute,
        size=len(data),
        profile=PROFILE_STANDARD_SMW_SLOTS,
        confidence=CONFIDENCE_MEDIUM,
        counter_kind=COUNTER_OVERWORLD_EVENTS,
        selected_value=selected.counter_value,
        selected_slot=selected.slot,
        selected_copy=selected.copy_kind,
        valid_slots=valid_slots,
        warnings=tuple(warnings),
        attempts=tuple(attempts),
    )
    return analysis, tuple(attempts)



def _expanded_sram_analysis(
    absolute: str,
    data: bytes,
    prior_attempts: tuple[ProfileAttempt, ...],
) -> SaveAnalysis:
    """Reject an unvalidated raw counter in an expanded SRAM image.

    Expanded images are used by SA-1/BW-RAM and other non-standard layouts.
    Unless the standard-slot profile has already succeeded, byte ``0x8C`` is
    retained only as diagnostic evidence and is not exposed as progress.
    """

    raw_value = (
        data[LEGACY_COUNTER_OFFSET]
        if len(data) > LEGACY_COUNTER_OFFSET
        else None
    )
    reason = (
        f"Save is {len(data)} bytes, indicating an expanded SRAM layout; "
        "no checksum-valid standard SMW slot was found, so the inherited "
        "raw counter at 0x8C was suppressed"
    )
    attempt = ProfileAttempt(
        profile=PROFILE_EXPANDED_SRAM_UNKNOWN,
        accepted=False,
        confidence=CONFIDENCE_NONE,
        reason=reason,
        counter_offset=(
            LEGACY_COUNTER_OFFSET if raw_value is not None else None
        ),
        counter_kind=COUNTER_UNKNOWN,
        counter_value=raw_value,
    )
    return SaveAnalysis(
        path=absolute,
        size=len(data),
        profile=PROFILE_EXPANDED_SRAM_UNKNOWN,
        confidence=CONFIDENCE_NONE,
        counter_kind=COUNTER_UNKNOWN,
        selected_value=None,
        warnings=(reason,),
        attempts=prior_attempts + (attempt,),
    )

def _legacy_analysis(
    absolute: str,
    data: bytes,
    prior_attempts: tuple[ProfileAttempt, ...] = (),
) -> SaveAnalysis:
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
            attempts=prior_attempts + (attempt,),
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
            attempts=prior_attempts + (attempt,),
        )

    warning = (
        "Legacy raw counter at 0x8C is not checksum-validated and may not equal "
        "the hack's advertised exits"
    )
    warnings = (warning,)
    if prior_attempts:
        warnings = (
            "No usable checksum-valid standard SMW slot was found",
            warning,
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
        warnings=warnings,
        attempts=prior_attempts + (attempt,),
    )


def analyze_save(path: os.PathLike[str] | str) -> SaveAnalysis:
    """Read *path* and return the strongest supported parser evidence.

    Checksum-valid standard SMW slots take precedence. Expanded SRAM images
    without a proven standard slot suppress the inherited ``0x8C`` byte. Smaller
    non-standard saves retain that read as low-confidence compatibility evidence.
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

    standard, standard_attempts = _analyze_standard_slots(absolute, data)
    if standard is not None:
        return standard
    if len(data) >= EXPANDED_SRAM_MIN_SIZE:
        return _expanded_sram_analysis(absolute, data, standard_attempts)
    return _legacy_analysis(absolute, data, standard_attempts)
