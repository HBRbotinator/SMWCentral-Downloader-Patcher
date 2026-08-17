"""Transactional v5.1 HackDataManager adapter for bulk Collection imports."""

from __future__ import annotations

import copy
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping, Sequence

from bulk_collection_import_application import (
    bulk_collection_import_shared_record_sha256,
)
from bulk_collection_import_collection_adapter import (
    COLLECTION_IMPORT_EXTENSION_KEY,
    COLLECTION_IMPORT_EXTENSION_VERSION,
    bulk_collection_import_collection_records_to_documents,
    project_bulk_collection_import_collection,
)
from hack_data_manager import HackDataManager


BULK_IMPORT_EXTENSION_KEY = COLLECTION_IMPORT_EXTENSION_KEY
BULK_IMPORT_EXTENSION_VERSION = COLLECTION_IMPORT_EXTENSION_VERSION
BULK_IMPORT_TEMP_SUFFIX = ".bulk-import.tmp"

_CORE_ATTRIBUTE_TARGETS = {
    "authors": "authors",
    "difficulty": "current_difficulty",
    "exit_count": "exits",
    "release_date": "date",
}
_RESERVED_LOCAL_ATTRIBUTE_FIELDS = frozenset(
    {
        "completed",
        "completed_date",
        "personal_rating",
        "notes",
        "time_to_beat",
        "file_path",
        "files",
        "additional_paths",
        "save_sync_metadata",
        "provider_extension",
        "local_save_entry",
        "obsolete",
        "hack_type",
        "hack_types",
        "folder_name",
    }
)


class BulkCollectionImportHackDataStoreError(RuntimeError):
    """Raised when the concrete v5.1 Collection store cannot proceed safely."""


class BulkCollectionImportHackDataStore:
    """Expose HackDataManager through the Commit 105 store contract."""

    def __init__(self, manager: HackDataManager):
        if not isinstance(manager, HackDataManager):
            raise TypeError("manager must be a HackDataManager")
        self.manager = manager

    def record_exists(self, collection_key: str) -> bool:
        key = _require_collection_key(collection_key)
        return key in self.manager.data

    def shared_sha256(self, collection_key: str) -> str | None:
        key = _require_collection_key(collection_key)
        record = self.manager.data.get(key)
        if not isinstance(record, Mapping):
            return None

        projection = project_bulk_collection_import_collection(
            {key: record}
        )
        documents = (
            bulk_collection_import_collection_records_to_documents(
                projection
            )
        )
        if len(documents) != 1:
            raise BulkCollectionImportHackDataStoreError(
                "Collection projection did not return exactly one record."
            )

        return bulk_collection_import_shared_record_sha256(
            documents[0]
        )

    def begin_transaction(self):
        return BulkCollectionImportHackDataTransaction(self.manager)


