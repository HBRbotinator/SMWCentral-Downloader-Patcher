"""Read-only review model for merging two existing numeric Collection identities.

This boundary exists only after the user explicitly confirmed that one numeric SMWC
submission may replace another and the selected target already exists in Collection.
It compares user/local state, identifies choices that cannot be inferred safely, and
returns a detached decision. It never hydrates providers, finalizes a change plan, or
writes user data.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from collection_plan_apply import collection_revision_token
from collection_update_discovery import CollectionUpdateSelection
from hack_data_manager import HackDataManager


class CollectionUpdateMergeReviewError(RuntimeError):
    """Raised when an existing-target merge cannot be reviewed safely."""


class MergeValueOrigin(str, Enum):
    """Which existing Collection record supplies one explicitly reviewed value."""

    SOURCE = "source"
    TARGET = "target"


@dataclass(frozen=True)
class MergeFieldConflict:
    """One user-owned top-level value that requires an explicit source/target choice."""

    field: str
    label: str
    source_value: Any
    target_value: Any


@dataclass(frozen=True)
class MergePrimaryRomChoice:
    """One currently selected primary ROM path available to the merge review."""

    path: str
    origin: MergeValueOrigin


@dataclass(frozen=True)
class MergeFieldDecision:
    """Explicitly retain the source or target value for one reviewed field."""

    field: str
    origin: MergeValueOrigin


@dataclass(frozen=True)
class CollectionUpdateExistingTargetMergeReview:
    """Frozen comparison of two populated numeric Collection records."""

    selection: CollectionUpdateSelection
    collection_revision_token: str
    field_conflicts: tuple[MergeFieldConflict, ...]
    primary_rom_choices: tuple[MergePrimaryRomChoice, ...]
    primary_rom_required: bool
    safe_combination_notes: tuple[str, ...]
    unsupported_conflicts: tuple[str, ...]

    @property
    def blocking_unsupported_conflicts(self) -> bool:
        return bool(self.unsupported_conflicts)


@dataclass(frozen=True)
class CollectionUpdateExistingTargetMergeDecision:
    """Detached explicit choices produced by the read-only merge review."""

    source_collection_key: str
    target_collection_key: str
    collection_revision_token: str
    field_decisions: tuple[MergeFieldDecision, ...]
    primary_rom_path: str


_REVIEW_FIELDS = (
    ("completed_date", "Completion date"),
    ("personal_rating", "Personal rating"),
    ("notes", "Notes"),
    ("time_to_beat", "Time to beat"),
    ("first_clear_playthrough", "First-clear playthrough"),
)

# These values either belong to the target submission/catalogue identity or are handled by
# the existing migration/union rules. They are deliberately not treated as user conflicts.
_NONCONFLICT_FIELDS = frozenset(
    {
        "title",
        "difficulty_id",
        "current_difficulty",
        "folder_name",
        "hack_type",
        "hack_types",
        "hall_of_fame",
        "sa1_compatibility",
        "collaboration",
        "demo",
        "authors",
        "exits",
        "rating",
        "smwc_rating",
        "time",
        "date",
        "obsolete",
        "completed",
        "file_path",
        "files",
        "local_files",
        "additional_paths",
        "import_sources",
        "playthroughs",
        "prior_smwc_submission_ids",
        "identity_migration_history",
        *(field for field, _label in _REVIEW_FIELDS),
    }
)


def build_collection_update_existing_target_merge_review(
    selection: CollectionUpdateSelection,
    manager: HackDataManager,
) -> CollectionUpdateExistingTargetMergeReview:
    """Compare the two existing numeric records without making any merge decision."""

    if not isinstance(selection, CollectionUpdateSelection):
        raise CollectionUpdateMergeReviewError(
            "Existing-target merge review requires the explicit update-discovery selection."
        )
    if not isinstance(manager, HackDataManager):
        raise TypeError("manager must be a HackDataManager")
    if bool(getattr(manager, "unsaved_changes", False)):
        raise CollectionUpdateMergeReviewError(
            "Collection changes are still unsaved. Wait for them to save before reviewing a merge."
        )
    if not selection.target_already_in_collection:
        raise CollectionUpdateMergeReviewError(
            "Existing-target merge review is only valid when the selected target is already in Collection."
        )

    source_key = str(selection.source_collection_key)
    target_key = str(selection.target_entry.smwc_submission_id)
    if source_key == target_key:
        raise CollectionUpdateMergeReviewError("A Collection entry cannot merge into itself.")
    source = manager.data.get(source_key)
    target = manager.data.get(target_key)
    if not isinstance(source, Mapping):
        raise CollectionUpdateMergeReviewError(
            "The source Collection entry no longer exists. Start update discovery again."
        )
    if not isinstance(target, Mapping):
        raise CollectionUpdateMergeReviewError(
            "The selected target is no longer in Collection. Start update discovery again."
        )

    conflicts = []
    for field, label in _REVIEW_FIELDS:
        source_value = source.get(field)
        target_value = target.get(field)
        if _meaningful(source_value) and _meaningful(target_value) and source_value != target_value:
            conflicts.append(
                MergeFieldConflict(
                    field=field,
                    label=label,
                    source_value=copy.deepcopy(source_value),
                    target_value=copy.deepcopy(target_value),
                )
            )

    source_primary = _primary_rom_path(source)
    target_primary = _primary_rom_path(target)
    primary_rows = []
    if source_primary:
        primary_rows.append(MergePrimaryRomChoice(source_primary, MergeValueOrigin.SOURCE))
    if target_primary and target_primary != source_primary:
        primary_rows.append(MergePrimaryRomChoice(target_primary, MergeValueOrigin.TARGET))
    primary_required = bool(source_primary and target_primary and source_primary != target_primary)

    notes = []
    if bool(source.get("completed")) or bool(target.get("completed")):
        notes.append("Completion remains true when either record is completed.")
    if len(_combined_unique_paths(source, target)) > 1:
        notes.append("Distinct ROM paths can be retained together without moving, renaming, or deleting ROM files.")
    if _has_any_rows(source, target, "playthroughs"):
        notes.append("Imported playthrough/history rows are retained from both records.")
    if _has_any_rows(source, target, "prior_smwc_submission_ids"):
        notes.append("Existing prior-SMWC provenance is retained and the source ID remains provenance after migration.")

    unsupported = _unsupported_conflicts(source, target)
    unsupported.extend(_playthrough_identity_conflicts(source, target))
    unsupported.extend(_same_path_hash_conflicts(source, target))
    unsupported.extend(_legacy_primary_path_conflicts(source, target))

    return CollectionUpdateExistingTargetMergeReview(
        selection=selection,
        collection_revision_token=collection_revision_token(manager),
        field_conflicts=tuple(conflicts),
        primary_rom_choices=tuple(primary_rows),
        primary_rom_required=primary_required,
        safe_combination_notes=tuple(notes),
        unsupported_conflicts=tuple(dict.fromkeys(unsupported)),
    )


def finalize_collection_update_existing_target_merge_decision(
    review: CollectionUpdateExistingTargetMergeReview,
    *,
    field_origins: Mapping[str, MergeValueOrigin | str],
    primary_rom_path: str = "",
) -> CollectionUpdateExistingTargetMergeDecision:
    """Validate explicit review choices and return detached immutable merge intent."""

    if not isinstance(review, CollectionUpdateExistingTargetMergeReview):
        raise TypeError("review must be CollectionUpdateExistingTargetMergeReview")
    if review.unsupported_conflicts:
        raise CollectionUpdateMergeReviewError(
            "This merge contains unsupported conflicting state and cannot be finalized safely."
        )

    expected_fields = {item.field for item in review.field_conflicts}
    supplied_fields = set(field_origins)
    missing = expected_fields.difference(supplied_fields)
    unknown = supplied_fields.difference(expected_fields)
    if missing:
        raise CollectionUpdateMergeReviewError(
            "Choose which record to keep for: " + ", ".join(sorted(missing))
        )
    if unknown:
        raise CollectionUpdateMergeReviewError(
            "Merge decision contains unknown field choices: " + ", ".join(sorted(unknown))
        )

    decisions = []
    for conflict in review.field_conflicts:
        raw = field_origins[conflict.field]
        try:
            origin = raw if isinstance(raw, MergeValueOrigin) else MergeValueOrigin(str(raw))
        except ValueError as error:
            raise CollectionUpdateMergeReviewError(
                f"Invalid merge origin for {conflict.field}: {raw!r}"
            ) from error
        decisions.append(MergeFieldDecision(conflict.field, origin))

    allowed_primary = {item.path for item in review.primary_rom_choices}
    if review.primary_rom_required:
        if primary_rom_path not in allowed_primary:
            raise CollectionUpdateMergeReviewError(
                "Choose which existing ROM remains primary after the merge."
            )
    elif primary_rom_path and primary_rom_path not in allowed_primary:
        raise CollectionUpdateMergeReviewError("Selected primary ROM is not part of this review.")
    if not primary_rom_path and len(allowed_primary) == 1:
        primary_rom_path = next(iter(allowed_primary))

    return CollectionUpdateExistingTargetMergeDecision(
        source_collection_key=str(review.selection.source_collection_key),
        target_collection_key=str(review.selection.target_entry.smwc_submission_id),
        collection_revision_token=review.collection_revision_token,
        field_decisions=tuple(decisions),
        primary_rom_path=primary_rom_path,
    )


def _meaningful(value: Any) -> bool:
    return value not in (None, "", 0, False, [], {})


def _primary_rom_path(record: Mapping[str, Any]) -> str:
    rows = record.get("files")
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, Mapping) and row.get("primary"):
                path = row.get("path")
                if isinstance(path, str) and path:
                    return path
    fallback = record.get("file_path")
    return fallback if isinstance(fallback, str) else ""


def _combined_unique_paths(source: Mapping[str, Any], target: Mapping[str, Any]) -> tuple[str, ...]:
    paths = []
    for record in (target, source):
        rows = record.get("files")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                path = row.get("path")
                if isinstance(path, str) and path and path not in paths:
                    paths.append(path)
        fallback = record.get("file_path")
        if isinstance(fallback, str) and fallback and fallback not in paths:
            paths.append(fallback)
    return tuple(paths)


def _has_any_rows(source: Mapping[str, Any], target: Mapping[str, Any], field: str) -> bool:
    return bool(source.get(field)) or bool(target.get(field))


def _unsupported_conflicts(source: Mapping[str, Any], target: Mapping[str, Any]) -> list[str]:
    result = []
    for field in sorted(set(source).intersection(target).difference(_NONCONFLICT_FIELDS)):
        source_value = source.get(field)
        target_value = target.get(field)
        if source_value != target_value and _meaningful(source_value) and _meaningful(target_value):
            result.append(
                f"Unsupported conflicting field {field!r} differs on both Collection records."
            )
    return result


def _playthrough_identity_conflicts(source: Mapping[str, Any], target: Mapping[str, Any]) -> list[str]:
    source_rows = _rows_by_source_identity(source.get("playthroughs"))
    target_rows = _rows_by_source_identity(target.get("playthroughs"))
    result = []
    for identity in sorted(set(source_rows).intersection(target_rows)):
        if source_rows[identity] != target_rows[identity]:
            result.append(
                "Imported playthrough identity "
                f"{identity[0]}:{identity[1]} differs between the two records."
            )
    return result


def _rows_by_source_identity(raw: Any) -> dict[tuple[str, str], Mapping[str, Any]]:
    result = {}
    if not isinstance(raw, list):
        return result
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        source = row.get("source")
        record_id = row.get("source_record_id")
        if isinstance(source, str) and isinstance(record_id, str) and record_id:
            result[(source, record_id)] = row
    return result


def _same_path_hash_conflicts(source: Mapping[str, Any], target: Mapping[str, Any]) -> list[str]:
    source_rows = _file_rows_by_path(source.get("files"))
    target_rows = _file_rows_by_path(target.get("files"))
    result = []
    for path in sorted(set(source_rows).intersection(target_rows)):
        source_hash = source_rows[path].get("sha256")
        target_hash = target_rows[path].get("sha256")
        if (
            isinstance(source_hash, str)
            and source_hash
            and isinstance(target_hash, str)
            and target_hash
            and source_hash != target_hash
        ):
            result.append(
                f"ROM path {path!r} has different SHA-256 values in the two records."
            )
    return result



def _legacy_primary_path_conflicts(source: Mapping[str, Any], target: Mapping[str, Any]) -> list[str]:
    source_primary = _primary_rom_path(source)
    target_primary = _primary_rom_path(target)
    if not source_primary or not target_primary or source_primary == target_primary:
        return []
    source_paths = set(_file_rows_by_path(source.get("files")))
    target_paths = set(_file_rows_by_path(target.get("files")))
    missing = []
    if source_primary not in source_paths:
        missing.append(f"source primary {source_primary!r}")
    if target_primary not in target_paths:
        missing.append(f"target primary {target_primary!r}")
    if not missing:
        return []
    return [
        "Different primary ROM paths include legacy file_path-only state ("
        + ", ".join(missing)
        + "). The current merge model cannot yet guarantee both paths survive identity migration."
    ]

def _file_rows_by_path(raw: Any) -> dict[str, Mapping[str, Any]]:
    result = {}
    if not isinstance(raw, list):
        return result
    for row in raw:
        if not isinstance(row, Mapping):
            continue
        path = row.get("path")
        if isinstance(path, str) and path:
            result[path] = row
    return result


__all__ = [
    "CollectionUpdateExistingTargetMergeDecision",
    "CollectionUpdateExistingTargetMergeReview",
    "CollectionUpdateMergeReviewError",
    "MergeFieldConflict",
    "MergeFieldDecision",
    "MergePrimaryRomChoice",
    "MergeValueOrigin",
    "build_collection_update_existing_target_merge_review",
    "finalize_collection_update_existing_target_merge_decision",
]
