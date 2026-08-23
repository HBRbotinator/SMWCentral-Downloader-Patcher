"""Adapter for user-exported GiganticBucket checkpoint JSON."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from collection_ingestion import (
    CollectionCandidate,
    EvidenceStrength,
    IdentityEvidence,
    IdentityEvidenceKind,
    IngestionSource,
    UserPlaythroughEvidence,
)
from rom_title_matching import CatalogueEntry, CatalogueMatcher


GIGANTIC_BUCKET_MAX_BYTES = 32 * 1024 * 1024
GIGANTIC_BUCKET_SERIALIZATION_VERSION = 1


class GiganticBucketImportError(RuntimeError):
    """Raised when a GiganticBucket export cannot be interpreted safely."""


@dataclass(frozen=True)
class GiganticBucketHack:
    """One played hack from a GiganticBucket checkpoint export."""

    hack_id: int
    title: str
    source_kind: str
    link_id: int | None
    creators: tuple[str, ...]
    candidate: CollectionCandidate

    @property
    def smwc_submission_id(self) -> int | None:
        """Only SMWCHack link_Id is treated as SMWC submission evidence."""

        if self.source_kind == "SMWCHack":
            return self.link_id
        return None


@dataclass(frozen=True)
class GiganticBucketImport:
    """Validated local checkpoint export."""

    serialization_version: int
    hacks: tuple[GiganticBucketHack, ...]


@dataclass(frozen=True)
class GiganticBucketCatalogueResolution:
    """Conservative catalogue resolution for one imported history record."""

    item: GiganticBucketHack
    selected: CatalogueEntry | None
    suggestion: CatalogueEntry | None
    confidence: float
    classification: str
    auto_selected: bool


def load_giganticbucket_export(path: str | Path) -> GiganticBucketImport:
    """Load one local user export without accepting paths from its contents."""

    source = Path(path).expanduser().resolve()
    if source.suffix.casefold() != ".json":
        raise GiganticBucketImportError("GiganticBucket import must be a .json file.")
    if not source.is_file():
        raise GiganticBucketImportError("GiganticBucket import file does not exist.")
    size = source.stat().st_size
    if size <= 0:
        raise GiganticBucketImportError("GiganticBucket import file is empty.")
    if size > GIGANTIC_BUCKET_MAX_BYTES:
        raise GiganticBucketImportError("GiganticBucket import file is too large.")

    try:
        payload = _loads_json(source.read_bytes())
    except UnicodeError as error:
        raise GiganticBucketImportError(
            "GiganticBucket import must be UTF-8 JSON."
        ) from error
    except json.JSONDecodeError as error:
        raise GiganticBucketImportError(
            "GiganticBucket import contains malformed JSON."
        ) from error
    return parse_giganticbucket_export(payload)


def parse_giganticbucket_export(payload: Any) -> GiganticBucketImport:
    """Parse a deserialized GiganticBucket v1 checkpoint."""

    if not isinstance(payload, Mapping):
        raise GiganticBucketImportError("GiganticBucket export must be a JSON object.")
    version = payload.get("serializationVersion")
    if version != GIGANTIC_BUCKET_SERIALIZATION_VERSION:
        raise GiganticBucketImportError(
            "Unsupported GiganticBucket serializationVersion."
        )
    played = payload.get("playedHacks")
    if not isinstance(played, list):
        raise GiganticBucketImportError("GiganticBucket playedHacks must be a list.")

    hacks = []
    seen_ids = set()
    for index, raw in enumerate(played):
        item = _parse_hack(raw, index)
        if item.hack_id in seen_ids:
            raise GiganticBucketImportError(
                f"GiganticBucket contains duplicate hackId: {item.hack_id}"
            )
        seen_ids.add(item.hack_id)
        hacks.append(item)

    return GiganticBucketImport(
        serialization_version=version,
        hacks=tuple(hacks),
    )


def resolve_giganticbucket_hack_against_catalogue(
    item: GiganticBucketHack,
    matcher: CatalogueMatcher,
) -> GiganticBucketCatalogueResolution:
    """Use direct SMWCHack identity when available, otherwise title matching."""

    identifier = item.smwc_submission_id
    if identifier is not None:
        entry = matcher.get(identifier)
        if entry is None:
            return GiganticBucketCatalogueResolution(
                item=item,
                selected=None,
                suggestion=None,
                confidence=0.0,
                classification="SMWC ID not in current catalogue - review",
                auto_selected=False,
            )
        scored = matcher.score_entry(item.title, identifier)
        score = scored.score if scored is not None else 0.0
        if score >= 0.68:
            return GiganticBucketCatalogueResolution(
                item=item,
                selected=entry,
                suggestion=entry,
                confidence=score,
                classification="GiganticBucket SMWC ID",
                auto_selected=True,
            )
        return GiganticBucketCatalogueResolution(
            item=item,
            selected=None,
            suggestion=entry,
            confidence=score,
            classification="SMWC ID/title conflict - review",
            auto_selected=False,
        )

    result = matcher.find(item.title)
    return GiganticBucketCatalogueResolution(
        item=item,
        selected=result.selected,
        suggestion=result.suggestion,
        confidence=result.confidence,
        classification=result.classification,
        auto_selected=result.auto_selected,
    )


def _parse_hack(value: Any, index: int) -> GiganticBucketHack:
    if not isinstance(value, Mapping):
        raise GiganticBucketImportError(
            f"GiganticBucket playedHacks[{index}] must be an object."
        )
    hack_id = _positive_int(value.get("hackId"), f"playedHacks[{index}].hackId")
    title = _required_text(value.get("title"), f"playedHacks[{index}].title")
    source_kind = _required_text(
        value.get("source"),
        f"playedHacks[{index}].source",
    )
    link_id = _optional_positive_int(
        value.get("link_Id"),
        f"playedHacks[{index}].link_Id",
    )
    creators = _parse_creators(value.get("creators"), index)
    playthroughs = _parse_playthroughs(value.get("playthroughs"), hack_id, index)

    identity = [
        IdentityEvidence(
            kind=IdentityEvidenceKind.SOURCE_RECORD_ID,
            value=str(hack_id),
            source=IngestionSource.GIGANTIC_BUCKET,
            strength=EvidenceStrength.EXACT,
        ),
        IdentityEvidence(
            kind=IdentityEvidenceKind.TITLE,
            value=title,
            source=IngestionSource.GIGANTIC_BUCKET,
            strength=EvidenceStrength.HINT,
        ),
    ]
    # The supplied v1 export shows link_Id aligning with SMWC submission IDs
    # specifically for source == SMWCHack. Other source kinds use link_Id for
    # different purposes and therefore must not be promoted to SMWC identity.
    if source_kind == "SMWCHack" and link_id is not None:
        identity.append(
            IdentityEvidence(
                kind=IdentityEvidenceKind.SMWC_SUBMISSION_ID,
                value=str(link_id),
                source=IngestionSource.GIGANTIC_BUCKET,
                strength=EvidenceStrength.STRONG,
            )
        )

    candidate = CollectionCandidate(
        source=IngestionSource.GIGANTIC_BUCKET,
        title_hints=(title,),
        author_hints=creators,
        identity_evidence=tuple(identity),
        user_history=playthroughs,
        allow_local_only=True,
    )
    return GiganticBucketHack(
        hack_id=hack_id,
        title=title,
        source_kind=source_kind,
        link_id=link_id,
        creators=creators,
        candidate=candidate,
    )


def _parse_creators(value: Any, hack_index: int) -> tuple[str, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise GiganticBucketImportError(
            f"playedHacks[{hack_index}].creators must be a list."
        )
    result = []
    for creator_index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise GiganticBucketImportError(
                f"playedHacks[{hack_index}].creators[{creator_index}] must be an object."
            )
        username = str(raw.get("username") or "").strip()
        if username:
            result.append(username)
    return tuple(result)


def _parse_playthroughs(
    value: Any,
    hack_id: int,
    hack_index: int,
) -> tuple[UserPlaythroughEvidence, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise GiganticBucketImportError(
            f"playedHacks[{hack_index}].playthroughs must be a list."
        )

    result = []
    for play_index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise GiganticBucketImportError(
                f"playedHacks[{hack_index}].playthroughs[{play_index}] must be an object."
            )
        elapsed_text = str(raw.get("time") or "").strip()
        completed_text = str(raw.get("date_Completed") or "").strip()
        result.append(
            UserPlaythroughEvidence(
                source=IngestionSource.GIGANTIC_BUCKET,
                source_record_id=f"{hack_id}:{play_index}",
                category=str(raw.get("category") or "").strip(),
                play_kind=str(raw.get("playKind") or "").strip(),
                icon=str(raw.get("icon") or "").strip(),
                elapsed_text=elapsed_text,
                elapsed_seconds=_parse_elapsed_seconds(elapsed_text),
                version=str(raw.get("version") or "").strip(),
                completed_date_text=completed_text,
                completed_date_iso=_parse_completion_date(completed_text),
                notes=str(raw.get("notes") or "").strip(),
                counts_as_hack=_optional_bool(
                    raw.get("countsAsHack"),
                    f"playedHacks[{hack_index}].playthroughs[{play_index}].countsAsHack",
                    default=False,
                ),
                exit_count=_optional_nonnegative_int(
                    raw.get("exitCount"),
                    "GiganticBucket playthrough exitCount",
                ),
                duration_milliseconds=_optional_nonnegative_int(
                    raw.get("durationMilliseconds"),
                    "GiganticBucket playthrough durationMilliseconds",
                ),
                duration_precision=str(raw.get("durationPrecision") or "").strip(),
            )
        )
    return tuple(result)


def _parse_elapsed_seconds(value: str) -> int | None:
    if not value:
        return None
    parts = value.split(":")
    if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
        return None
    numbers = [int(part) for part in parts]
    if any(part < 0 for part in numbers):
        return None
    if numbers[-1] >= 60 or numbers[-2] >= 60:
        return None
    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds


def _parse_completion_date(value: str) -> str:
    if not value:
        return ""
    for pattern in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            continue
    return ""


def _loads_json(data: bytes) -> Any:
    text = data.decode("utf-8-sig")

    def reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise GiganticBucketImportError(
                    f"Duplicate GiganticBucket JSON object key: {key}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise GiganticBucketImportError(
            f"GiganticBucket JSON contains non-finite number: {value}"
        )

    return json.loads(
        text,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GiganticBucketImportError(f"{label} must be non-empty text.")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise GiganticBucketImportError(f"{label} must be a positive integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise GiganticBucketImportError(f"{label} must be a positive integer.") from error
    if result <= 0:
        raise GiganticBucketImportError(f"{label} must be a positive integer.")
    return result


def _optional_positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, label)


def _optional_nonnegative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise GiganticBucketImportError(f"{label} must be a non-negative integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise GiganticBucketImportError(f"{label} must be a non-negative integer.") from error
    if result < 0:
        raise GiganticBucketImportError(f"{label} must be a non-negative integer.")
    return result


def _optional_bool(value: Any, label: str, *, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise GiganticBucketImportError(f"{label} must be boolean.")
    return value


__all__ = [
    "GIGANTIC_BUCKET_MAX_BYTES",
    "GIGANTIC_BUCKET_SERIALIZATION_VERSION",
    "GiganticBucketCatalogueResolution",
    "GiganticBucketHack",
    "GiganticBucketImport",
    "GiganticBucketImportError",
    "load_giganticbucket_export",
    "parse_giganticbucket_export",
    "resolve_giganticbucket_hack_against_catalogue",
]
