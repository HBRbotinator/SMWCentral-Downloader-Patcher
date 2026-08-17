"""Build a read-only UI-ready preview for v5.1 bulk Collection imports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from bulk_collection_import import bulk_collection_import_to_document
from bulk_collection_import_collection_adapter import (
    bulk_collection_import_collection_identities_to_documents,
    bulk_collection_import_collection_records_to_documents,
    project_bulk_collection_import_hack_data_manager,
)
from bulk_collection_import_merge import (
    bulk_collection_import_merge_plan_to_document,
)
from bulk_collection_import_planning import (
    plan_bulk_collection_import_file,
)
from bulk_collection_import_preview import (
    bulk_collection_import_preview_to_document,
)
from hack_data_manager import HackDataManager


WORKFLOW_PREVIEW_SCHEMA = "smwc-bulk-collection-workflow-preview"
WORKFLOW_PREVIEW_VERSION = 1
WORKFLOW_ROW_OUTCOMES = (
    "add_new",
    "match_existing",
    "review_required",
)

_MERGE_ACTIONS = (
    "create_record",
    "update_record",
    "no_change",
    "review_required",
)
_SUMMARY_KEYS = ("total", *_MERGE_ACTIONS)


class BulkCollectionImportWorkflowPreviewError(ValueError):
    """Raised when a planning session cannot be projected safely for UI."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportWorkflowSourceReference:
    """One source identity displayed by the preview."""

    source: str
    external_id: str


@dataclass(frozen=True, slots=True)
class BulkCollectionImportWorkflowConflict:
    """One field-level metadata conflict for explicit review."""

    field: str
    existing_value: Any
    imported_value: Any


@dataclass(frozen=True, slots=True)
class BulkCollectionImportWorkflowCandidate:
    """Safe display-only view of an existing Collection candidate."""

    collection_key: str
    title: str
    authors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportWorkflowRow:
    """One ordered UI-ready imported entry."""

    entry_key: str
    title: str
    outcome: str
    merge_action: str
    resolution_status: str
    collection_keys: tuple[str, ...]
    proposed_source_references: tuple[
        BulkCollectionImportWorkflowSourceReference,
        ...,
    ]
    warnings: tuple[str, ...]
    conflicts: tuple[BulkCollectionImportWorkflowConflict, ...]
    candidates: tuple[BulkCollectionImportWorkflowCandidate, ...]
    requires_review: bool


@dataclass(frozen=True, slots=True)
class BulkCollectionImportWorkflowGroup:
    """One ordered imported display group."""

    group_key: str
    title: str
    entry_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportWorkflowPreview:
    """Immutable read-only workflow model ready for a UI."""

    schema: str
    version: int
    source_name: str
    byte_count: int
    source_sha256: str
    import_id: str
    title: str
    summary: Mapping[str, int]
    rows: tuple[BulkCollectionImportWorkflowRow, ...]
    groups: tuple[BulkCollectionImportWorkflowGroup, ...]

    @property
    def review_required_count(self) -> int:
        return self.summary["review_required"]

    @property
    def requires_review(self) -> bool:
        return self.review_required_count > 0


