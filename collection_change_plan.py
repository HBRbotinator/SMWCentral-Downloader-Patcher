"""Immutable semantic change plans finalized from reviewed ingestion evidence."""
from __future__ import annotations

from dataclasses import dataclass
import re
from enum import Enum
from typing import Iterable, Mapping, Sequence

from collection_ingestion import (
    EvidenceStrength,
    IdentityEvidenceKind,
    IngestionSource,
    SharedMetadataEvidence,
    UserPlaythroughEvidence,
)
from collection_reconciliation import (
    IdentityMigrationKind,
    ReconciliationError,
    ReconciliationGroup,
    ReviewAction,
    ReviewDecision,
    UserFieldProposal,
    automatic_first_clear,
    is_local_collection_key,
    is_numeric_collection_key,
    resolved_target_key,
    validate_collection_key,
    validate_review_decision,
)


class PlanFinalizationError(ReconciliationError):
    """Raised when reviewed evidence cannot become one deterministic plan."""


_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class RecordIntentKind(str, Enum):
    """Whether the resolved target already exists in the reviewed Collection."""

    CREATE = "create"
    UPDATE = "update"


@dataclass(frozen=True)
class StorePrecondition:
    """Opaque reviewed-state token checked later by the transactional apply layer."""

    store_name: str
    revision_token: str

    def __post_init__(self) -> None:
        if not self.store_name.strip() or not self.revision_token.strip():
            raise PlanFinalizationError("Store preconditions require name and revision token.")


@dataclass(frozen=True)
class RecordIntent:
    """One resolved Collection target and whether it is created or updated."""

    target_key: str
    kind: RecordIntentKind

    def __post_init__(self) -> None:
        validate_collection_key(self.target_key)


@dataclass(frozen=True)
class CatalogueMetadataSnapshot:
    """Durable shared metadata owned by KaizOFF/SMWC for a numeric submission."""

    submission_id: int
    title: str
    authors: tuple[str, ...]
    difficulty: str
    hack_types: tuple[str, ...]
    exits: int | None
    release_timestamp: int | None
    rating: float | None
    hall_of_fame: bool | None
    sa1_compatible: bool | None
    collaboration: bool | None
    demo: bool | None


@dataclass(frozen=True)
class CatalogueMetadataOperation:
    """Refresh provider-owned durable metadata with explicit source provenance."""

    target_key: str
    metadata: CatalogueMetadataSnapshot
    source: IngestionSource
    source_candidate_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not is_numeric_collection_key(self.target_key):
            raise PlanFinalizationError("Catalogue metadata target must be numeric SMWC ID.")
        if self.source is not IngestionSource.KAIZOFF:
            raise PlanFinalizationError("KaizOFF is the catalogue metadata authority.")
        if self.metadata.submission_id != int(self.target_key):
            raise PlanFinalizationError("Catalogue snapshot ID must match its target key.")


@dataclass(frozen=True)
class LocalRecordSeedOperation:
    """User-owned metadata used only when a new usr_* record is created."""

    target_key: str
    title: str
    authors: tuple[str, ...]
    difficulty: str = ""
    hack_types: tuple[str, ...] = ()
    exits: int | None = None
    source_candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not is_local_collection_key(self.target_key):
            raise PlanFinalizationError("Local record seed requires an opaque usr_* target.")
        if not self.title.strip():
            raise PlanFinalizationError("Local record seed requires a title.")
        if self.exits is not None and (isinstance(self.exits, bool) or self.exits < 0):
            raise PlanFinalizationError("Local record exits cannot be negative.")


