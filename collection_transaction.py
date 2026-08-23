"""Source-neutral atomic transactions for v5.1 Collection state."""

from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Mapping

from hack_data_manager import HackDataManager


COLLECTION_TRANSACTION_TEMP_MARKER = ".collection-transaction."


class CollectionTransactionError(RuntimeError):
    """Raised when a Collection transaction cannot proceed safely."""


class CollectionStaleStateError(CollectionTransactionError):
    """Raised when live Collection state changes during a transaction."""


class HackDataManagerCollectionStore:
    """Expose HackDataManager through a source-neutral transaction boundary."""

    def __init__(self, manager: HackDataManager):
        if not isinstance(manager, HackDataManager):
            raise TypeError("manager must be a HackDataManager")
        self.manager = manager

    def record_exists(self, collection_key: str) -> bool:
        key = _require_collection_key(collection_key)
        return key in self.manager.data

    def record_snapshot(
        self,
        collection_key: str,
    ) -> dict[str, Any] | None:
        key = _require_collection_key(collection_key)
        record = self.manager.data.get(key)
        if not isinstance(record, Mapping):
            return None
        return copy.deepcopy(dict(record))

    def begin_transaction(self) -> CollectionTransaction:
        return CollectionTransaction(self.manager)


class CollectionTransaction:
    """Stage one all-or-nothing processed.json replacement."""

    def __init__(self, manager: HackDataManager):
        if not isinstance(manager, HackDataManager):
            raise TypeError("manager must be a HackDataManager")

        self.manager = manager
        self._staged_data = copy.deepcopy(manager.data)
        self._manager_data_at_begin = copy.deepcopy(manager.data)
        self._unsaved_at_begin = bool(manager.unsaved_changes)

        self._path = Path(manager.json_path)
        self._backup_path = Path(f"{manager.json_path}.backup")
        self._temp_path: Path | None = None

        self._disk_exists_at_begin = self._path.exists()
        self._disk_bytes_at_begin = (
            self._path.read_bytes()
            if self._disk_exists_at_begin
            else None
        )

        self._finished = False
        self._timer_cancelled = False

        # Explicit test seam immediately before the atomic replacement.
        self.fail_before_replace = False

    def create_record(
        self,
        collection_key: str,
        record: Mapping[str, Any],
    ) -> None:
        """Create one complete Collection record in staged state."""

        self._require_open()
        key = _require_collection_key(collection_key)
        if key in self._staged_data:
            raise CollectionTransactionError(
                f"Collection key already exists: {key}"
            )

        self._staged_data[key] = _validated_record_copy(
            record,
            "record",
        )

    def update_record(
        self,
        collection_key: str,
        changes: Mapping[str, Any],
    ) -> None:
        """Apply top-level field changes while preserving other record state."""

        self._require_open()
        key = _require_collection_key(collection_key)
        record = self._staged_data.get(key)
        if not isinstance(record, dict):
            raise CollectionTransactionError(
                f"Collection record does not exist: {key}"
            )
        if not isinstance(changes, Mapping):
            raise CollectionTransactionError(
                "changes must be a mapping."
            )

        for raw_field, raw_value in changes.items():
            field = _require_field_name(raw_field)
            record[field] = _validated_json_copy(
                raw_value,
                f"field {field}",
            )

    def replace_record(
        self,
        collection_key: str,
        record: Mapping[str, Any],
    ) -> None:
        """Replace one existing record with an explicitly supplied record."""

        self._require_open()
        key = _require_collection_key(collection_key)
        if key not in self._staged_data:
            raise CollectionTransactionError(
                f"Collection record does not exist: {key}"
            )

        self._staged_data[key] = _validated_record_copy(
            record,
            "record",
        )

    def staged_record(
        self,
        collection_key: str,
    ) -> dict[str, Any] | None:
        """Return a detached view of one staged record."""

        self._require_open()
        key = _require_collection_key(collection_key)
        record = self._staged_data.get(key)
        if not isinstance(record, Mapping):
            return None
        return copy.deepcopy(dict(record))

    def commit(self) -> None:
        """Atomically publish the staged Collection to manager and disk."""

        self._require_open()

        previous_backup_exists = self._backup_path.exists()
        previous_backup_bytes = (
            self._backup_path.read_bytes()
            if previous_backup_exists
            else None
        )
        backup_changed = False

        # Prepare publication before the atomic disk commit point. Everything
        # after os.replace() is deliberately non-failing bookkeeping.
        published_data = copy.deepcopy(self._staged_data)

        try:
            self._assert_live_state_unchanged_since_begin()
            self._cancel_pending_timer()
            self._write_staged_temp()

            # Serialization can take time for a large Collection. Detect UI,
            # delayed-save, or external changes that happened while staging.
            self._assert_live_state_unchanged_since_begin()

            if self.fail_before_replace:
                raise CollectionTransactionError(
                    "Injected failure before atomic Collection replacement."
                )

            if self._path.exists():
                # copy2 can alter its destination before raising, so backup
                # restoration must be armed before the copy starts.
                backup_changed = True
                shutil.copy2(self._path, self._backup_path)

            # Close the largest remaining stale-state window immediately
            # before replacing processed.json.
            self._assert_live_state_unchanged_since_begin()
            assert self._temp_path is not None
            os.replace(self._temp_path, self._path)
            self._temp_path = None

        except CollectionStaleStateError:
            self._remove_temp_file()
            if backup_changed:
                self._restore_previous_backup(
                    previous_backup_exists,
                    previous_backup_bytes,
                )

            # Concurrent state belongs to another actor. Never overwrite it
            # during defensive rollback.
            self._restore_pending_timer_if_needed()
            self._finished = True
            raise

        except Exception:
            self._remove_temp_file()
            if backup_changed:
                self._restore_previous_backup(
                    previous_backup_exists,
                    previous_backup_bytes,
                )
            self._restore_manager_after_failed_commit()
            raise

        # os.replace() above is the commit point.
        self.manager.data = published_data
        self.manager.unsaved_changes = False
        self.manager._save_timer = None
        self._timer_cancelled = False
        self._finished = True
        self._log_success_best_effort()

    def rollback(self) -> None:
        """Discard this transaction without overwriting newer external state."""

        if self._finished:
            return

        self._remove_temp_file()
        self.manager.data = copy.deepcopy(self._manager_data_at_begin)
        self.manager.unsaved_changes = self._unsaved_at_begin
        self._restore_pending_timer_if_needed()
        self._finished = True

    def _assert_live_state_unchanged_since_begin(self) -> None:
        if self.manager.data != self._manager_data_at_begin:
            raise CollectionStaleStateError(
                "HackDataManager changed after the Collection "
                "transaction began."
            )

        disk_exists = self._path.exists()
        if disk_exists != self._disk_exists_at_begin:
            raise CollectionStaleStateError(
                "processed.json changed after the Collection "
                "transaction began."
            )
        if (
            disk_exists
            and self._path.read_bytes() != self._disk_bytes_at_begin
        ):
            raise CollectionStaleStateError(
                "processed.json changed after the Collection "
                "transaction began."
            )

    def _cancel_pending_timer(self) -> None:
        timer = getattr(self.manager, "_save_timer", None)
        if timer is not None:
            timer.cancel()
            self.manager._save_timer = None
            self._timer_cancelled = True

    def _restore_pending_timer_if_needed(self) -> None:
        if (
            self._unsaved_at_begin
            and self._timer_cancelled
            and getattr(self.manager, "_save_timer", None) is None
        ):
            self.manager._schedule_delayed_save()
        self._timer_cancelled = False

    def _restore_manager_after_failed_commit(self) -> None:
        self.manager.data = copy.deepcopy(self._manager_data_at_begin)
        self.manager.unsaved_changes = self._unsaved_at_begin
        self._restore_pending_timer_if_needed()

    def _write_staged_temp(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_temp_file()

        descriptor = None
        try:
            descriptor, raw_path = tempfile.mkstemp(
                prefix=(
                    f"{self._path.name}"
                    f"{COLLECTION_TRANSACTION_TEMP_MARKER}"
                ),
                suffix=".tmp",
                dir=self._path.parent,
            )
            self._temp_path = Path(raw_path)

            with os.fdopen(
                descriptor,
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
                descriptor = None
                json.dump(
                    self._staged_data,
                    handle,
                    ensure_ascii=False,
                    indent=2,
                    allow_nan=False,
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            self._remove_temp_file()
            raise

    def _restore_previous_backup(
        self,
        existed: bool,
        contents: bytes | None,
    ) -> None:
        try:
            if existed:
                assert contents is not None
                self._backup_path.write_bytes(contents)
            elif self._backup_path.exists():
                self._backup_path.unlink()
        except Exception as error:
            raise CollectionTransactionError(
                "Collection transaction failed and the previous backup "
                "could not be restored."
            ) from error

    def _remove_temp_file(self) -> None:
        path = self._temp_path
        self._temp_path = None
        if path is None:
            return

        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass

    def _log_success_best_effort(self) -> None:
        try:
            self.manager._log(
                (
                    "💾 Collection transaction committed "
                    f"{len(self.manager.data)} records atomically to "
                    f"{self.manager.json_path}"
                ),
                "Information",
            )
        except Exception:
            # Logging is downstream of the atomic commit point and cannot
            # change the outcome of an already committed Collection write.
            pass

    def _require_open(self) -> None:
        if self._finished:
            raise CollectionTransactionError(
                "Collection transaction is already finished."
            )


def _validated_record_copy(
    value: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise CollectionTransactionError(
            f"{label} must be a mapping."
        )

    copied = _validated_json_copy(value, label)
    if not isinstance(copied, dict):
        raise CollectionTransactionError(
            f"{label} must be a JSON object."
        )
    return copied


def _validated_json_copy(value: Any, label: str) -> Any:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        return json.loads(encoded)
    except (TypeError, ValueError) as error:
        raise CollectionTransactionError(
            f"{label} must contain finite JSON data."
        ) from error


def _require_collection_key(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise CollectionTransactionError(
            "collection_key must be a non-empty trimmed string."
        )
    return value


def _require_field_name(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise CollectionTransactionError(
            "Collection field names must be non-empty trimmed strings."
        )
    return value


__all__ = [
    "COLLECTION_TRANSACTION_TEMP_MARKER",
    "CollectionStaleStateError",
    "CollectionTransaction",
    "CollectionTransactionError",
    "HackDataManagerCollectionStore",
]
