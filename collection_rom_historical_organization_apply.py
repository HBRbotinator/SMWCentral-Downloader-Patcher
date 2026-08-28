"""Transactional Apply for finalized historical-provenance ROM organization plans.

Historical execution plans retain the exact SMWC submission metadata that justified
layout.  Apply validates that provenance against the matching Collection files[] row,
then delegates the already-proven copy/verify/journal/commit/cleanup mechanics to the
ordinary organization transaction engine.  No provider or discovery work occurs here.
"""
from __future__ import annotations

from collection_rom_historical_organization_execution_plan import (
    HistoricalRomOrganizationExecutionPlan,
)
from collection_rom_organization_apply import (
    CollectionRomOrganizationApplyResult,
    CollectionRomOrganizationStaleStateError,
    apply_collection_rom_organization_execution_plan,
)
from collection_rom_organization_execution_plan import (
    CollectionRomOrganizationExecutionPlan,
)
from collection_rom_organization_plan import CollectionRomMoveOperation
from hack_data_manager import HackDataManager


class HistoricalRomOrganizationApplyError(RuntimeError):
    """Raised when a finalized historical organization plan cannot be adapted safely."""


def _ordinary_execution_plan(
    plan: HistoricalRomOrganizationExecutionPlan,
) -> CollectionRomOrganizationExecutionPlan:
    """Preserve historical per-ROM provenance while reusing the transaction engine."""

    moves = tuple(
        CollectionRomMoveOperation(
            collection_id=move.collection_id,
            title=move.collection_title,
            asset_name=move.asset_name,
            source_path=move.source_path,
            target_path=move.target_path,
            sha256=move.sha256,
            size_bytes=move.size_bytes,
            source_mtime_ns=move.source_mtime_ns,
            primary=move.primary,
            # Critical: the generic Apply engine validates this value against the
            # exact matching files[] row.  For historical moves it must be the ROM's
            # own retained submission provenance, never the current Collection ID.
            smwc_submission_id=move.historical_smwc_submission_id,
        )
        for move in plan.rom_moves
    )
    return CollectionRomOrganizationExecutionPlan(
        output_dir=plan.output_dir,
        collection_revision_token=plan.collection_revision_token,
        save_review_fingerprint=plan.save_review_fingerprint,
        rom_moves=moves,
        save_moves=plan.save_moves,
        save_leaves=plan.save_leaves,
        blocked_move_count=plan.blocked_move_count,
        external_save_evidence_count=plan.external_save_evidence_count,
        rom_only_acknowledgement_count=plan.rom_only_acknowledgement_count,
    )


def apply_historical_rom_organization_execution_plan(
    plan: HistoricalRomOrganizationExecutionPlan,
    manager: HackDataManager,
    *,
    fail_after_target_copy: int | None = None,
    fail_after_store_replace: int | None = None,
    fail_after_commit: bool = False,
) -> CollectionRomOrganizationApplyResult:
    """Apply exactly one finalized historical plan with ordinary journal semantics."""

    if not isinstance(plan, HistoricalRomOrganizationExecutionPlan):
        raise TypeError("plan must be a HistoricalRomOrganizationExecutionPlan")
    if not isinstance(manager, HackDataManager):
        raise TypeError("manager must be a HackDataManager")

    try:
        ordinary = _ordinary_execution_plan(plan)
    except Exception as error:
        raise HistoricalRomOrganizationApplyError(
            f"Historical organization plan could not be adapted for Apply: {error}"
        ) from error

    # The ordinary transaction engine performs the decisive live checks, including
    # exact files[] ownership, SHA-256/size/primary state, smwc_submission_id,
    # file_path projection, targets, colocated-save evidence, journal conflicts,
    # rollback, commit ordering, and crash recovery.
    try:
        return apply_collection_rom_organization_execution_plan(
            ordinary,
            manager,
            fail_after_target_copy=fail_after_target_copy,
            fail_after_store_replace=fail_after_store_replace,
            fail_after_commit=fail_after_commit,
        )
    except CollectionRomOrganizationStaleStateError:
        raise