@dataclass(frozen=True)
class PlannedRomAsset:
    """One retained local ROM path with byte identity and source provenance."""

    path: str
    filename: str
    sha256: str
    size_bytes: int
    sources: tuple[IngestionSource, ...]
    source_candidate_ids: tuple[str, ...]
    smwc_submission_id: int | None = None

    def __post_init__(self) -> None:
        if not self.path or not self.filename:
            raise PlanFinalizationError("Planned ROM asset requires path and filename.")
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise PlanFinalizationError("Planned ROM asset requires lowercase SHA-256.")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise PlanFinalizationError("Planned ROM asset size cannot be negative.")
        if not self.sources or not self.source_candidate_ids:
            raise PlanFinalizationError("Planned ROM asset requires source provenance.")
        if self.smwc_submission_id is not None and (
            isinstance(self.smwc_submission_id, bool) or self.smwc_submission_id <= 0
        ):
            raise PlanFinalizationError("ROM SMWC submission provenance must be positive.")


@dataclass(frozen=True)
class RomAssetsOperation:
    """Add/retain ROM assets and explicitly set or preserve the primary choice."""

    target_key: str
    assets: tuple[PlannedRomAsset, ...]
    primary_path: str = ""
    preserve_existing_primary: bool = False

    def __post_init__(self) -> None:
        validate_collection_key(self.target_key)
        if not self.assets:
            raise PlanFinalizationError("ROM operation requires at least one retained asset.")
        if self.primary_path and self.preserve_existing_primary:
            raise PlanFinalizationError(
                "ROM operation cannot both set and preserve the primary path."
            )
        paths = {asset.path for asset in self.assets}
        if self.primary_path and self.primary_path not in paths:
            raise PlanFinalizationError("Primary ROM must be included in retained assets.")


@dataclass(frozen=True)
class UserHistoryOperation:
    """Preserve imported playthrough evidence plus the verified first-clear selection."""

    target_key: str
    playthroughs: tuple[UserPlaythroughEvidence, ...]
    first_clear_decided: bool
    first_clear_source: IngestionSource | None = None
    first_clear_source_record_id: str | None = None

    def __post_init__(self) -> None:
        validate_collection_key(self.target_key)
        if not self.playthroughs:
            raise PlanFinalizationError("History operation requires imported playthroughs.")
        if not self.first_clear_decided:
            raise PlanFinalizationError("Final plan cannot contain unresolved first-clear state.")
        if (self.first_clear_source is None) != (self.first_clear_source_record_id is None):
            raise PlanFinalizationError(
                "First-clear reference requires both source and source_record_id."
            )
        if self.first_clear_source_record_id is not None:
            known = {(item.source, item.source_record_id) for item in self.playthroughs}
            if (self.first_clear_source, self.first_clear_source_record_id) not in known:
                raise PlanFinalizationError("First-clear reference must select imported history.")


@dataclass(frozen=True)
class UserStateOperation:
    """One resolved scalar update to user-owned Collection state."""

    target_key: str
    field: str
    value: bool | int | float | str | None
    source: IngestionSource
    reason: str

    def __post_init__(self) -> None:
        validate_collection_key(self.target_key)
        if not self.field or not self.reason.strip():
            raise PlanFinalizationError("User-state operation requires field and provenance.")
        if self.source in {
            IngestionSource.KAIZOFF,
            IngestionSource.ROM_SCAN,
            IngestionSource.TOOL_PATCH,
        }:
            raise PlanFinalizationError(
                f"{self.source.value} cannot own finalized user-state changes."
            )


@dataclass(frozen=True)
class FirstClearSelectionOperation:
    """Select one existing imported playthrough reference as first clear after a merge."""

    target_key: str
    source: str
    source_record_id: str
    reason: str

    def __post_init__(self) -> None:
        validate_collection_key(self.target_key)
        if not self.source.strip() or not self.source_record_id.strip():
            raise PlanFinalizationError("First-clear selection requires source identity.")
        if not self.reason.strip():
            raise PlanFinalizationError("First-clear selection requires review provenance.")


@dataclass(frozen=True)
class PrimaryRomSelectionOperation:
    """Select one already-retained ROM path as primary after reconciliation/merge."""

    target_key: str
    primary_path: str
    reason: str

    def __post_init__(self) -> None:
        validate_collection_key(self.target_key)
        if not isinstance(self.primary_path, str) or not self.primary_path:
            raise PlanFinalizationError("Primary ROM selection requires a path.")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise PlanFinalizationError("Primary ROM selection requires review provenance.")


