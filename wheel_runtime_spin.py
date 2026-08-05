"""Versioned Python-authored spin instructions for browser runtimes."""

from __future__ import annotations

import copy
import json
import math
import threading
import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from wheel_runtime_contract import validate_wheel_runtime_snapshot


WHEEL_RUNTIME_SPIN_SCHEMA = "smwc-wheel-spin"
WHEEL_RUNTIME_SPIN_SCHEMA_VERSION = 1
WHEEL_RUNTIME_DEFAULT_DURATION_MS = 6500
WHEEL_RUNTIME_DEFAULT_TURNS = 6
WHEEL_RUNTIME_DEFAULT_LANDING_OFFSET = 0.5

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "schema_version",
        "spin_id",
        "sequence",
        "issued_at",
        "snapshot",
        "winner",
        "animation",
    }
)
_SNAPSHOT_KEYS = frozenset(
    {
        "generated_at",
        "source_revision",
        "candidate_count",
    }
)
_WINNER_KEYS = frozenset({"id", "title", "index"})
_ANIMATION_KEYS = frozenset(
    {
        "duration_ms",
        "turns",
        "landing_offset",
    }
)


class WheelRuntimeSpinContractError(ValueError):
    """Raised when a spin instruction violates the runtime contract."""


class WheelRuntimeSpinUnavailableError(RuntimeError):
    """Raised when no spin instruction has been published yet."""


def build_wheel_runtime_spin(
    snapshot: Mapping[str, Any],
    winner_id: Any,
    *,
    spin_id: Any,
    sequence: int,
    issued_at: datetime | str | None = None,
    duration_ms: int = WHEEL_RUNTIME_DEFAULT_DURATION_MS,
    turns: int = WHEEL_RUNTIME_DEFAULT_TURNS,
    landing_offset: float = WHEEL_RUNTIME_DEFAULT_LANDING_OFFSET,
) -> dict[str, Any]:
    """Build one instruction around a winner already selected by Python."""

    validated_snapshot = validate_wheel_runtime_snapshot(snapshot)
    normalized_winner_id = _required_text(
        winner_id,
        "winner_id must be a nonblank value",
    )
    normalized_spin_id = _required_text(
        spin_id,
        "spin_id must be a nonblank value",
    )
    normalized_sequence = _positive_int(sequence, "sequence")
    normalized_duration = _duration_ms(duration_ms)
    normalized_turns = _turns(turns)
    normalized_offset = _landing_offset(landing_offset)

    winner_index = None
    winner = None
    for index, candidate in enumerate(
        validated_snapshot["candidates"]
    ):
        if candidate["id"] == normalized_winner_id:
            winner_index = index
            winner = candidate
            break

    if winner is None or winner_index is None:
        raise WheelRuntimeSpinContractError(
            f"Winner {normalized_winner_id!r} is not in the snapshot"
        )

    document = {
        "schema": WHEEL_RUNTIME_SPIN_SCHEMA,
        "schema_version": WHEEL_RUNTIME_SPIN_SCHEMA_VERSION,
        "spin_id": normalized_spin_id,
        "sequence": normalized_sequence,
        "issued_at": _normalize_timestamp(issued_at),
        "snapshot": {
            "generated_at": validated_snapshot["generated_at"],
            "source_revision": validated_snapshot["source"]["revision"],
            "candidate_count": len(
                validated_snapshot["candidates"]
            ),
        },
        "winner": {
            "id": winner["id"],
            "title": winner["title"],
            "index": winner_index,
        },
        "animation": {
            "duration_ms": normalized_duration,
            "turns": normalized_turns,
            "landing_offset": normalized_offset,
        },
    }
    return validate_wheel_runtime_spin(document)


