"""Runtime composition for real Collection ingestion review and plan preview."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from collection_change_plan import CollectionChangePlan
from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion_finalization import finalize_reviewed_ingestion_session
from collection_plan_apply import (
    COLLECTION_APPLY_JOURNAL_FILENAME,
    CollectionPlanApplyResult,
    apply_collection_change_plan,
    recover_interrupted_collection_apply,
)
from collection_ingestion_session import (
    CollectionIngestionSession,
    create_collection_ingestion_session,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffCatalogueProvider
from planner_reference_participant import PlannerCollectionReferenceParticipant
from save_sync_reference_participant import SaveSyncAssociationReferenceParticipant


KAIZOFF_CACHE_DIRECTORY = "kaizoff_cache"


class CollectionIngestionEntrypointError(ValueError):
    """Raised before source orchestration when a launch selection is invalid."""


@dataclass(frozen=True)
class CollectionIngestionSourceSelection:
    """User-selected real inputs for one non-persisting ingestion session."""

    rom_root: str = ""
    giganticbucket_path: str = ""

    @property
    def has_rom_source(self) -> bool:
        return bool(self.rom_root)

    @property
    def has_giganticbucket_source(self) -> bool:
        return bool(self.giganticbucket_path)


def validate_collection_ingestion_selection(
    selection: CollectionIngestionSourceSelection,
) -> CollectionIngestionSourceSelection:
    """Validate and freeze real filesystem source paths before background work."""

    if not isinstance(selection, CollectionIngestionSourceSelection):
        raise CollectionIngestionEntrypointError(
            "Collection import source selection has an invalid shape."
        )

    rom_root = str(selection.rom_root or "").strip()
    giganticbucket_path = str(selection.giganticbucket_path or "").strip()
    if not rom_root and not giganticbucket_path:
        raise CollectionIngestionEntrypointError(
            "Choose a ROM folder, a GiganticBucket JSON export, or both."
        )

    normalized_rom = ""
    if rom_root:
        path = Path(rom_root).expanduser()
        if not path.is_dir():
            raise CollectionIngestionEntrypointError(
                f"ROM import folder does not exist: {rom_root}"
            )
        normalized_rom = str(path.resolve())

    normalized_bucket = ""
    if giganticbucket_path:
        path = Path(giganticbucket_path).expanduser()
        if path.suffix.casefold() != ".json":
            raise CollectionIngestionEntrypointError(
                "GiganticBucket import must be a .json export."
            )
        if not path.is_file():
            raise CollectionIngestionEntrypointError(
                f"GiganticBucket JSON does not exist: {giganticbucket_path}"
            )
        normalized_bucket = str(path.resolve())

    return CollectionIngestionSourceSelection(
        rom_root=normalized_rom,
        giganticbucket_path=normalized_bucket,
    )


def known_difficulties_from_config(config: Mapping | None) -> tuple[str, ...]:
    """Extract stable display difficulties for weak folder-name hints."""

    if not isinstance(config, Mapping):
        return ()
    lookup = config.get("difficulty_lookup", {})
    if not isinstance(lookup, Mapping):
        return ()
    values = []
    seen = set()
    for value in lookup.values():
        text = str(value or "").strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        values.append(text)
    return tuple(values)


def kaizoff_cache_dir_for_processed_json(processed_json_path: str | Path) -> Path:
    """Keep provider cache beside the application's user-owned Collection state."""

    processed = Path(processed_json_path).expanduser().resolve()
    return processed.with_name(KAIZOFF_CACHE_DIRECTORY)


def collection_identity_reference_participants(
    processed_json_path: str | Path,
):
    """Compose optional feature-owned stores that persist Collection identities."""

    processed = Path(processed_json_path).expanduser().resolve()
    return (
        SaveSyncAssociationReferenceParticipant.beside_processed_json(processed),
        PlannerCollectionReferenceParticipant.beside_processed_json(processed),
    )


