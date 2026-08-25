"""Finalize an explicitly confirmed SMWC replacement relationship into a read-only plan.

The user has already selected the target submission through the frozen Index discovery flow.
This module hydrates that exact target, freezes the participating user-owned stores, and builds
an immutable CollectionChangePlan. It never downloads/patches ROMs and never applies the plan.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from collection_change_plan import (
    CollectionChangePlan,
    FirstClearSelectionOperation,
    PrimaryRomSelectionOperation,
    RomSubmissionProvenanceOperation,
    StorePrecondition,
    UserStateOperation,
    finalize_collection_change_plan,
)
from collection_identity_hints import CollectionIdentityHintsStore
from collection_plan_apply import (
    CollectionIdentityReferenceParticipant,
    collect_store_preconditions,
    collection_revision_token,
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
from collection_ingestion import IngestionSource
from collection_update_discovery import CollectionUpdateSelection
from collection_update_merge_review import (
    CollectionUpdateExistingTargetMergeDecision,
    CollectionUpdateExistingTargetMergeReview,
    MergeValueOrigin,
)
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
    """Finalized replacement plan plus provider context used before transactional Apply."""

    selection: CollectionUpdateSelection
    plan: CollectionChangePlan
    detail_fetched_at: float
    detail_source: str
    detail_stale: bool
    merge_decision: CollectionUpdateExistingTargetMergeDecision | None = None
    target_download_url: str = ""


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
    plan = _overlay_replacement_rom_submission_provenance(
        plan,
        source_key=source_key,
        target_key=target_key,
        source_record=source_record,
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
        target_download_url=str(detail.metadata.download_url or ""),
    )



def finalize_collection_update_existing_target_merge_plan(
    review: CollectionUpdateExistingTargetMergeReview,
    merge_decision: CollectionUpdateExistingTargetMergeDecision,
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    provider: KaizOffCatalogueProvider,
    *,
    participants: Sequence[CollectionIdentityReferenceParticipant] = (),
    force_detail_refresh: bool = True,
) -> FinalizedCollectionUpdatePlan:
    """Finalize a reviewed existing-target replacement merge into a read-only plan."""

    if not isinstance(review, CollectionUpdateExistingTargetMergeReview):
        raise TypeError("review must be CollectionUpdateExistingTargetMergeReview")
    if not isinstance(merge_decision, CollectionUpdateExistingTargetMergeDecision):
        raise TypeError("merge_decision must be CollectionUpdateExistingTargetMergeDecision")
    if not isinstance(manager, HackDataManager):
        raise TypeError("manager must be a HackDataManager")
    if not isinstance(identity_hints, CollectionIdentityHintsStore):
        raise TypeError("identity_hints must be a CollectionIdentityHintsStore")
    if not isinstance(provider, KaizOffCatalogueProvider):
        raise TypeError("provider must be a KaizOffCatalogueProvider")

    selection = review.selection
    source_key = str(selection.source_collection_key)
    target_key = str(selection.target_entry.smwc_submission_id)
    if not selection.target_already_in_collection:
        raise CollectionUpdatePlanError(
            "Existing-target merge planning requires a target that is already in Collection."
        )
    if merge_decision.source_collection_key != source_key or merge_decision.target_collection_key != target_key:
        raise CollectionUpdatePlanError(
            "Merge decision does not belong to the reviewed replacement relationship."
        )
    current_collection_token = collection_revision_token(manager)
    if review.collection_revision_token != current_collection_token or merge_decision.collection_revision_token != current_collection_token:
        raise CollectionUpdatePlanStaleStateError(
            "Collection changed after the existing-target merge review. Start update discovery again."
        )
    if review.unsupported_conflicts:
        raise CollectionUpdatePlanError(
            "Existing-target merge review contains unsupported conflicts and cannot become a plan."
        )

    source_record = _require_source_record(manager.data, source_key)
    target_record = _require_target_record(manager.data, target_key)
    _reject_prior_submission_cycle(source_record, target_key)
    _require_merge_decision_complete(review, merge_decision)
    _require_legacy_paths_representable(source_record, target_record)

    participant_tuple = tuple(participants)
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
    plan = _overlay_existing_target_merge_choices(
        plan,
        review,
        merge_decision,
        source_record,
        target_record,
    )
    plan = _overlay_replacement_rom_submission_provenance(
        plan,
        source_key=source_key,
        target_key=target_key,
        source_record=source_record,
        target_record=target_record,
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
        merge_decision=merge_decision,
        target_download_url=str(detail.metadata.download_url or ""),
    )


def finalize_collection_update_existing_target_selection_plan(
    processed_json_path: str | Path,
    review: CollectionUpdateExistingTargetMergeReview,
    merge_decision: CollectionUpdateExistingTargetMergeDecision,
    *,
    force_detail_refresh: bool = True,
    provider: KaizOffCatalogueProvider | None = None,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants=None,
) -> FinalizedCollectionUpdatePlan:
    """Compose runtime dependencies and finalize one reviewed existing-target merge."""

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
    return finalize_collection_update_existing_target_merge_plan(
        review,
        merge_decision,
        runtime_manager,
        hints,
        runtime_provider,
        participants=tuple(runtime_participants),
        force_detail_refresh=force_detail_refresh,
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

def _require_target_record(records: Mapping, target_key: str) -> Mapping:
    record = records.get(target_key)
    if not isinstance(record, Mapping):
        raise CollectionUpdatePlanStaleStateError(
            "The reviewed target Collection entry no longer exists. Start update discovery again."
        )
    return record


def _require_merge_decision_complete(
    review: CollectionUpdateExistingTargetMergeReview,
    decision: CollectionUpdateExistingTargetMergeDecision,
) -> None:
    expected = {item.field for item in review.field_conflicts}
    supplied = {item.field for item in decision.field_decisions}
    if expected != supplied:
        raise CollectionUpdatePlanError(
            "Existing-target merge decision no longer matches the reviewed conflict set."
        )
    allowed_primary = {item.path for item in review.primary_rom_choices}
    if review.primary_rom_required and decision.primary_rom_path not in allowed_primary:
        raise CollectionUpdatePlanError(
            "Existing-target merge decision is missing the reviewed primary ROM choice."
        )


def _require_legacy_paths_representable(source: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    file_paths = set()
    for record in (source, target):
        rows = record.get("files")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            path = row.get("path")
            if isinstance(path, str) and path:
                file_paths.add(path)
    if not file_paths:
        return
    missing = []
    for label, record in (("source", source), ("target", target)):
        fallback = record.get("file_path")
        if isinstance(fallback, str) and fallback and fallback not in file_paths:
            missing.append(f"{label} file_path {fallback!r}")
    if missing:
        raise CollectionUpdatePlanError(
            "The reviewed merge still contains legacy ROM paths that the current files[] merge "
            "cannot preserve safely: " + ", ".join(missing) + "."
        )


def _overlay_replacement_rom_submission_provenance(
    plan: CollectionChangePlan,
    *,
    source_key: str,
    target_key: str,
    source_record: Mapping[str, Any],
    target_record: Mapping[str, Any] | None = None,
) -> CollectionChangePlan:
    """Make retained modern ROM provenance explicit before a numeric identity migration."""

    source_rows = _rom_provenance_by_path(source_record, "source")
    target_rows = (
        _rom_provenance_by_path(target_record, "target")
        if target_record is not None
        else {}
    )
    operations = list(plan.rom_submission_provenance_updates)
    for path in sorted(set(source_rows) | set(target_rows)):
        source_provenance = source_rows.get(path)
        target_provenance = target_rows.get(path)
        if (
            source_provenance is not None
            and target_provenance is not None
            and source_provenance != target_provenance
        ):
            raise CollectionUpdatePlanError(
                "The same retained ROM path has conflicting explicit SMWC submission "
                f"provenance across the replacement records: {path!r}."
            )

        if target_provenance is not None:
            continue
        if source_provenance is not None:
            if path in target_rows:
                operations.append(
                    RomSubmissionProvenanceOperation(
                        target_key=target_key,
                        path=path,
                        smwc_submission_id=source_provenance,
                        reason=(
                            "Preserve explicit source-ROM submission provenance while merging "
                            "the reviewed numeric replacement."
                        ),
                    )
                )
            continue

        if path in target_rows:
            provenance_id = int(target_key)
            reason = (
                "The retained ROM belonged to the existing target Collection record before "
                "the reviewed replacement merge."
            )
        else:
            provenance_id = int(source_key)
            reason = (
                "The retained ROM belonged to the source Collection record before its "
                "reviewed numeric replacement."
            )
        operations.append(
            RomSubmissionProvenanceOperation(
                target_key=target_key,
                path=path,
                smwc_submission_id=provenance_id,
                reason=reason,
            )
        )

    return replace(
        plan,
        rom_submission_provenance_updates=tuple(operations),
    )


def _rom_provenance_by_path(
    record: Mapping[str, Any] | None,
    label: str,
) -> dict[str, int | None]:
    if record is None:
        return {}
    rows = record.get("files")
    if not isinstance(rows, list):
        return {}
    result: dict[str, int | None] = {}
    for raw in rows:
        if not isinstance(raw, Mapping):
            continue
        path = raw.get("path")
        if not isinstance(path, str) or not path:
            continue
        value = raw.get("smwc_submission_id")
        if value in (None, ""):
            provenance = None
        elif isinstance(value, int) and not isinstance(value, bool) and value > 0:
            provenance = value
        else:
            raise CollectionUpdatePlanError(
                f"The {label} ROM {path!r} has invalid SMWC submission provenance."
            )
        if path in result and result[path] != provenance:
            raise CollectionUpdatePlanError(
                f"The {label} Collection record repeats ROM path {path!r} with conflicting "
                "SMWC submission provenance."
            )
        result[path] = provenance
    return result


def _overlay_existing_target_merge_choices(
    plan: CollectionChangePlan,
    review: CollectionUpdateExistingTargetMergeReview,
    decision: CollectionUpdateExistingTargetMergeDecision,
    source_record: Mapping[str, Any],
    target_record: Mapping[str, Any],
) -> CollectionChangePlan:
    target_key = decision.target_collection_key
    conflict_by_field = {item.field: item for item in review.field_conflicts}
    user_updates = list(plan.user_state_updates)
    first_clear_updates = list(plan.first_clear_selections)
    for item in decision.field_decisions:
        conflict = conflict_by_field[item.field]
        if item.origin is MergeValueOrigin.SOURCE:
            value = source_record.get(item.field)
            origin_label = "source"
        else:
            value = target_record.get(item.field)
            origin_label = "target"
        expected_value = (
            conflict.source_value if item.origin is MergeValueOrigin.SOURCE else conflict.target_value
        )
        if value != expected_value:
            raise CollectionUpdatePlanStaleStateError(
                f"Reviewed merge value changed for {item.field!r}. Start update discovery again."
            )
        reason = (
            "Explicit existing-target replacement merge review selected the "
            f"{origin_label} Collection value."
        )
        if item.field == "first_clear_playthrough":
            source, record_id = _first_clear_identity(value)
            first_clear_updates.append(
                FirstClearSelectionOperation(
                    target_key=target_key,
                    source=source,
                    source_record_id=record_id,
                    reason=reason,
                )
            )
            continue
        user_updates.append(
            UserStateOperation(
                target_key=target_key,
                field=item.field,
                value=value,
                source=IngestionSource.MANUAL,
                reason=reason,
            )
        )

    primary_updates = list(plan.primary_rom_selections)
    if review.primary_rom_required:
        primary_updates.append(
            PrimaryRomSelectionOperation(
                target_key=target_key,
                primary_path=decision.primary_rom_path,
                reason="Explicit existing-target replacement merge review selected this primary ROM.",
            )
        )
    return replace(
        plan,
        user_state_updates=tuple(
            sorted(user_updates, key=lambda item: (item.target_key, item.field, item.source.value))
        ),
        primary_rom_selections=tuple(primary_updates),
        first_clear_selections=tuple(first_clear_updates),
    )


def _first_clear_identity(value: Any) -> tuple[str, str]:
    if not isinstance(value, Mapping):
        raise CollectionUpdatePlanError(
            "Reviewed first-clear value is not a source-scoped playthrough reference."
        )
    source = value.get("source")
    record_id = value.get("source_record_id")
    if not isinstance(source, str) or not source or not isinstance(record_id, str) or not record_id:
        raise CollectionUpdatePlanError(
            "Reviewed first-clear value is missing source or source_record_id."
        )
    return source, record_id


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
    "finalize_collection_update_existing_target_merge_plan",
    "finalize_collection_update_existing_target_selection_plan",
    "finalize_collection_update_replacement_plan",
    "finalize_collection_update_selection_plan",
]