@dataclass(frozen=True)
class IdentityMigrationOperation:
    """Move/merge one reviewed Collection identity into another."""

    source_key: str
    target_key: str
    kind: IdentityMigrationKind
    merge_existing_target: bool
    prior_submission_ids: tuple[int, ...]
    provenance: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_collection_key(self.source_key)
        validate_collection_key(self.target_key)
        if self.source_key == self.target_key:
            raise PlanFinalizationError("Identity migration source and target must differ.")
        if self.kind is IdentityMigrationKind.LOCAL_PROMOTION:
            if not is_local_collection_key(self.source_key):
                raise PlanFinalizationError("Local promotion must start at usr_* identity.")
            if not is_numeric_collection_key(self.target_key):
                raise PlanFinalizationError("Local promotion must target numeric SMWC identity.")
            if self.prior_submission_ids:
                raise PlanFinalizationError("Local promotion cannot retain numeric provenance.")
        elif self.kind is IdentityMigrationKind.SUBMISSION_REPLACEMENT:
            if not is_numeric_collection_key(self.source_key):
                raise PlanFinalizationError("Submission replacement source must be numeric.")
            if not is_numeric_collection_key(self.target_key):
                raise PlanFinalizationError("Submission replacement target must be numeric.")
            if int(self.source_key) not in self.prior_submission_ids:
                raise PlanFinalizationError(
                    "Submission replacement must retain its previous SMWC ID provenance."
                )


@dataclass(frozen=True)
class ReferenceMigrationOperation:
    """Request every registered dependent store to repoint one Collection key."""

    source_key: str
    target_key: str

    def __post_init__(self) -> None:
        validate_collection_key(self.source_key)
        validate_collection_key(self.target_key)
        if self.source_key == self.target_key:
            raise PlanFinalizationError("Reference migration source and target must differ.")


@dataclass(frozen=True)
class IgnoredRomOperation:
    """Suppress rediscovery only while both path and SHA-256 remain unchanged."""

    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.path or _SHA256_RE.fullmatch(self.sha256) is None:
            raise PlanFinalizationError("Ignored ROM requires path + lowercase SHA-256.")


@dataclass(frozen=True)
class RememberedAssociationOperation:
    """Persist a user-confirmed source-scoped matching hint."""

    source: IngestionSource
    value: str
    target_key: str

    def __post_init__(self) -> None:
        validate_collection_key(self.target_key)
        if not self.value.strip():
            raise PlanFinalizationError("Remembered association value must be non-empty.")


@dataclass(frozen=True)
class CollectionChangePlan:
    """Complete deterministic result of a reviewed reconciliation session."""

    preconditions: tuple[StorePrecondition, ...]
    record_intents: tuple[RecordIntent, ...]
    catalogue_updates: tuple[CatalogueMetadataOperation, ...]
    local_record_seeds: tuple[LocalRecordSeedOperation, ...]
    rom_updates: tuple[RomAssetsOperation, ...]
    user_history_updates: tuple[UserHistoryOperation, ...]
    user_state_updates: tuple[UserStateOperation, ...]
    identity_migrations: tuple[IdentityMigrationOperation, ...]
    reference_migrations: tuple[ReferenceMigrationOperation, ...]
    ignored_roms: tuple[IgnoredRomOperation, ...]
    remembered_associations: tuple[RememberedAssociationOperation, ...]
    skipped_candidate_ids: tuple[str, ...]
    ignored_candidate_ids: tuple[str, ...]
    primary_rom_selections: tuple[PrimaryRomSelectionOperation, ...] = ()
    first_clear_selections: tuple[FirstClearSelectionOperation, ...] = ()

    @property
    def creates(self) -> tuple[RecordIntent, ...]:
        return tuple(item for item in self.record_intents if item.kind is RecordIntentKind.CREATE)

    @property
    def updates(self) -> tuple[RecordIntent, ...]:
        return tuple(item for item in self.record_intents if item.kind is RecordIntentKind.UPDATE)


