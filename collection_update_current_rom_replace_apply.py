"""Crash-recoverable same-path replacement for reviewed same-ID current ROM updates.

Download/patch work has already completed before this module runs.  Apply consumes only
the frozen plan and reviewed old/new byte identities.  It replaces the current primary
ROM at its existing path, commits processed.json, and only then removes the temporary
published downloaded sibling.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from collection_identity_hints import CollectionIdentityHintsStore
from collection_plan_apply import (
    COLLECTION_APPLY_JOURNAL_FILENAME,
    CollectionIdentityReferenceParticipant,
    CollectionPlanApplyResult,
    CollectionPlanRecoveryError,
    CollectionPlanStaleStateError,
    _apply_plan_to_collection,
    collect_store_preconditions,
)
from collection_update_current_refresh import (
    CurrentRomDisposition,
    FinalizedCurrentSubmissionRefreshPlan,
)
from hack_data_manager import HackDataManager


COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME = ".collection-current-rom-replace.journal.json"
COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_SCHEMA = 1
_COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME = ".collection-rom-organization.journal.json"
_TEMP_MARKER = ".collection-current-rom-replace."
_APPLY_LOCK = threading.RLock()


class CollectionCurrentRomReplaceApplyError(RuntimeError):
    """Raised when a reviewed same-path replacement cannot be applied."""


class CollectionCurrentRomReplaceStaleStateError(CollectionPlanStaleStateError):
    """Raised when reviewed Collection/ROM bytes changed before replacement Apply."""


class CollectionCurrentRomReplaceRecoveryError(CollectionPlanRecoveryError):
    """Raised when a current-ROM replacement journal cannot be recovered safely."""


class CollectionCurrentRomReplaceRecoveryRequiredError(CollectionCurrentRomReplaceRecoveryError):
    """Raised after commit when journaled cleanup must be completed by recovery."""


@dataclass(frozen=True)
class CollectionCurrentRomReplaceRecoveryInfo:
    state: str
    affected_targets: tuple[str, ...]
    transaction_kind: str = "current ROM replacement"

    def __post_init__(self) -> None:
        if self.state not in {"prepared", "committed"}:
            raise CollectionCurrentRomReplaceRecoveryError(
                "Current-ROM replacement recovery state is invalid."
            )
        if not self.affected_targets:
            raise CollectionCurrentRomReplaceRecoveryError(
                "Current-ROM replacement recovery has no affected targets."
            )


@dataclass
class _StoreState:
    target: Path
    new_bytes: bytes
    original_exists: bool
    original_bytes: bytes | None
    staged_path: Path | None = None
    rollback_path: Path | None = None


class _SimulatedCrash(BaseException):
    pass


def apply_current_rom_replacement(
    processed_json_path: str | Path,
    finalized: FinalizedCurrentSubmissionRefreshPlan,
    *,
    manager: HackDataManager | None = None,
    identity_hints: CollectionIdentityHintsStore | None = None,
    participants: Sequence[CollectionIdentityReferenceParticipant] | None = None,
    _crash_after: str | None = None,
) -> CollectionPlanApplyResult:
    """Apply one frozen Replace Current ROM decision without network/patch work."""
    _validate_finalized(finalized)
    processed = Path(processed_json_path).expanduser().resolve()
    runtime_manager = manager or HackDataManager(str(processed))
    if Path(runtime_manager.json_path).expanduser().resolve() != processed:
        raise CollectionCurrentRomReplaceApplyError(
            "Collection manager does not reference the selected processed.json."
        )
    hints = identity_hints or CollectionIdentityHintsStore.beside_processed_json(processed)
    runtime_participants = _runtime_participants(processed, participants)
    replacement = finalized.rom_replacement
    assert replacement is not None

    root = processed.parent
    journal_path = root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME
    collection_journal = root / COLLECTION_APPLY_JOURNAL_FILENAME
    organization_journal = root / _COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME

    with _APPLY_LOCK:
        if journal_path.exists():
            raise CollectionCurrentRomReplaceRecoveryError(
                "An interrupted current-ROM replacement journal already exists. Recover it before Apply."
            )
        if collection_journal.exists() or organization_journal.exists():
            raise CollectionCurrentRomReplaceRecoveryError(
                "Another Collection transaction journal exists. Recover it before replacing the current ROM."
            )

        _require_preconditions_current(finalized, runtime_manager, hints, runtime_participants)
        manager_snapshot = copy.deepcopy(runtime_manager.data)
        manager_unsaved = bool(runtime_manager.unsaved_changes)
        processed_original = _capture_file(processed)
        if not processed_original[0]:
            raise CollectionCurrentRomReplaceStaleStateError("processed.json disappeared before Apply.")
        timer = getattr(runtime_manager, "_save_timer", None)
        timer_cancelled = False
        stores: tuple[_StoreState, ...] = ()
        journal_written = False
        committed = False
        journal: dict[str, Any] | None = None
        try:
            _assert_replacement_preconditions(finalized, runtime_manager)
            staged_collection = _apply_plan_to_collection(finalized.plan, manager_snapshot)
            _assert_staged_replacement(finalized, staged_collection)
            collection_bytes = _json_bytes(staged_collection)
            stores = _prepare_store_states(root, processed, collection_bytes)
            rom_staged, rom_rollback = _prepare_rom_states(replacement)

            if timer is not None:
                timer.cancel()
                runtime_manager._save_timer = None
                timer_cancelled = True

            _assert_manager_unchanged(runtime_manager, manager_snapshot, processed_original)
            _require_preconditions_current(finalized, runtime_manager, hints, runtime_participants)
            _assert_replacement_preconditions(finalized, runtime_manager)

            journal = _journal_document(
                processed=processed,
                stores=stores,
                finalized=finalized,
                rom_staged=rom_staged,
                rom_rollback=rom_rollback,
                collection_bytes=collection_bytes,
                processed_original=processed_original[1] or b"",
            )
            _write_initial_journal(root, journal)
            journal_written = True

            _replace_rom_target(journal)
            _maybe_crash(_crash_after, "rom")

            _replace_store_states(
                root,
                stores,
                processed=processed,
                manager=runtime_manager,
                manager_snapshot=manager_snapshot,
                processed_original=processed_original,
                finalized=finalized,
                hints=hints,
                participants=runtime_participants,
                crash_after=_crash_after,
            )

            journal["state"] = "committed"
            _write_journal(root, journal)
            committed = True
            runtime_manager.data = copy.deepcopy(staged_collection)
            runtime_manager.unsaved_changes = False
            runtime_manager._save_timer = None
            timer_cancelled = False
            _maybe_crash(_crash_after, "commit")

            try:
                _finish_committed(root, journal)
            except Exception as error:
                raise CollectionCurrentRomReplaceRecoveryRequiredError(
                    f"Current ROM replacement committed, but cleanup is incomplete: {error}"
                ) from error
            _remove_journal(root)
            return CollectionPlanApplyResult(
                collection_record_count=len(staged_collection),
                written_files=tuple(_result_paths(stores, replacement.target_path)),
                identity_migration_count=0,
                reference_participant_count=0,
            )
        except _SimulatedCrash:
            raise
        except Exception as error:
            if committed:
                # The commit point is durable.  Never make the live manager pretend the
                # old Collection state still owns ROM bytes that have already committed.
                runtime_manager.data = copy.deepcopy(staged_collection)
                runtime_manager.unsaved_changes = False
                runtime_manager._save_timer = None
                raise

            runtime_manager.data = copy.deepcopy(manager_snapshot)
            runtime_manager.unsaved_changes = manager_unsaved
            if timer_cancelled and manager_unsaved:
                try:
                    runtime_manager._schedule_delayed_save()
                except Exception:
                    runtime_manager._save_timer = None
            if journal_written:
                try:
                    recover_interrupted_current_rom_replacement(root)
                except Exception as recovery_error:
                    raise CollectionCurrentRomReplaceRecoveryError(
                        "Current-ROM replacement failed and automatic rollback also failed. "
                        f"Manual/startup recovery is required: {recovery_error}"
                    ) from error
            raise


def inspect_interrupted_current_rom_replacement(
    data_root: str | Path,
) -> CollectionCurrentRomReplaceRecoveryInfo | None:
    root = Path(data_root).expanduser().resolve()
    journal_path = root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME
    if not journal_path.exists():
        return None
    document = _load_journal(root)
    return CollectionCurrentRomReplaceRecoveryInfo(
        state=document["state"],
        affected_targets=(document["rom"]["target"], document["processed"]["path"]),
    )


def recover_interrupted_current_rom_replacement(data_root: str | Path) -> bool:
    """Rollback a prepared replacement or finish cleanup after its commit point."""
    root = Path(data_root).expanduser().resolve()
    journal_path = root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME
    if not journal_path.exists():
        return False
    document = _load_journal(root)
    try:
        processed = Path(document["processed"]["path"])
        old_sha = document["processed"]["old_sha256"]
        new_sha = document["processed"]["new_sha256"]
        current_sha = _file_sha256_or_none(processed)

        logically_committed = document["state"] == "committed" or current_sha == new_sha
        if logically_committed:
            if current_sha != new_sha:
                raise CollectionCurrentRomReplaceRecoveryError(
                    "Committed current-ROM replacement no longer has the reviewed processed.json bytes."
                )
            _assert_rom_target_hash(document, expected_new=True)
            _finish_committed(root, document)
        else:
            if current_sha != old_sha:
                raise CollectionCurrentRomReplaceRecoveryError(
                    "Prepared current-ROM replacement processed.json is neither reviewed old nor committed new state."
                )
            _rollback_prepared(root, document)

        _cleanup_artifacts(document)
        _remove_journal(root)
        return True
    except CollectionCurrentRomReplaceRecoveryError:
        raise
    except Exception as error:
        raise CollectionCurrentRomReplaceRecoveryError(
            f"Could not recover interrupted current-ROM replacement: {error}"
        ) from error


def _validate_finalized(finalized: FinalizedCurrentSubmissionRefreshPlan) -> None:
    if not isinstance(finalized, FinalizedCurrentSubmissionRefreshPlan):
        raise TypeError("finalized must be FinalizedCurrentSubmissionRefreshPlan")
    if finalized.rom_disposition is not CurrentRomDisposition.REPLACE_CURRENT:
        raise CollectionCurrentRomReplaceApplyError(
            "Same-path replacement requires an explicit reviewed Replace Current ROM decision."
        )
    if finalized.rom_replacement is None:
        raise CollectionCurrentRomReplaceApplyError(
            "Replace Current ROM decision is missing frozen old/new byte preconditions."
        )
    plan = finalized.plan
    if plan.identity_migrations or plan.reference_migrations:
        raise CollectionCurrentRomReplaceApplyError(
            "Same-ID ROM replacement must not contain identity/reference migrations."
        )
    if any((plan.local_record_seeds, plan.user_history_updates, plan.user_state_updates,
            plan.ignored_roms, plan.remembered_associations, plan.first_clear_selections,
            plan.rom_submission_provenance_updates)):
        raise CollectionCurrentRomReplaceApplyError(
            "Same-ID current-ROM replacement plan contains unsupported semantic operations."
        )
    if len(plan.record_intents) != 1 or plan.record_intents[0].target_key != finalized.source_collection_key:
        raise CollectionCurrentRomReplaceApplyError(
            "Current-ROM replacement plan does not target exactly the current Collection entry."
        )
    if len(plan.rom_updates) != 1:
        raise CollectionCurrentRomReplaceApplyError(
            "Current-ROM replacement requires exactly one frozen ROM operation."
        )
    replacement = finalized.rom_replacement
    if os.path.normcase(os.path.abspath(replacement.source_path)) == os.path.normcase(os.path.abspath(replacement.target_path)):
        raise CollectionCurrentRomReplaceApplyError(
            "Replacement source and current target path must be distinct before Apply."
        )


def _assert_replacement_preconditions(finalized, manager: HackDataManager) -> None:
    replacement = finalized.rom_replacement
    assert replacement is not None
    _hash_exact(
        replacement.source_path,
        replacement.source_sha256,
        replacement.source_size_bytes,
        replacement.source_mtime_ns,
        "downloaded ROM",
    )
    _hash_exact(
        replacement.target_path,
        replacement.target_sha256,
        replacement.target_size_bytes,
        replacement.target_mtime_ns,
        "current primary ROM",
    )
    record = manager.data.get(finalized.source_collection_key)
    if not isinstance(record, Mapping):
        raise CollectionCurrentRomReplaceStaleStateError(
            "Current Collection entry disappeared before Replace Current ROM Apply."
        )
    rows = record.get("files")
    if not isinstance(rows, list):
        raise CollectionCurrentRomReplaceStaleStateError(
            "Current Collection files[] changed before Replace Current ROM Apply."
        )
    matches = [
        row for row in rows
        if isinstance(row, Mapping) and row.get("path") == replacement.target_path
    ]
    if len(matches) != 1:
        raise CollectionCurrentRomReplaceStaleStateError(
            "Reviewed current primary path no longer identifies exactly one Collection ROM asset."
        )
    row = matches[0]
    if row.get("sha256") != replacement.target_sha256 or row.get("size_bytes") != replacement.target_size_bytes:
        raise CollectionCurrentRomReplaceStaleStateError(
            "Current primary ROM metadata changed after disposition review."
        )
    primary_paths = [
        str(item.get("path") or "")
        for item in rows
        if isinstance(item, Mapping) and item.get("primary") and item.get("path")
    ]
    if len(primary_paths) > 1:
        raise CollectionCurrentRomReplaceStaleStateError(
            "Collection has multiple primary ROM rows after disposition review."
        )
    projected = record.get("file_path")
    if projected != replacement.target_path:
        raise CollectionCurrentRomReplaceStaleStateError(
            "Current primary ROM projection changed after disposition review."
        )
    if primary_paths and primary_paths[0] != replacement.target_path:
        raise CollectionCurrentRomReplaceStaleStateError(
            "Current primary ROM selection changed after disposition review."
        )


def _assert_staged_replacement(finalized, staged: Mapping[str, Any]) -> None:
    replacement = finalized.rom_replacement
    assert replacement is not None
    record = staged.get(finalized.source_collection_key)
    if not isinstance(record, Mapping):
        raise CollectionCurrentRomReplaceApplyError("Staged Collection lost the current entry.")
    rows = record.get("files")
    if not isinstance(rows, list):
        raise CollectionCurrentRomReplaceApplyError("Staged Collection lost modern ROM assets.")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("path") == replacement.target_path]
    if len(matches) != 1:
        raise CollectionCurrentRomReplaceApplyError(
            "Staged replacement does not produce exactly one asset at the preserved current path."
        )
    row = matches[0]
    if row.get("sha256") != replacement.source_sha256 or row.get("size_bytes") != replacement.source_size_bytes:
        raise CollectionCurrentRomReplaceApplyError(
            "Staged replacement asset does not match the downloaded reviewed ROM bytes."
        )
    if not row.get("primary") or record.get("file_path") != replacement.target_path:
        raise CollectionCurrentRomReplaceApplyError(
            "Staged replacement did not preserve the current path as primary."
        )


def _prepare_rom_states(replacement):
    source = Path(replacement.source_path).expanduser()
    target = Path(replacement.target_path).expanduser()
    staged = _copy_temp(source, target.parent, target.name, "staged")
    rollback = _copy_temp(target, target.parent, target.name, "rollback")
    _hash_exact(staged, replacement.source_sha256, replacement.source_size_bytes, None, "staged replacement")
    _hash_exact(rollback, replacement.target_sha256, replacement.target_size_bytes, None, "replacement rollback")
    return staged, rollback


def _prepare_store_states(root: Path, processed: Path, new_processed_bytes: bytes) -> tuple[_StoreState, ...]:
    processed_exists, processed_bytes = _capture_file(processed)
    backup = Path(f"{processed}.backup")
    states: list[_StoreState] = []
    if processed_exists:
        backup_exists, backup_bytes = _capture_file(backup)
        states.append(_StoreState(backup, processed_bytes or b"", backup_exists, backup_bytes))
    states.append(_StoreState(processed, new_processed_bytes, processed_exists, processed_bytes))
    try:
        for state in states:
            state.staged_path = _temp_bytes(root, state.target.name, "staged", state.new_bytes)
            if state.original_exists:
                state.rollback_path = _temp_bytes(
                    root, state.target.name, "rollback", state.original_bytes or b""
                )
        return tuple(states)
    except Exception:
        for state in states:
            for path in (state.staged_path, state.rollback_path):
                if path and path.exists():
                    path.unlink()
        raise


def _replace_rom_target(document: Mapping[str, Any]) -> None:
    entry = document["rom"]
    target = Path(entry["target"])
    staged = Path(entry["staged"])
    _hash_exact(target, entry["old_sha256"], entry["old_size_bytes"], entry["old_mtime_ns"], "current primary ROM")
    _hash_exact(staged, entry["new_sha256"], entry["new_size_bytes"], None, "staged downloaded ROM")
    os.replace(staged, target)
    _fsync_directory_best_effort(target.parent)
    _hash_exact(target, entry["new_sha256"], entry["new_size_bytes"], None, "replaced current ROM")


def _replace_store_states(
    root: Path,
    states: tuple[_StoreState, ...],
    *,
    processed: Path,
    manager: HackDataManager,
    manager_snapshot: Mapping[str, Any],
    processed_original,
    finalized,
    hints,
    participants,
    crash_after,
) -> None:
    for index, state in enumerate(states, 1):
        if state.target == processed:
            _assert_manager_unchanged(manager, manager_snapshot, processed_original)
            _require_preconditions_current(finalized, manager, hints, participants)
            _assert_rom_target_new(finalized)
        if _capture_file(state.target) != (state.original_exists, state.original_bytes):
            raise CollectionCurrentRomReplaceStaleStateError(
                f"Collection store changed during current-ROM replacement: {state.target.name}"
            )
        if state.staged_path is None or not state.staged_path.exists():
            raise CollectionCurrentRomReplaceRecoveryError(
                f"Staged Collection store is missing: {state.target.name}"
            )
        if _file_sha256_or_none(state.staged_path) != hashlib.sha256(state.new_bytes).hexdigest():
            raise CollectionCurrentRomReplaceRecoveryError(
                f"Staged Collection store bytes changed before replacement: {state.target.name}"
            )
        os.replace(state.staged_path, state.target)
        state.staged_path = None
        _fsync_directory_best_effort(root)
        if crash_after == f"store{index}":
            raise _SimulatedCrash(f"Simulated crash after store {index}")


def _assert_rom_target_new(finalized) -> None:
    replacement = finalized.rom_replacement
    assert replacement is not None
    _hash_exact(
        replacement.target_path,
        replacement.source_sha256,
        replacement.source_size_bytes,
        None,
        "replaced current ROM",
    )


def _finish_committed(root: Path, document: Mapping[str, Any]) -> None:
    _assert_rom_target_hash(document, expected_new=True)
    for entry in document["stores"]:
        target = root / entry["target"]
        if _file_sha256_or_none(target) != entry["new_sha256"]:
            raise CollectionCurrentRomReplaceRecoveryError(
                f"Committed Collection store no longer has the reviewed bytes: {target.name}"
            )
    source = Path(document["rom"]["source"])
    if os.path.lexists(source):
        _hash_exact(
            source,
            document["rom"]["new_sha256"],
            document["rom"]["new_size_bytes"],
            document["rom"]["source_mtime_ns"],
            "downloaded source ROM",
        )
        source.unlink()
        _fsync_directory_best_effort(source.parent)
    _cleanup_artifacts(document)


def _rollback_prepared(root: Path, document: Mapping[str, Any]) -> None:
    _restore_store_states(root, document)
    entry = document["rom"]
    target = Path(entry["target"])
    rollback = Path(entry["rollback"])
    current = _file_sha256_or_none(target)
    if current == entry["new_sha256"]:
        if not rollback.is_file():
            raise CollectionCurrentRomReplaceRecoveryError(
                "Prepared replacement lacks old-ROM rollback bytes."
            )
        _hash_exact(rollback, entry["old_sha256"], entry["old_size_bytes"], None, "old-ROM rollback")
        os.replace(rollback, target)
        _fsync_directory_best_effort(target.parent)
    elif current != entry["old_sha256"]:
        raise CollectionCurrentRomReplaceRecoveryError(
            "Current ROM path is neither reviewed old nor replacement bytes during rollback."
        )
    _hash_exact(target, entry["old_sha256"], entry["old_size_bytes"], None, "restored current ROM")
    _cleanup_artifacts(document)


def _restore_store_states(root: Path, document: Mapping[str, Any]) -> None:
    for entry in reversed(document["stores"]):
        target = root / entry["target"]
        current_sha = _file_sha256_or_none(target)
        old_sha = entry.get("old_sha256")
        new_sha = entry["new_sha256"]
        if current_sha not in {old_sha, new_sha}:
            raise CollectionCurrentRomReplaceRecoveryError(
                f"Collection store changed outside reviewed transaction during recovery: {target.name}"
            )
        if entry["original_exists"]:
            rollback = root / entry["rollback"]
            if _file_sha256_or_none(rollback) != old_sha:
                raise CollectionCurrentRomReplaceRecoveryError(
                    f"Missing or changed Collection rollback bytes for {target.name}."
                )
            os.replace(rollback, target)
        elif target.exists():
            target.unlink()
        _fsync_directory_best_effort(root)


def _journal_document(*, processed, stores, finalized, rom_staged, rom_rollback, collection_bytes, processed_original):
    replacement = finalized.rom_replacement
    assert replacement is not None
    return {
        "schema_version": COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_SCHEMA,
        "transaction_id": secrets.token_hex(8),
        "state": "prepared",
        "processed": {
            "path": str(processed),
            "old_sha256": hashlib.sha256(processed_original).hexdigest(),
            "new_sha256": hashlib.sha256(collection_bytes).hexdigest(),
        },
        "rom": {
            "source": replacement.source_path,
            "target": replacement.target_path,
            "staged": str(rom_staged),
            "rollback": str(rom_rollback),
            "old_sha256": replacement.target_sha256,
            "old_size_bytes": replacement.target_size_bytes,
            "old_mtime_ns": replacement.target_mtime_ns,
            "new_sha256": replacement.source_sha256,
            "new_size_bytes": replacement.source_size_bytes,
            "source_mtime_ns": replacement.source_mtime_ns,
        },
        "stores": [
            {
                "target": state.target.name,
                "staged": state.staged_path.name if state.staged_path else "",
                "rollback": state.rollback_path.name if state.rollback_path else None,
                "original_exists": state.original_exists,
                "old_sha256": (
                    hashlib.sha256(state.original_bytes or b"").hexdigest()
                    if state.original_exists else None
                ),
                "old_size_bytes": (len(state.original_bytes or b"") if state.original_exists else None),
                "new_sha256": hashlib.sha256(state.new_bytes).hexdigest(),
                "new_size_bytes": len(state.new_bytes),
            }
            for state in stores
        ],
    }


def _load_journal(root: Path) -> dict[str, Any]:
    path = root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicates,
            parse_constant=_reject_nonfinite,
        )
    except Exception as error:
        raise CollectionCurrentRomReplaceRecoveryError(
            f"Could not read current-ROM replacement journal: {error}"
        ) from error
    _validate_journal(root, document)
    return document


def _validate_journal(root: Path, document: Any) -> None:
    if not isinstance(document, dict) or document.get("schema_version") != COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_SCHEMA:
        raise CollectionCurrentRomReplaceRecoveryError("Unsupported current-ROM replacement journal schema.")
    transaction_id = document.get("transaction_id")
    if (
        not isinstance(transaction_id, str)
        or len(transaction_id) != 16
        or any(character not in "0123456789abcdef" for character in transaction_id)
    ):
        raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid transaction ID.")
    if document.get("state") not in {"prepared", "committed"}:
        raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid state.")

    processed = document.get("processed")
    rom = document.get("rom")
    stores = document.get("stores")
    if not isinstance(processed, dict) or not isinstance(rom, dict) or not isinstance(stores, list) or not stores:
        raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal is incomplete.")

    processed_value = processed.get("path")
    if not isinstance(processed_value, str) or not processed_value or not Path(processed_value).is_absolute():
        raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid processed.json path.")
    processed_path = Path(processed_value).expanduser().resolve()
    if processed_path.parent != root:
        raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal targets the wrong data directory.")
    for key in ("old_sha256", "new_sha256"):
        if not _valid_sha(processed.get(key)):
            raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid processed.json SHA-256.")

    for key in ("source", "target", "staged", "rollback"):
        value = rom.get(key)
        if not isinstance(value, str) or not value or not Path(value).is_absolute():
            raise CollectionCurrentRomReplaceRecoveryError(
                f"Current-ROM replacement journal has invalid ROM {key} path."
            )
    source = Path(rom["source"]).expanduser()
    target = Path(rom["target"]).expanduser()
    staged = Path(rom["staged"]).expanduser()
    rollback = Path(rom["rollback"]).expanduser()
    if _same_path(source, target):
        raise CollectionCurrentRomReplaceRecoveryError(
            "Current-ROM replacement journal source and target paths must be distinct."
        )
    target_parent = target.parent.resolve()
    if staged.parent.resolve() != target_parent or rollback.parent.resolve() != target_parent:
        raise CollectionCurrentRomReplaceRecoveryError(
            "Current-ROM replacement journal temp ROM paths are outside the reviewed target directory."
        )
    if not _safe_rom_temp_name(staged.name, target.name, "staged"):
        raise CollectionCurrentRomReplaceRecoveryError(
            "Current-ROM replacement journal has an unsafe staged ROM path."
        )
    if not _safe_rom_temp_name(rollback.name, target.name, "rollback"):
        raise CollectionCurrentRomReplaceRecoveryError(
            "Current-ROM replacement journal has an unsafe rollback ROM path."
        )
    for key in ("old_sha256", "new_sha256"):
        if not _valid_sha(rom.get(key)):
            raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid ROM SHA-256.")
    for key in ("old_size_bytes", "new_size_bytes", "old_mtime_ns", "source_mtime_ns"):
        if not _valid_nonnegative_int(rom.get(key)):
            raise CollectionCurrentRomReplaceRecoveryError(
                f"Current-ROM replacement journal has invalid ROM {key}."
            )

    seen_targets: set[str] = set()
    for entry in stores:
        if not isinstance(entry, dict):
            raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid store entry.")
        target_name = entry.get("target")
        if not _safe_basename(target_name) or target_name in seen_targets:
            raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid or duplicate store target.")
        seen_targets.add(target_name)
        if not isinstance(entry.get("original_exists"), bool):
            raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid store existence state.")
        staged_name = entry.get("staged")
        if not _safe_store_temp_name(staged_name, target_name, "staged"):
            raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has unsafe staged store path.")
        rollback_name = entry.get("rollback")
        if entry["original_exists"]:
            if not _valid_sha(entry.get("old_sha256")) or not _valid_nonnegative_int(entry.get("old_size_bytes")):
                raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid old store identity.")
            if not _safe_store_temp_name(rollback_name, target_name, "rollback"):
                raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has unsafe rollback store path.")
        elif entry.get("old_sha256") is not None or entry.get("old_size_bytes") is not None or rollback_name is not None:
            raise CollectionCurrentRomReplaceRecoveryError(
                "Current-ROM replacement journal invents rollback data for a previously missing store."
            )
        if not _valid_sha(entry.get("new_sha256")) or not _valid_nonnegative_int(entry.get("new_size_bytes")):
            raise CollectionCurrentRomReplaceRecoveryError("Current-ROM replacement journal has invalid new store identity.")

    expected_targets = {processed_path.name, f"{processed_path.name}.backup"}
    if seen_targets != expected_targets:
        raise CollectionCurrentRomReplaceRecoveryError(
            "Current-ROM replacement journal store set does not match processed.json and its backup."
        )
    processed_store = next(entry for entry in stores if entry["target"] == processed_path.name)
    if (
        processed_store.get("old_sha256") != processed.get("old_sha256")
        or processed_store.get("new_sha256") != processed.get("new_sha256")
    ):
        raise CollectionCurrentRomReplaceRecoveryError(
            "Current-ROM replacement journal processed.json identities disagree with its store entry."
        )


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.abspath(str(left))) == os.path.normcase(os.path.abspath(str(right)))


def _safe_basename(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and Path(value).name == value
        and value not in {".", ".."}
    )


def _safe_rom_temp_name(name: str, target_name: str, kind: str) -> bool:
    prefix = f"{target_name}{_TEMP_MARKER}{kind}."
    return _safe_basename(name) and name.startswith(prefix) and name.endswith(".tmp")


def _safe_store_temp_name(name: Any, target_name: str, kind: str) -> bool:
    if not _safe_basename(name):
        return False
    prefix = f"{target_name}{_TEMP_MARKER}{kind}."
    return name.startswith(prefix) and name.endswith(".tmp")


def _valid_nonnegative_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _write_initial_journal(root: Path, document: Mapping[str, Any]) -> None:
    path = root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME
    content = _json_bytes(document)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        _fsync_directory_best_effort(root)
    except FileExistsError as error:
        raise CollectionCurrentRomReplaceRecoveryError(
            "Another or interrupted current-ROM replacement owns the journal."
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_journal(root: Path, document: Mapping[str, Any]) -> None:
    temp = _temp_bytes(root, COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME, "journal", _json_bytes(document))
    os.replace(temp, root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME)
    _fsync_directory_best_effort(root)


def _remove_journal(root: Path) -> None:
    path = root / COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME
    if path.exists():
        path.unlink()
    _fsync_directory_best_effort(root)


def _cleanup_artifacts(document: Mapping[str, Any]) -> None:
    for raw in (document["rom"].get("staged"), document["rom"].get("rollback")):
        if raw:
            try:
                Path(raw).unlink(missing_ok=True)
            except OSError:
                pass
    root = Path(document["processed"]["path"]).parent
    for entry in document["stores"]:
        for key in ("staged", "rollback"):
            name = entry.get(key)
            if name:
                try:
                    (root / name).unlink(missing_ok=True)
                except OSError:
                    pass


def _assert_rom_target_hash(document, *, expected_new: bool) -> None:
    entry = document["rom"]
    if expected_new:
        _hash_exact(entry["target"], entry["new_sha256"], entry["new_size_bytes"], None, "committed current ROM")
    else:
        _hash_exact(entry["target"], entry["old_sha256"], entry["old_size_bytes"], None, "reviewed current ROM")


def _assert_manager_unchanged(manager, snapshot, disk_state) -> None:
    if manager.data != snapshot or _capture_file(Path(manager.json_path)) != disk_state:
        raise CollectionCurrentRomReplaceStaleStateError(
            "Collection changed while Replace Current ROM Apply was running."
        )


def _require_preconditions_current(finalized, manager, hints, participants) -> None:
    expected = {(item.store_name, item.revision_token) for item in finalized.plan.preconditions}
    actual = {(item.store_name, item.revision_token) for item in collect_store_preconditions(manager, hints, participants)}
    if expected != actual:
        raise CollectionCurrentRomReplaceStaleStateError(
            "Collection/dependent state changed after current-ROM disposition review. Restart the update check."
        )


def _runtime_participants(processed: Path, participants):
    if participants is not None:
        return tuple(participants)
    from collection_ingestion_entrypoint import collection_identity_reference_participants
    return tuple(collection_identity_reference_participants(processed))


def _capture_file(path: Path) -> tuple[bool, bytes | None]:
    if not path.exists():
        return False, None
    if not path.is_file() or path.is_symlink():
        raise CollectionCurrentRomReplaceStaleStateError(f"Transaction store is not a regular file: {path}")
    return True, path.read_bytes()


def _hash_exact(path_value, expected_sha, expected_size, expected_mtime, label) -> None:
    path = Path(path_value).expanduser()
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as error:
        raise CollectionCurrentRomReplaceStaleStateError(f"{label} cannot be inspected: {path}: {error}") from error
    if path.is_symlink() or not path.is_file():
        raise CollectionCurrentRomReplaceStaleStateError(f"{label} is not a regular non-symlink file: {path}")
    mtime = int(getattr(before, "st_mtime_ns", int(before.st_mtime * 1e9)))
    if int(before.st_size) != expected_size or (expected_mtime is not None and mtime != expected_mtime):
        raise CollectionCurrentRomReplaceStaleStateError(f"{label} changed after review: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    after_mtime = int(getattr(after, "st_mtime_ns", int(after.st_mtime * 1e9)))
    if (before.st_size, mtime) != (after.st_size, after_mtime) or digest.hexdigest() != expected_sha:
        raise CollectionCurrentRomReplaceStaleStateError(f"{label} bytes changed after review: {path}")


def _copy_temp(source: Path, directory: Path, target_name: str, kind: str) -> Path:
    if not directory.is_dir() or directory.is_symlink():
        raise CollectionCurrentRomReplaceStaleStateError(
            f"Current ROM parent directory is unavailable or unsafe: {directory}"
        )
    fd, raw = tempfile.mkstemp(prefix=f"{target_name}{_TEMP_MARKER}{kind}.", suffix=".tmp", dir=directory)
    path = Path(raw)
    try:
        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            fd = -1
            shutil.copyfileobj(src, dst, length=1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        return path
    except Exception:
        if fd >= 0:
            os.close(fd)
        path.unlink(missing_ok=True)
        raise


def _temp_bytes(root: Path, target_name: str, kind: str, content: bytes) -> Path:
    fd, raw = tempfile.mkstemp(prefix=f"{target_name}{_TEMP_MARKER}{kind}.", suffix=".tmp", dir=root)
    path = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return path
    except Exception:
        if fd >= 0:
            os.close(fd)
        path.unlink(missing_ok=True)
        raise


def _json_bytes(value: Any) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        normalized = json.loads(encoded)
        return (json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise CollectionCurrentRomReplaceApplyError(f"Transaction JSON is not serializable: {error}") from error


def _file_sha256_or_none(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file() or path.is_symlink():
        raise CollectionCurrentRomReplaceRecoveryError(f"Recovery target is not a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_sha(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _reject_nonfinite(value):
    raise CollectionCurrentRomReplaceRecoveryError(
        f"Non-finite JSON number in current-ROM replacement journal: {value}"
    )


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CollectionCurrentRomReplaceRecoveryError(f"Duplicate JSON key in current-ROM journal: {key}")
        result[key] = value
    return result


def _fsync_directory_best_effort(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _result_paths(stores: Sequence[_StoreState], rom_target: str):
    for state in stores:
        yield str(state.target)
    yield str(rom_target)


def _maybe_crash(requested, step):
    if requested == step:
        raise _SimulatedCrash(f"Simulated crash after {step}")


__all__ = [
    "COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME",
    "CollectionCurrentRomReplaceApplyError",
    "CollectionCurrentRomReplaceRecoveryError",
    "CollectionCurrentRomReplaceRecoveryInfo",
    "CollectionCurrentRomReplaceRecoveryRequiredError",
    "CollectionCurrentRomReplaceStaleStateError",
    "apply_current_rom_replacement",
    "inspect_interrupted_current_rom_replacement",
    "recover_interrupted_current_rom_replacement",
]