def build_bulk_collection_import_workflow_preview(
    planning_session_document: Mapping[str, Any],
    collection_snapshot: Mapping[str, Mapping[str, Any]],
) -> BulkCollectionImportWorkflowPreview:
    """Project one read-only planning session into a UI-ready model."""

    if not isinstance(planning_session_document, Mapping):
        raise BulkCollectionImportWorkflowPreviewError(
            "planning_session_document must be a mapping."
        )
    if not isinstance(collection_snapshot, Mapping):
        raise BulkCollectionImportWorkflowPreviewError(
            "collection_snapshot must be a mapping."
        )

    source_name = _require_text(
        planning_session_document.get("source_name"),
        "source_name",
    )
    byte_count = planning_session_document.get("byte_count")
    if (
        isinstance(byte_count, bool)
        or not isinstance(byte_count, int)
        or byte_count < 0
    ):
        raise BulkCollectionImportWorkflowPreviewError(
            "byte_count must be a non-negative integer."
        )
    source_sha256 = _require_sha256(
        planning_session_document.get("sha256"),
        "sha256",
    )

    import_document = _require_mapping(
        planning_session_document.get("import"),
        "import",
    )
    preview_document = _require_mapping(
        planning_session_document.get("preview"),
        "preview",
    )
    merge_document = _require_mapping(
        planning_session_document.get("merge"),
        "merge",
    )

    import_id = _require_text(
        import_document.get("import_id"),
        "import.import_id",
    )
    title = _require_text(
        import_document.get("title"),
        "import.title",
    )
    if preview_document.get("import_id") != import_id:
        raise BulkCollectionImportWorkflowPreviewError(
            "Preview import_id does not match import document."
        )
    if merge_document.get("import_id") != import_id:
        raise BulkCollectionImportWorkflowPreviewError(
            "Merge import_id does not match import document."
        )

    entries = _parse_entries(import_document.get("entries"))
    preview_items = _parse_preview_items(
        preview_document.get("items")
    )
    merge_items = _parse_merge_items(merge_document.get("items"))

    entry_keys = tuple(entry["entry_key"] for entry in entries)
    if tuple(item["entry_key"] for item in preview_items) != entry_keys:
        raise BulkCollectionImportWorkflowPreviewError(
            "Preview rows must align exactly with import entry order."
        )
    if tuple(item["entry_key"] for item in merge_items) != entry_keys:
        raise BulkCollectionImportWorkflowPreviewError(
            "Merge rows must align exactly with import entry order."
        )

    _validate_unique_entry_keys(entry_keys)
    summary = _validate_merge_summary(
        merge_document.get("summary"),
        merge_items,
    )

    import_groups = _parse_groups(
        import_document.get("groups"),
        entry_keys,
        "import.groups",
    )
    preview_groups = _parse_groups(
        preview_document.get("groups"),
        entry_keys,
        "preview.groups",
    )
    merge_groups = _parse_groups(
        merge_document.get("groups"),
        entry_keys,
        "merge.groups",
    )
    if preview_groups != import_groups or merge_groups != import_groups:
        raise BulkCollectionImportWorkflowPreviewError(
            "Import, preview, and merge groups must align exactly."
        )

    rows = []
    for entry, preview_item, merge_item in zip(
        entries,
        preview_items,
        merge_items,
    ):
        if (
            preview_item["collection_keys"]
            != merge_item["collection_keys"]
        ):
            raise BulkCollectionImportWorkflowPreviewError(
                f"Collection targets disagree for {entry['entry_key']}."
            )

        candidates = tuple(
            _build_candidate(collection_snapshot, collection_key)
            for collection_key in preview_item["collection_keys"]
        )
        conflicts = _build_conflicts(merge_item)

        rows.append(
            BulkCollectionImportWorkflowRow(
                entry_key=entry["entry_key"],
                title=entry["title"],
                outcome=preview_item["outcome"],
                merge_action=merge_item["action"],
                resolution_status=preview_item[
                    "resolution_status"
                ],
                collection_keys=preview_item["collection_keys"],
                proposed_source_references=tuple(
                    BulkCollectionImportWorkflowSourceReference(
                        source=reference["source"],
                        external_id=reference["external_id"],
                    )
                    for reference
                    in preview_item["proposed_source_references"]
                ),
                warnings=_ordered_union(
                    preview_item["warnings"],
                    merge_item["warnings"],
                ),
                conflicts=conflicts,
                candidates=candidates,
                requires_review=(
                    merge_item["action"] == "review_required"
                ),
            )
        )

    return BulkCollectionImportWorkflowPreview(
        schema=WORKFLOW_PREVIEW_SCHEMA,
        version=WORKFLOW_PREVIEW_VERSION,
        source_name=source_name,
        byte_count=byte_count,
        source_sha256=source_sha256,
        import_id=import_id,
        title=title,
        summary=MappingProxyType(dict(summary)),
        rows=tuple(rows),
        groups=tuple(
            BulkCollectionImportWorkflowGroup(
                group_key=group["group_key"],
                title=group["title"],
                entry_keys=group["entry_keys"],
            )
            for group in import_groups
        ),
    )


def plan_v5_1_bulk_collection_import_workflow_preview(
    path: str,
    data_manager: HackDataManager,
) -> BulkCollectionImportWorkflowPreview:
    """Plan a real local JSON import against live v5.1 Collection data."""

    if not isinstance(data_manager, HackDataManager):
        raise TypeError("data_manager must be a HackDataManager")

    projection = project_bulk_collection_import_hack_data_manager(
        data_manager
    )
    identities = (
        bulk_collection_import_collection_identities_to_documents(
            projection
        )
    )
    records = bulk_collection_import_collection_records_to_documents(
        projection
    )

    planning = plan_bulk_collection_import_file(
        path,
        identities,
        records,
    )
    planning_document = _planning_session_to_document(planning)

    return build_bulk_collection_import_workflow_preview(
        planning_document,
        data_manager.data,
    )