class BulkCollectionImportHackDataTransaction:
    """Stage one all-or-nothing processed.json replacement."""

    def __init__(self, manager: HackDataManager):
        self.manager = manager
        self._staged_data = copy.deepcopy(manager.data)
        self._manager_data_at_begin = copy.deepcopy(manager.data)
        self._unsaved_at_begin = bool(manager.unsaved_changes)
        self._path = Path(manager.json_path)
        self._backup_path = Path(f"{manager.json_path}.backup")
        self._temp_path = Path(f"{manager.json_path}{BULK_IMPORT_TEMP_SUFFIX}")
        self._disk_exists_at_begin = self._path.exists()
        self._disk_bytes_at_begin = (
            self._path.read_bytes()
            if self._disk_exists_at_begin
            else None
        )
        self._finished = False
        self._timer_cancelled = False

        # Explicit test seam for failure handling immediately before replace.
        self.fail_before_replace = False

    def create_record(
        self,
        *,
        collection_key,
        title,
        source_references,
        attributes,
        user_state,
    ):
        self._require_open()

        key = _require_collection_key(collection_key)
        if key in self._staged_data:
            raise BulkCollectionImportHackDataStoreError(
                f"Collection key already exists: {key}"
            )
        if user_state != {}:
            raise BulkCollectionImportHackDataStoreError(
                "Bulk import creates must initialize empty user-owned state."
            )

        shared_attributes = _parse_attribute_mapping(attributes)
        references = _parse_source_references(source_references)

        record = {
            "title": _require_text(title, "title"),
            "current_difficulty": "No Difficulty",
            "authors": [],
            "exits": 0,
            "date": "",
            "completed": False,
            "completed_date": "",
            "personal_rating": 0,
            "time_to_beat": 0,
            "notes": "",
            "obsolete": False,
            "file_path": "",
            "files": [],
            "additional_paths": [],
        }

        extension_attributes = {}
        for field, value in shared_attributes.items():
            if field in _CORE_ATTRIBUTE_TARGETS:
                _apply_core_attribute(record, field, value)
            else:
                _require_extension_attribute_field(field)
                extension_attributes[field] = copy.deepcopy(value)

        record[BULK_IMPORT_EXTENSION_KEY] = {
            "version": BULK_IMPORT_EXTENSION_VERSION,
            "aliases": [],
            "source_references": copy.deepcopy(references),
            "attributes": extension_attributes,
        }

        self._staged_data[key] = record

    def update_record(
        self,
        *,
        collection_key,
        title_value,
        source_reference_additions,
        attribute_changes,
    ):
        self._require_open()

        key = _require_collection_key(collection_key)
        record = self._staged_data.get(key)
        if not isinstance(record, dict):
            raise BulkCollectionImportHackDataStoreError(
                f"Collection record does not exist: {key}"
            )

        if title_value is not None:
            record["title"] = _require_text(
                title_value,
                "title_value",
            )

        additions = _parse_source_references(
            source_reference_additions
        )
        extension = _ensure_extension(record)

        existing_references = {
            (
                reference["source"],
                reference["external_id"],
            )
            for reference in extension["source_references"]
        }
        for reference in additions:
            identity = (
                reference["source"],
                reference["external_id"],
            )
            if identity in existing_references:
                continue
            extension["source_references"].append(
                copy.deepcopy(reference)
            )
            existing_references.add(identity)

        changes = _parse_attribute_changes(attribute_changes)
        for field, value in changes:
            if field in _CORE_ATTRIBUTE_TARGETS:
                _apply_core_attribute(record, field, value)
            else:
                _require_extension_attribute_field(field)
                extension["attributes"][field] = copy.deepcopy(value)

    def commit(self):
        self._require_open()
        previous_backup_exists = self._backup_path.exists()
        previous_backup_bytes = (
            self._backup_path.read_bytes()
            if previous_backup_exists
            else None
        )
        backup_changed = False

        preflight_passed = False
        try:
            self._assert_live_state_unchanged_since_begin()
            preflight_passed = True
            self._cancel_pending_timer()
            self._write_staged_temp()

            if self.fail_before_replace:
                raise BulkCollectionImportHackDataStoreError(
                    "Injected failure before atomic Collection replacement."
                )

            if self._path.exists():
                shutil.copy2(self._path, self._backup_path)
                backup_changed = True

            os.replace(self._temp_path, self._path)

            self.manager.data = copy.deepcopy(self._staged_data)
            self.manager.unsaved_changes = False
            self.manager._save_timer = None
            self._finished = True
            self.manager._log(
                (
                    "💾 Bulk Collection import committed "
                    f"{len(self.manager.data)} records atomically to "
                    f"{self.manager.json_path}"
                ),
                "Information",
            )
        except Exception:
            self._remove_temp_file()
            if backup_changed:
                self._restore_previous_backup(
                    previous_backup_exists,
                    previous_backup_bytes,
                )
            if preflight_passed:
                self._restore_manager_after_failed_commit()
            else:
                # A concurrent manager/disk change is external to this
                # transaction. Mark the transaction finished so a caller's
                # defensive rollback cannot overwrite that newer state.
                self._finished = True
            raise

    def rollback(self):
        if self._finished:
            return

        self._remove_temp_file()
        self.manager.data = copy.deepcopy(self._manager_data_at_begin)
        self.manager.unsaved_changes = self._unsaved_at_begin
        self._restore_pending_timer_if_needed()
        self._finished = True

    def _assert_live_state_unchanged_since_begin(self):
        if self.manager.data != self._manager_data_at_begin:
            raise BulkCollectionImportHackDataStoreError(
                "HackDataManager changed after the import transaction began."
            )

        disk_exists = self._path.exists()
        if disk_exists != self._disk_exists_at_begin:
            raise BulkCollectionImportHackDataStoreError(
                "processed.json changed after the import transaction began."
            )
        if (
            disk_exists
            and self._path.read_bytes() != self._disk_bytes_at_begin
        ):
            raise BulkCollectionImportHackDataStoreError(
                "processed.json changed after the import transaction began."
            )

    def _cancel_pending_timer(self):
        timer = getattr(self.manager, "_save_timer", None)
        if timer is not None:
            timer.cancel()
            self.manager._save_timer = None
            self._timer_cancelled = True

    def _restore_pending_timer_if_needed(self):
        if (
            self._unsaved_at_begin
            and self._timer_cancelled
            and getattr(self.manager, "_save_timer", None) is None
        ):
            self.manager._schedule_delayed_save()
        self._timer_cancelled = False

    def _restore_manager_after_failed_commit(self):
        self.manager.data = copy.deepcopy(self._manager_data_at_begin)
        self.manager.unsaved_changes = self._unsaved_at_begin
        self._restore_pending_timer_if_needed()

    def _write_staged_temp(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._remove_temp_file()

        try:
            with self._temp_path.open(
                "w",
                encoding="utf-8",
                newline="\n",
            ) as handle:
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
            self._remove_temp_file()
            raise

    def _restore_previous_backup(
        self,
        existed: bool,
        contents: bytes | None,
    ):
        try:
            if existed:
                assert contents is not None
                self._backup_path.write_bytes(contents)
            elif self._backup_path.exists():
                self._backup_path.unlink()
        except Exception as error:
            raise BulkCollectionImportHackDataStoreError(
                "Bulk import failed and the previous backup "
                "could not be restored."
            ) from error

    def _remove_temp_file(self):
        try:
            if self._temp_path.exists():
                self._temp_path.unlink()
        except OSError:
            pass

    def _require_open(self):
        if self._finished:
            raise BulkCollectionImportHackDataStoreError(
                "Bulk import transaction is already finished."
            )


def _ensure_extension(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get(BULK_IMPORT_EXTENSION_KEY)
    if raw is None:
        extension = {
            "version": BULK_IMPORT_EXTENSION_VERSION,
            "aliases": [],
            "source_references": [],
            "attributes": {},
        }
        record[BULK_IMPORT_EXTENSION_KEY] = extension
        return extension

    if not isinstance(raw, dict):
        raise BulkCollectionImportHackDataStoreError(
            "Existing bulk import extension is malformed."
        )
    if raw.get("version") != BULK_IMPORT_EXTENSION_VERSION:
        raise BulkCollectionImportHackDataStoreError(
            "Existing bulk import extension version is unsupported."
        )
    if set(raw) != {
        "version",
        "aliases",
        "source_references",
        "attributes",
    }:
        raise BulkCollectionImportHackDataStoreError(
            "Existing bulk import extension fields are malformed."
        )
    if not isinstance(raw["aliases"], list):
        raise BulkCollectionImportHackDataStoreError(
            "Existing bulk import aliases must be a list."
        )
    if not isinstance(raw["source_references"], list):
        raise BulkCollectionImportHackDataStoreError(
            "Existing bulk import source references must be a list."
        )
    if not isinstance(raw["attributes"], dict):
        raise BulkCollectionImportHackDataStoreError(
            "Existing bulk import attributes must be an object."
        )

    _parse_source_references(raw["source_references"])
    _parse_attribute_mapping(raw["attributes"])
    return raw


def _apply_core_attribute(
    record: dict[str, Any],
    field: str,
    value: Any,
):
    if field == "authors":
        if not isinstance(value, (list, tuple)):
            raise BulkCollectionImportHackDataStoreError(
                "authors must be a list of strings."
            )
        record["authors"] = [
            _require_text(author, "author")
            for author in value
        ]
        return

    if field == "difficulty":
        record["current_difficulty"] = _require_text(
            value,
            "difficulty",
        )
        return

    if field == "exit_count":
        if (
            isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
        ):
            raise BulkCollectionImportHackDataStoreError(
                "exit_count must be a non-negative integer."
            )
        record["exits"] = value
        return

    if field == "release_date":
        if value == "":
            record["date"] = ""
            return
        record["date"] = _require_text(
            value,
            "release_date",
        )
        return

    raise BulkCollectionImportHackDataStoreError(
        f"Unsupported core shared attribute: {field}"
    )


def _parse_source_references(
    value: Any,
) -> list[dict[str, str]]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportHackDataStoreError(
            "source references must be a sequence."
        )

    result = []
    seen = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise BulkCollectionImportHackDataStoreError(
                f"source reference {index} must be an object."
            )
        if set(raw) != {"source", "external_id"}:
            raise BulkCollectionImportHackDataStoreError(
                f"source reference {index} fields are invalid."
            )

        reference = {
            "source": _require_text(
                raw["source"],
                f"source reference {index} source",
            ),
            "external_id": _require_text(
                raw["external_id"],
                f"source reference {index} external_id",
            ),
        }
        identity = (
            reference["source"],
            reference["external_id"],
        )
        if identity in seen:
            continue
        seen.add(identity)
        result.append(reference)

    return result


def _parse_attribute_mapping(
    value: Any,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportHackDataStoreError(
            "attributes must be an object."
        )

    result = {}
    for raw_field, raw_value in value.items():
        field = _require_text(raw_field, "attribute field")
        if (
            field in _RESERVED_LOCAL_ATTRIBUTE_FIELDS
            and field not in _CORE_ATTRIBUTE_TARGETS
        ):
            raise BulkCollectionImportHackDataStoreError(
                f"Local Collection field cannot be imported: {field}"
            )
        result[field] = _validated_json_copy(
            raw_value,
            f"attribute {field}",
        )
    return result


def _parse_attribute_changes(
    value: Any,
) -> list[tuple[str, Any]]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportHackDataStoreError(
            "attribute_changes must be a sequence."
        )

    result = []
    seen = set()
    for index, raw in enumerate(value):
        if not isinstance(raw, Mapping):
            raise BulkCollectionImportHackDataStoreError(
                f"attribute change {index} must be an object."
            )
        if set(raw) != {"field", "value"}:
            raise BulkCollectionImportHackDataStoreError(
                f"attribute change {index} fields are invalid."
            )

        field = _require_text(
            raw["field"],
            f"attribute change {index} field",
        )
        if field in seen:
            raise BulkCollectionImportHackDataStoreError(
                f"Duplicate attribute change field: {field}"
            )
        seen.add(field)

        if (
            field in _RESERVED_LOCAL_ATTRIBUTE_FIELDS
            and field not in _CORE_ATTRIBUTE_TARGETS
        ):
            raise BulkCollectionImportHackDataStoreError(
                f"Local Collection field cannot be imported: {field}"
            )

        result.append(
            (
                field,
                _validated_json_copy(
                    raw["value"],
                    f"attribute change {field}",
                ),
            )
        )

    return result


def _require_extension_attribute_field(field: str):
    if field in _CORE_ATTRIBUTE_TARGETS:
        raise BulkCollectionImportHackDataStoreError(
            f"Core shared field cannot be stored in extension: {field}"
        )
    if field in _RESERVED_LOCAL_ATTRIBUTE_FIELDS:
        raise BulkCollectionImportHackDataStoreError(
            f"Local Collection field cannot be stored in extension: {field}"
        )


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
        raise BulkCollectionImportHackDataStoreError(
            f"{label} must contain finite JSON data."
        ) from error


def _require_collection_key(value: Any) -> str:
    return _require_text(value, "collection_key")


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportHackDataStoreError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


__all__ = [
    "BULK_IMPORT_EXTENSION_KEY",
    "BULK_IMPORT_EXTENSION_VERSION",
    "BULK_IMPORT_TEMP_SUFFIX",
    "BulkCollectionImportHackDataStoreError",
    "BulkCollectionImportHackDataStore",
    "BulkCollectionImportHackDataTransaction",
]
