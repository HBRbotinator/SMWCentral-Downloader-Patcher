"""KaizOFF public catalogue adapter with validated stale-cache fallback."""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse

from collection_ingestion import (
    CollectionCandidate,
    EvidenceStrength,
    IdentityEvidence,
    IdentityEvidenceKind,
    IngestionSource,
    SharedMetadataEvidence,
)
from rom_title_matching import CatalogueEntry


KAIZOFF_PUBLIC_BASE_URL = "https://kaizoff.com/api/public/v1"
KAIZOFF_INDEX_URL = f"{KAIZOFF_PUBLIC_BASE_URL}/hacks/index"
KAIZOFF_LIST_URL = f"{KAIZOFF_PUBLIC_BASE_URL}/hacks"
KAIZOFF_DETAIL_URL_TEMPLATE = f"{KAIZOFF_PUBLIC_BASE_URL}/hacks/{{id}}"
DEFAULT_INDEX_MAX_AGE_SECONDS = 6 * 60 * 60
DEFAULT_CATALOGUE_MAX_AGE_SECONDS = 6 * 60 * 60
DEFAULT_DETAIL_MAX_AGE_SECONDS = 24 * 60 * 60
PUBLIC_CATALOGUE_PAGE_SIZE = 500
MAX_PUBLIC_CATALOGUE_PAGES = 100
MAX_KAIZOFF_RESPONSE_BYTES = 8 * 1024 * 1024


class KaizOffProviderError(RuntimeError):
    """Raised when public KaizOFF catalogue data cannot be used safely."""


@dataclass(frozen=True)
class KaizOffIndexSnapshot:
    """One validated lightweight catalogue snapshot."""

    entries: tuple[CatalogueEntry, ...]
    fetched_at: float
    source: str
    stale: bool


@dataclass(frozen=True)
class KaizOffCatalogueSnapshot:
    """One validated full public catalogue snapshot."""

    records: tuple["KaizOffHackMetadata", ...]
    fetched_at: float
    source: str
    stale: bool


@dataclass(frozen=True)
class KaizOffHackMetadata:
    """Validated rich metadata for one SMWCentral submission."""

    smwc_submission_id: int
    title: str
    authors: tuple[str, ...]
    tags: tuple[str, ...]
    image_urls: tuple[str, ...]
    rating: float | None
    size_bytes: int | None
    downloads: int | None
    download_url: str
    release_timestamp: int | None
    difficulty: str
    hack_types: tuple[str, ...]
    exits: int | None
    demo: bool | None
    hall_of_fame: bool | None
    sa1_compatible: bool | None
    collaboration: bool | None
    description: str
    active: bool | None
    last_fetched: str
    obsoleted_by_submission_id: int | None
    difficulty_id: str = ""
    moderated: bool | None = None

    def as_catalogue_entry(self) -> CatalogueEntry:
        return CatalogueEntry(
            smwc_submission_id=self.smwc_submission_id,
            title=self.title,
            difficulty=self.difficulty,
            hack_type=", ".join(self.hack_types),
            exits=self.exits,
            authors=self.authors,
        )

    def as_candidate(self) -> CollectionCandidate:
        metadata = SharedMetadataEvidence(
            source=IngestionSource.KAIZOFF,
            title=self.title,
            authors=self.authors,
            difficulty=self.difficulty,
            hack_types=self.hack_types,
            exits=self.exits,
            release_timestamp=self.release_timestamp,
            rating=self.rating,
            hall_of_fame=self.hall_of_fame,
            sa1_compatible=self.sa1_compatible,
            collaboration=self.collaboration,
            demo=self.demo,
            description=self.description,
            tags=self.tags,
            image_urls=self.image_urls,
            download_url=self.download_url,
            active=self.active,
            # Informational only. No version/latest inference is made from it.
            obsoleted_by_submission_id=self.obsoleted_by_submission_id,
        )
        return CollectionCandidate(
            source=IngestionSource.KAIZOFF,
            title_hints=(self.title,),
            author_hints=self.authors,
            identity_evidence=(
                IdentityEvidence(
                    kind=IdentityEvidenceKind.SMWC_SUBMISSION_ID,
                    value=str(self.smwc_submission_id),
                    source=IngestionSource.KAIZOFF,
                    strength=EvidenceStrength.EXACT,
                ),
            ),
            shared_metadata=(metadata,),
        )


