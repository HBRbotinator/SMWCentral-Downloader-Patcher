"""Transactional application of finalized Collection ingestion change plans."""

from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from collection_change_plan import (
    CatalogueMetadataOperation,
    CollectionChangePlan,
    IdentityMigrationOperation,
    LocalRecordSeedOperation,
    RecordIntentKind,
    ReferenceMigrationOperation,
    RomAssetsOperation,
    RomSubmissionProvenanceOperation,
    StorePrecondition,
    UserHistoryOperation,
)
from collection_identity_hints import (
    CollectionIdentityHintsStore,
)
from collection_ingestion import UserPlaythroughEvidence
from collection_reconciliation import validate_collection_key
from hack_data_manager import HackDataManager


COLLECTION_STORE_NAME = "collection"
COLLECTION_APPLY_TEMP_MARKER = ".collection-plan-apply."
COLLECTION_APPLY_JOURNAL_FILENAME = ".collection-plan-apply.journal.json"
COLLECTION_APPLY_JOURNAL_SCHEMA = 1
_COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME = ".collection-rom-organization.journal.json"
_APPLY_LOCK = threading.RLock()


class CollectionPlanApplyError(RuntimeError):
    """Raised when a finalized plan cannot be safely applied."""


class CollectionPlanStaleStateError(CollectionPlanApplyError):
    """Raised when reviewed state changed before/during application."""


class CollectionPlanRecoveryError(CollectionPlanApplyError):
    """Raised when an interrupted coordinated write cannot be recovered."""


@dataclass(frozen=True)
class CollectionApplyRecoveryInfo:
    """Read-only description of a validated coordinated Apply journal."""

    state: str
    affected_targets: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.state not in {"prepared", "committed"}:
            raise CollectionPlanRecoveryError("Collection recovery state is invalid.")
        if not self.affected_targets:
            raise CollectionPlanRecoveryError("Collection recovery has no affected targets.")


@dataclass(frozen=True)
class PreparedFileWrite:
    """One already-serialized sidecar replacement owned by a participant."""

    path: Path
    content_bytes: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path):
            raise TypeError("Prepared file path must be pathlib.Path.")
        if not isinstance(self.content_bytes, bytes):
            raise TypeError("Prepared file content must be bytes.")


@dataclass(frozen=True)
class PreparedReferenceMutation:
    """All writes one dependent-reference participant wants for a migration."""

    store_name: str
    expected_revision_token: str
    writes: tuple[PreparedFileWrite, ...]

    def __post_init__(self) -> None:
        if not self.store_name.strip():
            raise CollectionPlanApplyError("Reference participant needs a store name.")
        if not self.expected_revision_token:
            raise CollectionPlanApplyError("Reference participant needs a revision token.")
        paths = [item.path for item in self.writes]
        if len(paths) != len(set(paths)):
            raise CollectionPlanApplyError("Reference participant prepared duplicate file paths.")


@runtime_checkable
class CollectionIdentityReferenceParticipant(Protocol):
    """Feature-owned store that can repoint Collection IDs without exposing semantics."""

    store_name: str

    def revision_token(self) -> str:
        """Return the exact state token used during review/freshness checks."""

    def prepare_reference_migrations(
        self,
        migrations: Sequence[ReferenceMigrationOperation],
    ) -> PreparedReferenceMutation:
        """Prepare detached writes; this method must not mutate persistent state."""


@dataclass(frozen=True)
class CollectionPlanApplyResult:
    """Summary of one successfully coordinated apply."""

    collection_record_count: int
    written_files: tuple[str, ...]
    identity_migration_count: int
    reference_participant_count: int


@dataclass
class _TargetState:
    target: Path
    content_bytes: bytes
    original_exists: bool
    original_bytes: bytes | None
    staged_path: Path | None = None
    rollback_path: Path | None = None


class _InjectedFailure(CollectionPlanApplyError):
    pass


def collect_store_preconditions(
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    participants: Sequence[CollectionIdentityReferenceParticipant] = (),
) -> tuple[StorePrecondition, ...]:
    """Capture deterministic reviewed-state tokens for plan finalization."""

    _require_manager(manager)
    participants = _validate_participants(participants)
    rows = [
        StorePrecondition(
            store_name=COLLECTION_STORE_NAME,
            revision_token=collection_revision_token(manager),
        ),
        StorePrecondition(
            store_name=identity_hints.store_name,
            revision_token=identity_hints.revision_token(),
        ),
    ]
    rows.extend(
        StorePrecondition(
            store_name=item.store_name,
            revision_token=item.revision_token(),
        )
        for item in participants
    )
    return tuple(sorted(rows, key=lambda item: item.store_name))