def create_collection_ingestion_review_session(
    processed_json_path: str | Path,
    selection: CollectionIngestionSourceSelection,
    *,
    known_difficulties: Sequence[str] = (),
    force_catalogue_refresh: bool = False,
    provider: KaizOffCatalogueProvider | None = None,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants=None,
) -> CollectionIngestionSession:
    """Wire real sources into one frozen review session without applying changes."""

    normalized = validate_collection_ingestion_selection(selection)
    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = _runtime_manager(processed, manager)
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(
        processed
    )
    runtime_provider = provider or KaizOffCatalogueProvider(
        cache_dir=kaizoff_cache_dir_for_processed_json(processed)
    )
    runtime_participants = (
        collection_identity_reference_participants(processed)
        if participants is None
        else tuple(participants)
    )

    return create_collection_ingestion_session(
        runtime_manager,
        hints,
        runtime_provider,
        rom_root=normalized.rom_root or None,
        giganticbucket_path=normalized.giganticbucket_path or None,
        known_difficulties=tuple(known_difficulties),
        participants=tuple(runtime_participants),
        force_catalogue_refresh=force_catalogue_refresh,
    )


def finalize_collection_ingestion_review_plan(
    processed_json_path: str | Path,
    session: CollectionIngestionSession,
    decisions,
    *,
    force_detail_refresh: bool = False,
    provider: KaizOffCatalogueProvider | None = None,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants=None,
    id_factory=None,
):
    """Hydrate completed review into a final immutable plan without Apply."""

    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = _runtime_manager(processed, manager)
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(
        processed
    )
    runtime_provider = provider or KaizOffCatalogueProvider(
        cache_dir=kaizoff_cache_dir_for_processed_json(processed)
    )
    runtime_participants = (
        collection_identity_reference_participants(processed)
        if participants is None
        else tuple(participants)
    )
    kwargs = {
        "participants": tuple(runtime_participants),
        "force_detail_refresh": force_detail_refresh,
    }
    if id_factory is not None:
        kwargs["id_factory"] = id_factory
    return finalize_reviewed_ingestion_session(
        session,
        decisions,
        runtime_manager,
        hints,
        runtime_provider,
        **kwargs,
    )



def apply_collection_ingestion_plan(
    processed_json_path: str | Path,
    plan: CollectionChangePlan,
    *,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants=None,
) -> CollectionPlanApplyResult:
    """Apply the already-finalized immutable plan without discovery or network work."""

    if not isinstance(plan, CollectionChangePlan):
        raise CollectionIngestionEntrypointError(
            "Collection import Apply requires the finalized immutable change plan."
        )
    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = _runtime_manager(processed, manager)
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(
        processed
    )
    runtime_participants = (
        collection_identity_reference_participants(processed)
        if participants is None
        else tuple(participants)
    )
    return apply_collection_change_plan(
        plan,
        runtime_manager,
        hints,
        reference_participants=tuple(runtime_participants),
    )


def collection_ingestion_apply_recovery_pending(
    processed_json_path: str | Path,
) -> bool:
    """Return whether a prior coordinated Apply journal still needs attention."""

    processed = Path(processed_json_path).expanduser().resolve()
    return (processed.parent / COLLECTION_APPLY_JOURNAL_FILENAME).exists()


def recover_collection_ingestion_apply(
    processed_json_path: str | Path,
) -> bool:
    """Recover/clean a prior Apply only after the caller confirms it is abandoned."""

    processed = Path(processed_json_path).expanduser().resolve()
    return recover_interrupted_collection_apply(processed.parent)

def _runtime_manager(
    processed: Path,
    manager: HackDataManager | None,
) -> HackDataManager:
    runtime_manager = manager or HackDataManager(str(processed))
    if Path(runtime_manager.json_path).expanduser().resolve() != processed:
        raise CollectionIngestionEntrypointError(
            "Collection manager does not reference the selected processed.json."
        )
    return runtime_manager


__all__ = [
    "KAIZOFF_CACHE_DIRECTORY",
    "apply_collection_ingestion_plan",
    "collection_ingestion_apply_recovery_pending",
    "CollectionIngestionEntrypointError",
    "CollectionIngestionSourceSelection",
    "collection_identity_reference_participants",
    "create_collection_ingestion_review_session",
    "finalize_collection_ingestion_review_plan",
    "kaizoff_cache_dir_for_processed_json",
    "known_difficulties_from_config",
    "recover_collection_ingestion_apply",
    "validate_collection_ingestion_selection",
]