@dataclass(frozen=True)
class KaizOffDetailSnapshot:
    """One validated rich metadata snapshot."""

    metadata: KaizOffHackMetadata
    fetched_at: float
    source: str
    stale: bool


FetchJson = Callable[[str, float], Any]


class KaizOffCatalogueProvider:
    """Use cached public Index, per-ID detail, and paginated rich catalogue APIs."""

    def __init__(
        self,
        *,
        cache_dir: str | Path | None = None,
        fetch_json: FetchJson | None = None,
        timeout_seconds: float = 20.0,
        index_max_age_seconds: float = DEFAULT_INDEX_MAX_AGE_SECONDS,
        detail_max_age_seconds: float = DEFAULT_DETAIL_MAX_AGE_SECONDS,
        catalogue_max_age_seconds: float = DEFAULT_CATALOGUE_MAX_AGE_SECONDS,
    ):
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if (
            index_max_age_seconds < 0
            or detail_max_age_seconds < 0
            or catalogue_max_age_seconds < 0
        ):
            raise ValueError("cache max age must be non-negative.")

        self.cache_dir = (
            Path(cache_dir).expanduser().resolve()
            if cache_dir is not None
            else None
        )
        self.fetch_json = fetch_json or _http_get_json
        self.timeout_seconds = float(timeout_seconds)
        self.index_max_age_seconds = float(index_max_age_seconds)
        self.detail_max_age_seconds = float(detail_max_age_seconds)
        self.catalogue_max_age_seconds = float(catalogue_max_age_seconds)
        self._memory_index: tuple[Any, float] | None = None
        self._memory_catalogue: tuple[Any, float] | None = None
        self._memory_catalogue_records: tuple[KaizOffHackMetadata, ...] | None = None
        self._memory_details: dict[int, tuple[Any, float]] = {}

    def get_index(self, *, force_refresh: bool = False) -> KaizOffIndexSnapshot:
        """Return all lightweight hacks from one Index call when refresh is needed."""

        memory = self._memory_index
        if memory is not None and not force_refresh:
            payload, fetched_at = memory
            if _is_fresh(fetched_at, self.index_max_age_seconds):
                return KaizOffIndexSnapshot(
                    entries=_parse_index_payload(payload),
                    fetched_at=fetched_at,
                    source="memory",
                    stale=False,
                )

        cache = self._read_cache(self._index_cache_path())
        if cache is not None and not force_refresh:
            payload, fetched_at = cache
            try:
                entries = _parse_index_payload(payload)
            except KaizOffProviderError:
                cache = None
            else:
                if _is_fresh(fetched_at, self.index_max_age_seconds):
                    self._memory_index = (payload, fetched_at)
                    return KaizOffIndexSnapshot(
                        entries=entries,
                        fetched_at=fetched_at,
                        source="disk_cache",
                        stale=False,
                    )

        try:
            payload = self.fetch_json(KAIZOFF_INDEX_URL, self.timeout_seconds)
            entries = _parse_index_payload(payload)
        except Exception as error:
            stale = self._validated_stale_index(memory, cache)
            if stale is not None:
                return stale
            if isinstance(error, KaizOffProviderError):
                raise
            raise KaizOffProviderError(
                "KaizOFF Index request failed and no valid cached catalogue is available."
            ) from error

        fetched_at = time.time()
        self._memory_index = (payload, fetched_at)
        self._write_cache(self._index_cache_path(), payload)
        return KaizOffIndexSnapshot(
            entries=entries,
            fetched_at=fetched_at,
            source="network",
            stale=False,
        )

    def get_catalogue(self, *, force_refresh: bool = False) -> KaizOffCatalogueSnapshot:
        """Return the full active SMWC catalogue from KaizOFF public pages.

        KaizOFF deliberately exposes this no-auth, cached endpoint for clients that
        need rich catalogue filtering locally.  The complete validated payload is
        cached as one snapshot so callers do not repeatedly walk every page.
        """

        memory = self._memory_catalogue
        if memory is not None and not force_refresh:
            payload, fetched_at = memory
            if _is_fresh(fetched_at, self.catalogue_max_age_seconds):
                records = self._memory_catalogue_records
                if records is None:
                    records = _parse_catalogue_payload(payload)
                    self._memory_catalogue_records = records
                return KaizOffCatalogueSnapshot(
                    records=records,
                    fetched_at=fetched_at,
                    source="memory",
                    stale=False,
                )

        cache = self._read_cache(self._catalogue_cache_path())
        if cache is not None and not force_refresh:
            payload, fetched_at = cache
            try:
                records = _parse_catalogue_payload(payload)
            except KaizOffProviderError:
                cache = None
            else:
                if _is_fresh(fetched_at, self.catalogue_max_age_seconds):
                    self._memory_catalogue = (payload, fetched_at)
                    self._memory_catalogue_records = records
                    return KaizOffCatalogueSnapshot(
                        records=records,
                        fetched_at=fetched_at,
                        source="disk_cache",
                        stale=False,
                    )

        try:
            rows = []
            seen_ids = set()
            page = 1
            while True:
                if page > MAX_PUBLIC_CATALOGUE_PAGES:
                    raise KaizOffProviderError(
                        "KaizOFF public catalogue exceeded the safety page limit."
                    )
                url = (
                    f"{KAIZOFF_LIST_URL}?page={page}"
                    f"&limit={PUBLIC_CATALOGUE_PAGE_SIZE}"
                )
                page_payload = self.fetch_json(url, self.timeout_seconds)
                page_rows, has_more = _parse_catalogue_page(page_payload, page)
                for row in page_rows:
                    identifier = _positive_int(row.get("id"), "KaizOFF hack ID")
                    if identifier in seen_ids:
                        raise KaizOffProviderError(
                            "KaizOFF public catalogue contains duplicate SMWC submission IDs."
                        )
                    seen_ids.add(identifier)
                    rows.append(row)
                if not has_more:
                    break
                page += 1
            payload = {"data": rows, "count": len(rows)}
            records = _parse_catalogue_payload(payload)
        except Exception as error:
            stale = self._validated_stale_catalogue(memory, cache)
            if stale is not None:
                return stale
            if isinstance(error, KaizOffProviderError):
                raise
            raise KaizOffProviderError(
                "KaizOFF public catalogue request failed and no valid cached catalogue is available."
            ) from error

        fetched_at = time.time()
        self._memory_catalogue = (payload, fetched_at)
        self._memory_catalogue_records = records
        self._write_cache(self._catalogue_cache_path(), payload)
        return KaizOffCatalogueSnapshot(
            records=records,
            fetched_at=fetched_at,
            source="network",
            stale=False,
        )

    def get_hack(
        self,
        smwc_submission_id: int,
        *,
        force_refresh: bool = False,
    ) -> KaizOffDetailSnapshot:
        """Fetch/cache rich metadata for one already-known SMWC submission ID."""

        identifier = _positive_int(smwc_submission_id, "SMWC submission ID")
        memory = self._memory_details.get(identifier)
        if memory is not None and not force_refresh:
            payload, fetched_at = memory
            if _is_fresh(fetched_at, self.detail_max_age_seconds):
                return KaizOffDetailSnapshot(
                    metadata=_parse_detail_payload(payload, identifier),
                    fetched_at=fetched_at,
                    source="memory",
                    stale=False,
                )

        cache = self._read_cache(self._detail_cache_path(identifier))
        if cache is not None and not force_refresh:
            payload, fetched_at = cache
            try:
                metadata = _parse_detail_payload(payload, identifier)
            except KaizOffProviderError:
                cache = None
            else:
                if _is_fresh(fetched_at, self.detail_max_age_seconds):
                    self._memory_details[identifier] = (payload, fetched_at)
                    return KaizOffDetailSnapshot(
                        metadata=metadata,
                        fetched_at=fetched_at,
                        source="disk_cache",
                        stale=False,
                    )

        url = KAIZOFF_DETAIL_URL_TEMPLATE.format(id=identifier)
        try:
            payload = self.fetch_json(url, self.timeout_seconds)
            metadata = _parse_detail_payload(payload, identifier)
        except Exception as error:
            stale = self._validated_stale_detail(identifier, memory, cache)
            if stale is not None:
                return stale
            if isinstance(error, KaizOffProviderError):
                raise
            raise KaizOffProviderError(
                "KaizOFF hack-detail request failed and no valid cached metadata is available."
            ) from error

        fetched_at = time.time()
        self._memory_details[identifier] = (payload, fetched_at)
        self._write_cache(self._detail_cache_path(identifier), payload)
        return KaizOffDetailSnapshot(
            metadata=metadata,
            fetched_at=fetched_at,
            source="network",
            stale=False,
        )

    def _validated_stale_index(
        self,
        memory: tuple[Any, float] | None,
        cache: tuple[Any, float] | None,
    ) -> KaizOffIndexSnapshot | None:
        for source, candidate in (("memory", memory), ("disk_cache", cache)):
            if candidate is None:
                continue
            payload, fetched_at = candidate
            try:
                entries = _parse_index_payload(payload)
            except KaizOffProviderError:
                continue
            self._memory_index = (payload, fetched_at)
            return KaizOffIndexSnapshot(
                entries=entries,
                fetched_at=fetched_at,
                source=source,
                stale=True,
            )
        return None

    def _validated_stale_catalogue(
        self,
        memory: tuple[Any, float] | None,
        cache: tuple[Any, float] | None,
    ) -> KaizOffCatalogueSnapshot | None:
        for source, candidate in (("memory", memory), ("disk_cache", cache)):
            if candidate is None:
                continue
            payload, fetched_at = candidate
            try:
                records = _parse_catalogue_payload(payload)
            except KaizOffProviderError:
                continue
            self._memory_catalogue = (payload, fetched_at)
            self._memory_catalogue_records = records
            return KaizOffCatalogueSnapshot(
                records=records,
                fetched_at=fetched_at,
                source=source,
                stale=True,
            )
        return None

    def _validated_stale_detail(
        self,
        identifier: int,
        memory: tuple[Any, float] | None,
        cache: tuple[Any, float] | None,
    ) -> KaizOffDetailSnapshot | None:
        for source, candidate in (("memory", memory), ("disk_cache", cache)):
            if candidate is None:
                continue
            payload, fetched_at = candidate
            try:
                metadata = _parse_detail_payload(payload, identifier)
            except KaizOffProviderError:
                continue
            self._memory_details[identifier] = (payload, fetched_at)
            return KaizOffDetailSnapshot(
                metadata=metadata,
                fetched_at=fetched_at,
                source=source,
                stale=True,
            )
        return None

    def _index_cache_path(self) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / "kaizoff_hacks_index.json"

    def _catalogue_cache_path(self) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / "kaizoff_hacks_catalogue.json"

    def _detail_cache_path(self, identifier: int) -> Path | None:
        if self.cache_dir is None:
            return None
        return self.cache_dir / "kaizoff_hacks" / f"{identifier}.json"

    @staticmethod
    def _read_cache(path: Path | None) -> tuple[Any, float] | None:
        if path is None or not path.is_file():
            return None
        try:
            payload = _loads_json(path.read_bytes())
            return payload, path.stat().st_mtime
        except (OSError, UnicodeError, ValueError, KaizOffProviderError):
            return None

    @staticmethod
    def _write_cache(path: Path | None, payload: Any) -> None:
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = None
        temp_path = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=f"{path.name}.",
                suffix=".tmp",
                dir=path.parent,
            )
            temp_path = Path(raw_path)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                descriptor = None
                json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            temp_path = None
        except OSError:
            # Cache persistence must never turn valid network data into failure.
            pass
        finally:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


