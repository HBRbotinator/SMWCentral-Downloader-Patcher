"""Transactional Collection-ID migration support for Save Data Sync aliases."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from collection_change_plan import ReferenceMigrationOperation
from collection_plan_apply import PreparedFileWrite, PreparedReferenceMutation
from collection_reconciliation import validate_collection_key

SAVE_SYNC_REFERENCE_STORE_NAME = "save_sync_config"
SAVE_SYNC_ASSOCIATION_CONFIG_KEY = "save_sync_associations"
SAVE_SYNC_PATH_ASSOCIATION_CONFIG_KEY = "save_sync_path_associations"
DEFAULT_CONFIG_FILENAME = "config.json"


class SaveSyncReferenceError(RuntimeError):
    """Raised when Save Data Sync reference state cannot be migrated safely."""


class SaveSyncAssociationReferenceParticipant:
    """Repoint Save Data Sync's config-held save associations transactionally."""

    store_name = SAVE_SYNC_REFERENCE_STORE_NAME
    def __init__(self, config_path: str | Path):
        self.path = Path(config_path)

    @classmethod
    def beside_processed_json(cls, processed_json_path: str | Path):
        """Create a participant for the config.json beside processed.json."""

        processed = Path(processed_json_path)
        return cls(processed.with_name(DEFAULT_CONFIG_FILENAME))

    def revision_token(self) -> str:
        """Hash the exact config bytes so unrelated settings cannot be overwritten."""
        return _file_revision_token(self.path)

    def prepare_reference_migrations(
        self,
        migrations: Sequence[ReferenceMigrationOperation],
    ) -> PreparedReferenceMutation:
        """Prepare a detached config replacement without mutating disk or live config."""

        expected = self.revision_token()
        document = _load_config_document(self.path)
        associations = _load_associations(document)
        path_associations = _load_associations(
            document, SAVE_SYNC_PATH_ASSOCIATION_CONFIG_KEY
        )
        migration_map = _validated_migration_map(migrations)
        migrated = {
            key: migration_map.get(target, target)
            for key, target in associations.items()
        }
        migrated_paths = {
            key: migration_map.get(target, target)
            for key, target in path_associations.items()
        }
        changed = migrated != associations or migrated_paths != path_associations
        writes = ()
        if changed:
            updated = dict(document)
            if migrated != associations:
                updated[SAVE_SYNC_ASSOCIATION_CONFIG_KEY] = migrated
            if migrated_paths != path_associations:
                updated[SAVE_SYNC_PATH_ASSOCIATION_CONFIG_KEY] = migrated_paths
            writes = (
                PreparedFileWrite(
                    path=self.path,
                    content_bytes=_serialize_config(updated),
                ),
            )
        return PreparedReferenceMutation(
            store_name=self.store_name,
            expected_revision_token=expected,
            writes=writes,
        )

def _validated_migration_map(
    migrations: Sequence[ReferenceMigrationOperation],
) -> dict[str, str]:
    result: dict[str, str] = {}
    targets = set()
    for migration in migrations:
        source = validate_collection_key(migration.source_key)
        target = validate_collection_key(migration.target_key)
        previous = result.get(source)
        if previous is not None and previous != target:
            raise SaveSyncReferenceError(
                f"Conflicting Save Sync migrations for Collection key {source!r}."
            )
        result[source] = target
        targets.add(target)
    if set(result).intersection(targets):
        raise SaveSyncReferenceError(
            "Chained/cyclic Save Sync Collection-ID migrations are not supported."
        )
    return result

def _load_config_document(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
        raw = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, SaveSyncReferenceError) as error:
        raise SaveSyncReferenceError(f"Cannot read Save Sync config references: {error}") from error
    if not isinstance(raw, dict):
        raise SaveSyncReferenceError("Application config must be a JSON object.")
    return raw

def _load_associations(
    document: Mapping[str, Any],
    config_key: str = SAVE_SYNC_ASSOCIATION_CONFIG_KEY,
) -> dict[str, str]:
    raw = document.get(config_key, {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SaveSyncReferenceError(
            f"{config_key} must be a JSON object."
        )
    result = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise SaveSyncReferenceError(
                "Save Sync association keys and Collection IDs must be strings."
            )
        clean_key = key.strip()
        clean_value = value.strip()
        if not clean_key or not clean_value:
            raise SaveSyncReferenceError(
                "Save Sync associations cannot contain empty keys or Collection IDs."
            )
        if clean_key in result and result[clean_key] != clean_value:
            raise SaveSyncReferenceError(
                f"Save Sync config contains conflicting association {clean_key!r}."
            )
        result[clean_key] = clean_value
    return result

def _serialize_config(document: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise SaveSyncReferenceError(f"Application config is not JSON-safe: {error}") from error
    return text.encode("utf-8")

def _file_revision_token(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        content = path.read_bytes()
    except OSError as error:
        raise SaveSyncReferenceError(f"Cannot read Save Sync config revision: {error}") from error
    return "sha256:" + hashlib.sha256(content).hexdigest()

def _reject_duplicate_object_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SaveSyncReferenceError(f"Duplicate config JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str):
    raise SaveSyncReferenceError(f"Non-finite config JSON number is not allowed: {value}")

__all__ = [
    "DEFAULT_CONFIG_FILENAME",
    "SAVE_SYNC_ASSOCIATION_CONFIG_KEY",
    "SAVE_SYNC_PATH_ASSOCIATION_CONFIG_KEY",
    "SAVE_SYNC_REFERENCE_STORE_NAME",
    "SaveSyncAssociationReferenceParticipant",
    "SaveSyncReferenceError",
]
