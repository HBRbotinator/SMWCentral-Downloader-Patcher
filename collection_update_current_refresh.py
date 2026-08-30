"""Read-only planning for refreshing the current SMWC submission in-place.

This workflow is deliberately separate from numeric-to-numeric replacement. It refreshes
KaizOFF-owned catalogue metadata for the Collection entry's existing SMWC submission ID and
may later attach a newly patched ROM for that same submission without changing Collection
identity or dependent references.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from collection_change_plan import (
    CatalogueMetadataOperation,
    CatalogueMetadataSnapshot,
    CollectionChangePlan,
    RecordIntent,
    RecordIntentKind,
    StorePrecondition,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion import IngestionSource
from collection_plan_apply import (
    CollectionIdentityReferenceParticipant,
    collect_store_preconditions,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffCatalogueProvider, KaizOffDetailSnapshot
from rom_title_matching import CatalogueEntry


class CollectionCurrentRefreshError(RuntimeError):
    """Raised when same-submission refresh cannot be planned safely."""


class CollectionCurrentRefreshStaleStateError(CollectionCurrentRefreshError):
    """Raised when reviewed Collection/dependent state changes during hydration."""


@dataclass(frozen=True)
class FinalizedCurrentSubmissionRefreshPlan:
    """Immutable metadata-refresh plan for one existing numeric Collection identity."""

    source_collection_key: str
    source_entry: CatalogueEntry
    plan: CollectionChangePlan
    detail_fetched_at: float
    detail_source: str
    detail_stale: bool
    download_url: str
    rom_acquisition_checked: bool = False
    rom_matches_existing: bool = False


def finalize_current_submission_refresh_plan(
    processed_json_path: str | Path,
    source_collection_key: str | int,
    *,
    force_detail_refresh: bool = True,
    provider: KaizOffCatalogueProvider | None = None,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants: Sequence[CollectionIdentityReferenceParticipant] | None = None,
) -> FinalizedCurrentSubmissionRefreshPlan:
    """Hydrate the current SMWC ID and freeze a metadata-only update plan.

    No ROM is downloaded and no Collection/store state is mutated here.
    """

    source_key = _numeric_key(source_collection_key)
    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = manager or HackDataManager(str(processed))
    if Path(runtime_manager.json_path).expanduser().resolve() != processed:
        raise CollectionCurrentRefreshError(
            "Collection manager does not reference the selected processed.json."
        )
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(processed)

    if participants is None:
        from collection_ingestion_entrypoint import (
            collection_identity_reference_participants,
            kaizoff_cache_dir_for_processed_json,
        )

        runtime_participants = tuple(collection_identity_reference_participants(processed))
        runtime_provider = provider or KaizOffCatalogueProvider(
            cache_dir=kaizoff_cache_dir_for_processed_json(processed)
        )
    else:
        runtime_participants = tuple(participants)
        if provider is None:
            from collection_ingestion_entrypoint import kaizoff_cache_dir_for_processed_json

            runtime_provider = KaizOffCatalogueProvider(
                cache_dir=kaizoff_cache_dir_for_processed_json(processed)
            )
        else:
            runtime_provider = provider

    if not isinstance(runtime_provider, KaizOffCatalogueProvider):
        raise TypeError("provider must be a KaizOffCatalogueProvider")

    source_record = runtime_manager.data.get(source_key)
    if not isinstance(source_record, dict):
        raise CollectionCurrentRefreshStaleStateError(
            "The selected Collection entry no longer exists. Restart the update check."
        )

    expected = collect_store_preconditions(runtime_manager, hints, runtime_participants)
    detail = runtime_provider.get_hack(int(source_key), force_refresh=force_detail_refresh)
    _require_same_submission(detail, source_key)
    _require_preconditions_current(
        expected,
        runtime_manager,
        hints,
        runtime_participants,
    )

    snapshot = _catalogue_snapshot(detail)
    source_entry = CatalogueEntry(
        smwc_submission_id=int(source_key),
        title=str(source_record.get("title") or snapshot.title or f"SMWC {source_key}"),
        difficulty=str(source_record.get("current_difficulty") or ""),
        hack_type=str(source_record.get("hack_type") or ""),
        exits=_safe_int(source_record.get("exits")),
        authors=tuple(str(item) for item in source_record.get("authors", []) if str(item)),
    )
    plan = CollectionChangePlan(
        preconditions=tuple(expected),
        record_intents=(
            RecordIntent(target_key=source_key, kind=RecordIntentKind.UPDATE),
        ),
        catalogue_updates=(
            CatalogueMetadataOperation(
                target_key=source_key,
                metadata=snapshot,
                source=IngestionSource.KAIZOFF,
                source_candidate_ids=(f"current-submission-refresh:{source_key}",),
            ),
        ),
        local_record_seeds=(),
        rom_updates=(),
        user_history_updates=(),
        user_state_updates=(),
        identity_migrations=(),
        reference_migrations=(),
        ignored_roms=(),
        remembered_associations=(),
        skipped_candidate_ids=(),
        ignored_candidate_ids=(),
    )
    return FinalizedCurrentSubmissionRefreshPlan(
        source_collection_key=source_key,
        source_entry=source_entry,
        plan=plan,
        detail_fetched_at=float(detail.fetched_at),
        detail_source=str(detail.source or "unknown"),
        detail_stale=bool(detail.stale),
        download_url=str(detail.metadata.download_url or ""),
    )


def _catalogue_snapshot(detail: KaizOffDetailSnapshot) -> CatalogueMetadataSnapshot:
    metadata = detail.metadata
    return CatalogueMetadataSnapshot(
        submission_id=int(metadata.smwc_submission_id),
        title=str(metadata.title),
        authors=tuple(metadata.authors),
        difficulty=str(metadata.difficulty or ""),
        hack_types=tuple(metadata.hack_types),
        exits=metadata.exits,
        release_timestamp=metadata.release_timestamp,
        rating=metadata.rating,
        hall_of_fame=metadata.hall_of_fame,
        sa1_compatible=metadata.sa1_compatible,
        collaboration=metadata.collaboration,
        demo=metadata.demo,
    )


def _require_same_submission(detail: KaizOffDetailSnapshot, source_key: str) -> None:
    if not isinstance(detail, KaizOffDetailSnapshot):
        raise CollectionCurrentRefreshError("KaizOFF returned invalid current-submission detail.")
    if int(detail.metadata.smwc_submission_id) != int(source_key):
        raise CollectionCurrentRefreshError(
            "KaizOFF current-submission detail does not match the selected Collection identity."
        )


def _require_preconditions_current(
    expected: Sequence[StorePrecondition],
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    participants: Sequence[CollectionIdentityReferenceParticipant],
) -> None:
    current = collect_store_preconditions(manager, identity_hints, participants)
    expected_map = _precondition_map(expected)
    current_map = _precondition_map(current)
    if expected_map == current_map:
        return
    changed = sorted(
        name
        for name in set(expected_map).union(current_map)
        if expected_map.get(name) != current_map.get(name)
    )
    raise CollectionCurrentRefreshStaleStateError(
        "Collection update state changed while the current SMWC submission was being hydrated: "
        + (", ".join(changed) if changed else "reviewed stores")
        + ". Restart the update check."
    )


def _precondition_map(items: Sequence[StorePrecondition]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        if item.store_name in result:
            raise CollectionCurrentRefreshError(
                f"Duplicate reviewed store precondition: {item.store_name!r}."
            )
        result[item.store_name] = item.revision_token
    return result


def _numeric_key(value: str | int) -> str:
    text = str(value).strip()
    if not text.isdigit() or int(text) <= 0:
        raise CollectionCurrentRefreshError(
            "Current-submission refresh requires a positive numeric SMWC Collection ID."
        )
    return str(int(text))


def _safe_int(value):
    if isinstance(value, bool):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None
    return result if result >= 0 else None


__all__ = [
    "CollectionCurrentRefreshError",
    "CollectionCurrentRefreshStaleStateError",
    "FinalizedCurrentSubmissionRefreshPlan",
    "finalize_current_submission_refresh_plan",
]
