"""KaizOFF-first catalogue lookup for Save Data Sync orphan resolution."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable

import save_sync
from kaizoff_provider import KaizOffCatalogueProvider, KaizOffProviderError
from rom_title_matching import CatalogueEntry, CatalogueMatcher


BULK_RICH_DETAIL_THRESHOLD = 25


class SaveSyncCatalogueLookup:
    """Share one KaizOFF catalogue snapshot across a Save Data Sync review.

    Automatic checked-row resolution never falls back to many direct SMWCentral
    requests.  Explicit manual search/selection may use one direct SMWCentral
    request when KaizOFF cannot supply the catalogue or selected rich metadata.
    """

    def __init__(
        self,
        *,
        processed_json_path: str | Path | None = None,
        provider: KaizOffCatalogueProvider | None = None,
        fallback_fetch_fn: Callable[..., Any] | None = None,
        log: Callable[..., Any] | None = None,
    ):
        if provider is None:
            cache_dir = None
            if processed_json_path:
                processed = Path(processed_json_path).expanduser().absolute()
                cache_dir = processed.with_name("kaizoff_cache")
            provider = KaizOffCatalogueProvider(cache_dir=cache_dir)
        self.provider = provider
        self.fallback_fetch_fn = fallback_fetch_fn
        self.log = log
        self._entries: tuple[CatalogueEntry, ...] | None = None
        self._index_error: Exception | None = None
        self._fallback_announced = False
        self._bulk_details: dict[int, Any] = {}

    def _write_log(self, message: str, level: str = "Information") -> None:
        if not self.log:
            return
        try:
            self.log(message, level)
        except TypeError:
            self.log(message)

    def _index(self) -> tuple[CatalogueEntry, ...]:
        if self._entries is not None:
            return self._entries
        if self._index_error is not None:
            raise KaizOffProviderError(str(self._index_error))
        try:
            snapshot = self.provider.get_index()
        except Exception as exc:
            self._index_error = exc
            if isinstance(exc, KaizOffProviderError):
                raise
            raise KaizOffProviderError("KaizOFF catalogue lookup failed.") from exc
        self._entries = tuple(snapshot.entries)
        stale = " stale-cache" if snapshot.stale else ""
        self._write_log(
            f"Save Data Sync loaded {len(self._entries)} SMWC catalogue rows "
            f"from KaizOFF ({snapshot.source}{stale}).",
            "Debug",
        )
        return self._entries

    def resolve_automatic(self, save_name: str, existing_ids: Iterable[str]) -> dict:
        """Resolve one save through the shared KaizOFF Index and calibrated matcher.

        Only matcher results already classified as safe automatic selections are
        hydrated and resolved. Plausible abbreviation/partial/fuzzy results are
        returned as review-only suggestions without any rich-detail request.
        Direct SMWCentral fallback remains disabled for this bulk path.
        """

        query = save_sync.make_search_query(save_name)
        if not query:
            return self._resolution(save_sync.RESOLUTION_NO_MATCH)
        try:
            entries = self._index()
        except KaizOffProviderError as exc:
            self._write_log(
                "KaizOFF catalogue is unavailable for Save Data Sync bulk lookup; "
                "direct SMWCentral fallback was not started to avoid rate limiting. "
                "Use manual search for an explicit fallback lookup.",
                "Warning",
            )
            return self._resolution(
                save_sync.RESOLUTION_ERROR,
                catalogue_unavailable=True,
                error=str(exc),
            )

        matcher = CatalogueMatcher(entries)
        return self._resolve_automatic_with_matcher(
            save_name, existing_ids, matcher, query=query
        )

    def _resolve_automatic_with_matcher(
        self,
        save_name: str,
        existing_ids: Iterable[str],
        matcher: CatalogueMatcher,
        *,
        query: str | None = None,
    ) -> dict:
        query = query if query is not None else save_sync.make_search_query(save_name)
        if not query:
            return self._resolution(save_sync.RESOLUTION_NO_MATCH)
        match = matcher.find(query)

        # Preserve the established duplicate-exact-title behavior: if the only
        # ambiguity is multiple identical title rows, rich active/obsolete state
        # may safely identify one current submission.
        exact_rows = tuple(
            ranked.entry for ranked in match.ranked if ranked.exact
        )
        if match.classification == "Ambiguous" and len(exact_rows) > 1:
            hydrated = []
            for entry in exact_rows:
                try:
                    hydrated.append(
                        self._legacy_hack(
                            self._detail_metadata(entry.smwc_submission_id)
                        )
                    )
                except Exception as exc:
                    self._write_log(
                        f"KaizOFF detail lookup failed for SMWC "
                        f"{entry.smwc_submission_id}: {exc}",
                        "Error",
                    )
                    return self._resolution(save_sync.RESOLUTION_ERROR, error=str(exc))
            live = [
                hack
                for hack in hydrated
                if not (hack.get("raw_fields", {}) or {}).get("obsolete")
            ]
            if len(live) == 1:
                return self._resolved_hack(live[0], existing_ids)

        if match.auto_selected and match.selected is not None:
            try:
                hack = self._legacy_hack(
                    self._detail_metadata(match.selected.smwc_submission_id)
                )
            except Exception as exc:
                self._write_log(
                    f"KaizOFF detail lookup failed for SMWC "
                    f"{match.selected.smwc_submission_id}: {exc}",
                    "Error",
                )
                return self._resolution(save_sync.RESOLUTION_ERROR, error=str(exc))
            result = self._resolved_hack(hack, existing_ids)
            result.update(
                match_classification=match.classification,
                match_confidence=float(match.confidence),
                match_margin=float(match.margin),
            )
            return result

        if match.suggestion is not None and match.classification != "Unmatched":
            suggestion = self._suggestion_payload(match)
            self._write_log(
                f"Save Data Sync suggests SMWC {suggestion['hack_id']} "
                f"'{suggestion['title']}' for '{save_name}' "
                f"({match.classification}, {match.confidence:.0%}); review required.",
                "Debug",
            )
            return self._resolution(
                save_sync.RESOLUTION_REVIEW,
                suggestion=suggestion,
                match_classification=match.classification,
                match_confidence=float(match.confidence),
                match_margin=float(match.margin),
            )

        return self._resolution(
            save_sync.RESOLUTION_NO_MATCH,
            match_classification=match.classification,
            match_confidence=float(match.confidence),
            match_margin=float(match.margin),
        )

    def resolve_automatic_many(
        self,
        save_names: Iterable[str],
        existing_ids: Iterable[str],
        *,
        bulk_detail_threshold: int = BULK_RICH_DETAIL_THRESHOLD,
    ) -> tuple[dict, ...]:
        """Resolve a scan batch through one frozen KaizOFF Index snapshot.

        Matching itself is local.  When more than ``bulk_detail_threshold``
        distinct safe/duplicate-exact matches need rich metadata, prime those
        details from KaizOFF's paginated rich catalogue once instead of issuing
        dozens of singular detail requests.  Missing catalogue rows (for
        example obsolete submissions) still fall back to KaizOFF per-ID detail.
        Direct SMWCentral fallback remains disabled for this automatic path.
        """

        names = tuple(str(name or "") for name in save_names)
        existing = {str(value) for value in existing_ids}
        if not names:
            return ()
        try:
            entries = self._index()
        except KaizOffProviderError as exc:
            self._write_log(
                "KaizOFF catalogue is unavailable for Save Data Sync automatic scan lookup; "
                "direct SMWCentral fallback was not started to avoid rate limiting. "
                "Use manual search for an explicit fallback lookup.",
                "Warning",
            )
            return tuple(
                self._resolution(
                    save_sync.RESOLUTION_ERROR,
                    catalogue_unavailable=True,
                    error=str(exc),
                )
                for _name in names
            )

        matcher = CatalogueMatcher(entries)
        detail_ids: set[int] = set()
        for save_name in names:
            query = save_sync.make_search_query(save_name)
            if not query:
                continue
            match = matcher.find(query)
            exact_rows = tuple(ranked.entry for ranked in match.ranked if ranked.exact)
            if match.classification == "Ambiguous" and len(exact_rows) > 1:
                detail_ids.update(entry.smwc_submission_id for entry in exact_rows)
            elif match.auto_selected and match.selected is not None:
                detail_ids.add(match.selected.smwc_submission_id)

        threshold = max(1, int(bulk_detail_threshold))
        if len(detail_ids) > threshold:
            self._prime_bulk_details(detail_ids)

        return tuple(
            self._resolve_automatic_with_matcher(name, existing, matcher)
            for name in names
        )

    def _prime_bulk_details(self, identifiers: Iterable[int]) -> None:
        wanted = {int(identifier) for identifier in identifiers}
        if not wanted:
            return
        try:
            snapshot = self.provider.get_catalogue()
        except Exception as exc:
            self._write_log(
                f"KaizOFF bulk catalogue hydration failed; falling back to "
                f"per-hack KaizOFF details: {exc}",
                "Warning",
            )
            return

        loaded = 0
        for metadata in snapshot.records:
            identifier = int(metadata.smwc_submission_id)
            if identifier in wanted:
                self._bulk_details[identifier] = metadata
                loaded += 1
        stale = " stale-cache" if snapshot.stale else ""
        self._write_log(
            f"Save Data Sync bulk-hydrated {loaded}/{len(wanted)} matched hacks "
            f"from KaizOFF catalogue ({snapshot.source}{stale}).",
            "Debug",
        )

    def _detail_metadata(self, identifier: int):
        identifier = int(identifier)
        metadata = self._bulk_details.get(identifier)
        if metadata is not None:
            return metadata
        return self.provider.get_hack(identifier).metadata

    def _resolved_hack(self, hack: dict, existing_ids: Iterable[str]) -> dict:
        hack_id = str(hack.get("id", ""))
        if not hack_id:
            return self._resolution(save_sync.RESOLUTION_NO_MATCH)
        existing = {str(value) for value in existing_ids}
        status = (
            save_sync.RESOLUTION_EXISTS
            if hack_id in existing
            else save_sync.RESOLUTION_RESOLVED
        )
        return self._resolution(status, hack=hack, hack_id=hack_id)

    @staticmethod
    def _suggestion_payload(match) -> dict:
        suggestion = match.suggestion
        candidates = []
        for ranked in match.ranked[:5]:
            if ranked.score < 0.48 and not (
                ranked.exact
                or ranked.core_exact
                or ranked.articleless_exact
                or ranked.abbreviation_match
                or ranked.phrase_match
            ):
                continue
            candidates.append(
                {
                    "hack_id": str(ranked.entry.smwc_submission_id),
                    "title": ranked.entry.title,
                    "difficulty": ranked.entry.difficulty,
                    "score": round(float(ranked.score), 6),
                }
            )
        return {
            "hack_id": str(suggestion.smwc_submission_id),
            "title": suggestion.title,
            "difficulty": suggestion.difficulty,
            "classification": match.classification,
            "confidence": round(float(match.confidence), 6),
            "margin": round(float(match.margin), 6),
            "candidates": candidates,
        }

    def search_manual(self, query: str, existing_ids: Iterable[str], limit: int = 50) -> dict:
        """Search the KaizOFF Index locally, falling back once to direct SMWC."""

        cleaned = save_sync.make_search_query(query)
        if not cleaned:
            return {"status": save_sync.RESOLUTION_NO_MATCH, "query": "", "options": []}
        try:
            entries = self._index()
        except KaizOffProviderError as exc:
            self._announce_fallback(exc)
            return self._fallback_search(cleaned, existing_ids, limit)

        existing = {str(value) for value in existing_ids}
        matcher = CatalogueMatcher(entries)
        ranked = matcher.rank(cleaned, limit=max(int(limit) * 3, 100))
        target = save_sync._normalize(cleaned)
        selected: dict[int, tuple[CatalogueEntry, float, bool]] = {}

        for ranked_match in ranked:
            entry = ranked_match.entry
            normalized = save_sync._normalize(entry.title)
            useful = bool(
                ranked_match.exact
                or ranked_match.core_exact
                or ranked_match.articleless_exact
                or ranked_match.abbreviation_match
                or ranked_match.phrase_match
                or ranked_match.score >= 0.48
                or (target and (target in normalized or normalized in target))
            )
            if useful:
                selected[entry.smwc_submission_id] = (
                    entry,
                    float(ranked_match.score),
                    normalized == target,
                )

        # Ensure simple substring results are not omitted by the matcher's pool.
        for entry in entries:
            normalized = save_sync._normalize(entry.title)
            if not target or not normalized:
                continue
            if target in normalized or normalized in target:
                selected.setdefault(
                    entry.smwc_submission_id,
                    (entry, 0.50, normalized == target),
                )

        options = []
        for entry, score, exact_title in selected.values():
            options.append(
                {
                    "hack_id": str(entry.smwc_submission_id),
                    "name": entry.title,
                    "exact_title": exact_title,
                    "obsolete": None,
                    "in_collection": str(entry.smwc_submission_id) in existing,
                    "difficulty": entry.difficulty,
                    "hack": None,
                    "lookup_source": "kaizoff",
                    "score": score,
                }
            )
        options.sort(
            key=lambda option: (
                not option["exact_title"],
                -float(option["score"]),
                not option["in_collection"],
                option["name"].casefold(),
                option["hack_id"],
            )
        )
        options = options[: max(1, int(limit))]
        return {
            "status": save_sync.SEARCH_RESULTS if options else save_sync.RESOLUTION_NO_MATCH,
            "query": cleaned,
            "options": options,
            "lookup_source": "kaizoff",
        }

    def resolve_selected_option(self, option: dict, existing_ids: Iterable[str]) -> dict:
        """Hydrate one selected KaizOFF row; use direct SMWC only as fallback."""

        if option.get("lookup_source") != "kaizoff":
            return save_sync.resolution_for_selected_hack(option.get("hack"), existing_ids)
        try:
            identifier = int(option.get("hack_id"))
            hack = self._legacy_hack(self.provider.get_hack(identifier).metadata)
        except Exception as exc:
            self._announce_fallback(exc)
            return self._fallback_selected(option, existing_ids)
        return save_sync.resolution_for_selected_hack(hack, existing_ids)

    def _fallback_fetch(self) -> Callable[..., Any]:
        if self.fallback_fetch_fn is not None:
            return self.fallback_fetch_fn
        from api_pipeline import fetch_hack_list_direct_smwc
        return fetch_hack_list_direct_smwc

    def _fallback_search(self, query: str, existing_ids: Iterable[str], limit: int) -> dict:
        result = save_sync.search_orphan_options(
            query,
            existing_ids,
            fetch_fn=self._fallback_fetch(),
            log=self.log,
            limit=limit,
        )
        options = []
        for option in result.get("options", []):
            copied = dict(option)
            copied["lookup_source"] = "smwc_fallback"
            copied.setdefault("score", 0.0)
            options.append(copied)
        result = dict(result)
        result["options"] = options
        result["lookup_source"] = "smwc_fallback"
        return result

    def _fallback_selected(self, option: dict, existing_ids: Iterable[str]) -> dict:
        result = self._fallback_search(option.get("name", ""), existing_ids, 100)
        if result.get("status") == save_sync.RESOLUTION_ERROR:
            return self._resolution(save_sync.RESOLUTION_ERROR)
        wanted = str(option.get("hack_id", ""))
        for fallback in result.get("options", []):
            if str(fallback.get("hack_id", "")) == wanted and fallback.get("hack"):
                return save_sync.resolution_for_selected_hack(
                    fallback["hack"], existing_ids
                )
        return self._resolution(save_sync.RESOLUTION_NO_MATCH)

    def _announce_fallback(self, error: Exception) -> None:
        if self._fallback_announced:
            return
        self._fallback_announced = True
        self._write_log(
            "KaizOFF could not satisfy the explicit Save Data Sync lookup; "
            f"falling back to the direct SMWCentral API for this manual request: {error}",
            "Warning",
        )

    @staticmethod
    def _resolution(status: str, *, hack=None, hack_id: str = "", **extra) -> dict:
        result = {"status": status, "hack": hack, "hack_id": hack_id, "lookup_source": "kaizoff"}
        result.update(extra)
        return result

    @staticmethod
    def _legacy_hack(metadata) -> dict:
        """Adapt validated KaizOFF rich metadata to the established import shape."""

        difficulty_id = str(getattr(metadata, "difficulty_id", "") or "").strip()
        if not difficulty_id and metadata.difficulty:
            try:
                from utils import DIFFICULTY_LOOKUP
                display = str(metadata.difficulty).casefold()
                for key, value in DIFFICULTY_LOOKUP.items():
                    if str(value).casefold() == display:
                        difficulty_id = str(key)
                        break
            except Exception:
                difficulty_id = ""
        obsolete = bool(
            metadata.active is False
            or metadata.obsoleted_by_submission_id is not None
        )
        return {
            "id": str(metadata.smwc_submission_id),
            "name": metadata.title,
            "time": int(metadata.release_timestamp or 0),
            "authors": list(metadata.authors),
            "rating": metadata.rating,
            "raw_fields": {
                "difficulty": difficulty_id,
                "type": list(metadata.hack_types) or ["standard"],
                "length": int(metadata.exits or 0),
                "hof": bool(metadata.hall_of_fame),
                "sa1": bool(metadata.sa1_compatible),
                "collab": bool(metadata.collaboration),
                "demo": bool(metadata.demo),
                "obsolete": obsolete,
            },
        }
