"""Bounded read-only JSON loading for bulk Collection imports."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bulk_collection_import import (
    BulkCollectionImportDocument,
    BulkCollectionImportError,
    parse_bulk_collection_import,
)


MAX_IMPORT_JSON_BYTES = 16 * 1024 * 1024


class BulkCollectionImportJsonError(ValueError):
    """Raised when a local bulk-import JSON file cannot be loaded."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportJsonLoadResult:
    """Detached immutable result of loading one local JSON file."""

    source_name: str
    byte_count: int
    sha256: str
    document: BulkCollectionImportDocument


def load_bulk_collection_import_json(
    path: str | Path,
) -> BulkCollectionImportJsonLoadResult:
    """Load one bounded UTF-8 JSON file into the immutable contract."""

    try:
        source_path = Path(path)
    except TypeError as error:
        raise BulkCollectionImportJsonError(
            "Import path must be path-like."
        ) from error

    if source_path.suffix.lower() != ".json":
        raise BulkCollectionImportJsonError(
            "Bulk Collection imports must use a .json file."
        )
    if not source_path.exists():
        raise BulkCollectionImportJsonError(
            "Bulk Collection import file does not exist."
        )
    if not source_path.is_file():
        raise BulkCollectionImportJsonError(
            "Bulk Collection import path must be a regular file."
        )

    try:
        declared_size = source_path.stat().st_size
    except OSError as error:
        raise BulkCollectionImportJsonError(
            "Could not inspect the bulk Collection import file."
        ) from error

    if declared_size > MAX_IMPORT_JSON_BYTES:
        raise BulkCollectionImportJsonError(
            "Bulk Collection import JSON exceeds the 16 MiB limit."
        )

    try:
        with source_path.open("rb") as stream:
            payload = stream.read(MAX_IMPORT_JSON_BYTES + 1)
    except OSError as error:
        raise BulkCollectionImportJsonError(
            "Could not read the bulk Collection import file."
        ) from error

    if len(payload) > MAX_IMPORT_JSON_BYTES:
        raise BulkCollectionImportJsonError(
            "Bulk Collection import JSON exceeds the 16 MiB limit."
        )
    if not payload:
        raise BulkCollectionImportJsonError(
            "Bulk Collection import JSON is empty."
        )

    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise BulkCollectionImportJsonError(
            "Bulk Collection import JSON must be valid UTF-8."
        ) from error

    try:
        raw_document = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_nonstandard_constant,
        )
    except BulkCollectionImportJsonError:
        raise
    except json.JSONDecodeError as error:
        raise BulkCollectionImportJsonError(
            "Bulk Collection import file contains malformed JSON."
        ) from error

    try:
        document = parse_bulk_collection_import(raw_document)
    except BulkCollectionImportError as error:
        raise BulkCollectionImportJsonError(
            f"Bulk Collection import contract is invalid: {error}"
        ) from error

    return BulkCollectionImportJsonLoadResult(
        source_name=source_path.name,
        byte_count=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        document=document,
    )


def _unique_object(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BulkCollectionImportJsonError(
                f"Duplicate JSON object key is not allowed: {key}"
            )
        result[key] = value
    return result


def _reject_nonstandard_constant(value: str) -> None:
    raise BulkCollectionImportJsonError(
        f"Non-standard JSON numeric constant is not allowed: {value}"
    )


__all__ = [
    "MAX_IMPORT_JSON_BYTES",
    "BulkCollectionImportJsonError",
    "BulkCollectionImportJsonLoadResult",
    "load_bulk_collection_import_json",
]
