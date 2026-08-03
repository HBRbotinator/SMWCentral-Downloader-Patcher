"""Versioned read-only data contract for external Wheel runtimes.

The contract deliberately contains only normalized display and filtering
metadata. It never exposes local ROM/save paths, download URLs, notes, raw API
payloads, or mutable application records.
"""

from __future__ import annotations

import copy
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any


WHEEL_RUNTIME_SCHEMA = "smwc-wheel-runtime"
WHEEL_RUNTIME_SCHEMA_VERSION = 1
WHEEL_RUNTIME_SOURCE_KIND = "collection_snapshot"

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema",
        "schema_version",
        "generated_at",
        "source",
        "planner",
        "candidates",
    }
)
_SOURCE_KEYS = frozenset({"kind", "revision"})
_PLANNER_KEYS = frozenset({"available", "lists"})
_LIST_KEYS = frozenset({"id", "name"})
_CANDIDATE_KEYS = frozenset(
    {
        "id",
        "title",
        "authors",
        "type",
        "difficulty",
        "completed",
        "downloaded",
        "smwc_rating",
        "release_year",
        "planner",
    }
)
_CANDIDATE_PLANNER_KEYS = frozenset(
    {
        "lifecycle",
        "horizon",
        "list_ids",
        "next_position",
    }
)


class WheelRuntimeContractError(ValueError):
    """Raised when a Wheel runtime snapshot violates the schema contract."""


def build_wheel_runtime_snapshot(
    candidates: Iterable[Mapping[str, Any]],
    *,
    planner_lists: Iterable[Mapping[str, Any]] = (),
    planner_available: bool | None = None,
    generated_at: datetime | str | None = None,
    source_revision: Any | None = None,
) -> dict[str, Any]:
    """Build one detached JSON-friendly snapshot from projected records."""

    normalized_lists = _normalize_planner_lists(planner_lists)
    normalized_candidates = _normalize_candidates(candidates)

    known_list_ids = {item["id"] for item in normalized_lists}
    for candidate in normalized_candidates:
        unknown_ids = [
            list_id
            for list_id in candidate["planner"]["list_ids"]
            if list_id not in known_list_ids
        ]
        if unknown_ids:
            raise WheelRuntimeContractError(
                "Candidate "
                f"{candidate['id']!r} references unknown Planner list IDs: "
                + ", ".join(unknown_ids)
            )

    inferred_planner = bool(
        normalized_lists
        or any(
            _candidate_has_planner_data(candidate)
            for candidate in normalized_candidates
        )
    )
    if planner_available is None:
        planner_enabled = inferred_planner
    elif not isinstance(planner_available, bool):
        raise TypeError("planner_available must be True, False, or None")
    else:
        planner_enabled = planner_available

    if not planner_enabled and inferred_planner:
        raise WheelRuntimeContractError(
            "planner_available cannot be false while Planner data is present"
        )

    revision = (
        None
        if source_revision is None
        else _required_text(
            source_revision,
            "source_revision cannot be blank",
        )
    )
    snapshot = {
        "schema": WHEEL_RUNTIME_SCHEMA,
        "schema_version": WHEEL_RUNTIME_SCHEMA_VERSION,
        "generated_at": _normalize_generated_at(generated_at),
        "source": {
            "kind": WHEEL_RUNTIME_SOURCE_KIND,
            "revision": revision,
        },
        "planner": {
            "available": planner_enabled,
            "lists": normalized_lists,
        },
        "candidates": normalized_candidates,
    }
    return validate_wheel_runtime_snapshot(snapshot)


