"""Orchestrate real Collection ingestion sources into one review session.

This module is intentionally UI-free and write-free. It freezes matching against
one validated KaizOFF Index snapshot, combines ROM/GiganticBucket evidence with
existing Collection and user-confirmed identity hints, and produces the
ReconciliationGroup objects consumed by the Commit 004/005 plan pipeline.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from pathlib import Path
import os
import re
from typing import Mapping, Sequence

from collection_change_plan import CollectionChangePlan
from collection_ingestion_convergence_review import ConvergedRomDecision
from collection_identity_hints import (
    CollectionIdentityHintsStore,
    IdentityHintsSnapshot,
)
from collection_ingestion import CollectionCandidate, IngestionSource
from collection_plan_apply import (
    CollectionIdentityReferenceParticipant,
    collect_store_preconditions,
)
from collection_reconciliation import (
    CandidateResolution,
    MatchBasis,
    ReconciliationError,
    ReconciliationGroup,
    ReviewAction,
    ReviewDecision,
    automatic_first_clear,
    giganticbucket_user_field_proposals,
    build_reconciliation_groups,
    is_local_collection_key,
    is_numeric_collection_key,
    resolved_target_key,
)
from giganticbucket_ingestion import (
    GiganticBucketCatalogueResolution,
    GiganticBucketHack,
    GiganticBucketImport,
    load_giganticbucket_export,
    resolve_giganticbucket_hack_against_catalogue,
)
from hack_data_manager import HackDataManager
from local_collection_matching import (
    LocalCollectionEntry,
    snapshot_local_collection_entries,
)
from kaizoff_provider import (
    KaizOffCatalogueProvider,
    KaizOffDetailSnapshot,
    KaizOffHackMetadata,
    KaizOffIndexSnapshot,
)
from rom_ingestion import (
    RomCatalogueResolution,
    RomLibraryScan,
    candidate_from_rom,
    resolve_rom_against_catalogue,
    scan_rom_library,
)
from rom_title_matching import CatalogueEntry, CatalogueMatcher, RankedCatalogueMatch


_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class CollectionIngestionSessionError(RuntimeError):
    """Raised when a review session cannot be constructed safely."""


class CollectionIngestionSessionStaleStateError(CollectionIngestionSessionError):
    """Raised when Collection/sidecar state changes while the session is captured."""


class MissingCatalogueDetailError(CollectionIngestionSessionError):
    """Raised when a new numeric record lacks authoritative KaizOFF detail."""


@dataclass(frozen=True)
class CatalogueSuggestion:
    """One review-friendly ranked catalogue suggestion from the frozen Index."""

    target_key: str
    title: str
    difficulty: str
    hack_type: str
    exits: int | None
    confidence: float
    authors: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateReviewEntry:
    """Matcher context retained for a candidate without rerunning matching later."""

    candidate_id: str
    source: IngestionSource
    classification: str
    confidence: float
    suggestions: tuple[CatalogueSuggestion, ...]
    reason: str


@dataclass(frozen=True)
class SuppressedRom:
    """A discovered ROM intentionally omitted from ordinary hack reconciliation."""

    path: str
    sha256: str
    reason: str


@dataclass(frozen=True)
class CollectionIngestionSession:
    """Immutable source-orchestration result ready for the eventual review UI."""

    catalogue_fetched_at: float
    catalogue_source: str
    catalogue_stale: bool
    catalogue_entries: tuple[CatalogueEntry, ...]
    existing_collection_keys: tuple[str, ...]
    preconditions: tuple
    resolutions: tuple[CandidateResolution, ...]
    groups: tuple[ReconciliationGroup, ...]
    review_entries: tuple[CandidateReviewEntry, ...]
    suppressed_roms: tuple[SuppressedRom, ...]
    local_collection_entries: tuple[LocalCollectionEntry, ...] = ()
    existing_collection_titles: tuple[tuple[str, str], ...] = ()

    @property
    def blocking_groups(self) -> tuple[ReconciliationGroup, ...]:
        return tuple(group for group in self.groups if group.blocking)


@dataclass(frozen=True)
class _ExistingState:
    records: Mapping[str, dict]
    identity_hints: IdentityHintsSnapshot
    preconditions: tuple


@dataclass(frozen=True)
class _ResolutionBuild:
    resolution: CandidateResolution
    review: CandidateReviewEntry


def create_collection_ingestion_session(
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    provider: KaizOffCatalogueProvider,
    *,
    rom_root: str | Path | None = None,
    giganticbucket_path: str | Path | None = None,
    known_difficulties: Sequence[str] = (),
    participants: Sequence[CollectionIdentityReferenceParticipant] = (),
    force_catalogue_refresh: bool = False,
) -> CollectionIngestionSession:
    """Load requested real sources, then reconcile them against current user state."""

    catalogue = provider.get_index(force_refresh=force_catalogue_refresh)
    rom_scan = (
        scan_rom_library(rom_root, known_difficulties=known_difficulties)
        if rom_root is not None
        else None
    )
    giganticbucket = (
        load_giganticbucket_export(giganticbucket_path)
        if giganticbucket_path is not None
        else None
    )
    return build_collection_ingestion_session(
        manager,
        identity_hints,
        catalogue,
        rom_scan=rom_scan,
        giganticbucket=giganticbucket,
        participants=participants,
    )


def build_collection_ingestion_session(
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    catalogue: KaizOffIndexSnapshot,
    *,
    rom_scan: RomLibraryScan | None = None,
    giganticbucket: GiganticBucketImport | None = None,
    participants: Sequence[CollectionIdentityReferenceParticipant] = (),
) -> CollectionIngestionSession:
    """Freeze source matching and reviewed-state preconditions without writing."""

    if rom_scan is None and giganticbucket is None:
        raise CollectionIngestionSessionError("At least one ingestion source is required.")
    if not isinstance(catalogue, KaizOffIndexSnapshot):
        raise CollectionIngestionSessionError("A validated KaizOFF Index snapshot is required.")

    state = _capture_existing_state(manager, identity_hints, participants)
    matcher = CatalogueMatcher(catalogue.entries)
    hash_targets = _existing_hash_targets(state.records)
    remembered = _remembered_lookup(state.identity_hints)
    ignored = _ignored_lookup(state.identity_hints)

    resolutions: list[CandidateResolution] = []
    reviews: list[CandidateReviewEntry] = []
    suppressed: list[SuppressedRom] = []

    if rom_scan is not None:
        for index, rom in enumerate(rom_scan.roms):
            if _ignored_rom_key(rom.path, rom.sha256) in ignored:
                suppressed.append(
                    SuppressedRom(
                        path=rom.path,
                        sha256=rom.sha256,
                        reason="remembered path + SHA-256 ignore rule",
                    )
                )
                continue
            if rom.probable_base_rom:
                suppressed.append(
                    SuppressedRom(
                        path=rom.path,
                        sha256=rom.sha256,
                        reason="probable clean/base Super Mario World ROM",
                    )
                )
                continue
            built = _resolve_rom_candidate(
                index,
                rom,
                matcher,
                state.records,
                hash_targets,
                remembered,
            )
            resolutions.append(built.resolution)
            reviews.append(built.review)

    if giganticbucket is not None:
        for item in giganticbucket.hacks:
            built = _resolve_giganticbucket_candidate(
                item,
                matcher,
                state.records,
                remembered,
            )
            resolutions.append(built.resolution)
            reviews.append(built.review)

    groups = build_reconciliation_groups(resolutions)
    if giganticbucket is not None:
        user_state = tuple(
            (key, tuple((field, copy.deepcopy(record.get(field)))
                        for field in ("completed", "completed_date", "time_to_beat")))
            for key, record in sorted(state.records.items())
        )
        groups = tuple(
            replace(group, giganticbucket_user_state=user_state)
            if any(item.source is IngestionSource.GIGANTIC_BUCKET for item in group.user_history)
            else group
            for group in groups
        )
    return CollectionIngestionSession(
        catalogue_fetched_at=float(catalogue.fetched_at),
        catalogue_source=str(catalogue.source),
        catalogue_stale=bool(catalogue.stale),
        catalogue_entries=tuple(catalogue.entries),
        existing_collection_keys=tuple(sorted(state.records, key=_collection_key_sort)),
        preconditions=state.preconditions,
        resolutions=tuple(sorted(resolutions, key=lambda item: item.candidate_id)),
        groups=groups,
        review_entries=tuple(sorted(reviews, key=lambda item: item.candidate_id)),
        suppressed_roms=tuple(sorted(suppressed, key=lambda item: (item.path.casefold(), item.sha256))),
        local_collection_entries=snapshot_local_collection_entries(state.records),
        existing_collection_titles=tuple(
            (key, str(state.records[key].get("title") or "").strip())
            for key in sorted(state.records, key=_collection_key_sort)
            if str(state.records[key].get("title") or "").strip()
        ),
    )



def search_session_catalogue(
    session: CollectionIngestionSession,
    query: str,
    *,
    limit: int = 20,
) -> tuple[CatalogueSuggestion, ...]:
    """Search only the immutable KaizOFF Index snapshot captured by this session."""

    text = str(query or "").strip()
    if not text:
        return ()
    if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0 or limit > 50:
        raise CollectionIngestionSessionError("Catalogue search limit must be 1-50.")
    matcher = CatalogueMatcher(session.catalogue_entries)

    numeric = text
    lowered = text.casefold()
    for prefix in ("smwc-id-", "smwc id " , "smwc-"):
        if lowered.startswith(prefix):
            numeric = text[len(prefix):].strip()
            break
    if numeric.isdecimal():
        direct = matcher.get(int(numeric))
        if direct is not None:
            return (_catalogue_suggestion(direct, 1.0),)

    ranked = matcher.rank(text, limit=limit)
    return tuple(_catalogue_suggestion(item.entry, item.score) for item in ranked)

def required_catalogue_detail_ids(
    session: CollectionIngestionSession,
    decisions: Mapping[str, ReviewDecision] | None = None,
    *,
    local_identity_allocations: Mapping[str, str] | None = None,
) -> tuple[int, ...]:
    """Return new numeric targets that need rich KaizOFF metadata before planning."""

    decisions = dict(decisions or {})
    allocations = dict(local_identity_allocations or {})
    existing = set(session.existing_collection_keys)
    required = set()
    for group in session.groups:
        decision = decisions.get(group.group_id)
        if decision is not None and decision.action in {ReviewAction.SKIP, ReviewAction.IGNORE}:
            continue
        local_identity = allocations.get(group.group_id, "")
        try:
            target = resolved_target_key(group, decision, local_identity)
        except ReconciliationError:
            # The review is not resolved enough to know its final target yet.
            continue
        if target is None or not is_numeric_collection_key(target) or target in existing:
            continue
        required.add(int(target))
    return tuple(sorted(required))


def fetch_required_catalogue_details(
    session: CollectionIngestionSession,
    provider: KaizOffCatalogueProvider,
    decisions: Mapping[str, ReviewDecision] | None = None,
    *,
    local_identity_allocations: Mapping[str, str] | None = None,
    force_refresh: bool = False,
) -> tuple[KaizOffDetailSnapshot, ...]:
    """Fetch only rich records required for the reviewed new numeric targets."""

    return tuple(
        provider.get_hack(identifier, force_refresh=force_refresh)
        for identifier in required_catalogue_detail_ids(
            session,
            decisions,
            local_identity_allocations=local_identity_allocations,
        )
    )


def finalize_ingestion_session_plan(
    session: CollectionIngestionSession,
    decisions: Mapping[str, ReviewDecision] | None = None,
    *,
    local_identity_allocations: Mapping[str, str] | None = None,
    catalogue_details: Sequence[KaizOffDetailSnapshot | KaizOffHackMetadata] = (),
    converged_rom_decisions: Mapping[str, ConvergedRomDecision] | None = None,
) -> CollectionChangePlan:
    """Finalize a frozen session after review without rerunning source matching."""

    from collection_change_plan import finalize_collection_change_plan

    decisions = dict(decisions or {})
    allocations = dict(local_identity_allocations or {})
    details = _detail_map(catalogue_details)
    required = required_catalogue_detail_ids(
        session,
        decisions,
        local_identity_allocations=allocations,
    )
    missing = tuple(identifier for identifier in required if identifier not in details)
    if missing:
        joined = ", ".join(str(value) for value in missing)
        raise MissingCatalogueDetailError(
            f"New SMWC Collection targets require KaizOFF detail before finalization: {joined}"
        )

    augmented_groups = tuple(
        _augment_group_with_catalogue_detail(
            group,
            decisions.get(group.group_id),
            allocations.get(group.group_id, ""),
            details,
        )
        for group in session.groups
    )
    return finalize_collection_change_plan(
        augmented_groups,
        decisions,
        existing_collection_keys=session.existing_collection_keys,
        local_identity_allocations=allocations,
        converged_rom_decisions=converged_rom_decisions,
        preconditions=session.preconditions,
        target_display_titles=_target_display_titles(
            session,
            decisions,
            allocations,
            details,
        ),
    )


def _target_display_titles(
    session: CollectionIngestionSession,
    decisions: Mapping[str, ReviewDecision],
    allocations: Mapping[str, str],
    details: Mapping[int, KaizOffHackMetadata],
) -> dict[str, str]:
    """Freeze preview-only target titles without consulting mutable live state."""

    result = {
        target_key: title.strip()
        for target_key, title in session.existing_collection_titles
        if title.strip()
    }
    result.update(
        {
            str(entry.smwc_submission_id): entry.title.strip()
            for entry in session.catalogue_entries
            if entry.title.strip()
        }
    )
    result.update(
        {entry.target_key: entry.title.strip() for entry in session.local_collection_entries}
    )
    result.update(
        {str(identifier): metadata.title.strip() for identifier, metadata in details.items()}
    )
    for group_id, target_key in allocations.items():
        decision = decisions.get(group_id)
        if decision is None or decision.local_metadata is None:
            continue
        title = decision.local_metadata.title.strip()
        if title:
            result[target_key] = title
    return result


def _capture_existing_state(
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    participants: Sequence[CollectionIdentityReferenceParticipant],
) -> _ExistingState:
    first = collect_store_preconditions(manager, identity_hints, participants)
    records = copy.deepcopy(manager.data)
    hints = identity_hints.snapshot()
    second = collect_store_preconditions(manager, identity_hints, participants)
    if first != second:
        raise CollectionIngestionSessionStaleStateError(
            "Collection or identity-reference state changed while review state was captured."
        )
    if not isinstance(records, dict):
        raise CollectionIngestionSessionError("Collection state must be a JSON object.")
    eligible = {
        str(key): value
        for key, value in records.items()
        if isinstance(value, dict)
        and (is_numeric_collection_key(str(key)) or is_local_collection_key(str(key)))
    }
    return _ExistingState(records=eligible, identity_hints=hints, preconditions=first)


def _existing_hash_targets(records: Mapping[str, dict]) -> dict[str, tuple[str, ...]]:
    result: dict[str, set[str]] = {}
    for key, record in records.items():
        files = record.get("files", [])
        if isinstance(files, list):
            for row in files:
                if not isinstance(row, Mapping):
                    continue
                sha = _normalized_sha256(row.get("sha256"))
                if sha:
                    result.setdefault(sha, set()).add(key)
        top_sha = _normalized_sha256(record.get("sha256"))
        if top_sha and record.get("file_path"):
            result.setdefault(top_sha, set()).add(key)
    return {
        sha: tuple(sorted(keys, key=_collection_key_sort))
        for sha, keys in result.items()
    }


def _remembered_lookup(snapshot: IdentityHintsSnapshot) -> dict[tuple[IngestionSource, str], tuple[str, ...]]:
    result: dict[tuple[IngestionSource, str], set[str]] = {}
    for item in snapshot.remembered_associations:
        result.setdefault((item.source, _association_key(item.value)), set()).add(item.target_key)
    return {
        key: tuple(sorted(values, key=_collection_key_sort))
        for key, values in result.items()
    }


def _ignored_lookup(snapshot: IdentityHintsSnapshot) -> set[tuple[str, str]]:
    return {_ignored_rom_key(item.path, item.sha256) for item in snapshot.ignored_roms}


def _resolve_rom_candidate(
    index: int,
    rom,
    matcher: CatalogueMatcher,
    records: Mapping[str, dict],
    hash_targets: Mapping[str, tuple[str, ...]],
    remembered: Mapping[tuple[IngestionSource, str], tuple[str, ...]],
) -> _ResolutionBuild:
    candidate = candidate_from_rom(rom)
    candidate_id = f"rom:{index:06d}:{rom.sha256[:16]}"
    direct_sources: dict[str, set[str]] = {}

    for target in hash_targets.get(rom.sha256.lower(), ()):
        direct_sources.setdefault(target, set()).add("existing Collection ROM SHA-256")
    if rom.embedded_smwc_submission_id is not None:
        target = str(rom.embedded_smwc_submission_id)
        direct_sources.setdefault(target, set()).add("explicit SMWC ID in ROM filename")
    for value in candidate.title_hints:
        for target in remembered.get((IngestionSource.ROM_SCAN, _association_key(value)), ()):
            direct_sources.setdefault(target, set()).add("remembered ROM filename/title association")

    catalogue_resolution = resolve_rom_against_catalogue(rom, matcher)
    suggestions = _rom_suggestions(rom, matcher, catalogue_resolution)
    targets = tuple(sorted(direct_sources, key=_collection_key_sort))

    if len(targets) > 1:
        alternatives = _merge_alternatives(targets, suggestions)
        return _build_resolution(
            candidate_id,
            candidate,
            MatchBasis.CONFLICT,
            alternatives=alternatives,
            classification="Identity conflict",
            confidence=catalogue_resolution.confidence,
            suggestions=suggestions,
            reason=_direct_conflict_reason(direct_sources),
        )

    if len(targets) == 1:
        target = targets[0]
        reason = "; ".join(sorted(direct_sources[target]))
        embedded_only = direct_sources[target] == {"explicit SMWC ID in ROM filename"}
        if rom.embedded_smwc_submission_id is not None and str(rom.embedded_smwc_submission_id) == target:
            if catalogue_resolution.classification == "SMWC ID/title conflict - review":
                alternatives = _merge_alternatives((target,), suggestions)
                if len(alternatives) > 1:
                    return _build_resolution(
                        candidate_id,
                        candidate,
                        MatchBasis.CONFLICT,
                        alternatives=alternatives,
                        existing=_existing_key(target, records),
                        classification=catalogue_resolution.classification,
                        confidence=catalogue_resolution.confidence,
                        suggestions=suggestions,
                        reason=f"{reason}; explicit ID conflicts with catalogue title evidence",
                    )
                return _build_resolution(
                    candidate_id,
                    candidate,
                    MatchBasis.SUGGESTED_TITLE,
                    target=target,
                    existing=_existing_key(target, records),
                    classification=catalogue_resolution.classification,
                    confidence=catalogue_resolution.confidence,
                    suggestions=suggestions,
                    reason=f"{reason}; title disagreement requires review",
                )
            if embedded_only and catalogue_resolution.classification == "SMWC ID not in current catalogue - review":
                return _build_resolution(
                    candidate_id,
                    candidate,
                    MatchBasis.SUGGESTED_TITLE,
                    target=target,
                    existing=_existing_key(target, records),
                    classification=catalogue_resolution.classification,
                    confidence=0.0,
                    suggestions=suggestions,
                    reason=f"{reason}; ID is absent from the frozen KaizOFF Index",
                )
        return _build_resolution(
            candidate_id,
            candidate,
            MatchBasis.DIRECT,
            target=target,
            existing=_existing_key(target, records),
            classification="Direct evidence",
            confidence=1.0,
            suggestions=suggestions,
            reason=reason,
        )

    return _resolution_from_rom_catalogue(
        candidate_id,
        candidate,
        catalogue_resolution,
        records,
        suggestions,
    )


def _resolve_giganticbucket_candidate(
    item: GiganticBucketHack,
    matcher: CatalogueMatcher,
    records: Mapping[str, dict],
    remembered: Mapping[tuple[IngestionSource, str], tuple[str, ...]],
) -> _ResolutionBuild:
    candidate_id = f"giganticbucket:{item.hack_id}"
    direct_sources: dict[str, set[str]] = {}
    if item.smwc_submission_id is not None:
        target = str(item.smwc_submission_id)
        direct_sources.setdefault(target, set()).add("GiganticBucket SMWCHack link_Id")
    for value in item.candidate.title_hints:
        for target in remembered.get((IngestionSource.GIGANTIC_BUCKET, _association_key(value)), ()):
            direct_sources.setdefault(target, set()).add("remembered GiganticBucket title association")

    catalogue_resolution = resolve_giganticbucket_hack_against_catalogue(item, matcher)
    suggestions = _giganticbucket_suggestions(item, matcher, catalogue_resolution)
    targets = tuple(sorted(direct_sources, key=_collection_key_sort))

    if len(targets) > 1:
        alternatives = _merge_alternatives(targets, suggestions)
        base = _build_resolution(
            candidate_id,
            item.candidate,
            MatchBasis.CONFLICT,
            alternatives=alternatives,
            classification="Identity conflict",
            confidence=catalogue_resolution.confidence,
            suggestions=suggestions,
            reason=_direct_conflict_reason(direct_sources),
        )
        return _with_giganticbucket_user_state(base, records)

    if len(targets) == 1:
        target = targets[0]
        reason = "; ".join(sorted(direct_sources[target]))
        if item.smwc_submission_id is not None and str(item.smwc_submission_id) == target:
            if catalogue_resolution.classification == "SMWC ID/title conflict - review":
                alternatives = _merge_alternatives((target,), suggestions)
                if len(alternatives) > 1:
                    built = _build_resolution(
                        candidate_id,
                        item.candidate,
                        MatchBasis.CONFLICT,
                        alternatives=alternatives,
                        existing=_existing_key(target, records),
                        classification=catalogue_resolution.classification,
                        confidence=catalogue_resolution.confidence,
                        suggestions=suggestions,
                        reason=f"{reason}; direct ID conflicts with catalogue title evidence",
                    )
                    return _with_giganticbucket_user_state(built, records)
                built = _build_resolution(
                    candidate_id,
                    item.candidate,
                    MatchBasis.SUGGESTED_TITLE,
                    target=target,
                    existing=_existing_key(target, records),
                    classification=catalogue_resolution.classification,
                    confidence=catalogue_resolution.confidence,
                    suggestions=suggestions,
                    reason=f"{reason}; title disagreement requires review",
                )
                return _with_giganticbucket_user_state(built, records)
            if catalogue_resolution.classification == "SMWC ID not in current catalogue - review":
                built = _build_resolution(
                    candidate_id,
                    item.candidate,
                    MatchBasis.SUGGESTED_TITLE,
                    target=target,
                    existing=_existing_key(target, records),
                    classification=catalogue_resolution.classification,
                    confidence=0.0,
                    suggestions=suggestions,
                    reason=f"{reason}; ID is absent from the frozen KaizOFF Index",
                )
                return _with_giganticbucket_user_state(built, records)
        built = _build_resolution(
            candidate_id,
            item.candidate,
            MatchBasis.DIRECT,
            target=target,
            existing=_existing_key(target, records),
            classification="Direct evidence",
            confidence=1.0,
            suggestions=suggestions,
            reason=reason,
        )
        return _with_giganticbucket_user_state(built, records)

    built = _resolution_from_giganticbucket_catalogue(
        candidate_id,
        item,
        catalogue_resolution,
        records,
        suggestions,
    )
    return _with_giganticbucket_user_state(built, records)


def _with_giganticbucket_user_state(
    built: _ResolutionBuild,
    records: Mapping[str, dict],
) -> _ResolutionBuild:
    resolution = built.resolution
    current = records.get(resolution.target_key, {}) if resolution.target_key else {}
    history = resolution.candidate.user_history
    proposals = giganticbucket_user_field_proposals(
        history, current, automatic_first_clear(history)
    )
    updated = replace(
        resolution,
        user_field_proposals=tuple(proposals),
        first_clear_requires_verification=bool(history and automatic_first_clear(history) is None),
    )
    return _ResolutionBuild(resolution=updated, review=built.review)


def _resolution_from_rom_catalogue(
    candidate_id: str,
    candidate: CollectionCandidate,
    result: RomCatalogueResolution,
    records: Mapping[str, dict],
    suggestions: tuple[CatalogueSuggestion, ...],
) -> _ResolutionBuild:
    if result.auto_selected and result.selected is not None:
        target = str(result.selected.smwc_submission_id)
        return _build_resolution(
            candidate_id,
            candidate,
            MatchBasis.AUTO_TITLE,
            target=target,
            existing=_existing_key(target, records),
            classification=result.classification,
            confidence=result.confidence,
            suggestions=suggestions,
            reason=f"KaizOFF Index title match from {result.evidence_title!r}.",
        )
    if result.classification == "Ambiguous":
        return _build_resolution(
            candidate_id,
            candidate,
            MatchBasis.AMBIGUOUS,
            alternatives=tuple(item.target_key for item in suggestions),
            classification=result.classification,
            confidence=result.confidence,
            suggestions=suggestions,
            reason="Several KaizOFF Index records remain plausible.",
        )
    if result.suggestion is not None:
        target = str(result.suggestion.smwc_submission_id)
        return _build_resolution(
            candidate_id,
            candidate,
            MatchBasis.SUGGESTED_TITLE,
            target=target,
            existing=_existing_key(target, records),
            alternatives=tuple(item.target_key for item in suggestions[1:]),
            classification=result.classification,
            confidence=result.confidence,
            suggestions=suggestions,
            reason=f"Guarded KaizOFF Index title suggestion from {result.evidence_title!r}.",
        )
    return _build_resolution(
        candidate_id,
        candidate,
        MatchBasis.UNMATCHED,
        classification=result.classification,
        confidence=result.confidence,
        suggestions=suggestions,
        reason="No safe KaizOFF Index identity was established.",
    )


def _resolution_from_giganticbucket_catalogue(
    candidate_id: str,
    item: GiganticBucketHack,
    result: GiganticBucketCatalogueResolution,
    records: Mapping[str, dict],
    suggestions: tuple[CatalogueSuggestion, ...],
) -> _ResolutionBuild:
    if result.auto_selected and result.selected is not None:
        target = str(result.selected.smwc_submission_id)
        return _build_resolution(
            candidate_id,
            item.candidate,
            MatchBasis.AUTO_TITLE,
            target=target,
            existing=_existing_key(target, records),
            classification=result.classification,
            confidence=result.confidence,
            suggestions=suggestions,
            reason=f"KaizOFF Index title match for GiganticBucket title {item.title!r}.",
        )
    if result.classification == "Ambiguous":
        return _build_resolution(
            candidate_id,
            item.candidate,
            MatchBasis.AMBIGUOUS,
            alternatives=tuple(value.target_key for value in suggestions),
            classification=result.classification,
            confidence=result.confidence,
            suggestions=suggestions,
            reason="Several KaizOFF Index records remain plausible.",
        )
    if result.suggestion is not None:
        target = str(result.suggestion.smwc_submission_id)
        return _build_resolution(
            candidate_id,
            item.candidate,
            MatchBasis.SUGGESTED_TITLE,
            target=target,
            existing=_existing_key(target, records),
            alternatives=tuple(value.target_key for value in suggestions[1:]),
            classification=result.classification,
            confidence=result.confidence,
            suggestions=suggestions,
            reason=f"Guarded KaizOFF Index title suggestion for {item.title!r}.",
        )
    return _build_resolution(
        candidate_id,
        item.candidate,
        MatchBasis.UNMATCHED,
        classification=result.classification,
        confidence=result.confidence,
        suggestions=suggestions,
        reason="No safe KaizOFF Index identity was established.",
    )


def _build_resolution(
    candidate_id: str,
    candidate: CollectionCandidate,
    basis: MatchBasis,
    *,
    target: str = "",
    existing: str = "",
    alternatives: Sequence[str] = (),
    classification: str,
    confidence: float,
    suggestions: Sequence[CatalogueSuggestion],
    reason: str,
) -> _ResolutionBuild:
    resolution = CandidateResolution(
        candidate_id=candidate_id,
        candidate=candidate,
        match_basis=basis,
        target_key=target,
        existing_collection_key=existing,
        alternative_target_keys=tuple(dict.fromkeys(value for value in alternatives if value)),
        reason=reason,
    )
    review = CandidateReviewEntry(
        candidate_id=candidate_id,
        source=candidate.source,
        classification=classification,
        confidence=float(confidence),
        suggestions=tuple(suggestions),
        reason=reason,
    )
    return _ResolutionBuild(resolution=resolution, review=review)


def _rom_suggestions(
    rom,
    matcher: CatalogueMatcher,
    result: RomCatalogueResolution,
) -> tuple[CatalogueSuggestion, ...]:
    ranked = matcher.rank(rom.title_hint, difficulty_hint=rom.difficulty_hint, limit=5)
    return _ranked_suggestions(ranked, preferred=result.suggestion)


def _giganticbucket_suggestions(
    item: GiganticBucketHack,
    matcher: CatalogueMatcher,
    result: GiganticBucketCatalogueResolution,
) -> tuple[CatalogueSuggestion, ...]:
    ranked = matcher.rank(item.title, limit=5)
    return _ranked_suggestions(ranked, preferred=result.suggestion)


def _ranked_suggestions(
    ranked: Sequence[RankedCatalogueMatch],
    *,
    preferred: CatalogueEntry | None,
) -> tuple[CatalogueSuggestion, ...]:
    rows: list[CatalogueSuggestion] = []
    seen = set()
    if preferred is not None:
        preferred_rank = next(
            (item for item in ranked if item.entry.smwc_submission_id == preferred.smwc_submission_id),
            None,
        )
        rows.append(_catalogue_suggestion(preferred, preferred_rank.score if preferred_rank else 0.0))
        seen.add(preferred.smwc_submission_id)
    for item in ranked:
        if item.entry.smwc_submission_id in seen:
            continue
        rows.append(_catalogue_suggestion(item.entry, item.score))
        seen.add(item.entry.smwc_submission_id)
        if len(rows) >= 5:
            break
    return tuple(rows)


def _catalogue_suggestion(entry: CatalogueEntry, score: float) -> CatalogueSuggestion:
    return CatalogueSuggestion(
        target_key=str(entry.smwc_submission_id),
        title=entry.title,
        difficulty=entry.difficulty,
        hack_type=entry.hack_type,
        exits=entry.exits,
        confidence=float(score),
        authors=tuple(entry.authors),
    )


def _merge_alternatives(
    direct_targets: Sequence[str],
    suggestions: Sequence[CatalogueSuggestion],
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            [*direct_targets, *(item.target_key for item in suggestions)]
        )
    )


def _direct_conflict_reason(direct_sources: Mapping[str, set[str]]) -> str:
    details = []
    for target in sorted(direct_sources, key=_collection_key_sort):
        details.append(f"{target}: {', '.join(sorted(direct_sources[target]))}")
    return "Conflicting direct identity evidence (" + "; ".join(details) + ")."


def _existing_key(target: str, records: Mapping[str, dict]) -> str:
    return target if target in records else ""


def _association_key(value: str) -> str:
    return " ".join(str(value).strip().split()).casefold()


def _ignored_rom_key(path: str, sha256: str) -> tuple[str, str]:
    return (os.path.normcase(os.path.normpath(str(path))), str(sha256).lower())


def _normalized_sha256(value) -> str:
    text = str(value or "").strip()
    if _SHA256_RE.fullmatch(text) is None:
        return ""
    return text.lower()


def _collection_key_sort(value: str):
    if is_numeric_collection_key(value):
        return (0, int(value))
    return (1, value)


def _detail_map(
    details: Sequence[KaizOffDetailSnapshot | KaizOffHackMetadata],
) -> dict[int, KaizOffHackMetadata]:
    result = {}
    for value in details:
        metadata = value.metadata if isinstance(value, KaizOffDetailSnapshot) else value
        if not isinstance(metadata, KaizOffHackMetadata):
            raise CollectionIngestionSessionError("catalogue_details contains invalid metadata.")
        identifier = metadata.smwc_submission_id
        previous = result.get(identifier)
        if previous is not None and previous != metadata:
            raise CollectionIngestionSessionError(
                f"Conflicting KaizOFF detail supplied for SMWC {identifier}."
            )
        result[identifier] = metadata
    return result


def _augment_group_with_catalogue_detail(
    group: ReconciliationGroup,
    decision: ReviewDecision | None,
    local_identity: str,
    details: Mapping[int, KaizOffHackMetadata],
) -> ReconciliationGroup:
    if decision is not None and decision.action in {ReviewAction.SKIP, ReviewAction.IGNORE}:
        return group
    try:
        target = resolved_target_key(group, decision, local_identity)
    except Exception:
        return group
    if target is None or not is_numeric_collection_key(target):
        return group
    metadata = details.get(int(target))
    if metadata is None:
        return group
    shared = metadata.as_candidate().shared_metadata
    members = []
    inserted = False
    for member in group.members:
        if member.target_key == target or (not member.target_key and not inserted):
            combined = tuple(
                dict.fromkeys([*member.candidate.shared_metadata, *shared])
            )
            candidate = replace(member.candidate, shared_metadata=combined)
            members.append(replace(member, candidate=candidate))
            inserted = True
        else:
            members.append(member)
    if not inserted and members:
        member = members[0]
        candidate = replace(
            member.candidate,
            shared_metadata=tuple(dict.fromkeys([*member.candidate.shared_metadata, *shared])),
        )
        members[0] = replace(member, candidate=candidate)
    return replace(group, members=tuple(members))


__all__ = [
    "CandidateReviewEntry",
    "CatalogueSuggestion",
    "CollectionIngestionSession",
    "CollectionIngestionSessionError",
    "CollectionIngestionSessionStaleStateError",
    "MissingCatalogueDetailError",
    "SuppressedRom",
    "build_collection_ingestion_session",
    "create_collection_ingestion_session",
    "fetch_required_catalogue_details",
    "finalize_ingestion_session_plan",
    "required_catalogue_detail_ids",
    "search_session_catalogue",
]
