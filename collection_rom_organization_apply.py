"""Transactional execution of finalized Collection ROM/save organization plans.

The executor consumes only the immutable final plan.  It does not rerun layout or
save-disposition decisions.  Files are copied to exclusively-created targets first,
Collection paths are committed second, and reviewed sources are deleted only after a
journaled commit point.  A prepared journal rolls back targets/Collection; a committed
journal only finishes source cleanup.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat as stat_module
import tempfile
import threading
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from collection_plan_apply import (
    COLLECTION_APPLY_JOURNAL_FILENAME,
    collection_revision_token,
)
from collection_rom_organization_execution_plan import (
    CollectionRomOrganizationExecutionPlan,
)
from hack_data_manager import HackDataManager
from save_sync import SAVE_EXTENSIONS


COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME = ".collection-rom-organization.journal.json"
COLLECTION_ROM_ORGANIZATION_TEMP_MARKER = ".collection-rom-organization."
COLLECTION_ROM_ORGANIZATION_JOURNAL_SCHEMA = 1
_COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME = ".collection-current-rom-replace.journal.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_APPLY_LOCK = threading.RLock()


class CollectionRomOrganizationApplyError(RuntimeError):
    """Raised when the finalized organization plan cannot be applied safely."""


class CollectionRomOrganizationStaleStateError(CollectionRomOrganizationApplyError):
    """Raised when reviewed Collection/filesystem state changed before commit."""


class CollectionRomOrganizationRecoveryError(CollectionRomOrganizationApplyError):
    """Raised when an interrupted organization transaction cannot be recovered."""


class CollectionRomOrganizationRecoveryRequiredError(CollectionRomOrganizationApplyError):
    """Raised after commit when cleanup is incomplete and journal recovery is required."""


@dataclass(frozen=True)
class CollectionRomOrganizationRecoveryInfo:
    """Read-only description of a validated interrupted organization transaction."""

    state: str
    affected_targets: tuple[str, ...]
    transaction_kind: str = "ROM organization"

    def __post_init__(self) -> None:
        if self.state not in {"prepared", "committed"}:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization recovery state is invalid."
            )
        if not self.affected_targets:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization recovery has no affected targets."
            )


@dataclass(frozen=True)
class CollectionRomOrganizationApplyResult:
    """Summary of a successfully committed and cleaned organization transaction."""

    rom_move_count: int
    save_move_count: int
    collection_record_count: int
    created_directory_count: int


@dataclass
class _StoreState:
    target: Path
    content_bytes: bytes
    original_exists: bool
    original_bytes: bytes | None
    staged_path: Path | None = None
    rollback_path: Path | None = None


@dataclass(frozen=True)
class _FileOperation:
    kind: str
    source: Path
    target: Path
    sha256: str
    size_bytes: int
    source_mtime_ns: int



def _absolute(path: str | Path) -> Path:
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _canonical(path: str | Path) -> Path:
    return Path(os.path.realpath(str(_absolute(path))))


def _path_identity(path: str | Path) -> str:
    return os.path.normcase(str(_canonical(path)))


def _is_within_root(path: str | Path, root: str | Path) -> bool:
    try:
        root_identity = _path_identity(root)
        return os.path.commonpath((_path_identity(path), root_identity)) == root_identity
    except ValueError:
        return False


def _capture_file(path: Path) -> tuple[bool, bytes | None]:
    if not path.exists():
        return False, None
    if not path.is_file():
        raise CollectionRomOrganizationApplyError(
            f"Collection store path is not a regular file: {path}"
        )
    return True, path.read_bytes()


def _json_bytes(value: Any, label: str) -> bytes:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        normalized = json.loads(encoded)
        return (
            json.dumps(normalized, ensure_ascii=False, indent=2, allow_nan=False)
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise CollectionRomOrganizationApplyError(
            f"{label} cannot be serialized safely: {error}"
        ) from error


def _stat_identity(path: Path) -> tuple[int, int, int | None, int | None]:
    try:
        stat = os.stat(path, follow_symlinks=False)
    except OSError as error:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed source can no longer be inspected: {path}: {error}"
        ) from error
    if os.path.islink(path) or not os.path.isfile(path):
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed source is no longer a regular non-symlink file: {path}"
        )
    return (
        int(stat.st_size),
        int(getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000))),
        getattr(stat, "st_dev", None),
        getattr(stat, "st_ino", None),
    )


def _hash_file(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
    expected_mtime_ns: int | None = None,
) -> str:
    before = _stat_identity(path)
    if before[0] != expected_size:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed file changed size before organization Apply: {path}"
        )
    if expected_mtime_ns is not None and before[1] != expected_mtime_ns:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed file modification time changed before organization Apply: {path}"
        )

    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed file could not be hashed: {path}: {error}"
        ) from error

    after = _stat_identity(path)
    if before != after:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed file changed while being verified: {path}"
        )
    actual = digest.hexdigest()
    if actual != expected_sha256:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed file bytes no longer match the finalized SHA-256: {path}"
        )
    return actual


def _copy_exclusive(operation: _FileOperation) -> None:
    """Create *target* without overwrite and verify exact copied bytes."""

    before = _stat_identity(operation.source)
    if before[0] != operation.size_bytes or before[1] != operation.source_mtime_ns:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed source changed before copy: {operation.source}"
        )

    descriptor = None
    digest = hashlib.sha256()
    try:
        source_mode = stat_module.S_IMODE(os.stat(operation.source, follow_symlinks=False).st_mode)
        descriptor = os.open(
            operation.target,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            source_mode or 0o600,
        )
        with operation.source.open("rb") as source, os.fdopen(descriptor, "wb") as target:
            descriptor = None
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
    except FileExistsError as error:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed target became occupied before copy: {operation.target}"
        ) from error
    except Exception:
        if descriptor is not None:
            os.close(descriptor)
        raise

    after = _stat_identity(operation.source)
    if before != after:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed source changed while it was being copied: {operation.source}"
        )
    if digest.hexdigest() != operation.sha256:
        raise CollectionRomOrganizationStaleStateError(
            f"Reviewed source bytes changed before copy: {operation.source}"
        )

    try:
        target_stat = os.stat(operation.target, follow_symlinks=False)
        os.utime(
            operation.target,
            ns=(target_stat.st_atime_ns, operation.source_mtime_ns),
            follow_symlinks=False,
        )
    except (OSError, NotImplementedError):
        pass

    _hash_file(
        operation.target,
        expected_size=operation.size_bytes,
        expected_sha256=operation.sha256,
    )


def _planned_file_operations(
    plan: CollectionRomOrganizationExecutionPlan,
) -> tuple[_FileOperation, ...]:
    rows = [
        _FileOperation(
            kind="rom",
            source=_canonical(item.source_path),
            target=_canonical(item.target_path),
            sha256=item.sha256,
            size_bytes=item.size_bytes,
            source_mtime_ns=item.source_mtime_ns,
        )
        for item in plan.rom_moves
    ]
    rows.extend(
        _FileOperation(
            kind="save",
            source=_canonical(item.source_path),
            target=_canonical(item.target_path),
            sha256=item.sha256,
            size_bytes=item.size_bytes,
            source_mtime_ns=item.source_mtime_ns,
        )
        for item in plan.save_moves
    )
    return tuple(rows)


def _assert_targets_absent(operations: Iterable[_FileOperation]) -> None:
    for operation in operations:
        if os.path.lexists(operation.target):
            raise CollectionRomOrganizationStaleStateError(
                f"Reviewed target became occupied before organization Apply: {operation.target}"
            )


def _assert_colocated_save_set(plan: CollectionRomOrganizationExecutionPlan) -> None:
    expected: dict[str, set[str]] = {}
    for item in plan.save_moves:
        expected.setdefault(_path_identity(item.rom_source_path), set()).add(
            _path_identity(item.source_path)
        )
    for item in plan.save_leaves:
        expected.setdefault(_path_identity(item.rom_source_path), set()).add(
            _path_identity(item.save_path)
        )

    for move in plan.rom_moves:
        source = _canonical(move.source_path)
        stem = source.stem.casefold()
        discovered: set[str] = set()
        try:
            names = os.listdir(source.parent)
        except OSError as error:
            raise CollectionRomOrganizationStaleStateError(
                f"Cannot recheck colocated save evidence beside {source}: {error}"
            ) from error
        for name in names:
            candidate = source.parent / name
            if candidate.suffix.lower() not in SAVE_EXTENSIONS:
                continue
            if candidate.stem.casefold() != stem:
                continue
            if not candidate.is_file() or os.path.islink(candidate):
                continue
            discovered.add(_path_identity(candidate))
        expected_for_move = expected.get(_path_identity(source), set())
        if discovered != expected_for_move:
            raise CollectionRomOrganizationStaleStateError(
                "Colocated save evidence changed after the final execution preview. "
                "Review save dispositions again."
            )


def _assert_target_path_stable(operation: _FileOperation, output_root: Path) -> None:
    frozen = os.path.normcase(str(_absolute(operation.target)))
    if _path_identity(operation.target) != frozen:
        raise CollectionRomOrganizationStaleStateError(
            f"Target path now resolves through a different filesystem location: {operation.target}"
        )
    if not _is_within_root(operation.target, output_root):
        raise CollectionRomOrganizationStaleStateError(
            f"Target path no longer stays inside configured output_dir: {operation.target}"
        )

    current = operation.target.parent
    while True:
        if os.path.lexists(current):
            if not current.is_dir() or os.path.islink(current):
                raise CollectionRomOrganizationStaleStateError(
                    f"Target parent path became unsafe: {current}"
                )
        if _path_identity(current) == _path_identity(output_root):
            break
        if current.parent == current:
            raise CollectionRomOrganizationStaleStateError(
                f"Target parent escaped configured output_dir: {operation.target}"
            )
        current = current.parent


def _assert_files_ready_for_collection_commit(
    plan: CollectionRomOrganizationExecutionPlan,
    operations: tuple[_FileOperation, ...],
) -> None:
    output_root = _canonical(plan.output_dir)
    _assert_colocated_save_set(plan)
    for operation in operations:
        _assert_target_path_stable(operation, output_root)
        _hash_file(
            operation.source,
            expected_size=operation.size_bytes,
            expected_mtime_ns=operation.source_mtime_ns,
            expected_sha256=operation.sha256,
        )
        _hash_file(
            operation.target,
            expected_size=operation.size_bytes,
            expected_sha256=operation.sha256,
        )


def _assert_plan_file_preconditions(
    plan: CollectionRomOrganizationExecutionPlan,
    operations: tuple[_FileOperation, ...],
) -> None:
    output_root = _canonical(plan.output_dir)
    for operation in operations:
        if not _is_within_root(operation.target, output_root):
            raise CollectionRomOrganizationApplyError(
                f"Finalized target escapes configured output directory: {operation.target}"
            )
        _assert_target_path_stable(operation, output_root)
        _hash_file(
            operation.source,
            expected_size=operation.size_bytes,
            expected_mtime_ns=operation.source_mtime_ns,
            expected_sha256=operation.sha256,
        )
    _assert_targets_absent(operations)
    _assert_colocated_save_set(plan)


def _assert_collection_target_refs_free(
    collection_data: Mapping[str, Any],
    plan: CollectionRomOrganizationExecutionPlan,
) -> None:
    target_ids = {_path_identity(item.target_path) for item in plan.rom_moves}
    for raw_collection_id, raw_record in collection_data.items():
        if not isinstance(raw_record, Mapping):
            continue
        references: list[str] = []
        rows = raw_record.get("files", [])
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, Mapping) and isinstance(row.get("path"), str):
                    references.append(row["path"])
        file_path = raw_record.get("file_path")
        if isinstance(file_path, str) and file_path:
            references.append(file_path)
        additional = raw_record.get("additional_paths", [])
        if isinstance(additional, list):
            references.extend(item for item in additional if isinstance(item, str) and item)
        for reference in references:
            if _path_identity(reference) in target_ids:
                raise CollectionRomOrganizationStaleStateError(
                    "A finalized ROM destination is already referenced by Collection metadata: "
                    f"{reference} (Collection {raw_collection_id}). Run the organization audit again."
                )


def _stage_collection_updates(
    current: Mapping[str, Any],
    plan: CollectionRomOrganizationExecutionPlan,
) -> dict[str, Any]:
    try:
        staged = json.loads(json.dumps(current, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, json.JSONDecodeError) as error:
        raise CollectionRomOrganizationApplyError(
            f"Collection snapshot is not JSON-safe: {error}"
        ) from error
    if not isinstance(staged, dict):
        raise CollectionRomOrganizationApplyError("Collection root must be a JSON object.")

    _assert_collection_target_refs_free(staged, plan)

    for move in plan.rom_moves:
        record = staged.get(move.collection_id)
        if not isinstance(record, dict):
            raise CollectionRomOrganizationStaleStateError(
                f"Collection record disappeared before organization Apply: {move.collection_id}"
            )
        rows = record.get("files")
        if not isinstance(rows, list):
            raise CollectionRomOrganizationStaleStateError(
                f"Collection files[] changed before organization Apply: {move.collection_id}"
            )

        matches = []
        for index, raw in enumerate(rows):
            if isinstance(raw, dict) and isinstance(raw.get("path"), str):
                if _path_identity(raw["path"]) == _path_identity(move.source_path):
                    matches.append((index, raw))
        if len(matches) != 1:
            raise CollectionRomOrganizationStaleStateError(
                "Finalized ROM source no longer identifies exactly one Collection files[] row: "
                f"{move.source_path}"
            )

        index, row = matches[0]
        if row.get("sha256") != move.sha256 or row.get("size_bytes") != move.size_bytes:
            raise CollectionRomOrganizationStaleStateError(
                f"Collection ROM byte identity changed before Apply: {move.asset_name}"
            )
        if bool(row.get("primary", False)) != move.primary:
            raise CollectionRomOrganizationStaleStateError(
                f"Collection ROM primary state changed before Apply: {move.asset_name}"
            )
        if row.get("smwc_submission_id") != move.smwc_submission_id:
            raise CollectionRomOrganizationStaleStateError(
                f"Collection ROM provenance changed before Apply: {move.asset_name}"
            )

        updated = copy.deepcopy(row)
        updated["path"] = str(_canonical(move.target_path))
        updated["name"] = os.path.basename(move.target_path)
        rows[index] = updated

        current_file_path = record.get("file_path")
        if move.primary:
            if not isinstance(current_file_path, str) or (
                _path_identity(current_file_path) != _path_identity(move.source_path)
            ):
                raise CollectionRomOrganizationStaleStateError(
                    "Primary file_path no longer matches the finalized primary ROM source."
                )
            record["file_path"] = str(_canonical(move.target_path))
        elif isinstance(current_file_path, str) and current_file_path and (
            _path_identity(current_file_path) == _path_identity(move.source_path)
        ):
            raise CollectionRomOrganizationStaleStateError(
                "A non-primary finalized ROM move is still projected through file_path."
            )

        additional = record.get("additional_paths")
        if isinstance(additional, list):
            record["additional_paths"] = [
                str(_canonical(move.target_path))
                if isinstance(item, str)
                and item
                and _path_identity(item) == _path_identity(move.source_path)
                else item
                for item in additional
            ]

    return staged


def _missing_target_directories(
    operations: tuple[_FileOperation, ...],
    output_root: Path,
) -> tuple[Path, ...]:
    if output_root.exists():
        if not output_root.is_dir() or os.path.islink(output_root):
            raise CollectionRomOrganizationStaleStateError(
                f"Configured output directory is no longer a regular directory: {output_root}"
            )

    missing: set[Path] = set()
    for operation in operations:
        target = operation.target
        if not _is_within_root(target, output_root):
            raise CollectionRomOrganizationApplyError(
                f"Target escapes configured output directory: {target}"
            )
        try:
            relative_parent = target.parent.relative_to(output_root)
        except ValueError as error:
            raise CollectionRomOrganizationApplyError(
                f"Target parent escapes configured output directory: {target}"
            ) from error

        current = output_root
        if not current.exists():
            missing.add(current)
        for part in relative_parent.parts:
            current = current / part
            if os.path.lexists(current):
                if not current.is_dir() or os.path.islink(current):
                    raise CollectionRomOrganizationStaleStateError(
                        f"Target directory path became unsafe before Apply: {current}"
                    )
            else:
                missing.add(current)

    return tuple(sorted(missing, key=lambda item: (len(item.parts), str(item))))


def _create_missing_directories(
    directories: tuple[Path, ...],
    root: Path,
    journal: dict[str, Any],
) -> None:
    for directory in directories:
        try:
            os.mkdir(directory)
        except FileExistsError as error:
            raise CollectionRomOrganizationStaleStateError(
                f"Target directory appeared after final preview: {directory}"
            ) from error
        _fsync_directory_best_effort(directory.parent)
        # Recovery may remove only directories this transaction definitely created.
        # If the process dies between mkdir and this journal update, an empty orphan
        # directory is safer than risking deletion of another actor's directory.
        journal["created_directories"].append(str(directory))
        _write_journal(root, journal)


def _create_temp_bytes(root: Path, target_name: str, kind: str, content: bytes) -> Path:
    descriptor = None
    path = None
    try:
        descriptor, raw = tempfile.mkstemp(
            prefix=f"{target_name}{COLLECTION_ROM_ORGANIZATION_TEMP_MARKER}{kind}.",
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


def _prepare_store_states(
    root: Path,
    processed_path: Path,
    collection_content: bytes,
) -> tuple[_StoreState, ...]:
    states: list[_StoreState] = []
    processed_exists, processed_bytes = _capture_file(processed_path)
    backup_path = Path(f"{processed_path}.backup")

    if processed_exists:
        backup_exists, backup_bytes = _capture_file(backup_path)
        states.append(
            _StoreState(
                target=backup_path,
                content_bytes=processed_bytes or b"",
                original_exists=backup_exists,
                original_bytes=backup_bytes,
            )
        )

    states.append(
        _StoreState(
            target=processed_path,
            content_bytes=collection_content,
            original_exists=processed_exists,
            original_bytes=processed_bytes,
        )
    )

    try:
        for state in states:
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
        return tuple(states)
    except Exception:
        for state in states:
            for path in (state.staged_path, state.rollback_path):
                if path is not None and path.exists():
                    path.unlink()
        raise


def _journal_document(
    *,
    output_root: Path,
    operations: tuple[_FileOperation, ...],
    directories: tuple[Path, ...],
    stores: tuple[_StoreState, ...],
) -> dict[str, Any]:
    return {
        "schema_version": COLLECTION_ROM_ORGANIZATION_JOURNAL_SCHEMA,
        "transaction_id": secrets.token_hex(8),
        "state": "prepared",
        "output_dir": str(output_root),
        "file_moves": [
            {
                "kind": item.kind,
                "source": str(item.source),
                "target": str(item.target),
                "sha256": item.sha256,
                "size_bytes": item.size_bytes,
                "source_mtime_ns": item.source_mtime_ns,
            }
            for item in operations
        ],
        "created_directories": [],
        "stores": [
            {
                "target": state.target.name,
                "staged": state.staged_path.name if state.staged_path else "",
                "rollback": state.rollback_path.name if state.rollback_path else None,
                "original_exists": state.original_exists,
            }
            for state in stores
        ],
    }


def _write_initial_journal(root: Path, document: Mapping[str, Any]) -> None:
    content = _json_bytes(document, "ROM organization journal")
    path = root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME
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
        raise CollectionRomOrganizationRecoveryError(
            "Another or interrupted ROM organization transaction owns the journal."
        ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _write_journal(root: Path, document: Mapping[str, Any]) -> None:
    content = _json_bytes(document, "ROM organization journal")
    temp = _create_temp_bytes(
        root,
        COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME,
        "journal",
        content,
    )
    os.replace(temp, root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME)
    _fsync_directory_best_effort(root)


def _safe_basename(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == Path(value).name
        and value not in {".", ".."}
    )


def _validate_journal(document: Any) -> None:
    if not isinstance(document, dict):
        raise CollectionRomOrganizationRecoveryError(
            "ROM organization journal must be a JSON object."
        )
    if document.get("schema_version") != COLLECTION_ROM_ORGANIZATION_JOURNAL_SCHEMA:
        raise CollectionRomOrganizationRecoveryError(
            "Unsupported ROM organization journal schema."
        )
    if document.get("state") not in {"prepared", "committed"}:
        raise CollectionRomOrganizationRecoveryError(
            "ROM organization journal has invalid state."
        )
    output_dir = document.get("output_dir")
    if not isinstance(output_dir, str) or not output_dir or not Path(output_dir).is_absolute():
        raise CollectionRomOrganizationRecoveryError(
            "ROM organization journal has an invalid output directory."
        )
    output_root = _canonical(output_dir)

    moves = document.get("file_moves")
    if not isinstance(moves, list) or not moves:
        raise CollectionRomOrganizationRecoveryError(
            "ROM organization journal has no filesystem moves."
        )
    sources: set[str] = set()
    targets: set[str] = set()
    for entry in moves:
        if not isinstance(entry, dict) or entry.get("kind") not in {"rom", "save"}:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal move entry is invalid."
            )
        source = entry.get("source")
        target = entry.get("target")
        sha256 = entry.get("sha256")
        size = entry.get("size_bytes")
        mtime = entry.get("source_mtime_ns")
        if (
            not isinstance(source, str)
            or not source
            or not Path(source).is_absolute()
            or not isinstance(target, str)
            or not target
            or not Path(target).is_absolute()
        ):
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal contains a non-absolute move path."
            )
        if _path_identity(source) == _path_identity(target):
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal contains an in-place move."
            )
        if not _is_within_root(target, output_root):
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal target escapes output_dir."
            )
        if _SHA256_RE.fullmatch(sha256 or "") is None:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal contains invalid SHA-256."
            )
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal contains invalid file size."
            )
        if isinstance(mtime, bool) or not isinstance(mtime, int) or mtime < 0:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal contains invalid file mtime."
            )
        source_id = _path_identity(source)
        target_id = _path_identity(target)
        if source_id in sources or target_id in targets:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal contains duplicate source/target paths."
            )
        sources.add(source_id)
        targets.add(target_id)

    directories = document.get("created_directories", [])
    if not isinstance(directories, list):
        raise CollectionRomOrganizationRecoveryError(
            "ROM organization journal created_directories must be an array."
        )
    seen_dirs: set[str] = set()
    for raw in directories:
        if not isinstance(raw, str) or not raw or not Path(raw).is_absolute():
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal contains an invalid created directory."
            )
        if not _is_within_root(raw, output_root):
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal created directory escapes output_dir."
            )
        identity = _path_identity(raw)
        if identity in seen_dirs:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization journal contains duplicate created directories."
            )
        seen_dirs.add(identity)

    stores = document.get("stores")
    if not isinstance(stores, list) or not stores:
        raise CollectionRomOrganizationRecoveryError(
            "ROM organization journal has no Collection store entries."
        )
    seen_store_targets: set[str] = set()
    for entry in stores:
        if not isinstance(entry, dict):
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization store journal entry is invalid."
            )
        target = entry.get("target")
        staged = entry.get("staged")
        rollback = entry.get("rollback")
        if not _safe_basename(target) or target in seen_store_targets:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization store target is unsafe or duplicated."
            )
        seen_store_targets.add(target)
        if not _safe_basename(staged) or COLLECTION_ROM_ORGANIZATION_TEMP_MARKER not in staged:
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization staged Collection file is unsafe."
            )
        if rollback and (
            not _safe_basename(rollback)
            or COLLECTION_ROM_ORGANIZATION_TEMP_MARKER not in rollback
        ):
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization rollback Collection file is unsafe."
            )
        if not isinstance(entry.get("original_exists"), bool):
            raise CollectionRomOrganizationRecoveryError(
                "ROM organization store original_exists must be boolean."
            )


def _load_journal(root: Path) -> dict[str, Any]:
    path = root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_keys,
            parse_constant=_reject_nonfinite,
        )
        _validate_journal(document)
        return document
    except CollectionRomOrganizationRecoveryError:
        raise
    except Exception as error:
        raise CollectionRomOrganizationRecoveryError(
            f"Could not read ROM organization recovery journal: {error}"
        ) from error


def inspect_interrupted_collection_rom_organization(
    data_root: str | Path,
) -> CollectionRomOrganizationRecoveryInfo | None:
    root = _canonical(data_root)
    path = root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME
    if not path.exists():
        return None
    document = _load_journal(root)
    affected = [entry["target"] for entry in document["stores"]]
    affected.extend(entry["target"] for entry in document["file_moves"])
    return CollectionRomOrganizationRecoveryInfo(
        state=document["state"],
        affected_targets=tuple(affected),
    )


def _cleanup_store_artifacts(root: Path, document: Mapping[str, Any]) -> None:
    for entry in document["stores"]:
        for key in ("staged", "rollback"):
            name = entry.get(key)
            if not name:
                continue
            path = root / name
            if path.exists():
                path.unlink()


def _remove_created_directories(document: Mapping[str, Any]) -> None:
    directories = sorted(
        (_canonical(item) for item in document.get("created_directories", [])),
        key=lambda path: (len(path.parts), str(path)),
        reverse=True,
    )
    for directory in directories:
        try:
            directory.rmdir()
        except FileNotFoundError:
            continue
        except OSError:
            # Non-empty means something else now uses the directory; keep it.
            continue


def _recover_prepared(root: Path, document: Mapping[str, Any]) -> None:
    for entry in reversed(document["stores"]):
        target = root / entry["target"]
        rollback_name = entry.get("rollback")
        if entry["original_exists"]:
            if not rollback_name:
                raise CollectionRomOrganizationRecoveryError(
                    f"Prepared organization transaction lacks rollback material for {target.name}."
                )
            rollback = root / rollback_name
            if not rollback.exists():
                raise CollectionRomOrganizationRecoveryError(
                    f"Prepared organization rollback material is missing for {target.name}."
                )
            os.replace(rollback, target)
        elif target.exists():
            target.unlink()

    for entry in document["file_moves"]:
        target = _canonical(entry["target"])
        if os.path.lexists(target):
            if os.path.isdir(target) and not os.path.islink(target):
                raise CollectionRomOrganizationRecoveryError(
                    f"Prepared organization target became a directory: {target}"
                )
            target.unlink()
    _remove_created_directories(document)


def _recover_committed(document: Mapping[str, Any]) -> None:
    for entry in document["file_moves"]:
        target = _canonical(entry["target"])
        source = _canonical(entry["source"])
        _hash_file(
            target,
            expected_size=entry["size_bytes"],
            expected_sha256=entry["sha256"],
        )
        if os.path.lexists(source):
            _hash_file(
                source,
                expected_size=entry["size_bytes"],
                expected_mtime_ns=entry["source_mtime_ns"],
                expected_sha256=entry["sha256"],
            )
            source.unlink()
            _fsync_directory_best_effort(source.parent)


def recover_interrupted_collection_rom_organization(data_root: str | Path) -> bool:
    """Rollback a prepared transaction or finish cleanup for a committed one."""

    root = _canonical(data_root)
    journal_path = root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME
    if not journal_path.exists():
        return False
    document = _load_journal(root)

    try:
        if document["state"] == "prepared":
            _recover_prepared(root, document)
        else:
            _recover_committed(document)
        _cleanup_store_artifacts(root, document)
        if journal_path.exists():
            journal_path.unlink()
        _fsync_directory_best_effort(root)
        return True
    except CollectionRomOrganizationRecoveryError:
        raise
    except Exception as error:
        raise CollectionRomOrganizationRecoveryError(
            f"Could not recover interrupted ROM organization transaction: {error}"
        ) from error


def _replace_store_states(
    root: Path,
    states: tuple[_StoreState, ...],
    *,
    processed_path: Path,
    before_processed_check,
    fail_after_store_replace: int | None,
) -> None:
    replaced = 0
    for state in states:
        if state.target == processed_path:
            before_processed_check()
        current = _capture_file(state.target)
        if current != (state.original_exists, state.original_bytes):
            raise CollectionRomOrganizationStaleStateError(
                f"Collection store changed during organization Apply: {state.target.name}"
            )
        if state.staged_path is None or not state.staged_path.exists():
            raise CollectionRomOrganizationRecoveryError(
                f"Staged Collection store is missing: {state.target.name}"
            )
        os.replace(state.staged_path, state.target)
        state.staged_path = None
        _fsync_directory_best_effort(root)
        replaced += 1
        if fail_after_store_replace == replaced:
            raise CollectionRomOrganizationApplyError(
                f"Injected failure after Collection store replacement {replaced}."
            )


def _assert_manager_state(
    manager: HackDataManager,
    snapshot: Mapping[str, Any],
    disk_state: tuple[bool, bytes | None],
    expected_revision: str,
) -> None:
    if manager.data != snapshot:
        raise CollectionRomOrganizationStaleStateError(
            "HackDataManager changed while organization Apply was running."
        )
    if _capture_file(Path(manager.json_path)) != disk_state:
        raise CollectionRomOrganizationStaleStateError(
            "processed.json changed while organization Apply was running."
        )
    if collection_revision_token(manager) != expected_revision:
        raise CollectionRomOrganizationStaleStateError(
            "Collection revision changed while organization Apply was running."
        )


def apply_collection_rom_organization_execution_plan(
    plan: CollectionRomOrganizationExecutionPlan,
    manager: HackDataManager,
    *,
    fail_after_target_copy: int | None = None,
    fail_after_store_replace: int | None = None,
    fail_after_commit: bool = False,
) -> CollectionRomOrganizationApplyResult:
    """Execute exactly one finalized plan with journaled rollback/recovery semantics."""

    if not isinstance(plan, CollectionRomOrganizationExecutionPlan):
        raise TypeError("plan must be a CollectionRomOrganizationExecutionPlan")
    if not isinstance(manager, HackDataManager):
        raise TypeError("manager must be a HackDataManager")
    for label, value in (
        ("fail_after_target_copy", fail_after_target_copy),
        ("fail_after_store_replace", fail_after_store_replace),
    ):
        if value is not None and (isinstance(value, bool) or value < 1):
            raise ValueError(f"{label} must be a positive integer when supplied.")

    processed_path = _canonical(manager.json_path)
    root = processed_path.parent
    output_root = _canonical(plan.output_dir)
    organization_journal = root / COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME
    collection_journal = root / COLLECTION_APPLY_JOURNAL_FILENAME
    current_rom_journal = root / _COLLECTION_CURRENT_ROM_REPLACE_JOURNAL_FILENAME
    with _APPLY_LOCK:
        if current_rom_journal.exists():
            raise CollectionRomOrganizationRecoveryError(
                "A current-ROM replacement transaction journal already exists. Recover it before organizing ROMs."
            )
        if organization_journal.exists():
            raise CollectionRomOrganizationRecoveryError(
                "An interrupted ROM organization journal already exists. Recover it before Apply."
            )
        if collection_journal.exists():
            raise CollectionRomOrganizationRecoveryError(
                "A Collection metadata Apply journal already exists. Recover it before organizing ROMs."
            )
        if collection_revision_token(manager) != plan.collection_revision_token:
            raise CollectionRomOrganizationStaleStateError(
                "Collection changed after the final ROM organization preview. Run the audit again."
            )

        manager_snapshot = copy.deepcopy(manager.data)
        manager_unsaved = bool(manager.unsaved_changes)
        manager_disk = _capture_file(processed_path)
        timer = getattr(manager, "_save_timer", None)
        timer_cancelled = False
        states: tuple[_StoreState, ...] = ()
        journal_written = False
        committed = False

        try:
            staged_collection = _stage_collection_updates(manager_snapshot, plan)
            collection_content = _json_bytes(staged_collection, "organized Collection")
            operations = _planned_file_operations(plan)
            _assert_plan_file_preconditions(plan, operations)
            directories = _missing_target_directories(operations, output_root)
            states = _prepare_store_states(root, processed_path, collection_content)

            if timer is not None:
                timer.cancel()
                manager._save_timer = None
                timer_cancelled = True

            _assert_manager_state(
                manager,
                manager_snapshot,
                manager_disk,
                plan.collection_revision_token,
            )
            _assert_plan_file_preconditions(plan, operations)

            journal = _journal_document(
                output_root=output_root,
                operations=operations,
                directories=directories,
                stores=states,
            )
            _write_initial_journal(root, journal)
            journal_written = True

            _create_missing_directories(directories, root, journal)
            copied = 0
            for operation in operations:
                _copy_exclusive(operation)
                copied += 1
                if fail_after_target_copy == copied:
                    raise CollectionRomOrganizationApplyError(
                        f"Injected failure after filesystem target copy {copied}."
                    )

            _assert_manager_state(
                manager,
                manager_snapshot,
                manager_disk,
                plan.collection_revision_token,
            )
            _assert_files_ready_for_collection_commit(plan, operations)

            def before_processed_commit():
                _assert_manager_state(
                    manager,
                    manager_snapshot,
                    manager_disk,
                    plan.collection_revision_token,
                )
                _assert_files_ready_for_collection_commit(plan, operations)

            _replace_store_states(
                root,
                states,
                processed_path=processed_path,
                before_processed_check=before_processed_commit,
                fail_after_store_replace=fail_after_store_replace,
            )

            journal["state"] = "committed"
            _write_journal(root, journal)
            committed = True

            manager.data = copy.deepcopy(staged_collection)
            manager.unsaved_changes = False
            manager._save_timer = None
            timer_cancelled = False

            if fail_after_commit:
                raise CollectionRomOrganizationRecoveryRequiredError(
                    "Injected failure after ROM organization commit point."
                )

            _recover_committed(journal)
            _cleanup_store_artifacts(root, journal)
            if organization_journal.exists():
                organization_journal.unlink()
            _fsync_directory_best_effort(root)

            _log_success_best_effort(manager, len(plan.rom_moves), len(plan.save_moves))
            return CollectionRomOrganizationApplyResult(
                rom_move_count=len(plan.rom_moves),
                save_move_count=len(plan.save_moves),
                collection_record_count=len(staged_collection),
                created_directory_count=len(directories),
            )

        except CollectionRomOrganizationRecoveryRequiredError:
            raise
        except Exception as error:
            if committed:
                raise CollectionRomOrganizationRecoveryRequiredError(
                    "ROM organization committed, but source cleanup did not finish. "
                    "The transaction journal must be recovered before further Collection writes."
                ) from error

            try:
                if journal_written and organization_journal.exists():
                    recover_interrupted_collection_rom_organization(root)
                else:
                    for state in states:
                        for path in (state.staged_path, state.rollback_path):
                            if path is not None and path.exists():
                                path.unlink()
            except Exception as recovery_error:
                raise CollectionRomOrganizationRecoveryError(
                    "ROM organization failed and rollback recovery also failed."
                ) from recovery_error

            manager.data = copy.deepcopy(manager_snapshot)
            manager.unsaved_changes = manager_unsaved
            if timer_cancelled and manager_unsaved:
                try:
                    manager._schedule_delayed_save()
                except Exception:
                    manager._save_timer = None
            raise error


def _reject_duplicate_object_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CollectionRomOrganizationRecoveryError(
                f"Duplicate ROM organization journal JSON key: {key!r}"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str):
    raise CollectionRomOrganizationRecoveryError(
        f"Non-finite ROM organization journal number: {value}"
    )


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


def _log_success_best_effort(manager: HackDataManager, roms: int, saves: int) -> None:
    try:
        manager._log(
            f"📁 Organized {roms} ROM files and {saves} reviewed save files transactionally",
            "Information",
        )
    except Exception:
        pass


__all__ = [
    "COLLECTION_ROM_ORGANIZATION_JOURNAL_FILENAME",
    "COLLECTION_ROM_ORGANIZATION_TEMP_MARKER",
    "CollectionRomOrganizationApplyError",
    "CollectionRomOrganizationApplyResult",
    "CollectionRomOrganizationRecoveryError",
    "CollectionRomOrganizationRecoveryInfo",
    "CollectionRomOrganizationRecoveryRequiredError",
    "CollectionRomOrganizationStaleStateError",
    "apply_collection_rom_organization_execution_plan",
    "inspect_interrupted_collection_rom_organization",
    "recover_interrupted_collection_rom_organization",
]