def catalogue_snapshot_from_evidence(
    target_key: str,
    evidence: SharedMetadataEvidence,
) -> CatalogueMetadataSnapshot:
    """Project only durable provider-owned fields into the finalized plan."""

    if evidence.source is not IngestionSource.KAIZOFF:
        raise PlanFinalizationError("Only KaizOFF may own catalogue metadata snapshots.")
    if not is_numeric_collection_key(target_key):
        raise PlanFinalizationError("Catalogue metadata requires a numeric SMWC target.")
    return CatalogueMetadataSnapshot(
        submission_id=int(target_key),
        title=evidence.title,
        authors=tuple(evidence.authors),
        difficulty=evidence.difficulty,
        hack_types=tuple(evidence.hack_types),
        exits=evidence.exits,
        release_timestamp=evidence.release_timestamp,
        rating=evidence.rating,
        hall_of_fame=evidence.hall_of_fame,
        sa1_compatible=evidence.sa1_compatible,
        collaboration=evidence.collaboration,
        demo=evidence.demo,
    )


def _candidate_smwc_id(member, target_key: str) -> int | None:
    if not is_numeric_collection_key(target_key):
        return None
    matching = []
    for evidence in member.candidate.identity_evidence:
        if evidence.kind is not IdentityEvidenceKind.SMWC_SUBMISSION_ID:
            continue
        if evidence.value != target_key:
            continue
        if evidence.strength not in {EvidenceStrength.EXACT, EvidenceStrength.STRONG}:
            continue
        matching.append(int(target_key))
    if matching:
        return matching[0]
    return None


def _rom_assets_for_group(
    group: ReconciliationGroup,
    target_key: str,
    decision: ReviewDecision | None,
    target_exists: bool,
) -> tuple[RomAssetsOperation | None, tuple[IgnoredRomOperation, ...]]:
    rows = []
    for member in group.members:
        submission_id = _candidate_smwc_id(member, target_key)
        for rom in member.candidate.rom_files:
            rows.append(
                (
                    member.candidate_id,
                    member.candidate.source,
                    rom,
                    submission_id,
                )
            )
    if not rows:
        return None, ()

    by_path = {}
    for candidate_id, source, rom, submission_id in rows:
        existing = by_path.get(rom.path)
        if existing is None:
            by_path[rom.path] = {
                "rom": rom,
                "submission_id": submission_id,
                "sources": {source},
                "candidate_ids": {candidate_id},
            }
            continue
        if existing["rom"] != rom or existing["submission_id"] != submission_id:
            raise PlanFinalizationError(
                f"Conflicting ROM evidence for one path: {rom.path!r}"
            )
        existing["sources"].add(source)
        existing["candidate_ids"].add(candidate_id)

    selection = decision.rom_selection if decision is not None else None
    if selection is None:
        kept_paths = tuple(sorted(by_path))
        ignored = ()
        migration_confirmed = (
            group.migration is not None
            and decision is not None
            and decision.action is ReviewAction.CONFIRM_MIGRATION
        )
        if target_exists or migration_confirmed:
            primary_path = ""
            preserve_existing_primary = True
        else:
            primary_path = kept_paths[0]
            preserve_existing_primary = False
    else:
        kept_paths = selection.kept_paths
        primary_path = selection.primary_path
        preserve_existing_primary = False
        ignored = tuple(
            IgnoredRomOperation(path=item.path, sha256=item.sha256)
            for item in selection.ignored
        )

    assets = []
    for path in kept_paths:
        row = by_path[path]
        rom = row["rom"]
        assets.append(
            PlannedRomAsset(
                path=rom.path,
                filename=rom.filename,
                sha256=rom.sha256,
                size_bytes=rom.size_bytes,
                sources=tuple(sorted(row["sources"], key=lambda item: item.value)),
                source_candidate_ids=tuple(sorted(row["candidate_ids"])),
                smwc_submission_id=row["submission_id"],
            )
        )
    return (
        RomAssetsOperation(
            target_key=target_key,
            assets=tuple(assets),
            primary_path=primary_path,
            preserve_existing_primary=preserve_existing_primary,
        ),
        ignored,
    )

