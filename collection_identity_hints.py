"""Versioned user-owned identity hints for Collection ingestion."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from collection_change_plan import (
    IgnoredRomOperation,
    ReferenceMigrationOperation,
    RememberedAssociationOperation,
)
from collection_ingestion import IngestionSource
from collection_reconciliation import validate_collection_key


IDENTITY_HINTS_SCHEMA_VERSION = 1
DEFAULT_IDENTITY_HINTS_FILENAME = "collection_identity_hints.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class IdentityHintsError(RuntimeError):
    """Raised when identity-hint state cannot be read or changed safely."""


class IdentityHintsStaleStateError(IdentityHintsError):
    """Raised when identity-hint state changed after review/staging."""


@dataclass(frozen=True)
class RememberedIdentityHint:
    """One source-scoped user-confirmed identity association."""

    source: IngestionSource
    value: str
    target_key: str

    def __post_init__(self) -> None:
        validate_collection_key(self.target_key)
        if not self.value.strip():
            raise IdentityHintsError("Remembered identity value must be non-empty.")


@dataclass(frozen=True)
class IgnoredRomHint:
    """Suppress one exact file only while both path and bytes still match."""

    path: str
    sha256: str

    def __post_init__(self) -> None:
        if not self.path:
            raise IdentityHintsError("Ignored ROM path must be non-empty.")
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise IdentityHintsError("Ignored ROM requires lowercase SHA-256.")


@dataclass(frozen=True)
class IdentityHintsSnapshot:
    """Detached validated sidecar state."""

    remembered_associations: tuple[RememberedIdentityHint, ...]
    ignored_roms: tuple[IgnoredRomHint, ...]
    extra_fields: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class PreparedIdentityHintsMutation:
    """Validated sidecar replacement prepared without writing to disk."""

    path: Path
    store_name: str
    expected_revision_token: str
    content_bytes: bytes
    snapshot: IdentityHintsSnapshot
    changed: bool


class CollectionIdentityHintsStore:
    """Read and stage the v1 Collection identity-hints sidecar."""

    store_name = "collection_identity_hints"

    def __init__(self, path: str | Path):
        self.path = Path(path)

    @classmethod
    def beside_processed_json(cls, processed_json_path: str | Path):
        path = Path(processed_json_path)
        return cls(path.with_name(DEFAULT_IDENTITY_HINTS_FILENAME))

    def revision_token(self) -> str:
        return _file_revision_token(self.path)

    def snapshot(self) -> IdentityHintsSnapshot:
        return _load_snapshot(self.path)

    def prepare_plan_changes(
        self,
        *,
        remembered_associations: Sequence[RememberedAssociationOperation] = (),
        ignored_roms: Sequence[IgnoredRomOperation] = (),
        reference_migrations: Sequence[ReferenceMigrationOperation] = (),
    ) -> PreparedIdentityHintsMutation:
        expected_token = self.revision_token()
        snapshot = self.snapshot()

        remembered = {
            (item.source, item.value): item
            for item in snapshot.remembered_associations
        }
        ignored = {
            (item.path, item.sha256): item
            for item in snapshot.ignored_roms
        }

        migrations = _validated_migration_map(reference_migrations)
        if migrations:
            remembered = {
                key: RememberedIdentityHint(
                    source=item.source,
                    value=item.value,
                    target_key=_follow_migration(item.target_key, migrations),
                )
                for key, item in remembered.items()
            }

        for operation in remembered_associations:
            hint = RememberedIdentityHint(
                source=operation.source,
                value=operation.value,
                target_key=_follow_migration(operation.target_key, migrations),
            )
            # Explicit newly reviewed associations replace an older association
            # for the same source/value rather than preserving a contradiction.
            remembered[(hint.source, hint.value)] = hint

        for operation in ignored_roms:
            hint = IgnoredRomHint(path=operation.path, sha256=operation.sha256)
            ignored[(hint.path, hint.sha256)] = hint

        new_snapshot = IdentityHintsSnapshot(
            remembered_associations=tuple(
                remembered[key]
                for key in sorted(remembered, key=lambda item: (item[0].value, item[1]))
            ),
            ignored_roms=tuple(
                ignored[key]
                for key in sorted(ignored, key=lambda item: (item[0], item[1]))
            ),
            extra_fields=snapshot.extra_fields,
        )
        content = _serialize_snapshot(new_snapshot)
        exists = self.path.exists()
        current_content = self.path.read_bytes() if exists else b""
        changed = (
            current_content != content
            if exists
            else bool(
                new_snapshot.remembered_associations
                or new_snapshot.ignored_roms
                or new_snapshot.extra_fields
            )
        )
        return PreparedIdentityHintsMutation(
            path=self.path,
            store_name=self.store_name,
            expected_revision_token=expected_token,
            content_bytes=content,
            snapshot=new_snapshot,
            changed=changed,
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
            raise IdentityHintsError(
                f"Conflicting identity migrations for Collection key {source!r}."
            )
        result[source] = target
        targets.add(target)
    if set(result).intersection(targets):
        raise IdentityHintsError("Chained/cyclic identity migrations are not supported.")
    return result


def _follow_migration(value: str, migrations: Mapping[str, str]) -> str:
    return migrations.get(value, value)


def _load_snapshot(path: Path) -> IdentityHintsSnapshot:
    if not path.exists():
        return IdentityHintsSnapshot(remembered_associations=(), ignored_roms=())

    try:
        raw = json.loads(
            path.read_text(encoding="utf-8-sig"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, IdentityHintsError) as error:
        raise IdentityHintsError(f"Cannot read identity hints: {error}") from error

    if not isinstance(raw, dict):
        raise IdentityHintsError("Identity-hints document must be a JSON object.")
    schema = raw.get("schema_version")
    if schema != IDENTITY_HINTS_SCHEMA_VERSION:
        raise IdentityHintsError(
            f"Unsupported identity-hints schema: {schema!r}."
        )

    remembered_raw = raw.get("remembered_associations", [])
    ignored_raw = raw.get("ignored_roms", [])
    if not isinstance(remembered_raw, list) or not isinstance(ignored_raw, list):
        raise IdentityHintsError("Identity-hints arrays have invalid shape.")

    remembered = []
    seen_associations: dict[tuple[IngestionSource, str], str] = {}
    for row in remembered_raw:
        if not isinstance(row, dict):
            raise IdentityHintsError("Remembered association must be an object.")
        try:
            source = IngestionSource(row.get("source"))
        except (TypeError, ValueError) as error:
            raise IdentityHintsError("Remembered association has invalid source.") from error
        value = row.get("value")
        target_key = row.get("target_key")
        if not isinstance(value, str) or not isinstance(target_key, str):
            raise IdentityHintsError("Remembered association fields must be strings.")
        hint = RememberedIdentityHint(source=source, value=value, target_key=target_key)
        key = (hint.source, hint.value)
        previous = seen_associations.get(key)
        if previous is not None and previous != hint.target_key:
            raise IdentityHintsError(
                "Identity-hints document contains contradictory remembered associations."
            )
        if previous is None:
            remembered.append(hint)
            seen_associations[key] = hint.target_key

    ignored = []
    seen_ignored = set()
    for row in ignored_raw:
        if not isinstance(row, dict):
            raise IdentityHintsError("Ignored ROM must be an object.")
        path_value = row.get("path")
        sha256 = row.get("sha256")
        if not isinstance(path_value, str) or not isinstance(sha256, str):
            raise IdentityHintsError("Ignored ROM fields must be strings.")
        hint = IgnoredRomHint(path=path_value, sha256=sha256)
        key = (hint.path, hint.sha256)
        if key not in seen_ignored:
            ignored.append(hint)
            seen_ignored.add(key)

    extras = tuple(
        (key, _validated_json_copy(value, f"extra field {key}"))
        for key, value in raw.items()
        if key not in {"schema_version", "remembered_associations", "ignored_roms"}
    )
    return IdentityHintsSnapshot(
        remembered_associations=tuple(remembered),
        ignored_roms=tuple(ignored),
        extra_fields=extras,
    )


def _serialize_snapshot(snapshot: IdentityHintsSnapshot) -> bytes:
    document = {key: _validated_json_copy(value, f"extra field {key}") for key, value in snapshot.extra_fields}
    document.update(
        {
            "schema_version": IDENTITY_HINTS_SCHEMA_VERSION,
            "remembered_associations": [
                {
                    "source": item.source.value,
                    "value": item.value,
                    "target_key": item.target_key,
                }
                for item in snapshot.remembered_associations
            ],
            "ignored_roms": [
                {"path": item.path, "sha256": item.sha256}
                for item in snapshot.ignored_roms
            ],
        }
    )
    try:
        text = json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n"
    except (TypeError, ValueError) as error:
        raise IdentityHintsError(f"Identity hints are not JSON-safe: {error}") from error
    return text.encode("utf-8")


def _file_revision_token(path: Path) -> str:
    if not path.exists():
        return "missing"
    try:
        content = path.read_bytes()
    except OSError as error:
        raise IdentityHintsError(f"Cannot read identity-hints revision: {error}") from error
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _reject_duplicate_object_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IdentityHintsError(f"Duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str):
    raise IdentityHintsError(f"Non-finite JSON number is not allowed: {value}")


def _validated_json_copy(value: Any, label: str):
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise IdentityHintsError(f"{label} is not JSON-safe: {error}") from error


__all__ = [
    "CollectionIdentityHintsStore",
    "DEFAULT_IDENTITY_HINTS_FILENAME",
    "IDENTITY_HINTS_SCHEMA_VERSION",
    "IdentityHintsError",
    "IdentityHintsSnapshot",
    "IdentityHintsStaleStateError",
    "IgnoredRomHint",
    "PreparedIdentityHintsMutation",
    "RememberedIdentityHint",
]