def _http_get_json(url: str, timeout_seconds: float) -> Any:
    """Bound one public unauthenticated HTTPS response before JSON parsing."""

    if not (
        url == KAIZOFF_INDEX_URL
        or url == KAIZOFF_LIST_URL
        or url.startswith(f"{KAIZOFF_LIST_URL}?")
        or url.startswith(f"{KAIZOFF_PUBLIC_BASE_URL}/hacks/")
    ):
        raise KaizOffProviderError("KaizOFF transport refused an unexpected URL.")

    import requests

    try:
        with requests.get(
            url,
            timeout=timeout_seconds,
            stream=True,
            headers={"User-Agent": "SMWC-Downloader-Patcher"},
        ) as response:
            response.raise_for_status()
            length = response.headers.get("Content-Length")
            if length is not None:
                try:
                    if int(length) > MAX_KAIZOFF_RESPONSE_BYTES:
                        raise KaizOffProviderError("KaizOFF response is too large.")
                except ValueError:
                    pass

            body = bytearray()
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > MAX_KAIZOFF_RESPONSE_BYTES:
                    raise KaizOffProviderError("KaizOFF response is too large.")
    except KaizOffProviderError:
        raise
    except requests.RequestException as error:
        raise KaizOffProviderError("KaizOFF public API request failed.") from error

    try:
        return _loads_json(bytes(body))
    except (UnicodeError, ValueError) as error:
        raise KaizOffProviderError("KaizOFF returned invalid JSON.") from error