def _catalogue_operation(
    group: ReconciliationGroup,
    target_key: str,
) -> CatalogueMetadataOperation | None:
    evidence = tuple(
        (member.candidate_id, metadata)
        for member in group.members
        for metadata in member.candidate.shared_metadata
        if metadata.source is IngestionSource.KAIZOFF
    )
    if not evidence:
        return None
    if not is_numeric_collection_key(target_key):
        return None
    snapshots = tuple(
        catalogue_snapshot_from_evidence(target_key, item)
        for _, item in evidence
    )
    distinct = tuple(dict.fromkeys(snapshots))
    if len(distinct) != 1:
        raise PlanFinalizationError(
            "One target has conflicting KaizOFF metadata snapshots; reconcile again."
        )
    return CatalogueMetadataOperation(
        target_key=target_key,
        metadata=distinct[0],
        source=IngestionSource.KAIZOFF,
        source_candidate_ids=tuple(sorted({candidate_id for candidate_id, _ in evidence})),
    )

def _local_seed_operation(
    group: ReconciliationGroup,
    target_key: str,
    target_exists: bool,
) -> LocalRecordSeedOperation | None:
    if target_exists or not is_local_collection_key(target_key):
        return None

    manual_metadata = tuple(
        (member.candidate_id, metadata)
        for member in group.members
        for metadata in member.candidate.shared_metadata
        if metadata.source is IngestionSource.MANUAL
    )
    if manual_metadata:
        snapshots = tuple(
            (
                metadata.title.strip(),
                tuple(metadata.authors),
                metadata.difficulty,
                tuple(metadata.hack_types),
                metadata.exits,
            )
            for _, metadata in manual_metadata
        )
        distinct = tuple(dict.fromkeys(snapshots))
        if len(distinct) != 1:
            raise PlanFinalizationError(
                "New local Collection record has conflicting manual metadata."
            )
        title, authors, difficulty, hack_types, exits = distinct[0]
        if not title:
            raise PlanFinalizationError("New local Collection record requires a title.")
        return LocalRecordSeedOperation(
            target_key=target_key,
            title=title,
            authors=authors,
            difficulty=difficulty,
            hack_types=hack_types,
            exits=exits,
            source_candidate_ids=tuple(
                sorted({candidate_id for candidate_id, _ in manual_metadata})
            ),
        )

    titles = tuple(
        title.strip()
        for member in group.members
        for title in member.candidate.title_hints
        if title.strip()
    )
    if not titles:
        raise PlanFinalizationError("New local Collection record requires a title hint.")
    authors = tuple(
        dict.fromkeys(
            author.strip()
            for member in group.members
            for author in member.candidate.author_hints
            if author.strip()
        )
    )
    return LocalRecordSeedOperation(
        target_key=target_key,
        title=titles[0],
        authors=authors,
        source_candidate_ids=tuple(sorted(member.candidate_id for member in group.members)),
    )