def collection_revision_token(manager: HackDataManager) -> str:
    """Bind a reviewed Collection to both live manager state and exact disk bytes."""

    _require_manager(manager)
    manager_bytes = _json_bytes(manager.data, "HackDataManager data")
    path = Path(manager.json_path)
    disk_token = _file_revision_token(path)
    payload = (
        hashlib.sha256(manager_bytes).hexdigest()
        + "\0"
        + disk_token
        + "\0"
        + ("unsaved" if bool(manager.unsaved_changes) else "saved")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def apply_collection_change_plan(
    plan: CollectionChangePlan,
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    *,
    reference_participants: Sequence[CollectionIdentityReferenceParticipant] = (),
    fail_after_replace: int | None = None,
) -> CollectionPlanApplyResult:
    """Apply one immutable plan without rerunning matching/reconciliation."""

    if not isinstance(plan, CollectionChangePlan):
        raise TypeError("plan must be a CollectionChangePlan")
    _require_manager(manager)
    participants = _validate_participants(reference_participants)
    root = Path(manager.json_path).parent.resolve()
    hints_path = identity_hints.path.resolve()
    if hints_path.parent != root:
        raise CollectionPlanApplyError(
            "Identity-hints sidecar must live beside processed.json."
        )
    if fail_after_replace is not None and (
        isinstance(fail_after_replace, bool) or fail_after_replace < 1
    ):
        raise ValueError("fail_after_replace must be a positive replacement count.")

    with _APPLY_LOCK:
        journal_path = root / COLLECTION_APPLY_JOURNAL_FILENAME
        organization_journal = root / _COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME
        if organization_journal.exists():
            raise CollectionPlanRecoveryError(
                "A ROM organization transaction journal already exists. Recover it "
                "before applying Collection metadata changes."
            )
        if journal_path.exists():
            raise CollectionPlanRecoveryError(
                "A Collection apply journal already exists. Recover it only after "
                "confirming no other application instance is applying a plan."
            )
        _validate_plan_preconditions(plan, manager, identity_hints, participants)

        manager_snapshot = copy.deepcopy(manager.data)
        manager_unsaved = bool(manager.unsaved_changes)
        manager_disk = _capture_file(Path(manager.json_path))
        timer = getattr(manager, "_save_timer", None)
        timer_cancelled = False

        try:
            staged_collection = _apply_plan_to_collection(plan, manager_snapshot)
            collection_content = _json_bytes(staged_collection, "staged Collection")

            hints_mutation = identity_hints.prepare_plan_changes(
                remembered_associations=plan.remembered_associations,
                ignored_roms=plan.ignored_roms,
                reference_migrations=plan.reference_migrations,
            )
            if hints_mutation.expected_revision_token != identity_hints.revision_token():
                raise CollectionPlanStaleStateError(
                    "Identity hints changed while preparing the reviewed plan."
                )

            participant_mutations = _prepare_reference_participants(
                plan,
                participants,
            )

            # A delayed HackDataManager save must not race the coordinated
            # replacement. Pending manager edits are already included above.
            if timer is not None:
                timer.cancel()
                manager._save_timer = None
                timer_cancelled = True

            _assert_manager_unchanged(manager, manager_snapshot, manager_disk)
            _validate_plan_preconditions(plan, manager, identity_hints, participants)

            writes = []
            for mutation in participant_mutations:
                writes.extend(mutation.writes)
            if hints_mutation.changed:
                writes.append(
                    PreparedFileWrite(
                        path=identity_hints.path,
                        content_bytes=hints_mutation.content_bytes,
                    )
                )

            processed_path = Path(manager.json_path)
            writes.append(
                PreparedFileWrite(
                    path=processed_path,
                    content_bytes=collection_content,
                )
            )
            if processed_path.exists():
                writes.append(
                    PreparedFileWrite(
                        path=Path(f"{manager.json_path}.backup"),
                        content_bytes=manager_disk[1] or b"",
                    )
                )

            # Keep processed.json last: feature sidecars are ready before the
            # canonical Collection identity switches. Backup is written before it.
            writes = _ordered_unique_writes(writes, processed_path)
            written = _coordinated_replace(
                root,
                writes,
                fail_after_replace=fail_after_replace,
                after_capture_check=lambda: (
                    _assert_manager_unchanged(manager, manager_snapshot, manager_disk),
                    _validate_plan_preconditions(plan, manager, identity_hints, participants),
                ),
                before_processed_check=lambda: _assert_manager_unchanged(
                    manager,
                    manager_snapshot,
                    manager_disk,
                ),
                processed_path=processed_path,
            )

        except Exception:
            manager.data = copy.deepcopy(manager_snapshot)
            manager.unsaved_changes = manager_unsaved
            if timer_cancelled and manager_unsaved:
                try:
                    manager._schedule_delayed_save()
                except Exception:
                    manager._save_timer = None
            raise

        manager.data = copy.deepcopy(staged_collection)
        manager.unsaved_changes = False
        manager._save_timer = None
        _log_success_best_effort(manager, len(staged_collection), len(written))
        return CollectionPlanApplyResult(
            collection_record_count=len(staged_collection),
            written_files=tuple(str(path) for path in written),
            identity_migration_count=len(plan.identity_migrations),
            reference_participant_count=len(participant_mutations),
        )


def inspect_interrupted_collection_apply(
    data_root: str | Path,
) -> CollectionApplyRecoveryInfo | None:
    """Return validated recovery facts without modifying journal or store files."""

    root = Path(data_root).resolve()
    journal_path = root / COLLECTION_APPLY_JOURNAL_FILENAME
    if not journal_path.exists():
        return None

    try:
        document = json.loads(
            journal_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonfinite,
        )
        _validate_journal(document)
        return CollectionApplyRecoveryInfo(
            state=document["state"],
            affected_targets=tuple(entry["target"] for entry in document["entries"]),
        )
    except CollectionPlanRecoveryError:
        raise
    except Exception as error:
        raise CollectionPlanRecoveryError(
            f"Could not inspect interrupted Collection apply: {error}"
        ) from error


def recover_interrupted_collection_apply(data_root: str | Path) -> bool:
    """Recover or finish cleanup for a journaled interrupted coordinated write."""

    root = Path(data_root).resolve()
    journal_path = root / COLLECTION_APPLY_JOURNAL_FILENAME
    if not journal_path.exists():
        return False

    try:
        document = json.loads(
            journal_path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonfinite,
        )
        _validate_journal(document)
        state = document["state"]
        entries = document["entries"]

        if state == "prepared":
            for entry in reversed(entries):
                target = root / entry["target"]
                rollback_name = entry.get("rollback")
                if entry["original_exists"]:
                    if not rollback_name:
                        raise CollectionPlanRecoveryError(
                            "Prepared transaction is missing rollback material."
                        )
                    rollback = root / rollback_name
                    if not rollback.exists():
                        raise CollectionPlanRecoveryError(
                            f"Rollback material is missing for {target.name}."
                        )
                    os.replace(rollback, target)
                elif target.exists():
                    target.unlink()

        for entry in entries:
            for key in ("staged", "rollback"):
                name = entry.get(key)
                if not name:
                    continue
                path = root / name
                if path.exists():
                    path.unlink()
        journal_path.unlink()
        _fsync_directory_best_effort(root)
        return True
    except CollectionPlanRecoveryError:
        raise
    except Exception as error:
        raise CollectionPlanRecoveryError(
            f"Could not recover interrupted Collection apply: {error}"
        ) from error


def _apply_plan_to_collection(
    plan: CollectionChangePlan,
    current: Mapping[str, Any],
) -> dict[str, Any]:
    staged = _json_round_trip(current, "Collection snapshot")
    if not isinstance(staged, dict):
        raise CollectionPlanApplyError("Collection root must be a JSON object.")

    for migration in plan.identity_migrations:
        _apply_identity_migration(staged, migration)

    migration_targets = {item.target_key for item in plan.identity_migrations}
    for intent in plan.record_intents:
        key = validate_collection_key(intent.target_key)
        exists = isinstance(staged.get(key), dict)
        if intent.kind is RecordIntentKind.CREATE:
            if exists:
                if key not in migration_targets:
                    raise CollectionPlanApplyError(
                        f"Plan expected new Collection key but it already exists: {key}"
                    )
            else:
                staged[key] = _new_record_defaults()
        elif intent.kind is RecordIntentKind.UPDATE:
            if not exists:
                raise CollectionPlanApplyError(
                    f"Plan expected existing Collection key: {key}"
                )
        else:
            raise CollectionPlanApplyError(f"Unsupported record intent: {intent.kind}")

    for operation in plan.local_record_seeds:
        record = _require_record(staged, operation.target_key)
        _apply_local_seed(record, operation)
    for operation in plan.catalogue_updates:
        record = _require_record(staged, operation.target_key)
        _apply_catalogue_metadata(record, operation)
    for operation in plan.rom_updates:
        record = _require_record(staged, operation.target_key)
        _apply_rom_assets(record, operation)
    for operation in plan.rom_submission_provenance_updates:
        record = _require_record(staged, operation.target_key)
        _apply_rom_submission_provenance(record, operation)
    for operation in plan.user_history_updates:
        record = _require_record(staged, operation.target_key)
        _apply_user_history(record, operation)
    for operation in plan.user_state_updates:
        record = _require_record(staged, operation.target_key)
        record[operation.field] = _json_round_trip(
            operation.value,
            f"user field {operation.field}",
        )
    for operation in plan.first_clear_selections:
        record = _require_record(staged, operation.target_key)
        record["first_clear_playthrough"] = {
            "source": operation.source,
            "source_record_id": operation.source_record_id,
        }
    for operation in plan.primary_rom_selections:
        record = _require_record(staged, operation.target_key)
        _apply_primary_rom_selection(record, operation.primary_path)

    return _json_round_trip(staged, "final staged Collection")


def _apply_identity_migration(
    staged: dict[str, Any],
    migration: IdentityMigrationOperation,
) -> None:
    source = migration.source_key
    target = migration.target_key
    source_record = staged.get(source)
    if not isinstance(source_record, dict):
        raise CollectionPlanApplyError(
            f"Identity migration source does not exist: {source}"
        )
    target_record = staged.get(target)
    if migration.merge_existing_target:
        if not isinstance(target_record, dict):
            raise CollectionPlanApplyError(
                f"Identity migration expected target to exist: {target}"
            )
        staged[target] = _merge_records_for_identity_migration(
            target_record,
            source_record,
        )
    else:
        if target in staged:
            raise CollectionPlanApplyError(
                f"Identity migration target unexpectedly exists: {target}"
            )
        staged[target] = copy.deepcopy(source_record)
    del staged[source]

    target_record = _require_record(staged, target)
    prior = _normalize_positive_ints(target_record.get("prior_smwc_submission_ids", []))
    prior.update(migration.prior_submission_ids)
    if prior:
        target_record["prior_smwc_submission_ids"] = sorted(prior)

    history = target_record.get("identity_migration_history", [])
    if not isinstance(history, list):
        history = []
    event = {
        "source_key": source,
        "target_key": target,
        "kind": migration.kind.value,
        "provenance": list(migration.provenance),
    }
    if event not in history:
        history.append(event)
    target_record["identity_migration_history"] = history


def _merge_records_for_identity_migration(
    target: Mapping[str, Any],
    source: Mapping[str, Any],
) -> dict[str, Any]:
    merged = copy.deepcopy(dict(target))

    for key, value in source.items():
        if key not in merged:
            merged[key] = copy.deepcopy(value)

    if bool(source.get("completed")):
        merged["completed"] = True
    for field in ("completed_date", "notes"):
        if not merged.get(field) and source.get(field):
            merged[field] = copy.deepcopy(source[field])
    for field in ("personal_rating", "time_to_beat"):
        if merged.get(field) in (None, "", 0) and source.get(field) not in (None, "", 0):
            merged[field] = copy.deepcopy(source[field])

    merged_files, merged_primary = _merge_file_lists_for_identity_migration(
        target.get("files"),
        source.get("files"),
        target.get("file_path"),
        source.get("file_path"),
    )
    if merged_files:
        merged["files"] = merged_files
        merged["file_path"] = merged_primary

    for field in (
        "local_files",
        "additional_paths",
        "import_sources",
        "playthroughs",
        "prior_smwc_submission_ids",
        "identity_migration_history",
    ):
        merged[field] = _merge_json_lists(merged.get(field), source.get(field))
        if not merged[field]:
            merged.pop(field, None)

    target_path = target.get("file_path")
    source_path = source.get("file_path")
    if not merged_files and not target_path and source_path:
        merged["file_path"] = source_path
    return merged


def _merge_file_lists_for_identity_migration(
    target_files: Any,
    source_files: Any,
    target_file_path: Any,
    source_file_path: Any,
) -> tuple[list[dict[str, Any]], str]:
    by_path: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    preferred = ""
    for file_rows, fallback_path, may_select_primary in (
        (target_files, target_file_path, True),
        (source_files, source_file_path, not preferred),
    ):
        if not isinstance(file_rows, list):
            continue
        local_primary = ""
        for raw in file_rows:
            if not isinstance(raw, dict):
                continue
            path = raw.get("path")
            if not isinstance(path, str) or not path:
                continue
            if path not in by_path:
                by_path[path] = copy.deepcopy(raw)
                order.append(path)
            if raw.get("primary") and not local_primary:
                local_primary = path
        if not local_primary and isinstance(fallback_path, str) and fallback_path in by_path:
            local_primary = fallback_path
        if may_select_primary and local_primary and not preferred:
            preferred = local_primary

    if not preferred and order:
        preferred = order[0]
    result = []
    for path in order:
        row = by_path[path]
        row["primary"] = bool(preferred and path == preferred)
        result.append(row)
    return result, preferred


def _apply_local_seed(record: dict[str, Any], operation: LocalRecordSeedOperation) -> None:
    record["title"] = operation.title
    record["authors"] = list(operation.authors)
    record["current_difficulty"] = operation.difficulty or "Unknown"
    record["hack_types"] = list(operation.hack_types)
    record["hack_type"] = operation.hack_types[0] if operation.hack_types else "unknown"
    if operation.exits is not None:
        record["exits"] = operation.exits


def _apply_catalogue_metadata(
    record: dict[str, Any],
    operation: CatalogueMetadataOperation,
) -> None:
    metadata = operation.metadata
    # ``rating`` is the canonical persisted SMWC community-rating field.
    # Remove the accidental v5.1 ingestion field so stale legacy data cannot
    # shadow future provider refreshes in compatibility consumers.
    record.pop("smwc_rating", None)
    record.update(
        {
            "title": metadata.title,
            "authors": list(metadata.authors),
            "current_difficulty": metadata.difficulty or "Unknown",
            "hack_types": list(metadata.hack_types),
            "hack_type": metadata.hack_types[0] if metadata.hack_types else "unknown",
            "exits": metadata.exits if metadata.exits is not None else 0,
            "time": metadata.release_timestamp if metadata.release_timestamp is not None else 0,
            "rating": metadata.rating if metadata.rating is not None else 0,
            "hall_of_fame": bool(metadata.hall_of_fame) if metadata.hall_of_fame is not None else False,
            "sa1_compatibility": bool(metadata.sa1_compatible) if metadata.sa1_compatible is not None else False,
            "collaboration": bool(metadata.collaboration) if metadata.collaboration is not None else False,
            "demo": bool(metadata.demo) if metadata.demo is not None else False,
        }
    )


def _apply_rom_assets(record: dict[str, Any], operation: RomAssetsOperation) -> None:
    existing_raw = record.get("files", [])
    if existing_raw is None:
        existing_raw = []
    if not isinstance(existing_raw, list):
        raise CollectionPlanApplyError("Collection files field must be an array.")

    by_path: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for row in existing_raw:
        if not isinstance(row, dict):
            raise CollectionPlanApplyError("Collection ROM file entry must be an object.")
        path = row.get("path")
        if not isinstance(path, str) or not path:
            raise CollectionPlanApplyError("Collection ROM file entry requires path.")
        if path not in by_path:
            by_path[path] = copy.deepcopy(row)
            order.append(path)

    previous_primary = ""
    for path in order:
        if by_path[path].get("primary"):
            previous_primary = path
            break
    if not previous_primary:
        file_path = record.get("file_path")
        if isinstance(file_path, str) and file_path in by_path:
            previous_primary = file_path

    for asset in operation.assets:
        row = by_path.get(asset.path, {})
        row.update(
            {
                "path": asset.path,
                "name": asset.filename,
                "sha256": asset.sha256,
                "size_bytes": asset.size_bytes,
            }
        )
        if asset.smwc_submission_id is not None:
            row["smwc_submission_id"] = asset.smwc_submission_id
        source_values = sorted({item.value for item in asset.sources})
        row["ingestion_sources"] = source_values
        by_path[asset.path] = row
        if asset.path not in order:
            order.append(asset.path)

    if operation.primary_path:
        primary = operation.primary_path
    elif operation.preserve_existing_primary and previous_primary in by_path:
        primary = previous_primary
    elif previous_primary in by_path:
        primary = previous_primary
    elif order:
        primary = order[0]
    else:
        primary = ""

    result = []
    for path in order:
        row = by_path[path]
        row["primary"] = bool(primary and path == primary)
        result.append(row)
    record["files"] = result
    record["file_path"] = primary


def _apply_rom_submission_provenance(
    record: dict[str, Any],
    operation: RomSubmissionProvenanceOperation,
) -> None:
    rows = record.get("files")
    if not isinstance(rows, list):
        raise CollectionPlanApplyError(
            "Reviewed ROM provenance requires Collection files[] state."
        )
    found = False
    result = []
    for raw in rows:
        if not isinstance(raw, dict):
            result.append(copy.deepcopy(raw))
            continue
        row = copy.deepcopy(raw)
        if row.get("path") == operation.path:
            found = True
            existing = row.get("smwc_submission_id")
            if existing in (None, ""):
                row["smwc_submission_id"] = operation.smwc_submission_id
            elif (
                not isinstance(existing, int)
                or isinstance(existing, bool)
                or existing <= 0
            ):
                raise CollectionPlanApplyError(
                    "Existing ROM submission provenance is invalid."
                )
            elif existing != operation.smwc_submission_id:
                raise CollectionPlanApplyError(
                    "Existing ROM submission provenance conflicts with the reviewed plan."
                )
        result.append(row)
    if not found:
        raise CollectionPlanApplyError(
            "Reviewed ROM provenance path is no longer present after Collection merge."
        )
    record["files"] = result


def _apply_primary_rom_selection(record: dict[str, Any], primary_path: str) -> None:
    rows = record.get("files")
    if not isinstance(rows, list):
        raise CollectionPlanApplyError(
            "Reviewed primary ROM selection requires Collection files[] state."
        )
    found = False
    result = []
    for raw in rows:
        if not isinstance(raw, dict):
            result.append(copy.deepcopy(raw))
            continue
        row = copy.deepcopy(raw)
        path = row.get("path")
        selected = isinstance(path, str) and path == primary_path
        if selected:
            found = True
        row["primary"] = selected
        result.append(row)
    if not found:
        raise CollectionPlanApplyError(
            "Reviewed primary ROM path is no longer present after Collection merge."
        )
    record["files"] = result
    record["file_path"] = primary_path


def _apply_user_history(record: dict[str, Any], operation: UserHistoryOperation) -> None:
    existing = record.get("playthroughs", [])
    if existing is None:
        existing = []
    if not isinstance(existing, list):
        raise CollectionPlanApplyError("Collection playthroughs field must be an array.")

    result = copy.deepcopy(existing)
    seen = {}
    for index, row in enumerate(result):
        if not isinstance(row, dict):
            continue
        source = row.get("source")
        record_id = row.get("source_record_id")
        if isinstance(source, str) and isinstance(record_id, str) and record_id:
            seen[(source, record_id)] = (index, row)

    for item in operation.playthroughs:
        row = _playthrough_document(item)
        key = (item.source.value, item.source_record_id)
        previous = seen.get(key)
        if previous is not None:
            if previous[1] != row:
                raise CollectionPlanApplyError(
                    "Existing imported playthrough changed since reconciliation."
                )
            continue
        seen[key] = (len(result), row)
        result.append(row)

    record["playthroughs"] = result
    if operation.first_clear_source is not None:
        record["first_clear_playthrough"] = {
            "source": operation.first_clear_source.value,
            "source_record_id": operation.first_clear_source_record_id,
        }


def _playthrough_document(item: UserPlaythroughEvidence) -> dict[str, Any]:
    return {
        "source": item.source.value,
        "source_record_id": item.source_record_id,
        "category": item.category,
        "play_kind": item.play_kind,
        "icon": item.icon,
        "time": item.elapsed_text,
        "elapsed_seconds": item.elapsed_seconds,
        "version": item.version,
        "completed_date": item.completed_date_text,
        "completed_date_iso": item.completed_date_iso,
        "notes": item.notes,
        "counts_as_hack": item.counts_as_hack,
        "exit_count": item.exit_count,
        "duration_milliseconds": item.duration_milliseconds,
        "duration_precision": item.duration_precision,
    }


def _new_record_defaults() -> dict[str, Any]:
    return {
        "title": "",
        "authors": [],
        "current_difficulty": "Unknown",
        "hack_type": "unknown",
        "hack_types": [],
        "exits": 0,
        "file_path": "",
        "files": [],
        "completed": False,
        "completed_date": "",
        "personal_rating": 0,
        "notes": "",
        "time_to_beat": 0,
        "obsolete": False,
    }


def _prepare_reference_participants(
    plan: CollectionChangePlan,
    participants: tuple[CollectionIdentityReferenceParticipant, ...],
) -> tuple[PreparedReferenceMutation, ...]:
    if not plan.reference_migrations:
        return ()
    result = []
    for participant in participants:
        before = participant.revision_token()
        prepared = participant.prepare_reference_migrations(plan.reference_migrations)
        if not isinstance(prepared, PreparedReferenceMutation):
            raise CollectionPlanApplyError(
                f"Reference participant {participant.store_name!r} returned invalid mutation."
            )
        if prepared.store_name != participant.store_name:
            raise CollectionPlanApplyError("Reference participant changed its store identity.")
        if prepared.expected_revision_token != before:
            raise CollectionPlanApplyError(
                f"Reference participant {participant.store_name!r} staged from wrong revision."
            )
        if participant.revision_token() != before:
            raise CollectionPlanStaleStateError(
                f"Reference store changed while preparing: {participant.store_name}"
            )
        result.append(prepared)
    return tuple(result)


def _validate_plan_preconditions(
    plan: CollectionChangePlan,
    manager: HackDataManager,
    identity_hints: CollectionIdentityHintsStore,
    participants: tuple[CollectionIdentityReferenceParticipant, ...],
) -> None:
    supplied = {item.store_name: item.revision_token for item in plan.preconditions}
    if len(supplied) != len(plan.preconditions):
        raise CollectionPlanApplyError("Plan contains duplicate store preconditions.")

    available = {
        COLLECTION_STORE_NAME: collection_revision_token(manager),
        identity_hints.store_name: identity_hints.revision_token(),
    }
    available.update({item.store_name: item.revision_token() for item in participants})

    required = {COLLECTION_STORE_NAME, identity_hints.store_name}
    if plan.reference_migrations:
        required.update(item.store_name for item in participants)
    missing = required.difference(supplied)
    if missing:
        raise CollectionPlanApplyError(
            "Plan is missing required store preconditions: " + ", ".join(sorted(missing))
        )
    unknown = set(supplied).difference(available)
    if unknown:
        raise CollectionPlanApplyError(
            "Plan references unregistered stores: " + ", ".join(sorted(unknown))
        )
    for name, expected in supplied.items():
        if available[name] != expected:
            raise CollectionPlanStaleStateError(
                f"Reviewed store changed before apply: {name}"
            )


def _validate_participants(
    participants: Sequence[CollectionIdentityReferenceParticipant],
) -> tuple[CollectionIdentityReferenceParticipant, ...]:
    result = tuple(participants)
    names = []
    for participant in result:
        if not isinstance(participant, CollectionIdentityReferenceParticipant):
            raise TypeError("reference participant does not implement required contract")
        name = participant.store_name
        if not isinstance(name, str) or not name.strip():
            raise CollectionPlanApplyError("Reference participant needs a store name.")
        if name in {COLLECTION_STORE_NAME, "collection_identity_hints"}:
            raise CollectionPlanApplyError(f"Reserved store name: {name}")
        names.append(name)
    if len(names) != len(set(names)):
        raise CollectionPlanApplyError("Reference participant store names must be unique.")
    return result


def _ordered_unique_writes(
    writes: Sequence[PreparedFileWrite],
    processed_path: Path,
) -> tuple[PreparedFileWrite, ...]:
    by_path = {}
    for write in writes:
        resolved = write.path.resolve()
        previous = by_path.get(resolved)
        if previous is not None and previous.content_bytes != write.content_bytes:
            raise CollectionPlanApplyError(f"Conflicting writes for {resolved}.")
        by_path[resolved] = PreparedFileWrite(path=resolved, content_bytes=write.content_bytes)
    processed = processed_path.resolve()
    ordered_paths = sorted((path for path in by_path if path != processed), key=str)
    if processed in by_path:
        ordered_paths.append(processed)
    return tuple(by_path[path] for path in ordered_paths)


def _coordinated_replace(
    root: Path,
    writes: Sequence[PreparedFileWrite],
    *,
    fail_after_replace: int | None,
    after_capture_check: Callable[[], object] | None = None,
    before_processed_check: Callable[[], object] | None = None,
    processed_path: Path | None = None,
) -> tuple[Path, ...]:
    root = root.resolve()
    journal_path = root / COLLECTION_APPLY_JOURNAL_FILENAME
    if journal_path.exists():
        raise CollectionPlanRecoveryError("Unrecovered Collection apply journal already exists.")

    target_states = []
    for write in writes:
        target = write.path.resolve()
        if target.parent != root:
            raise CollectionPlanApplyError(
                "Transactional participant writes must live beside processed.json."
            )
        if target.name == COLLECTION_APPLY_JOURNAL_FILENAME:
            raise CollectionPlanApplyError("Journal path cannot be a transaction target.")
        exists, content = _capture_file(target)
        target_states.append(
            _TargetState(
                target=target,
                content_bytes=write.content_bytes,
                original_exists=exists,
                original_bytes=content,
            )
        )

    if after_capture_check is not None:
        after_capture_check()

    try:
        for state in target_states:
            state.staged_path = _create_temp_bytes(
                root,
                state.target.name,
                "staged",
                state.content_bytes,
            )
            if state.original_exists:
                state.rollback_path = _create_temp_bytes(
                    root,
                    state.target.name,
                    "rollback",
                    state.original_bytes or b"",
                )

        journal = {
            "schema_version": COLLECTION_APPLY_JOURNAL_SCHEMA,
            "transaction_id": secrets.token_hex(8),
            "state": "prepared",
            "entries": [
                {
                    "target": state.target.name,
                    "staged": state.staged_path.name if state.staged_path else "",
                    "rollback": state.rollback_path.name if state.rollback_path else None,
                    "original_exists": state.original_exists,
                }
                for state in target_states
            ],
        }
        _write_initial_journal(root, journal)

        replaced = 0
        processed_resolved = processed_path.resolve() if processed_path is not None else None
        for state in target_states:
            if (
                processed_resolved is not None
                and state.target == processed_resolved
                and before_processed_check is not None
            ):
                before_processed_check()
            current_exists, current_bytes = _capture_file(state.target)
            if current_exists != state.original_exists or current_bytes != state.original_bytes:
                raise CollectionPlanStaleStateError(
                    f"Store file changed during coordinated apply: {state.target.name}"
                )
            assert state.staged_path is not None
            os.replace(state.staged_path, state.target)
            state.staged_path = None
            replaced += 1
            if fail_after_replace == replaced:
                raise _InjectedFailure(
                    f"Injected failure after coordinated replacement {replaced}."
                )

        journal["state"] = "committed"
        _write_journal(root, journal)
        # The committed journal is the cross-store commit point. Cleanup is
        # downstream bookkeeping: if it cannot finish now, the next recovery
        # pass sees state=committed and only removes transaction artifacts.
        try:
            _cleanup_committed_journal(root, journal)
        except OSError:
            pass
        _fsync_directory_best_effort(root)
        return tuple(state.target for state in target_states)
    except Exception:
        try:
            if journal_path.exists():
                recover_interrupted_collection_apply(root)
            else:
                for state in target_states:
                    for temp_path in (state.staged_path, state.rollback_path):
                        if temp_path is not None and temp_path.exists():
                            temp_path.unlink()
        except Exception as recovery_error:
            raise CollectionPlanRecoveryError(
                "Collection apply failed and rollback recovery also failed."
            ) from recovery_error
        raise


def _cleanup_committed_journal(root: Path, document: Mapping[str, Any]) -> None:
    for entry in document["entries"]:
        for key in ("staged", "rollback"):
            name = entry.get(key)
            if not name:
                continue
            path = root / name
            if path.exists():
                path.unlink()
    journal_path = root / COLLECTION_APPLY_JOURNAL_FILENAME
    if journal_path.exists():
        journal_path.unlink()



def _write_initial_journal(root: Path, document: Mapping[str, Any]) -> None:
    """Create the prepared journal exclusively as the cross-process writer claim."""

    content = _json_bytes(document, "Collection apply journal")
    journal_path = root / COLLECTION_APPLY_JOURNAL_FILENAME
    descriptor = None
    try:
        descriptor = os.open(
            journal_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory_best_effort(root)
    except FileExistsError as error:
        raise CollectionPlanApplyError(
            "Another or interrupted Collection apply already owns the transaction journal."
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_journal(root: Path, document: Mapping[str, Any]) -> None:
    content = _json_bytes(document, "Collection apply journal")
    temp = _create_temp_bytes(root, COLLECTION_APPLY_JOURNAL_FILENAME, "journal", content)
    os.replace(temp, root / COLLECTION_APPLY_JOURNAL_FILENAME)
    _fsync_directory_best_effort(root)


def _validate_journal(document: Any) -> None:
    if not isinstance(document, dict):
        raise CollectionPlanRecoveryError("Collection apply journal must be an object.")
    if document.get("schema_version") != COLLECTION_APPLY_JOURNAL_SCHEMA:
        raise CollectionPlanRecoveryError("Unsupported Collection apply journal schema.")
    if document.get("state") not in {"prepared", "committed"}:
        raise CollectionPlanRecoveryError("Collection apply journal has invalid state.")
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        raise CollectionPlanRecoveryError("Collection apply journal has no entries.")
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise CollectionPlanRecoveryError("Collection apply journal entry is invalid.")
        target = entry.get("target")
        staged = entry.get("staged")
        rollback = entry.get("rollback")
        if not _safe_basename(target):
            raise CollectionPlanRecoveryError("Unsafe Collection apply target in journal.")
        if target in seen:
            raise CollectionPlanRecoveryError("Duplicate Collection apply target in journal.")
        seen.add(target)
        if staged and (
            not _safe_basename(staged) or COLLECTION_APPLY_TEMP_MARKER not in staged
        ):
            raise CollectionPlanRecoveryError("Unsafe staged file in Collection apply journal.")
        if rollback and (
            not _safe_basename(rollback) or COLLECTION_APPLY_TEMP_MARKER not in rollback
        ):
            raise CollectionPlanRecoveryError("Unsafe rollback file in Collection apply journal.")
        if not isinstance(entry.get("original_exists"), bool):
            raise CollectionPlanRecoveryError("Journal original_exists must be boolean.")


def _safe_basename(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == Path(value).name
        and value not in {".", ".."}
    )


def _create_temp_bytes(root: Path, target_name: str, kind: str, content: bytes) -> Path:
    descriptor = None
    path = None
    try:
        descriptor, raw = tempfile.mkstemp(
            prefix=f"{target_name}{COLLECTION_APPLY_TEMP_MARKER}{kind}.",
            suffix=".tmp",
            dir=root,
        )
        path = Path(raw)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return path
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        if path is not None and path.exists():
            path.unlink()
        raise


def _assert_manager_unchanged(
    manager: HackDataManager,
    expected_data: Mapping[str, Any],
    expected_disk: tuple[bool, bytes | None],
) -> None:
    if manager.data != expected_data:
        raise CollectionPlanStaleStateError(
            "HackDataManager changed while applying reviewed Collection plan."
        )
    if _capture_file(Path(manager.json_path)) != expected_disk:
        raise CollectionPlanStaleStateError(
            "processed.json changed while applying reviewed Collection plan."
        )


def _require_manager(manager: HackDataManager) -> None:
    if not isinstance(manager, HackDataManager):
        raise TypeError("manager must be a HackDataManager")


def _require_record(staged: dict[str, Any], collection_key: str) -> dict[str, Any]:
    key = validate_collection_key(collection_key)
    record = staged.get(key)
    if not isinstance(record, dict):
        raise CollectionPlanApplyError(f"Collection record does not exist: {key}")
    return record


def _merge_json_lists(first: Any, second: Any) -> list[Any]:
    result = []
    seen = set()
    for source in (first, second):
        if not isinstance(source, list):
            continue
        for item in source:
            normalized = _json_round_trip(item, "merged list item")
            marker = json.dumps(normalized, ensure_ascii=False, sort_keys=True, allow_nan=False)
            if marker in seen:
                continue
            seen.add(marker)
            result.append(normalized)
    return result


def _normalize_positive_ints(value: Any) -> set[int]:
    result = set()
    if isinstance(value, list):
        for item in value:
            if isinstance(item, bool) or not isinstance(item, int) or item <= 0:
                continue
            result.add(item)
    return result


def _capture_file(path: Path) -> tuple[bool, bytes | None]:
    if not path.exists():
        return False, None
    return True, path.read_bytes()


def _file_revision_token(path: Path) -> str:
    exists, content = _capture_file(path)
    if not exists:
        return "missing"
    assert content is not None
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _json_bytes(value: Any, label: str) -> bytes:
    normalized = _json_round_trip(value, label)
    try:
        text = json.dumps(
            normalized,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise CollectionPlanApplyError(f"{label} cannot be serialized: {error}") from error
    return text.encode("utf-8")


def _json_round_trip(value: Any, label: str):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise CollectionPlanApplyError(f"{label} is not JSON-safe: {error}") from error


def _reject_duplicate_object_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CollectionPlanRecoveryError(f"Duplicate journal JSON key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str):
    raise CollectionPlanRecoveryError(f"Non-finite journal number: {value}")


def _fsync_directory_best_effort(path: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, os.O_RDONLY | flags)
    except (OSError, AttributeError):
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _log_success_best_effort(manager: HackDataManager, records: int, files: int) -> None:
    try:
        manager._log(
            f"💾 Applied reviewed Collection plan: {records} records, {files} files",
            "Information",
        )
    except Exception:
        pass


__all__ = [
    "COLLECTION_APPLY_JOURNAL_FILENAME",
    "COLLECTION_APPLY_TEMP_MARKER",
    "COLLECTION_STORE_NAME",
    "CollectionApplyRecoveryInfo",
    "CollectionIdentityReferenceParticipant",
    "CollectionPlanApplyError",
    "CollectionPlanApplyResult",
    "CollectionPlanRecoveryError",
    "CollectionPlanStaleStateError",
    "PreparedFileWrite",
    "PreparedReferenceMutation",
    "apply_collection_change_plan",
    "collect_store_preconditions",
    "collection_revision_token",
    "inspect_interrupted_collection_apply",
    "recover_interrupted_collection_apply",
]