def _loads_json(data: bytes) -> Any:
    text = data.decode("utf-8-sig")

    def reject_duplicates(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise KaizOffProviderError(
                    f"KaizOFF JSON contains duplicate object key: {key}"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise KaizOffProviderError(
            f"KaizOFF JSON contains non-finite number: {value}"
        )

    return json.loads(
        text,
        object_pairs_hook=reject_duplicates,
        parse_constant=reject_constant,
    )


def _parse_index_payload(payload: Any) -> tuple[CatalogueEntry, ...]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise KaizOffProviderError("KaizOFF Index payload is malformed.")

    entries = []
    seen = set()
    for raw in payload["data"]:
        if not isinstance(raw, Mapping):
            raise KaizOffProviderError("KaizOFF Index contains a malformed hack row.")
        try:
            entry = CatalogueEntry.from_mapping(raw)
        except (TypeError, ValueError) as error:
            raise KaizOffProviderError("KaizOFF Index contains invalid hack metadata.") from error
        if entry.smwc_submission_id in seen:
            raise KaizOffProviderError(
                "KaizOFF Index contains duplicate SMWC submission IDs."
            )
        seen.add(entry.smwc_submission_id)
        entries.append(entry)

    count = payload.get("count")
    if count is not None:
        if isinstance(count, bool) or not isinstance(count, int) or count != len(entries):
            raise KaizOffProviderError(
                "KaizOFF Index count does not match the returned catalogue."
            )
    return tuple(entries)


def _parse_detail_payload(payload: Any, requested_id: int) -> KaizOffHackMetadata:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), Mapping):
        raise KaizOffProviderError("KaizOFF hack-detail payload is malformed.")
    return _parse_hack_record(payload["data"], requested_id=requested_id)