def _history_operation(
    group: ReconciliationGroup,
    target_key: str,
    decision: ReviewDecision | None,
) -> UserHistoryOperation | None:
    history = group.user_history
    if not history:
        return None
    by_identity: dict[tuple[IngestionSource, str], UserPlaythroughEvidence] = {}
    for item in history:
        key = (item.source, item.source_record_id)
        previous = by_identity.get(key)
        if previous is not None and previous != item:
            raise PlanFinalizationError(
                "One imported playthrough identity contains conflicting history evidence."
            )
        by_identity[key] = item
    playthroughs = tuple(by_identity[key] for key in sorted(by_identity, key=lambda x: (x[0].value, x[1])))

    if decision is not None and decision.first_clear is not None:
        if not decision.first_clear.decided:
            raise PlanFinalizationError("First-clear decision was not finalized.")
        first_clear_source = decision.first_clear.source
        first_clear = decision.first_clear.source_record_id
        if first_clear is not None:
            known = {(item.source, item.source_record_id) for item in playthroughs}
            if (first_clear_source, first_clear) not in known:
                raise PlanFinalizationError(
                    "Selected first-clear playthrough is not present in imported history."
                )
        first_clear_decided = True
    else:
        automatic = automatic_first_clear(playthroughs)
        if automatic is None:
            raise PlanFinalizationError(
                "Ambiguous/PB/multiple playthrough history requires first-clear review."
            )
        first_clear_source = automatic.source
        first_clear = automatic.source_record_id
        first_clear_decided = True

    return UserHistoryOperation(
        target_key=target_key,
        playthroughs=playthroughs,
        first_clear_decided=first_clear_decided,
        first_clear_source=first_clear_source,
        first_clear_source_record_id=first_clear,
    )


def _user_state_operations(
    group: ReconciliationGroup,
    target_key: str,
    decision: ReviewDecision | None,
) -> tuple[UserStateOperation, ...]:
    proposals: dict[str, UserFieldProposal] = {}
    for proposal in group.user_field_proposals:
        previous = proposals.get(proposal.field)
        if previous is not None and previous.proposed_value != proposal.proposed_value:
            raise PlanFinalizationError(
                f"Multiple incompatible proposals exist for user field {proposal.field!r}."
            )
        if previous is None or (proposal.conflict and not previous.conflict):
            proposals[proposal.field] = proposal

    choices = {}
    if decision is not None:
        choices = {item.field: item.use_proposed for item in decision.user_field_resolutions}

    operations = []
    for field in sorted(proposals):
        proposal = proposals[field]
        if proposal.conflict and not choices.get(field, False):
            continue
        if proposal.current_value == proposal.proposed_value:
            continue
        operations.append(
            UserStateOperation(
                target_key=target_key,
                field=proposal.field,
                value=proposal.proposed_value,
                source=proposal.source,
                reason=proposal.reason,
            )
        )
    return tuple(operations)


def _identity_migration_operation(
    group: ReconciliationGroup,
    decision: ReviewDecision | None,
    existing_keys: frozenset[str],
) -> tuple[IdentityMigrationOperation | None, ReferenceMigrationOperation | None]:
    if group.migration is None:
        return None, None
    if decision is None or decision.action is not ReviewAction.CONFIRM_MIGRATION:
        return None, None
    proposal = group.migration
    if proposal.source_key not in existing_keys:
        raise PlanFinalizationError("Identity migration source is not in reviewed Collection state.")
    provenance = tuple(
        dict.fromkeys(
            member.reason.strip()
            for member in group.members
            if member.reason.strip()
        )
    )
    operation = IdentityMigrationOperation(
        source_key=proposal.source_key,
        target_key=proposal.target_key,
        kind=proposal.kind,
        merge_existing_target=proposal.target_key in existing_keys,
        prior_submission_ids=proposal.retained_submission_ids,
        provenance=provenance,
    )
    return (
        operation,
        ReferenceMigrationOperation(
            source_key=proposal.source_key,
            target_key=proposal.target_key,
        ),
    )


def _record_intent(
    target_key: str,
    existing_keys: frozenset[str],
    migration: IdentityMigrationOperation | None,
) -> RecordIntent:
    if target_key in existing_keys or (
        migration is not None and migration.merge_existing_target
    ):
        kind = RecordIntentKind.UPDATE
    else:
        kind = RecordIntentKind.CREATE
    return RecordIntent(target_key=target_key, kind=kind)


def _dedupe_equal_by_key(items, key, label: str):
    result = {}
    for item in items:
        item_key = key(item)
        previous = result.get(item_key)
        if previous is not None and previous != item:
            raise PlanFinalizationError(f"Conflicting {label} operations for {item_key!r}.")
        result[item_key] = item
    return tuple(result[value] for value in sorted(result))