def bulk_collection_import_workflow_preview_to_document(
    preview: BulkCollectionImportWorkflowPreview,
) -> dict[str, Any]:
    """Project a workflow preview into detached canonical JSON."""

    if not isinstance(
        preview,
        BulkCollectionImportWorkflowPreview,
    ):
        raise TypeError(
            "preview must be BulkCollectionImportWorkflowPreview"
        )

    return {
        "schema": preview.schema,
        "version": preview.version,
        "source_name": preview.source_name,
        "byte_count": preview.byte_count,
        "source_sha256": preview.source_sha256,
        "import_id": preview.import_id,
        "title": preview.title,
        "summary": {
            key: preview.summary[key]
            for key in _SUMMARY_KEYS
        },
        "rows": [
            {
                "entry_key": row.entry_key,
                "title": row.title,
                "outcome": row.outcome,
                "merge_action": row.merge_action,
                "resolution_status": row.resolution_status,
                "collection_keys": list(row.collection_keys),
                "proposed_source_references": [
                    {
                        "source": reference.source,
                        "external_id": reference.external_id,
                    }
                    for reference
                    in row.proposed_source_references
                ],
                "warnings": list(row.warnings),
                "conflicts": [
                    {
                        "field": conflict.field,
                        "existing_value": _thaw_json(
                            conflict.existing_value
                        ),
                        "imported_value": _thaw_json(
                            conflict.imported_value
                        ),
                    }
                    for conflict in row.conflicts
                ],
                "candidates": [
                    {
                        "collection_key": candidate.collection_key,
                        "title": candidate.title,
                        "authors": list(candidate.authors),
                    }
                    for candidate in row.candidates
                ],
                "requires_review": row.requires_review,
            }
            for row in preview.rows
        ],
        "groups": [
            {
                "group_key": group.group_key,
                "title": group.title,
                "entry_keys": list(group.entry_keys),
            }
            for group in preview.groups
        ],
    }