def _parse_hack_record(
    data: Mapping[str, Any],
    *,
    requested_id: int | None = None,
) -> KaizOffHackMetadata:
    identifier = _positive_int(data.get("id"), "KaizOFF hack ID")
    if requested_id is not None and identifier != requested_id:
        raise KaizOffProviderError(
            "KaizOFF hack-detail response ID does not match the requested submission."
        )

    title = _required_text(data.get("name"), "KaizOFF hack name")
    section = data.get("section")
    if section not in (None, "smwhacks"):
        raise KaizOffProviderError("KaizOFF hack-detail section is not smwhacks.")

    raw_fields = data.get("raw_fields")
    if raw_fields is not None and not isinstance(raw_fields, Mapping):
        raise KaizOffProviderError("KaizOFF raw_fields must be an object.")
    raw_fields = raw_fields or {}

    authors = _names_from_objects(data.get("authors"), "authors")
    tags = _text_sequence(data.get("tags"), "tags")
    image_urls = _https_urls(data.get("images"), "images", expected_host="dl.smwcentral.net")
    download_url = _download_url(data.get("download_url"))

    raw_types = raw_fields.get("type")
    if isinstance(raw_types, list):
        hack_types = tuple(
            _normalize_hack_type(item)
            for item in raw_types
            if str(item).strip()
        )
    else:
        normalized_type = str(data.get("type") or "").strip()
        hack_types = tuple(
            _normalize_hack_type(item)
            for item in normalized_type.split(",")
            if item.strip()
        )

    exits = _optional_nonnegative_int(
        raw_fields.get("length", data.get("exits")),
        "KaizOFF exits",
    )
    rating = _optional_rating(data.get("rating"))
    obsoleted_by = _optional_positive_int(
        data.get("obsoleted_by"),
        "KaizOFF obsoleted_by",
    )

    return KaizOffHackMetadata(
        smwc_submission_id=identifier,
        title=title,
        authors=authors,
        tags=tags,
        image_urls=image_urls,
        rating=rating,
        size_bytes=_optional_nonnegative_int(data.get("size"), "KaizOFF size"),
        downloads=_optional_nonnegative_int(
            data.get("downloads"),
            "KaizOFF downloads",
        ),
        download_url=download_url,
        release_timestamp=_optional_nonnegative_int(
            data.get("time"),
            "KaizOFF release timestamp",
        ),
        difficulty=str(data.get("difficulty") or "").strip(),
        hack_types=hack_types,
        exits=exits,
        demo=_optional_bool(data.get("demo"), "KaizOFF demo"),
        hall_of_fame=_optional_bool(data.get("hof"), "KaizOFF hof"),
        sa1_compatible=_optional_bool(data.get("sa1"), "KaizOFF sa1"),
        collaboration=_optional_bool(data.get("collab"), "KaizOFF collab"),
        description=str(data.get("description") or ""),
        active=_optional_bool(data.get("active"), "KaizOFF active"),
        last_fetched=str(data.get("last_fetched") or "").strip(),
        obsoleted_by_submission_id=obsoleted_by,
        difficulty_id=str(raw_fields.get("difficulty") or "").strip(),
        moderated=_optional_bool(data.get("moderated"), "KaizOFF moderated"),
    )