def finalize_collection_change_plan(
    groups: Sequence[ReconciliationGroup],
    decisions: Mapping[str, ReviewDecision] | None = None,
    *,
    existing_collection_keys: Iterable[str] = (),
    local_identity_allocations: Mapping[str, str] | None = None,
    preconditions: Sequence[StorePrecondition] = (),
) -> CollectionChangePlan:
    """Finalize reviewed evidence without rerunning matching or making hidden choices."""

    decisions = dict(decisions or {})
    allocations = dict(local_identity_allocations or {})
    ordered_groups = tuple(sorted(groups, key=lambda item: item.group_id))
    group_ids = {group.group_id for group in ordered_groups}
    if len(group_ids) != len(ordered_groups):
        raise PlanFinalizationError("Reconciliation group IDs must be unique.")
    if set(decisions).difference(group_ids):
        raise PlanFinalizationError("Review decisions contain an unknown group ID.")
    if set(allocations).difference(group_ids):
        raise PlanFinalizationError("Local allocations contain an unknown group ID.")

    existing_keys = frozenset(validate_collection_key(value) for value in existing_collection_keys)
    for allocation in allocations.values():
        if not is_local_collection_key(allocation):
            raise PlanFinalizationError("Local identity allocations must be opaque usr_* IDs.")
    if len(set(allocations.values())) != len(allocations):
        raise PlanFinalizationError("Local identity allocations must be unique.")
    if set(allocations.values()).intersection(existing_keys):
        raise PlanFinalizationError("Allocated local identity already exists.")

    precondition_names = [item.store_name for item in preconditions]
    if len(precondition_names) != len(set(precondition_names)):
        raise PlanFinalizationError("Store precondition names must be unique.")

    record_intents = []
    catalogue_updates = []
    local_seeds = []
    rom_updates = []
    history_updates = []
    user_state_updates = []
    migrations = []
    reference_migrations = []
    ignored_roms = []
    remembered = []
    skipped_candidate_ids = []
    ignored_candidate_ids = []
    used_allocations = set()

    for group in ordered_groups:
        decision = decisions.get(group.group_id)
        try:
            validate_review_decision(group, decision)
        except ReconciliationError as error:
            raise PlanFinalizationError(str(error)) from error

        if decision is not None and decision.action is ReviewAction.SKIP:
            skipped_candidate_ids.extend(member.candidate_id for member in group.members)
            continue
        if decision is not None and decision.action is ReviewAction.IGNORE:
            ignored_candidate_ids.extend(member.candidate_id for member in group.members)
            ignored_roms.extend(
                IgnoredRomOperation(path=rom.path, sha256=rom.sha256)
                for rom in group.rom_files
            )
            continue

        local_identity = ""
        if decision is not None and decision.action is ReviewAction.IMPORT_LOCAL:
            local_identity = allocations.get(group.group_id, "")
            used_allocations.add(group.group_id)
        try:
            target_key = resolved_target_key(group, decision, local_identity)
        except ReconciliationError as error:
            raise PlanFinalizationError(str(error)) from error
        if target_key is None:
            raise PlanFinalizationError("Non-skipped group finalized without a target.")

        migration, reference_migration = _identity_migration_operation(
            group,
            decision,
            existing_keys,
        )
        if migration is not None:
            migrations.append(migration)
            reference_migrations.append(reference_migration)

        target_exists = target_key in existing_keys
        record_intents.append(_record_intent(target_key, existing_keys, migration))

        catalogue = _catalogue_operation(group, target_key)
        if catalogue is not None:
            catalogue_updates.append(catalogue)

        local_seed = _local_seed_operation(group, target_key, target_exists)
        if local_seed is not None:
            local_seeds.append(local_seed)

        rom_operation, ignored = _rom_assets_for_group(
            group,
            target_key,
            decision,
            target_exists,
        )
        if rom_operation is not None:
            rom_updates.append(rom_operation)
        ignored_roms.extend(ignored)

        history = _history_operation(group, target_key, decision)
        if history is not None:
            history_updates.append(history)

        user_state_updates.extend(_user_state_operations(group, target_key, decision))

        if decision is not None:
            remembered.extend(
                RememberedAssociationOperation(
                    source=item.source,
                    value=item.value,
                    target_key=target_key,
                )
                for item in decision.remembered_associations
            )

    if used_allocations != set(allocations):
        raise PlanFinalizationError("Unused local identity allocation supplied to plan finalization.")

    record_intents = _dedupe_equal_by_key(
        record_intents,
        key=lambda item: item.target_key,
        label="record intent",
    )
    catalogue_updates = _dedupe_equal_by_key(
        catalogue_updates,
        key=lambda item: item.target_key,
        label="catalogue metadata",
    )
    local_seeds = _dedupe_equal_by_key(
        local_seeds,
        key=lambda item: item.target_key,
        label="local record seed",
    )
    rom_updates = _dedupe_equal_by_key(
        rom_updates,
        key=lambda item: item.target_key,
        label="ROM asset",
    )
    history_updates = _dedupe_equal_by_key(
        history_updates,
        key=lambda item: item.target_key,
        label="user history",
    )
    migrations = _dedupe_equal_by_key(
        migrations,
        key=lambda item: item.source_key,
        label="identity migration",
    )
    reference_migrations = _dedupe_equal_by_key(
        reference_migrations,
        key=lambda item: item.source_key,
        label="reference migration",
    )

    migration_sources = {item.source_key for item in migrations}
    migration_targets = {item.target_key for item in migrations}
    if migration_sources.intersection(migration_targets):
        raise PlanFinalizationError(
            "One change plan cannot contain chained/cyclic identity migrations."
        )
    active_targets = {item.target_key for item in record_intents}
    stale_sources = migration_sources.intersection(active_targets)
    if stale_sources:
        raise PlanFinalizationError(
            "A migrated source identity cannot also remain an active plan target: "
            f"{sorted(stale_sources)!r}"
        )

    ignored_roms = _dedupe_equal_by_key(
        ignored_roms,
        key=lambda item: (item.path, item.sha256),
        label="ignored ROM",
    )
    remembered = _dedupe_equal_by_key(
        remembered,
        key=lambda item: (item.source.value, item.value, item.target_key),
        label="remembered association",
    )

    user_state_updates = tuple(
        sorted(
            user_state_updates,
            key=lambda item: (item.target_key, item.field, item.source.value),
        )
    )

    return CollectionChangePlan(
        preconditions=tuple(sorted(preconditions, key=lambda item: item.store_name)),
        record_intents=record_intents,
        catalogue_updates=catalogue_updates,
        local_record_seeds=local_seeds,
        rom_updates=rom_updates,
        user_history_updates=history_updates,
        user_state_updates=user_state_updates,
        identity_migrations=migrations,
        reference_migrations=reference_migrations,
        ignored_roms=ignored_roms,
        remembered_associations=remembered,
        skipped_candidate_ids=tuple(sorted(set(skipped_candidate_ids))),
        ignored_candidate_ids=tuple(sorted(set(ignored_candidate_ids))),
    )


__all__ = [
    "CatalogueMetadataOperation",
    "CatalogueMetadataSnapshot",
    "CollectionChangePlan",
    "IdentityMigrationOperation",
    "IgnoredRomOperation",
    "LocalRecordSeedOperation",
    "PlanFinalizationError",
    "PlannedRomAsset",
    "RecordIntent",
    "RecordIntentKind",
    "ReferenceMigrationOperation",
    "RememberedAssociationOperation",
    "RomAssetsOperation",
    "StorePrecondition",
    "UserHistoryOperation",
    "UserStateOperation",
    "catalogue_snapshot_from_evidence",
    "finalize_collection_change_plan",
]
