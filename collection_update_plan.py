"""Finalize an explicitly confirmed SMWC replacement relationship into a read-only plan.

The user has already selected the target submission through the frozen Index discovery flow.
This module hydrates that exact target, freezes the participating user-owned stores, and builds
an immutable CollectionChangePlan. It never downloads/patches ROMs and never applies the plan.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from collection_change_plan import CollectionChangePlan, StorePrecondition, finalize_collection_change_plan
from collection_identity_hints import CollectionIdentityHintsStore
from collection_plan_apply import (
    CollectionIdentityReferenceParticipant,
    collect_store_preconditions,
)
from collection_reconciliation import (
    CandidateResolution,
    IdentityMigrationKind,
    IdentityMigrationProposal,
    MatchBasis,
    ReviewAction,
    ReviewDecision,
    build_reconciliation_groups,
)
from collection_update_discovery import CollectionUpdateSelection
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffCatalogueProvider, KaizOffDetailSnapshot


class CollectionUpdatePlanError(RuntimeError):
    """Raised when a confirmed replacement cannot safely become a final plan."""


class CollectionUpdatePlanStaleStateError(CollectionUpdatePlanError):
    """Raised when Collection/dependent state changes while rich detail is hydrated."""


class CollectionUpdateExistingTargetError(CollectionUpdatePlanError):
    """Raised when the selected target already owns independent Collection state."""


@dataclass(frozen=True)
class FinalizedCollectionUpdatePlan:
    """Read-only finalized replacement plan plus non-semantic provider freshness context."""

    selection: CollectionUpdateSelection
    plan: CollectionChangePlan
    detail_fetched_at: float
    detail_source: str
    detail_stale: bool


def finalize_collection_update_replacement_plan(
    selection: CollectionUpdateSelection,
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    provider: KaizOffCatalogueProvider,
    *,
    participants: Sequence[CollectionIdentityReferenceParticipant] = (),
    force_detail_refresh: bool = True,
) -> FinalizedCollectionUpdatePlan:
    """Build an immutable numeric-to-numeric replacement plan without Apply or ROM acquisition."""

    if not isinstance(selection, CollectionUpdateSelection):
        raise CollectionUpdatePlanError(
            "Replacement planning requires the explicit update-discovery selection."
        )
    if not isinstance(manager, HackDataManager):
        raise TypeError("manager must be a HackDataManager")
    if not isinstance(identity_hints, CollectionIdentityHintsStore):
        raise TypeError("identity_hints must be a CollectionIdentityHintsStore")
    if not isinstance(provider, KaizOffCatalogueProvider):
        raise TypeError("provider must be a KaizOffCatalogueProvider")

    participant_tuple = tuple(participants)
    source_key = str(selection.source_collection_key)
    target_key = str(selection.target_entry.smwc_submission_id)
    source_record = _require_source_record(manager.data, source_key)
    _reject_existing_target(manager.data, source_key, target_key)
    _reject_prior_submission_cycle(source_record, target_key)

    expected_preconditions = collect_store_preconditions(
        manager,
        identity_hints,
        participant_tuple,
    )
    detail = provider.get_hack(
        int(target_key),
        force_refresh=force_detail_refresh,
    )
    _require_preconditions_unchanged(
        expected_preconditions,
        manager,
        identity_hints,
        participant_tuple,
    )

    group = _replacement_group(selection, detail, source_record)
    decision = ReviewDecision(
        group_id=group.group_id,
        action=ReviewAction.CONFIRM_MIGRATION,
        target_key=target_key,
    )
    plan = finalize_collection_change_plan(
        (group,),
        {group.group_id: decision},
        existing_collection_keys=tuple(str(key) for key in manager.data),
        preconditions=expected_preconditions,
    )
    _preflight_reference_participants(plan, participant_tuple)
    _require_preconditions_unchanged(
        expected_preconditions,
        manager,
        identity_hints,
        participant_tuple,
    )
    return FinalizedCollectionUpdatePlan(
        selection=selection,
        plan=plan,
        detail_fetched_at=float(detail.fetched_at),
        detail_source=str(detail.source or "unknown"),
        detail_stale=bool(detail.stale),
    )



def finalize_collection_update_selection_plan(
    processed_json_path: str | Path,
    selection: CollectionUpdateSelection,
    *,
    force_detail_refresh: bool = True,
    provider: KaizOffCatalogueProvider | None = None,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants=None,
) -> FinalizedCollectionUpdatePlan:
    """Compose runtime stores/provider and finalize one explicit replacement selection."""

    from collection_ingestion_entrypoint import (
        collection_identity_reference_participants,
        kaizoff_cache_dir_for_processed_json,
    )

    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = manager or HackDataManager(str(processed))
    if Path(runtime_manager.json_path).expanduser().resolve() != processed:
        raise CollectionUpdatePlanError(
            "Collection manager does not reference the selected processed.json."
        )
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(processed)
    runtime_provider = provider or KaizOffCatalogueProvider(
        cache_dir=kaizoff_cache_dir_for_processed_json(processed)
    )
    runtime_participants = (
        collection_identity_reference_participants(processed)
        if participants is None
        else tuple(participants)
    )
    return finalize_collection_update_replacement_plan(
        selection,
        runtime_manager,
        hints,
        runtime_provider,
        participants=tuple(runtime_participants),
        force_detail_refresh=force_detail_refresh,
    )

def _replacement_group(
    selection: CollectionUpdateSelection,
    detail: KaizOffDetailSnapshot,
    source_record: Mapping,
):
    source_key = str(selection.source_collection_key)
    target_key = str(selection.target_entry.smwc_submission_id)
    metadata = detail.metadata
    if metadata.smwc_submission_id != int(target_key):
        raise CollectionUpdatePlanError(
            "Hydrated KaizOFF detail does not match the explicitly selected SMWC target."
        )

    prior = tuple(
        dict.fromkeys(
            value
            for value in source_record.get("prior_smwc_submission_ids", [])
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
        )
    )
    migration = IdentityMigrationProposal(
        source_key=source_key,
        target_key=target_key,
        kind=IdentityMigrationKind.SUBMISSION_REPLACEMENT,
        prior_submission_ids=prior,
    )
    candidate_id = f"update-replacement:{source_key}->{target_key}"
    resolution = CandidateResolution(
        candidate_id=candidate_id,
        candidate=metadata.as_candidate(),
        match_basis=MatchBasis.USER_CONFIRMED,
        target_key=target_key,
        existing_collection_key=source_key,
        migration=migration,
        reason=(
            "User explicitly confirmed this possible SMWC replacement/update relationship; "
            "the application does not infer which submission is newer."
        ),
    )
    groups = build_reconciliation_groups((resolution,))
    if len(groups) != 1 or groups[0].migration is None:
        raise CollectionUpdatePlanError(
            "Confirmed replacement relationship did not produce one migration group."
        )
    return groups[0]


def _require_source_record(records: Mapping, source_key: str) -> Mapping:
    record = records.get(source_key)
    if not isinstance(record, Mapping):
        raise CollectionUpdatePlanStaleStateError(
            "The source Collection entry no longer exists. Start update discovery again."
        )
    return record


def _reject_existing_target(records: Mapping, source_key: str, target_key: str) -> None:
    if target_key == source_key:
        raise CollectionUpdatePlanError("A Collection entry cannot replace itself.")
    if isinstance(records.get(target_key), Mapping):
        raise CollectionUpdateExistingTargetError(
            "The selected target already exists in Collection. Safely merging two numeric "
            "records requires explicit review of any conflicting user-owned state, so this "
            "replacement cannot be finalized by the current read-only planning slice."
        )


def _reject_prior_submission_cycle(source_record: Mapping, target_key: str) -> None:
    target_id = int(target_key)
    prior = source_record.get("prior_smwc_submission_ids", [])
    if isinstance(prior, list) and target_id in prior:
        raise CollectionUpdatePlanError(
            "The selected target is already recorded as a prior SMWC submission for this "
            "Collection entry. Refusing to create a replacement cycle."
        )


def _require_preconditions_unchanged(
    expected: Sequence[StorePrecondition],
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    participants: Sequence[CollectionIdentityReferenceParticipant],
) -> None:
    current = collect_store_preconditions(manager, identity_hints, participants)
    if _precondition_map(current) == _precondition_map(expected):
        return
    expected_map = _precondition_map(expected)
    current_map = _precondition_map(current)
    changed = sorted(
        name
        for name in set(expected_map).union(current_map)
        if expected_map.get(name) != current_map.get(name)
    )
    raise CollectionUpdatePlanStaleStateError(
        "Collection update state changed while the selected target was being hydrated: "
        + (", ".join(changed) if changed else "reviewed stores")
        + ". Start update discovery again."
    )


def _preflight_reference_participants(
    plan: CollectionChangePlan,
    participants: Sequence[CollectionIdentityReferenceParticipant],
) -> None:
    if not plan.reference_migrations:
        return
    preconditions = _precondition_map(plan.preconditions)
    for participant in participants:
        expected = preconditions.get(participant.store_name)
        if expected is None:
            raise CollectionUpdatePlanError(
                f"Replacement plan is missing the {participant.store_name!r} precondition."
            )
        try:
            prepared = participant.prepare_reference_migrations(plan.reference_migrations)
        except Exception as error:
            raise CollectionUpdatePlanError(
                f"Dependent store {participant.store_name!r} cannot safely follow the "
                f"confirmed Collection identity replacement: {error}"
            ) from error
        if prepared.store_name != participant.store_name:
            raise CollectionUpdatePlanError(
                "Reference participant returned a mismatched store name."
            )
        if prepared.expected_revision_token != expected:
            raise CollectionUpdatePlanStaleStateError(
                "Dependent Collection references changed while the replacement plan was built: "
                f"{participant.store_name}. Start update discovery again."
            )


def _precondition_map(preconditions: Sequence[StorePrecondition]) -> dict[str, str]:
    result = {}
    for item in preconditions:
        if item.store_name in result:
            raise CollectionUpdatePlanError(
                f"Duplicate replacement-plan store precondition: {item.store_name!r}."
            )
        result[item.store_name] = item.revision_token
    return result


__all__ = [
    "CollectionUpdateExistingTargetError",
    "CollectionUpdatePlanError",
    "CollectionUpdatePlanStaleStateError",
    "FinalizedCollectionUpdatePlan",
    "finalize_collection_update_replacement_plan",
    "finalize_collection_update_selection_plan",
]
