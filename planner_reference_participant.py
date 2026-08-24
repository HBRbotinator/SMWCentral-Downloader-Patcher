"""Transactional Collection-ID migration support for optional Planner state."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from collection_change_plan import ReferenceMigrationOperation
from collection_plan_apply import PreparedFileWrite, PreparedReferenceMutation
from collection_reconciliation import validate_collection_key
from planner_store import PLANNER_SCHEMA_VERSION


PLANNER_REFERENCE_STORE_NAME = "planner_state"
DEFAULT_PLANNER_FILENAME = "planner_state.json"


class PlannerReferenceError(RuntimeError):
    """Raised when persisted Planner Collection references cannot be migrated safely."""


class PlannerCollectionReferenceParticipant:
    """Repoint Planner-owned Collection references without exposing Planner semantics."""

    store_name = PLANNER_REFERENCE_STORE_NAME

    def __init__(self, planner_path: str | Path):
        self.path = Path(planner_path)

    @classmethod
    def beside_processed_json(cls, processed_json_path: str | Path):
        """Create the optional Planner participant beside processed.json."""

        processed = Path(processed_json_path)
        return cls(processed.with_name(DEFAULT_PLANNER_FILENAME))

    def revision_token(self) -> str:
        """Hash exact Planner bytes; a missing optional store is a stable state."""

        return _file_revision_token(self.path)

    def prepare_reference_migrations(
        self,
        migrations: Sequence[ReferenceMigrationOperation],
    ) -> PreparedReferenceMutation:
        """Prepare a detached Planner replacement without mutating disk or live state."""

        expected = self.revision_token()
        if not self.path.exists():
            return PreparedReferenceMutation(
                store_name=self.store_name,
                expected_revision_token=expected,
                writes=(),
            )

        document = _load_planner_document(self.path)
        migration_map = _validated_migration_map(migrations)
        if not migration_map:
            return PreparedReferenceMutation(
                store_name=self.store_name,
                expected_revision_token=expected,
                writes=(),
            )

        entries = _load_entries(document)
        queue = _load_next_queue(document)
        migrated_entries = _migrate_entries(entries, migration_map)
        migrated_queue = _migrate_next_queue(queue, migration_map)
        changed = migrated_entries != entries or migrated_queue != queue

        writes = ()
        if changed:
            updated = dict(document)
            updated["entries"] = migrated_entries
            updated["next_queue"] = migrated_queue
            writes = (
                PreparedFileWrite(
                    path=self.path,
                    content_bytes=_serialize_planner(updated),
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
    target_sources: dict[str, str] = {}
    for migration in migrations:
        source = validate_collection_key(migration.source_key)
        target = validate_collection_key(migration.target_key)
        previous = result.get(source)
        if previous is not None and previous != target:
            raise PlannerReferenceError(
                f"Conflicting Planner migrations for Collection key {source!r}."
            )
        other_source = target_sources.get(target)
        if other_source is not None and other_source != source:
            raise PlannerReferenceError(
                f"Multiple Collection identities cannot migrate into Planner target {target!r}."
            )
        result[source] = target
        target_sources[target] = source
    if set(result).intersection(target_sources):
        raise PlannerReferenceError(
            "Chained/cyclic Planner Collection-ID migrations are not supported."
        )
    return result


def _load_planner_document(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8-sig")
        raw = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, PlannerReferenceError) as error:
        raise PlannerReferenceError(f"Cannot read Planner references: {error}") from error
    if not isinstance(raw, dict):
        raise PlannerReferenceError("Planner state must be a JSON object.")
    schema = raw.get("schema_version", PLANNER_SCHEMA_VERSION)
    if schema != PLANNER_SCHEMA_VERSION:
        raise PlannerReferenceError(f"Unsupported Planner schema: {schema!r}.")
    return raw


def _load_entries(document: Mapping[str, Any]) -> dict[str, Any]:
    raw = document.get("entries", {})
    if not isinstance(raw, dict):
        raise PlannerReferenceError("Planner entries must be a JSON object.")
    return dict(raw)


def _load_next_queue(document: Mapping[str, Any]) -> list[str]:
    raw = document.get("next_queue", [])
    if not isinstance(raw, list):
        raise PlannerReferenceError("Planner next_queue must be a JSON array.")
    result = []
    for value in raw:
        if not isinstance(value, str) or not value.strip():
            raise PlannerReferenceError(
                "Planner next_queue Collection references must be non-empty strings."
            )
        result.append(value.strip())
    return result


def _migrate_entries(
    entries: Mapping[str, Any],
    migrations: Mapping[str, str],
) -> dict[str, Any]:
    for source, target in migrations.items():
        if source not in entries or target not in entries:
            continue
        if entries[source] != entries[target]:
            raise PlannerReferenceError(
                "Planner has different planning state for both sides of Collection "
                f"identity migration {source!r} -> {target!r}. Resolve that Planner "
                "state before applying the Collection migration."
            )

    result: dict[str, Any] = {}
    for key, value in entries.items():
        target = migrations.get(key, key)
        if target in result:
            if result[target] != value:
                raise PlannerReferenceError(
                    f"Planner migration would overwrite different state for {target!r}."
                )
            continue
        result[target] = value
    return result


def _migrate_next_queue(
    queue: Sequence[str],
    migrations: Mapping[str, str],
) -> list[str]:
    result = []
    seen = set()
    for value in queue:
        target = migrations.get(value, value)
        if target in seen:
            continue
        seen.add(target)
        result.append(target)
    return result


def _serialize_planner(document: Mapping[str, Any]) -> bytes:
    try:
        text = json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise PlannerReferenceError(f"Planner state is not JSON-safe: {error}") from error
    return text.encode("utf-8")


def _file_revision_token(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        content = path.read_bytes()
    except OSError as error:
        raise PlannerReferenceError(f"Cannot read Planner revision: {error}") from error
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _reject_duplicate_object_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise PlannerReferenceError(f"Duplicate Planner JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str):
    raise PlannerReferenceError(f"Non-finite Planner JSON number is not allowed: {value}")


__all__ = [
    "DEFAULT_PLANNER_FILENAME",
    "PLANNER_REFERENCE_STORE_NAME",
    "PlannerCollectionReferenceParticipant",
    "PlannerReferenceError",
]