def serialize_bulk_collection_import_workflow_preview(
    preview: BulkCollectionImportWorkflowPreview,
) -> str:
    """Serialize the workflow preview as stable compact JSON."""

    return json.dumps(
        bulk_collection_import_workflow_preview_to_document(
            preview
        ),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _planning_session_to_document(planning: Any) -> dict[str, Any]:
    return {
        "source_name": planning.source_name,
        "byte_count": planning.byte_count,
        "sha256": planning.sha256,
        "import": bulk_collection_import_to_document(
            planning.document
        ),
        "preview": bulk_collection_import_preview_to_document(
            planning.preview_plan
        ),
        "merge": bulk_collection_import_merge_plan_to_document(
            planning.merge_plan
        ),
    }


def _parse_entries(value: Any) -> tuple[Mapping[str, Any], ...]:
    values = _require_sequence(value, "import.entries")
    result = []
    for index, item in enumerate(values):
        item = _require_mapping(
            item,
            f"import.entries[{index}]",
        )
        result.append(
            MappingProxyType(
                {
                    "entry_key": _require_text(
                        item.get("entry_key"),
                        f"import.entries[{index}].entry_key",
                    ),
                    "title": _require_text(
                        item.get("title"),
                        f"import.entries[{index}].title",
                    ),
                }
            )
        )
    return tuple(result)


def _parse_preview_items(
    value: Any,
) -> tuple[Mapping[str, Any], ...]:
    values = _require_sequence(value, "preview.items")
    result = []

    for index, raw in enumerate(values):
        item = _require_mapping(
            raw,
            f"preview.items[{index}]",
        )
        outcome = item.get("outcome")
        if outcome not in WORKFLOW_ROW_OUTCOMES:
            raise BulkCollectionImportWorkflowPreviewError(
                f"preview.items[{index}].outcome is invalid."
            )

        result.append(
            MappingProxyType(
                {
                    "entry_key": _require_text(
                        item.get("entry_key"),
                        f"preview.items[{index}].entry_key",
                    ),
                    "outcome": outcome,
                    "resolution_status": _require_text(
                        item.get("resolution_status"),
                        (
                            f"preview.items[{index}]"
                            ".resolution_status"
                        ),
                    ),
                    "collection_keys": _parse_text_sequence(
                        item.get("collection_keys"),
                        (
                            f"preview.items[{index}]"
                            ".collection_keys"
                        ),
                    ),
                    "proposed_source_references": (
                        _parse_source_references(
                            item.get(
                                "proposed_source_references"
                            ),
                            (
                                f"preview.items[{index}]"
                                ".proposed_source_references"
                            ),
                        )
                    ),
                    "warnings": _parse_text_sequence(
                        item.get("warnings"),
                        f"preview.items[{index}].warnings",
                    ),
                }
            )
        )

    return tuple(result)


def _parse_merge_items(
    value: Any,
) -> tuple[Mapping[str, Any], ...]:
    values = _require_sequence(value, "merge.items")
    result = []

    for index, raw in enumerate(values):
        item = _require_mapping(
            raw,
            f"merge.items[{index}]",
        )
        action = item.get("action")
        if action not in _MERGE_ACTIONS:
            raise BulkCollectionImportWorkflowPreviewError(
                f"merge.items[{index}].action is invalid."
            )

        result.append(
            MappingProxyType(
                {
                    "entry_key": _require_text(
                        item.get("entry_key"),
                        f"merge.items[{index}].entry_key",
                    ),
                    "action": action,
                    "collection_keys": _parse_text_sequence(
                        item.get("collection_keys"),
                        (
                            f"merge.items[{index}]"
                            ".collection_keys"
                        ),
                    ),
                    "title_decision": _parse_optional_decision(
                        item.get("title_decision"),
                        (
                            f"merge.items[{index}]"
                            ".title_decision"
                        ),
                    ),
                    "attribute_decisions": _parse_decisions(
                        item.get("attribute_decisions"),
                        (
                            f"merge.items[{index}]"
                            ".attribute_decisions"
                        ),
                    ),
                    "warnings": _parse_text_sequence(
                        item.get("warnings"),
                        f"merge.items[{index}].warnings",
                    ),
                }
            )
        )

    return tuple(result)


def _build_conflicts(
    merge_item: Mapping[str, Any],
) -> tuple[BulkCollectionImportWorkflowConflict, ...]:
    decisions = []
    if merge_item["title_decision"] is not None:
        decisions.append(merge_item["title_decision"])
    decisions.extend(merge_item["attribute_decisions"])

    return tuple(
        BulkCollectionImportWorkflowConflict(
            field=decision["field"],
            existing_value=_freeze_json(
                decision["existing_value"]
            ),
            imported_value=_freeze_json(
                decision["imported_value"]
            ),
        )
        for decision in decisions
        if decision["action"] == "review_conflict"
    )


def _build_candidate(
    collection_snapshot: Mapping[str, Mapping[str, Any]],
    collection_key: str,
) -> BulkCollectionImportWorkflowCandidate:
    raw = collection_snapshot.get(collection_key)
    if not isinstance(raw, Mapping):
        raise BulkCollectionImportWorkflowPreviewError(
            f"Collection candidate is missing: {collection_key}"
        )

    authors_raw = raw.get("authors", [])
    if (
        isinstance(authors_raw, (str, bytes, bytearray))
        or not isinstance(authors_raw, Sequence)
    ):
        raise BulkCollectionImportWorkflowPreviewError(
            f"Collection candidate authors are invalid: {collection_key}"
        )

    authors = tuple(
        _require_text(
            author,
            f"Collection candidate {collection_key} author",
        )
        for author in authors_raw
    )

    return BulkCollectionImportWorkflowCandidate(
        collection_key=collection_key,
        title=_require_text(
            raw.get("title"),
            f"Collection candidate {collection_key} title",
        ),
        authors=authors,
    )


def _parse_groups(
    value: Any,
    expected_entry_keys: tuple[str, ...],
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    values = _require_sequence(value, label)
    result = []
    flattened = []

    for index, raw in enumerate(values):
        group = _require_mapping(raw, f"{label}[{index}]")
        entry_keys = _parse_text_sequence(
            group.get("entry_keys"),
            f"{label}[{index}].entry_keys",
        )
        flattened.extend(entry_keys)
        result.append(
            MappingProxyType(
                {
                    "group_key": _require_text(
                        group.get("group_key"),
                        f"{label}[{index}].group_key",
                    ),
                    "title": _require_text(
                        group.get("title"),
                        f"{label}[{index}].title",
                    ),
                    "entry_keys": entry_keys,
                }
            )
        )

    if tuple(flattened) != expected_entry_keys:
        raise BulkCollectionImportWorkflowPreviewError(
            f"{label} must cover entries exactly once and in order."
        )

    return tuple(result)


def _validate_merge_summary(
    value: Any,
    merge_items: tuple[Mapping[str, Any], ...],
) -> Mapping[str, int]:
    summary = _require_mapping(value, "merge.summary")
    if set(summary) != set(_SUMMARY_KEYS):
        raise BulkCollectionImportWorkflowPreviewError(
            "merge.summary fields are invalid."
        )

    expected = {
        "total": len(merge_items),
        **{
            action: sum(
                item["action"] == action
                for item in merge_items
            )
            for action in _MERGE_ACTIONS
        },
    }

    for key in _SUMMARY_KEYS:
        actual = summary[key]
        if (
            type(actual) is not int
            or actual < 0
            or actual != expected[key]
        ):
            raise BulkCollectionImportWorkflowPreviewError(
                "merge.summary does not match merge rows."
            )

    return MappingProxyType(expected)


def _parse_optional_decision(
    value: Any,
    label: str,
) -> Mapping[str, Any] | None:
    if value is None:
        return None
    return _parse_decision(value, label)


def _parse_decisions(
    value: Any,
    label: str,
) -> tuple[Mapping[str, Any], ...]:
    values = _require_sequence(value, label)
    return tuple(
        _parse_decision(
            item,
            f"{label}[{index}]",
        )
        for index, item in enumerate(values)
    )


def _parse_decision(
    value: Any,
    label: str,
) -> Mapping[str, Any]:
    decision = _require_mapping(value, label)
    action = decision.get("action")
    if action not in (
        "set_new",
        "add_missing",
        "unchanged",
        "review_conflict",
    ):
        raise BulkCollectionImportWorkflowPreviewError(
            f"{label}.action is invalid."
        )

    return MappingProxyType(
        {
            "field": _require_text(
                decision.get("field"),
                f"{label}.field",
            ),
            "action": action,
            "existing_value": _freeze_json(
                decision.get("existing_value")
            ),
            "imported_value": _freeze_json(
                decision.get("imported_value")
            ),
        }
    )


def _parse_source_references(
    value: Any,
    label: str,
) -> tuple[Mapping[str, str], ...]:
    values = _require_sequence(value, label)
    result = []
    seen = set()

    for index, raw in enumerate(values):
        reference = _require_mapping(
            raw,
            f"{label}[{index}]",
        )
        source = _require_text(
            reference.get("source"),
            f"{label}[{index}].source",
        )
        external_id = _require_text(
            reference.get("external_id"),
            f"{label}[{index}].external_id",
        )
        identity = (source, external_id)
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            MappingProxyType(
                {
                    "source": source,
                    "external_id": external_id,
                }
            )
        )

    return tuple(result)


def _parse_text_sequence(
    value: Any,
    label: str,
) -> tuple[str, ...]:
    values = _require_sequence(value, label)
    return tuple(
        _require_text(item, f"{label}[{index}]")
        for index, item in enumerate(values)
    )


def _validate_unique_entry_keys(
    entry_keys: tuple[str, ...],
) -> None:
    if len(set(entry_keys)) != len(entry_keys):
        raise BulkCollectionImportWorkflowPreviewError(
            "Import entry keys must be unique."
        )


def _ordered_union(
    first: tuple[str, ...],
    second: tuple[str, ...],
) -> tuple[str, ...]:
    result = []
    seen = set()
    for value in (*first, *second):
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _require_sequence(value: Any, label: str) -> Sequence[Any]:
    if (
        isinstance(value, (str, bytes, bytearray))
        or not isinstance(value, Sequence)
    ):
        raise BulkCollectionImportWorkflowPreviewError(
            f"{label} must be a sequence."
        )
    return value


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportWorkflowPreviewError(
            f"{label} must be a mapping."
        )
    return value


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportWorkflowPreviewError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


def _require_sha256(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if (
        len(text) != 64
        or text.lower() != text
        or any(character not in "0123456789abcdef" for character in text)
    ):
        raise BulkCollectionImportWorkflowPreviewError(
            f"{label} must be a lowercase 64-character SHA-256."
        )
    return text


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                str(key): _freeze_json(item)
                for key, item in value.items()
            }
        )
    if isinstance(value, list):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_json(item) for item in value)
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _thaw_json(item)
            for key, item in value.items()
        }
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


__all__ = [
    "WORKFLOW_PREVIEW_SCHEMA",
    "WORKFLOW_PREVIEW_VERSION",
    "WORKFLOW_ROW_OUTCOMES",
    "BulkCollectionImportWorkflowPreviewError",
    "BulkCollectionImportWorkflowSourceReference",
    "BulkCollectionImportWorkflowConflict",
    "BulkCollectionImportWorkflowCandidate",
    "BulkCollectionImportWorkflowRow",
    "BulkCollectionImportWorkflowGroup",
    "BulkCollectionImportWorkflowPreview",
    "build_bulk_collection_import_workflow_preview",
    "plan_v5_1_bulk_collection_import_workflow_preview",
    "bulk_collection_import_workflow_preview_to_document",
    "serialize_bulk_collection_import_workflow_preview",
]