def validate_wheel_runtime_snapshot(
    snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate a v1 snapshot and return a completely detached copy."""

    if not isinstance(snapshot, Mapping):
        raise TypeError("Wheel runtime snapshot must be a mapping")

    _require_exact_keys(snapshot, _TOP_LEVEL_KEYS, "snapshot")
    if snapshot["schema"] != WHEEL_RUNTIME_SCHEMA:
        raise WheelRuntimeContractError(
            f"Unsupported Wheel runtime schema: {snapshot['schema']!r}"
        )
    if snapshot["schema_version"] != WHEEL_RUNTIME_SCHEMA_VERSION:
        raise WheelRuntimeContractError(
            "Unsupported Wheel runtime schema version: "
            f"{snapshot['schema_version']!r}"
        )

    generated_at = snapshot["generated_at"]
    if not isinstance(generated_at, str):
        raise WheelRuntimeContractError("generated_at must be a string")
    if _normalize_generated_at(generated_at) != generated_at:
        raise WheelRuntimeContractError(
            "generated_at must be canonical UTC without fractional seconds"
        )

    source = snapshot["source"]
    if not isinstance(source, Mapping):
        raise WheelRuntimeContractError("source must be a mapping")
    _require_exact_keys(source, _SOURCE_KEYS, "source")
    if source["kind"] != WHEEL_RUNTIME_SOURCE_KIND:
        raise WheelRuntimeContractError(
            f"Unsupported source kind: {source['kind']!r}"
        )
    revision = source["revision"]
    if revision is not None and (
        not isinstance(revision, str) or not revision.strip()
    ):
        raise WheelRuntimeContractError(
            "source revision must be a nonblank string or null"
        )

    planner = snapshot["planner"]
    if not isinstance(planner, Mapping):
        raise WheelRuntimeContractError("planner must be a mapping")
    _require_exact_keys(planner, _PLANNER_KEYS, "planner")
    if not isinstance(planner["available"], bool):
        raise WheelRuntimeContractError("planner.available must be boolean")
    if not isinstance(planner["lists"], list):
        raise WheelRuntimeContractError("planner.lists must be a list")

    known_list_ids = set()
    for index, item in enumerate(planner["lists"]):
        _validate_planner_list(item, index)
        if item["id"] in known_list_ids:
            raise WheelRuntimeContractError(
                f"Duplicate Planner list ID: {item['id']!r}"
            )
        known_list_ids.add(item["id"])

    candidates = snapshot["candidates"]
    if not isinstance(candidates, list):
        raise WheelRuntimeContractError("candidates must be a list")

    seen_candidate_ids = set()
    any_planner_data = bool(planner["lists"])
    for index, candidate in enumerate(candidates):
        _validate_candidate(candidate, index, known_list_ids)
        candidate_id = candidate["id"]
        if candidate_id in seen_candidate_ids:
            raise WheelRuntimeContractError(
                f"Duplicate candidate ID: {candidate_id!r}"
            )
        seen_candidate_ids.add(candidate_id)
        any_planner_data = (
            any_planner_data
            or _candidate_has_planner_data(candidate)
        )

    if not planner["available"] and any_planner_data:
        raise WheelRuntimeContractError(
            "Planner data cannot be present when planner.available is false"
        )

    return copy.deepcopy(dict(snapshot))


def serialize_wheel_runtime_snapshot(
    snapshot: Mapping[str, Any],
    *,
    indent: int | None = 2,
) -> str:
    """Return stable UTF-8 JSON text with one final newline."""

    if isinstance(indent, bool) or (
        indent is not None
        and (not isinstance(indent, int) or indent < 0)
    ):
        raise TypeError("indent must be a non-negative integer or None")

    validated = validate_wheel_runtime_snapshot(snapshot)
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


def _normalize_candidates(
    candidates: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if isinstance(candidates, (str, bytes, Mapping)):
        raise TypeError("candidates must be an iterable of mappings")

    normalized = []
    seen_ids = set()
    for index, record in enumerate(candidates):
        if not isinstance(record, Mapping):
            raise TypeError(
                f"Candidate at index {index} must be a mapping"
            )
        candidate = _normalize_candidate(record, index)
        candidate_id = candidate["id"]
        if candidate_id in seen_ids:
            raise WheelRuntimeContractError(
                f"Duplicate candidate ID: {candidate_id!r}"
            )
        seen_ids.add(candidate_id)
        normalized.append(candidate)
    return normalized


def _normalize_candidate(
    record: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    candidate_id = _required_text(
        _first_present(record, "id", "hack_id"),
        f"Candidate at index {index} has no stable ID",
    )
    title = _required_text(
        _first_present(record, "title", "name"),
        f"Candidate {candidate_id!r} has no title",
    )

    raw_fields = record.get("raw_fields")
    if not isinstance(raw_fields, Mapping):
        raw_fields = {}

    planner_record = record.get("planner")
    if not isinstance(planner_record, Mapping):
        planner_record = {}

    lifecycle = _optional_text(
        _first_present(
            planner_record,
            "lifecycle",
            "status",
        )
        or _first_present(
            record,
            "planner_lifecycle",
            "lifecycle_status",
            "planner_status",
        )
    )
    horizon = _optional_text(
        _first_present(
            planner_record,
            "horizon",
            "planning_horizon",
        )
        or _first_present(
            record,
            "planning_horizon",
            "planner_horizon",
        )
    )
    list_ids = _normalize_id_list(
        _first_present(
            planner_record,
            "list_ids",
            "lists",
        )
        or _first_present(
            record,
            "planner_list_ids",
            "list_ids",
        )
        or []
    )
    next_position = _optional_positive_int(
        _first_present(
            planner_record,
            "next_position",
        )
        or _first_present(
            record,
            "planner_next_position",
            "next_position",
        )
    )

    return {
        "id": candidate_id,
        "title": title,
        "authors": _normalize_authors(
            _first_present(record, "authors", "author")
        ),
        "type": _optional_text(
            _first_present(record, "type", "hack_type")
        ),
        "difficulty": _optional_text(
            _first_present(record, "difficulty")
            or _first_present(raw_fields, "difficulty")
        ),
        "completed": _normalize_boolean(record.get("completed", False)),
        "downloaded": _has_recorded_download(record),
        "smwc_rating": _normalize_rating(
            _first_present(record, "smwc_rating", "rating")
        ),
        "release_year": _release_year(record),
        "planner": {
            "lifecycle": lifecycle,
            "horizon": horizon,
            "list_ids": list_ids,
            "next_position": next_position,
        },
    }


def _normalize_planner_lists(
    planner_lists: Iterable[Mapping[str, Any]],
) -> list[dict[str, str]]:
    if isinstance(planner_lists, (str, bytes, Mapping)):
        raise TypeError("planner_lists must be an iterable of mappings")

    normalized = []
    seen_ids = set()
    for index, item in enumerate(planner_lists):
        if not isinstance(item, Mapping):
            raise TypeError(
                f"Planner list at index {index} must be a mapping"
            )
        list_id = _required_text(
            _first_present(item, "id", "list_id"),
            f"Planner list at index {index} has no stable ID",
        )
        name = _required_text(
            _first_present(item, "name", "title"),
            f"Planner list {list_id!r} has no name",
        )
        if list_id in seen_ids:
            raise WheelRuntimeContractError(
                f"Duplicate Planner list ID: {list_id!r}"
            )
        seen_ids.add(list_id)
        normalized.append({"id": list_id, "name": name})
    return normalized


def _normalize_authors(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.replace(";", ",").split(",")
    elif isinstance(value, Mapping):
        items = [value]
    elif isinstance(value, Iterable) and not isinstance(
        value,
        (str, bytes),
    ):
        items = list(value)
    else:
        items = [value]

    result = []
    seen = set()
    for item in items:
        if isinstance(item, Mapping):
            item = _first_present(
                item,
                "name",
                "username",
                "display_name",
                "id",
            )
        text = _optional_text(item)
        folded = text.casefold()
        if text and folded not in seen:
            seen.add(folded)
            result.append(text)
    return result


def _normalize_id_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        items = [value]
    elif isinstance(value, Iterable):
        items = list(value)
    else:
        items = [value]

    result = []
    seen = set()
    for item in items:
        if isinstance(item, Mapping):
            item = _first_present(item, "id", "list_id")
        text = _optional_text(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _normalize_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "yes", "1"}:
            return True
        if lowered in {"false", "no", "0", ""}:
            return False
    return bool(value)


def _has_recorded_download(record: Mapping[str, Any]) -> bool:
    if "downloaded" in record:
        return _normalize_boolean(record["downloaded"])

    status = _optional_text(record.get("download_status")).casefold()
    if status in {"downloaded", "partially downloaded"}:
        return True

    file_path = record.get("file_path")
    if isinstance(file_path, str) and file_path.strip():
        return True

    files = record.get("files")
    if isinstance(files, list):
        return any(
            isinstance(item, Mapping)
            and isinstance(item.get("path"), str)
            and bool(item["path"].strip())
            for item in files
        )
    return False


def _normalize_rating(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        rating = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(rating) or not 0 < rating <= 5:
        return None
    return rating


def _release_year(record: Mapping[str, Any]) -> int | None:
    direct_year = _optional_year(record.get("release_year"))
    if direct_year is not None:
        return direct_year

    date_text = record.get("date")
    if isinstance(date_text, str):
        stripped = date_text.strip()
        if len(stripped) >= 4 and stripped[:4].isdigit():
            return _optional_year(stripped[:4])

    timestamp = record.get("time")
    if timestamp is None or isinstance(timestamp, bool):
        return None
    try:
        timestamp_number = float(timestamp)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(timestamp_number) or timestamp_number <= 0:
        return None
    try:
        return datetime.fromtimestamp(
            timestamp_number,
            tz=timezone.utc,
        ).year
    except (OSError, OverflowError, ValueError):
        return None


def _optional_year(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None
    return year if 1000 <= year <= 9999 else None


def _optional_positive_int(value: Any) -> int | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _normalize_generated_at(
    value: datetime | str | None,
) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    elif isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise WheelRuntimeContractError(
                "generated_at cannot be blank"
            )
        try:
            parsed = datetime.fromisoformat(
                text.replace("Z", "+00:00")
            )
        except ValueError as error:
            raise WheelRuntimeContractError(
                "generated_at must be an ISO-8601 timestamp"
            ) from error
    else:
        raise TypeError("generated_at must be datetime, string, or None")

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise WheelRuntimeContractError(
            "generated_at must include a timezone"
        )

    return (
        parsed.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _validate_planner_list(item: Any, index: int) -> None:
    if not isinstance(item, Mapping):
        raise WheelRuntimeContractError(
            f"Planner list at index {index} must be a mapping"
        )
    _require_exact_keys(item, _LIST_KEYS, f"planner list {index}")
    _require_nonblank_string(item["id"], f"planner list {index} ID")
    _require_nonblank_string(item["name"], f"planner list {index} name")


def _validate_candidate(
    candidate: Any,
    index: int,
    known_list_ids: set[str],
) -> None:
    if not isinstance(candidate, Mapping):
        raise WheelRuntimeContractError(
            f"Candidate at index {index} must be a mapping"
        )
    _require_exact_keys(candidate, _CANDIDATE_KEYS, f"candidate {index}")

    candidate_id = _require_nonblank_string(
        candidate["id"],
        f"candidate {index} ID",
    )
    _require_nonblank_string(
        candidate["title"],
        f"candidate {candidate_id!r} title",
    )

    authors = candidate["authors"]
    if not isinstance(authors, list):
        raise WheelRuntimeContractError(
            f"Candidate {candidate_id!r} authors must be a list"
        )
    normalized_authors = []
    for author in authors:
        normalized_authors.append(
            _require_nonblank_string(
                author,
                f"candidate {candidate_id!r} author",
            )
        )
    if len(set(normalized_authors)) != len(normalized_authors):
        raise WheelRuntimeContractError(
            f"Candidate {candidate_id!r} has duplicate authors"
        )

    for field in ("type", "difficulty"):
        if not isinstance(candidate[field], str):
            raise WheelRuntimeContractError(
                f"Candidate {candidate_id!r} {field} must be a string"
            )

    for field in ("completed", "downloaded"):
        if not isinstance(candidate[field], bool):
            raise WheelRuntimeContractError(
                f"Candidate {candidate_id!r} {field} must be boolean"
            )

    rating = candidate["smwc_rating"]
    if rating is not None:
        if (
            isinstance(rating, bool)
            or not isinstance(rating, (int, float))
            or not math.isfinite(float(rating))
            or not 0 < float(rating) <= 5
        ):
            raise WheelRuntimeContractError(
                f"Candidate {candidate_id!r} has invalid SMWC rating"
            )

    release_year = candidate["release_year"]
    if release_year is not None and (
        isinstance(release_year, bool)
        or not isinstance(release_year, int)
        or not 1000 <= release_year <= 9999
    ):
        raise WheelRuntimeContractError(
            f"Candidate {candidate_id!r} has invalid release year"
        )

    planner = candidate["planner"]
    if not isinstance(planner, Mapping):
        raise WheelRuntimeContractError(
            f"Candidate {candidate_id!r} planner must be a mapping"
        )
    _require_exact_keys(
        planner,
        _CANDIDATE_PLANNER_KEYS,
        f"candidate {candidate_id!r} planner",
    )
    for field in ("lifecycle", "horizon"):
        if not isinstance(planner[field], str):
            raise WheelRuntimeContractError(
                f"Candidate {candidate_id!r} planner {field} "
                "must be a string"
            )

    list_ids = planner["list_ids"]
    if not isinstance(list_ids, list):
        raise WheelRuntimeContractError(
            f"Candidate {candidate_id!r} Planner list IDs must be a list"
        )
    if len(set(list_ids)) != len(list_ids):
        raise WheelRuntimeContractError(
            f"Candidate {candidate_id!r} has duplicate Planner list IDs"
        )
    for list_id in list_ids:
        _require_nonblank_string(
            list_id,
            f"candidate {candidate_id!r} Planner list ID",
        )
        if list_id not in known_list_ids:
            raise WheelRuntimeContractError(
                f"Candidate {candidate_id!r} references unknown "
                f"Planner list ID {list_id!r}"
            )

    next_position = planner["next_position"]
    if next_position is not None and (
        isinstance(next_position, bool)
        or not isinstance(next_position, int)
        or next_position <= 0
    ):
        raise WheelRuntimeContractError(
            f"Candidate {candidate_id!r} next_position "
            "must be a positive integer or null"
        )


def _candidate_has_planner_data(
    candidate: Mapping[str, Any],
) -> bool:
    planner = candidate["planner"]
    return bool(
        planner["lifecycle"]
        or planner["horizon"]
        or planner["list_ids"]
        or planner["next_position"] is not None
    )


def _require_exact_keys(
    mapping: Mapping[str, Any],
    expected: frozenset[str],
    label: str,
) -> None:
    actual = set(mapping)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if unexpected:
            details.append("unexpected " + ", ".join(unexpected))
        raise WheelRuntimeContractError(
            f"{label} has invalid fields: " + "; ".join(details)
        )


def _first_present(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping:
            value = mapping[key]
            if value not in (None, "", [], {}):
                return value
    return None


def _required_text(value: Any, message: str) -> str:
    text = _optional_text(value)
    if not text:
        raise WheelRuntimeContractError(message)
    return text


def _optional_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _require_nonblank_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WheelRuntimeContractError(
            f"{label} must be a nonblank string"
        )
    return value


__all__ = [
    "WHEEL_RUNTIME_SCHEMA",
    "WHEEL_RUNTIME_SCHEMA_VERSION",
    "WHEEL_RUNTIME_SOURCE_KIND",
    "WheelRuntimeContractError",
    "build_wheel_runtime_snapshot",
    "validate_wheel_runtime_snapshot",
    "serialize_wheel_runtime_snapshot",
]