def _parse_catalogue_page(
    payload: Any, expected_page: int
) -> tuple[tuple[Mapping[str, Any], ...], bool]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise KaizOffProviderError("KaizOFF public catalogue page is malformed.")
    pagination = payload.get("pagination")
    if not isinstance(pagination, Mapping):
        raise KaizOffProviderError("KaizOFF public catalogue pagination is malformed.")
    page = pagination.get("page")
    if isinstance(page, bool) or page != expected_page:
        raise KaizOffProviderError("KaizOFF public catalogue returned an unexpected page.")
    has_more = pagination.get("has_more")
    if not isinstance(has_more, bool):
        raise KaizOffProviderError("KaizOFF public catalogue has invalid has_more metadata.")
    rows = []
    for row in payload["data"]:
        if not isinstance(row, Mapping):
            raise KaizOffProviderError("KaizOFF public catalogue contains a malformed hack row.")
        # Validate each full row before accepting the page.
        _parse_hack_record(row)
        rows.append(row)
    if has_more and not rows:
        raise KaizOffProviderError("KaizOFF public catalogue pagination made no progress.")
    return tuple(rows), has_more


def _parse_catalogue_payload(payload: Any) -> tuple[KaizOffHackMetadata, ...]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        raise KaizOffProviderError("KaizOFF cached public catalogue is malformed.")
    records = []
    seen = set()
    for row in payload["data"]:
        if not isinstance(row, Mapping):
            raise KaizOffProviderError("KaizOFF cached public catalogue contains a malformed row.")
        metadata = _parse_hack_record(row)
        if metadata.smwc_submission_id in seen:
            raise KaizOffProviderError(
                "KaizOFF cached public catalogue contains duplicate SMWC submission IDs."
            )
        seen.add(metadata.smwc_submission_id)
        records.append(metadata)
    count = payload.get("count")
    if count is not None and (
        isinstance(count, bool) or not isinstance(count, int) or count != len(records)
    ):
        raise KaizOffProviderError(
            "KaizOFF cached public catalogue count does not match the returned catalogue."
        )
    return tuple(records)


