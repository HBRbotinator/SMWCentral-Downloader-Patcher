"""Finalize completed Collection ingestion review into one immutable read-only plan."""
from __future__ import annotations

from typing import Callable, Mapping, Sequence

from collection_change_plan import CollectionChangePlan, StorePrecondition
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion_convergence_review import ConvergedRomDecision
from collection_ingestion_session import (
    CollectionIngestionSession,
    fetch_required_catalogue_details,
    finalize_ingestion_session_plan,
)
from collection_plan_apply import (
    CollectionIdentityReferenceParticipant,
    collect_store_preconditions,
)
from collection_reconciliation import (
    ReviewAction,
    ReviewDecision,
    generate_local_collection_id,
    is_local_collection_key,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffCatalogueProvider


class CollectionIngestionFinalizationError(RuntimeError):
    """Raised when completed review cannot safely become a final plan."""


class CollectionIngestionFinalizationStaleStateError(
    CollectionIngestionFinalizationError
):
    """Raised when reviewed Collection/dependent state changed before preview."""


LocalIdentityFactory = Callable[[], str]


def allocate_local_identity_allocations(
    session: CollectionIngestionSession,
    decisions: Mapping[str, ReviewDecision] | None,
    *,
    id_factory: LocalIdentityFactory = generate_local_collection_id,
) -> dict[str, str]:
    """Allocate opaque IDs only for explicitly approved local/manual imports."""

    if not isinstance(session, CollectionIngestionSession):
        raise CollectionIngestionFinalizationError(
            "Finalization requires the frozen ingestion session that was reviewed."
        )
    reviewed = dict(decisions or {})
    known_groups = {group.group_id for group in session.groups}
    unknown = set(reviewed).difference(known_groups)
    if unknown:
        raise CollectionIngestionFinalizationError(
            "Review decisions contain unknown group IDs: " + ", ".join(sorted(unknown))
        )

    reserved = set(session.existing_collection_keys)
    allocations: dict[str, str] = {}
    for group in session.groups:
        decision = reviewed.get(group.group_id)
        if decision is None or decision.action is not ReviewAction.IMPORT_LOCAL:
            continue
        allocated = ""
        for _attempt in range(100):
            candidate = id_factory()
            if not is_local_collection_key(candidate):
                raise CollectionIngestionFinalizationError(
                    "Local identity allocator returned an invalid usr_* identity."
                )
            if candidate in reserved:
                continue
            allocated = candidate
            break
        if not allocated:
            raise CollectionIngestionFinalizationError(
                "Could not allocate a unique local Collection identity."
            )
        allocations[group.group_id] = allocated
        reserved.add(allocated)
    return allocations


def validate_reviewed_store_state(
    session: CollectionIngestionSession,
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    participants: Sequence[CollectionIdentityReferenceParticipant] = (),
) -> tuple[StorePrecondition, ...]:
    """Require current stores to match the exact preconditions frozen for review."""

    current = collect_store_preconditions(manager, identity_hints, participants)
    expected_map = _precondition_map(session.preconditions)
    current_map = _precondition_map(current)
    if current_map != expected_map:
        changed = sorted(
            name
            for name in set(expected_map).union(current_map)
            if expected_map.get(name) != current_map.get(name)
        )
        label = ", ".join(changed) if changed else "reviewed stores"
        raise CollectionIngestionFinalizationStaleStateError(
            "Collection import state changed while review was open: "
            f"{label}. Start a new import review so the preview is based on current data."
        )
    return current


def finalize_reviewed_ingestion_session(
    session: CollectionIngestionSession,
    decisions: Mapping[str, ReviewDecision] | None,
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    provider: KaizOffCatalogueProvider,
    *,
    participants: Sequence[CollectionIdentityReferenceParticipant] = (),
    id_factory: LocalIdentityFactory = generate_local_collection_id,
    force_detail_refresh: bool = False,
    converged_rom_decisions: Mapping[str, ConvergedRomDecision] | None = None,
) -> CollectionChangePlan:
    """Hydrate required details and finalize a plan without applying user state."""

    participant_tuple = tuple(participants)
    validate_reviewed_store_state(
        session,
        manager,
        identity_hints,
        participant_tuple,
    )
    allocations = allocate_local_identity_allocations(
        session,
        decisions,
        id_factory=id_factory,
    )
    details = fetch_required_catalogue_details(
        session,
        provider,
        decisions,
        local_identity_allocations=allocations,
        force_refresh=force_detail_refresh,
    )

    # Provider/cache work can be slow. Revalidate user-owned state before freezing
    # the final plan so the preview never knowingly describes stale reviewed data.
    validate_reviewed_store_state(
        session,
        manager,
        identity_hints,
        participant_tuple,
    )
    plan = finalize_ingestion_session_plan(
        session,
        decisions,
        local_identity_allocations=allocations,
        catalogue_details=details,
        converged_rom_decisions=converged_rom_decisions,
    )
    _preflight_reference_participants(plan, participant_tuple)
    validate_reviewed_store_state(
        session,
        manager,
        identity_hints,
        participant_tuple,
    )
    return plan


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
            raise CollectionIngestionFinalizationError(
                f"Final plan is missing the {participant.store_name!r} precondition."
            )
        try:
            prepared = participant.prepare_reference_migrations(plan.reference_migrations)
        except Exception as error:
            raise CollectionIngestionFinalizationError(
                f"Dependent store {participant.store_name!r} cannot safely follow "
                f"the reviewed Collection identity migration: {error}"
            ) from error
        if prepared.store_name != participant.store_name:
            raise CollectionIngestionFinalizationError(
                "Reference participant returned a mismatched store name."
            )
        if prepared.expected_revision_token != expected:
            raise CollectionIngestionFinalizationStaleStateError(
                "Dependent Collection references changed while the final plan was built: "
                f"{participant.store_name}. Start a new import review."
            )


def _precondition_map(
    preconditions: Sequence[StorePrecondition],
) -> dict[str, str]:
    result = {}
    for item in preconditions:
        if item.store_name in result:
            raise CollectionIngestionFinalizationError(
                f"Duplicate reviewed store precondition: {item.store_name!r}."
            )
        result[item.store_name] = item.revision_token
    return result


__all__ = [
    "CollectionIngestionFinalizationError",
    "CollectionIngestionFinalizationStaleStateError",
    "allocate_local_identity_allocations",
    "finalize_reviewed_ingestion_session",
    "validate_reviewed_store_state",
]