def validate_wheel_runtime_spin(
    document: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one v1 spin instruction and return a detached copy."""

    if not isinstance(document, Mapping):
        raise TypeError("Wheel runtime spin must be a mapping")

    _require_exact_keys(document, _TOP_LEVEL_KEYS, "spin")
    if document["schema"] != WHEEL_RUNTIME_SPIN_SCHEMA:
        raise WheelRuntimeSpinContractError(
            f"Unsupported Wheel spin schema: {document['schema']!r}"
        )
    if (
        document["schema_version"]
        != WHEEL_RUNTIME_SPIN_SCHEMA_VERSION
    ):
        raise WheelRuntimeSpinContractError(
            "Unsupported Wheel spin schema version: "
            f"{document['schema_version']!r}"
        )

    _require_nonblank_string(document["spin_id"], "spin_id")
    _positive_int(document["sequence"], "sequence")

    issued_at = document["issued_at"]
    if not isinstance(issued_at, str):
        raise WheelRuntimeSpinContractError(
            "issued_at must be a string"
        )
    if _normalize_timestamp(issued_at) != issued_at:
        raise WheelRuntimeSpinContractError(
            "issued_at must be canonical UTC without fractional seconds"
        )

    snapshot = document["snapshot"]
    if not isinstance(snapshot, Mapping):
        raise WheelRuntimeSpinContractError(
            "snapshot must be a mapping"
        )
    _require_exact_keys(snapshot, _SNAPSHOT_KEYS, "snapshot")
    _validate_canonical_timestamp(
        snapshot["generated_at"],
        "snapshot.generated_at",
    )
    source_revision = snapshot["source_revision"]
    if source_revision is not None:
        _require_nonblank_string(
            source_revision,
            "snapshot.source_revision",
        )
    candidate_count = _positive_int(
        snapshot["candidate_count"],
        "snapshot.candidate_count",
    )

    winner = document["winner"]
    if not isinstance(winner, Mapping):
        raise WheelRuntimeSpinContractError(
            "winner must be a mapping"
        )
    _require_exact_keys(winner, _WINNER_KEYS, "winner")
    _require_nonblank_string(winner["id"], "winner.id")
    _require_nonblank_string(winner["title"], "winner.title")
    winner_index = _nonnegative_int(
        winner["index"],
        "winner.index",
    )
    if winner_index >= candidate_count:
        raise WheelRuntimeSpinContractError(
            "winner.index must be within snapshot.candidate_count"
        )

    animation = document["animation"]
    if not isinstance(animation, Mapping):
        raise WheelRuntimeSpinContractError(
            "animation must be a mapping"
        )
    _require_exact_keys(animation, _ANIMATION_KEYS, "animation")
    _duration_ms(animation["duration_ms"])
    _turns(animation["turns"])
    _landing_offset(animation["landing_offset"])

    return copy.deepcopy(dict(document))


def serialize_wheel_runtime_spin(
    document: Mapping[str, Any],
    *,
    indent: int | None = 2,
) -> str:
    """Return stable UTF-8 JSON text with one final newline."""

    if isinstance(indent, bool) or (
        indent is not None
        and (
            not isinstance(indent, int)
            or indent < 0
        )
    ):
        raise TypeError(
            "indent must be a non-negative integer or None"
        )

    validated = validate_wheel_runtime_spin(document)
    return (
        json.dumps(
            validated,
            ensure_ascii=False,
            indent=indent,
            sort_keys=True,
            separators=None if indent is not None else (",", ":"),
        )
        + "\n"
    )


class WheelRuntimeSpinCoordinator:
    """Publish validated winner instructions without selecting winners."""

    def __init__(
        self,
        snapshot_provider: Any,
        *,
        clock: Callable[[], datetime] | None = None,
        spin_id_supplier: Callable[[], Any] | None = None,
    ) -> None:
        if not callable(
            getattr(snapshot_provider, "current_snapshot", None)
        ):
            raise TypeError(
                "snapshot_provider must provide current_snapshot()"
            )
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")
        if (
            spin_id_supplier is not None
            and not callable(spin_id_supplier)
        ):
            raise TypeError(
                "spin_id_supplier must be callable or None"
            )

        self._snapshot_provider = snapshot_provider
        self._clock = clock or _utc_now
        self._spin_id_supplier = (
            spin_id_supplier or _new_spin_id
        )
        self._lock = threading.RLock()
        self._spin: dict[str, Any] | None = None
        self._serialized: str | None = None
        self._successful_publications = 0
        self._last_error: str | None = None

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._spin is not None

    def publish_winner(
        self,
        winner_id: Any,
        *,
        duration_ms: int = WHEEL_RUNTIME_DEFAULT_DURATION_MS,
        turns: int = WHEEL_RUNTIME_DEFAULT_TURNS,
        landing_offset: float = (
            WHEEL_RUNTIME_DEFAULT_LANDING_OFFSET
        ),
    ) -> dict[str, Any]:
        """Publish a winner already chosen by the application."""

        try:
            snapshot = self._snapshot_provider.current_snapshot()
            with self._lock:
                sequence = self._successful_publications + 1
                spin = build_wheel_runtime_spin(
                    snapshot,
                    winner_id,
                    spin_id=self._spin_id_supplier(),
                    sequence=sequence,
                    issued_at=self._clock(),
                    duration_ms=duration_ms,
                    turns=turns,
                    landing_offset=landing_offset,
                )
                serialized = serialize_wheel_runtime_spin(spin)
                self._spin = spin
                self._serialized = serialized
                self._successful_publications = sequence
                self._last_error = None
                return copy.deepcopy(spin)
        except Exception as error:
            with self._lock:
                self._last_error = _format_error(error)
            raise

    def current_spin(self) -> dict[str, Any]:
        with self._lock:
            if self._spin is None:
                raise WheelRuntimeSpinUnavailableError(
                    "No Wheel runtime spin has been published"
                )
            return copy.deepcopy(self._spin)

    def current_json(self) -> str:
        with self._lock:
            if self._serialized is None:
                raise WheelRuntimeSpinUnavailableError(
                    "No Wheel runtime spin has been published"
                )
            return self._serialized

    def status(self) -> dict[str, Any]:
        with self._lock:
            spin = self._spin
            return {
                "ready": spin is not None,
                "successful_publications": (
                    self._successful_publications
                ),
                "sequence": (
                    spin["sequence"] if spin else None
                ),
                "spin_id": (
                    spin["spin_id"] if spin else None
                ),
                "issued_at": (
                    spin["issued_at"] if spin else None
                ),
                "winner_id": (
                    spin["winner"]["id"] if spin else None
                ),
                "winner_title": (
                    spin["winner"]["title"] if spin else None
                ),
                "snapshot_generated_at": (
                    spin["snapshot"]["generated_at"]
                    if spin
                    else None
                ),
                "source_revision": (
                    spin["snapshot"]["source_revision"]
                    if spin
                    else None
                ),
                "last_error": self._last_error,
            }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_spin_id() -> str:
    return uuid.uuid4().hex


def _normalize_timestamp(
    value: datetime | str | None,
) -> str:
    if value is None:
        parsed = _utc_now()
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise WheelRuntimeSpinContractError(
                "timestamp cannot be blank"
            )
        try:
            parsed = datetime.fromisoformat(
                text.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise WheelRuntimeSpinContractError(
                "timestamp must be ISO-8601"
            ) from error
    else:
        raise TypeError(
            "timestamp must be datetime, string, or None"
        )

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WheelRuntimeSpinContractError(
            "timestamp must include a timezone"
        )

    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_canonical_timestamp(
    value: Any,
    label: str,
) -> None:
    if not isinstance(value, str):
        raise WheelRuntimeSpinContractError(
            f"{label} must be a string"
        )
    if _normalize_timestamp(value) != value:
        raise WheelRuntimeSpinContractError(
            f"{label} must be canonical UTC"
        )


def _duration_ms(value: Any) -> int:
    number = _positive_int(value, "animation.duration_ms")
    if not 1000 <= number <= 30000:
        raise WheelRuntimeSpinContractError(
            "animation.duration_ms must be between 1000 and 30000"
        )
    return number


def _turns(value: Any) -> int:
    number = _positive_int(value, "animation.turns")
    if not 1 <= number <= 20:
        raise WheelRuntimeSpinContractError(
            "animation.turns must be between 1 and 20"
        )
    return number


def _landing_offset(value: Any) -> float:
    if isinstance(value, bool):
        raise WheelRuntimeSpinContractError(
            "animation.landing_offset must be numeric"
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise WheelRuntimeSpinContractError(
            "animation.landing_offset must be numeric"
        ) from error
    if not math.isfinite(number) or not 0.0 < number < 1.0:
        raise WheelRuntimeSpinContractError(
            "animation.landing_offset must be between 0 and 1"
        )
    return number


def _positive_int(value: Any, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value <= 0
    ):
        raise WheelRuntimeSpinContractError(
            f"{label} must be a positive integer"
        )
    return value


def _nonnegative_int(value: Any, label: str) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
    ):
        raise WheelRuntimeSpinContractError(
            f"{label} must be a non-negative integer"
        )
    return value


def _required_text(value: Any, message: str) -> str:
    text = "" if value is None else str(value).strip()
    if not text:
        raise WheelRuntimeSpinContractError(message)
    return text


def _require_nonblank_string(
    value: Any,
    label: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WheelRuntimeSpinContractError(
            f"{label} must be a nonblank string"
        )
    return value


def _require_exact_keys(
    mapping: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(mapping)
    if actual == expected:
        return

    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details = []
    if missing:
        details.append("missing " + ", ".join(missing))
    if unexpected:
        details.append("unexpected " + ", ".join(unexpected))
    raise WheelRuntimeSpinContractError(
        f"{label} has invalid fields: " + "; ".join(details)
    )


def _format_error(error: Exception) -> str:
    name = type(error).__name__
    message = str(error).strip()
    return f"{name}: {message}" if message else name


__all__ = [
    "WHEEL_RUNTIME_SPIN_SCHEMA",
    "WHEEL_RUNTIME_SPIN_SCHEMA_VERSION",
    "WHEEL_RUNTIME_DEFAULT_DURATION_MS",
    "WHEEL_RUNTIME_DEFAULT_TURNS",
    "WHEEL_RUNTIME_DEFAULT_LANDING_OFFSET",
    "WheelRuntimeSpinContractError",
    "WheelRuntimeSpinUnavailableError",
    "WheelRuntimeSpinCoordinator",
    "build_wheel_runtime_spin",
    "validate_wheel_runtime_spin",
    "serialize_wheel_runtime_spin",
]