def _names_from_objects(value: Any, label: str) -> tuple[str, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise KaizOffProviderError(f"KaizOFF {label} must be a list.")
    result = []
    for item in value:
        if not isinstance(item, Mapping):
            raise KaizOffProviderError(f"KaizOFF {label} contains a malformed item.")
        name = str(item.get("name") or "").strip()
        if name:
            result.append(name)
    return tuple(result)


def _text_sequence(value: Any, label: str) -> tuple[str, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise KaizOffProviderError(f"KaizOFF {label} must be a list.")
    result = []
    for item in value:
        if not isinstance(item, str):
            raise KaizOffProviderError(f"KaizOFF {label} must contain strings.")
        text = item.strip()
        if text:
            result.append(text)
    return tuple(result)


def _https_urls(value: Any, label: str, *, expected_host: str) -> tuple[str, ...]:
    if value in (None, []):
        return ()
    if not isinstance(value, list):
        raise KaizOffProviderError(f"KaizOFF {label} must be a list.")
    result = []
    for item in value:
        url = str(item or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != expected_host:
            raise KaizOffProviderError(f"KaizOFF {label} contains an unexpected URL.")
        result.append(url)
    return tuple(result)


def _download_url(value: Any) -> str:
    if value in (None, ""):
        return ""
    url = str(value).strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != "dl.smwcentral.net":
        raise KaizOffProviderError("KaizOFF download URL is not an expected SMWC URL.")
    return url


def _normalize_hack_type(value: Any) -> str:
    return str(value).strip().casefold().replace("-", "_").replace(" ", "_")


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise KaizOffProviderError(f"{label} must be non-empty text.")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise KaizOffProviderError(f"{label} must be a positive integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise KaizOffProviderError(f"{label} must be a positive integer.") from error
    if result <= 0:
        raise KaizOffProviderError(f"{label} must be a positive integer.")
    return result


def _optional_positive_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    return _positive_int(value, label)


def _optional_nonnegative_int(value: Any, label: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise KaizOffProviderError(f"{label} must be a non-negative integer.")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise KaizOffProviderError(f"{label} must be a non-negative integer.") from error
    if result < 0:
        raise KaizOffProviderError(f"{label} must be a non-negative integer.")
    return result


def _optional_rating(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise KaizOffProviderError("KaizOFF rating must be between 0 and 5.")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise KaizOffProviderError("KaizOFF rating must be between 0 and 5.") from error
    if not 0 <= result <= 5:
        raise KaizOffProviderError("KaizOFF rating must be between 0 and 5.")
    return result


def _optional_bool(value: Any, label: str) -> bool | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise KaizOffProviderError(f"{label} must be boolean.")
    return value


def _is_fresh(fetched_at: float, max_age_seconds: float) -> bool:
    return max(0.0, time.time() - fetched_at) <= max_age_seconds


__all__ = [
    "DEFAULT_CATALOGUE_MAX_AGE_SECONDS",
    "DEFAULT_DETAIL_MAX_AGE_SECONDS",
    "DEFAULT_INDEX_MAX_AGE_SECONDS",
    "KAIZOFF_DETAIL_URL_TEMPLATE",
    "KAIZOFF_INDEX_URL",
    "KAIZOFF_LIST_URL",
    "KAIZOFF_PUBLIC_BASE_URL",
    "KaizOffCatalogueProvider",
    "KaizOffCatalogueSnapshot",
    "KaizOffDetailSnapshot",
    "KaizOffHackMetadata",
    "KaizOffIndexSnapshot",
    "KaizOffProviderError",
    "MAX_KAIZOFF_RESPONSE_BYTES",
]
