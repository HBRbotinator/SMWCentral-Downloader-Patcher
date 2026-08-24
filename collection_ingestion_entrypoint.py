"""Non-persisting entrypoint wiring for real Collection ingestion review sessions."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from collection_identity_hints import CollectionIdentityHintsStore
from collection_ingestion_session import (
    CollectionIngestionSession,
    create_collection_ingestion_session,
)
from hack_data_manager import HackDataManager
from kaizoff_provider import KaizOffCatalogueProvider
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
    """Wire real sources into Commit 006 without finalizing or applying a plan."""

    normalized = validate_collection_ingestion_selection(selection)
    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = manager or HackDataManager(str(processed))
    if Path(runtime_manager.json_path).expanduser().resolve() != processed:
        raise CollectionIngestionEntrypointError(
            "Collection manager does not reference the selected processed.json."
        )

    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(
        processed
    )
    runtime_provider = provider or KaizOffCatalogueProvider(
        cache_dir=kaizoff_cache_dir_for_processed_json(processed)
    )
    runtime_participants = participants
    if runtime_participants is None:
        runtime_participants = (
            SaveSyncAssociationReferenceParticipant.beside_processed_json(processed),
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


__all__ = [
    "KAIZOFF_CACHE_DIRECTORY",
    "CollectionIngestionEntrypointError",
    "CollectionIngestionSourceSelection",
    "create_collection_ingestion_review_session",
    "kaizoff_cache_dir_for_processed_json",
    "known_difficulties_from_config",
    "validate_collection_ingestion_selection",
]
