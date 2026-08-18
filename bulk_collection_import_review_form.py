"""Immutable UI review requirements for v5.1 bulk Collection imports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from bulk_collection_import_review import (
    BULK_COLLECTION_IMPORT_REVIEW_CONFLICT_CHOICES,
    BULK_COLLECTION_IMPORT_REVIEW_SCHEMA,
    BULK_COLLECTION_IMPORT_REVIEW_VERSION,
)
from bulk_collection_import_workflow_preview import (
    BulkCollectionImportWorkflowCandidate,
    BulkCollectionImportWorkflowConflict,
    BulkCollectionImportWorkflowPreview,
)


REVIEW_FORM_SCHEMA = "smwc-bulk-collection-review-form"
REVIEW_FORM_VERSION = 1

REVIEW_KIND_AMBIGUOUS_IDENTITY = "ambiguous_identity"
REVIEW_KIND_HARD_IDENTITY_CONFLICT = "hard_identity_conflict"
REVIEW_KIND_METADATA = "metadata"

REVIEW_SELECTION_ACTIONS = (
    "select_existing",
    "create_new",
    "resolve_metadata",
    "skip",
)
CONFLICT_CHOICES = tuple(
    BULK_COLLECTION_IMPORT_REVIEW_CONFLICT_CHOICES
)

REVIEW_DECISION_SCHEMA = BULK_COLLECTION_IMPORT_REVIEW_SCHEMA
REVIEW_DECISION_VERSION = BULK_COLLECTION_IMPORT_REVIEW_VERSION

_IDENTITY_REVIEW_WARNING = "identity_review_required"
_IDENTITY_AMBIGUOUS_WARNING = "identity_ambiguous"
_IDENTITY_CONFLICT_WARNING = "identity_conflict"
_HARD_IDENTITY_WARNINGS = frozenset(
    {
        "source_identity_conflict",
        "duplicate_import_target",
    }
)


class BulkCollectionImportReviewFormError(ValueError):
    """Raised when review requirements or UI selections are unsafe."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportReviewFormCandidate:
    """Safe existing Collection candidate shown to the user."""

    collection_key: str
    title: str
    authors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportReviewFormConflict:
    """One shared-metadata field requiring an explicit choice."""

    field: str
    existing_value: Any
    imported_value: Any
    selected_choice: str | None = None


@dataclass(frozen=True, slots=True)
class BulkCollectionImportReviewFormItem:
    """One blocked workflow row requiring an explicit user decision."""

    entry_key: str
    title: str
    review_kind: str
    allowed_actions: tuple[str, ...]
    collection_keys: tuple[str, ...]
    candidates: tuple[BulkCollectionImportReviewFormCandidate, ...]
    warnings: tuple[str, ...]
    conflicts: tuple[BulkCollectionImportReviewFormConflict, ...]
    selected_action: str | None = None
    selected_collection_key: str | None = None


@dataclass(frozen=True, slots=True)
class BulkCollectionImportReviewForm:
    """Immutable review requirements for one exact imported source."""

    schema: str
    version: int
    import_id: str
    source_sha256: str
    items: tuple[BulkCollectionImportReviewFormItem, ...]


def build_bulk_collection_import_review_form(
    preview: BulkCollectionImportWorkflowPreview,
) -> BulkCollectionImportReviewForm:
    """Build explicit review requirements from blocked workflow rows."""

    if not isinstance(preview, BulkCollectionImportWorkflowPreview):
        raise TypeError(
            "preview must be BulkCollectionImportWorkflowPreview"
        )

    items = tuple(
        _build_review_item(row)
        for row in preview.rows
        if row.requires_review
    )

    if len(items) != preview.review_required_count:
        raise BulkCollectionImportReviewFormError(
            "Workflow review count does not match blocked rows."
        )

    return BulkCollectionImportReviewForm(
        schema=REVIEW_FORM_SCHEMA,
        version=REVIEW_FORM_VERSION,
        import_id=_require_text(preview.import_id, "preview import_id"),
        source_sha256=_require_sha256(
            preview.source_sha256,
            "preview source_sha256",
        ),
        items=items,
    )


def bulk_collection_import_review_form_to_document(
    form: BulkCollectionImportReviewForm,
) -> dict[str, Any]:
    """Project immutable review requirements to detached UI state."""

    _require_form(form)

    return {
        "schema": form.schema,
        "version": form.version,
        "import_id": form.import_id,
        "source_sha256": form.source_sha256,
        "items": [
            {
                "entry_key": item.entry_key,
                "title": item.title,
                "review_kind": item.review_kind,
                "allowed_actions": list(item.allowed_actions),
                "collection_keys": list(item.collection_keys),
                "candidates": [
                    {
                        "collection_key": candidate.collection_key,
                        "title": candidate.title,
                        "authors": list(candidate.authors),
                    }
                    for candidate in item.candidates
                ],
                "warnings": list(item.warnings),
                "conflicts": [
                    {
                        "field": conflict.field,
                        "existing_value": _thaw_json(
                            conflict.existing_value
                        ),
                        "imported_value": _thaw_json(
                            conflict.imported_value
                        ),
                        "selected_choice": conflict.selected_choice,
                    }
                    for conflict in item.conflicts
                ],
                "selected_action": item.selected_action,
                "selected_collection_key": (
                    item.selected_collection_key
                ),
            }
            for item in form.items
        ],
    }


def build_bulk_collection_import_review_document(
    form: BulkCollectionImportReviewForm,
    selections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate explicit UI selections and emit the existing review schema."""

    _require_form(form)
    if not isinstance(selections, Mapping):
        raise BulkCollectionImportReviewFormError(
            "selections must be a mapping keyed by entry_key."
        )

    expected_keys = tuple(item.entry_key for item in form.items)
    actual_keys = tuple(selections.keys())
    if set(actual_keys) != set(expected_keys):
        missing = sorted(set(expected_keys) - set(actual_keys))
        unexpected = sorted(set(actual_keys) - set(expected_keys))
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append(
                "unexpected: " + ", ".join(unexpected)
            )
        raise BulkCollectionImportReviewFormError(
            "Selections must cover every review row exactly once"
            + (f" ({'; '.join(details)})" if details else ".")
        )

    decisions = [
        _build_decision(item, selections[item.entry_key])
        for item in form.items
    ]

    return {
        "schema": REVIEW_DECISION_SCHEMA,
        "version": REVIEW_DECISION_VERSION,
        "import_id": form.import_id,
        "source_sha256": form.source_sha256,
        "decisions": decisions,
    }


def serialize_bulk_collection_import_review_document(
    document: Mapping[str, Any],
) -> str:
    """Serialize one generated review document deterministically."""

    _validate_generated_review_document(document)
    return json.dumps(
        document,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _build_review_item(row) -> BulkCollectionImportReviewFormItem:
    if row.merge_action != "review_required":
        raise BulkCollectionImportReviewFormError(
            f"Blocked row {row.entry_key} must have "
            "merge_action review_required."
        )

    warnings = tuple(
        _require_text(
            warning,
            f"{row.entry_key} warning",
        )
        for warning in row.warnings
    )
    warning_set = set(warnings)

    identity_review = _IDENTITY_REVIEW_WARNING in warning_set
    ambiguous = _IDENTITY_AMBIGUOUS_WARNING in warning_set
    conflict = _IDENTITY_CONFLICT_WARNING in warning_set
    hard_conflicts = warning_set.intersection(
        _HARD_IDENTITY_WARNINGS
    )

    if identity_review:
        if ambiguous == conflict:
            raise BulkCollectionImportReviewFormError(
                "Identity review must identify exactly one reason: "
                "ambiguous or conflict."
            )
        if row.conflicts:
            raise BulkCollectionImportReviewFormError(
                "Identity review cannot also expose metadata conflicts."
            )

        if ambiguous:
            if hard_conflicts:
                raise BulkCollectionImportReviewFormError(
                    "Ambiguous identity review cannot carry a hard "
                    "identity-conflict warning."
                )
            review_kind = REVIEW_KIND_AMBIGUOUS_IDENTITY
            allowed_actions = (
                "select_existing",
                "create_new",
                "skip",
            )
            if not row.collection_keys or not row.candidates:
                raise BulkCollectionImportReviewFormError(
                    "Ambiguous identity review requires candidates."
                )
            candidate_keys = tuple(
                candidate.collection_key
                for candidate in row.candidates
            )
            if candidate_keys != row.collection_keys:
                raise BulkCollectionImportReviewFormError(
                    "Ambiguous identity candidates must match "
                    "Collection target order exactly."
                )
        else:
            if not hard_conflicts:
                raise BulkCollectionImportReviewFormError(
                    "Identity conflict review requires a known hard "
                    "identity-conflict warning."
                )
            review_kind = REVIEW_KIND_HARD_IDENTITY_CONFLICT
            allowed_actions = ("skip",)
    else:
        if ambiguous or conflict:
            raise BulkCollectionImportReviewFormError(
                "Identity reason warnings require "
                "identity_review_required."
            )
        if hard_conflicts:
            raise BulkCollectionImportReviewFormError(
                "Hard identity warning requires identity review."
            )
        if not row.conflicts:
            raise BulkCollectionImportReviewFormError(
                "Metadata review requires at least one conflict."
            )
        if len(row.collection_keys) != 1:
            raise BulkCollectionImportReviewFormError(
                "Metadata review requires exactly one matched "
                "Collection record."
            )
        review_kind = REVIEW_KIND_METADATA
        allowed_actions = ("resolve_metadata", "skip")

    conflicts = _copy_conflicts(row.conflicts)
    _validate_unique_conflict_fields(conflicts)

    return BulkCollectionImportReviewFormItem(
        entry_key=_require_text(row.entry_key, "entry_key"),
        title=_require_text(row.title, "title"),
        review_kind=review_kind,
        allowed_actions=allowed_actions,
        collection_keys=tuple(
            _require_text(key, "collection_key")
            for key in row.collection_keys
        ),
        candidates=tuple(
            _copy_candidate(candidate)
            for candidate in row.candidates
        ),
        warnings=warnings,
        conflicts=conflicts,
    )


def _build_decision(
    item: BulkCollectionImportReviewFormItem,
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(selection, Mapping):
        raise BulkCollectionImportReviewFormError(
            f"Selection for {item.entry_key} must be a mapping."
        )

    action = selection.get("action")
    if action not in item.allowed_actions:
        raise BulkCollectionImportReviewFormError(
            f"Action {action!r} is not allowed for {item.entry_key}."
        )

    if action == "select_existing":
        _require_exact_selection_keys(
            selection,
            ("action", "selected_collection_key"),
            item.entry_key,
        )
        selected_key = _require_text(
            selection["selected_collection_key"],
            f"{item.entry_key} selected_collection_key",
        )
        candidate_keys = tuple(
            candidate.collection_key
            for candidate in item.candidates
        )
        if selected_key not in candidate_keys:
            raise BulkCollectionImportReviewFormError(
                f"{item.entry_key} must select one of its "
                "displayed candidates."
            )
        return _decision_document(
            item.entry_key,
            action,
            selected_collection_key=selected_key,
        )

    if action == "create_new":
        _require_exact_selection_keys(
            selection,
            ("action",),
            item.entry_key,
        )
        return _decision_document(item.entry_key, action)

    if action == "skip":
        _require_exact_selection_keys(
            selection,
            ("action",),
            item.entry_key,
        )
        return _decision_document(item.entry_key, action)

    if action != "resolve_metadata":
        raise BulkCollectionImportReviewFormError(
            f"Unsupported review action: {action}"
        )

    _require_exact_selection_keys(
        selection,
        ("action", "choices"),
        item.entry_key,
    )
    choices = selection["choices"]
    if not isinstance(choices, Mapping):
        raise BulkCollectionImportReviewFormError(
            f"{item.entry_key} metadata choices must be a mapping."
        )

    expected_fields = tuple(
        conflict.field for conflict in item.conflicts
    )
    if set(choices) != set(expected_fields):
        missing = sorted(set(expected_fields) - set(choices))
        unexpected = sorted(set(choices) - set(expected_fields))
        details = []
        if missing:
            details.append("missing: " + ", ".join(missing))
        if unexpected:
            details.append(
                "unexpected: " + ", ".join(unexpected)
            )
        raise BulkCollectionImportReviewFormError(
            f"{item.entry_key} must resolve every metadata conflict"
            + (f" ({'; '.join(details)})" if details else ".")
        )

    selected_collection_key = item.collection_keys[0]
    title_choice = None
    attribute_choices = []

    for conflict in item.conflicts:
        choice = choices[conflict.field]
        if choice not in CONFLICT_CHOICES:
            raise BulkCollectionImportReviewFormError(
                f"{item.entry_key} choice for {conflict.field} "
                "must be keep_existing or use_imported."
            )
        if conflict.field == "title":
            title_choice = choice
        else:
            attribute_choices.append(
                {
                    "field": conflict.field,
                    "choice": choice,
                }
            )

    return _decision_document(
        item.entry_key,
        action,
        selected_collection_key=selected_collection_key,
        title_choice=title_choice,
        attribute_choices=attribute_choices,
    )


def _decision_document(
    entry_key: str,
    action: str,
    *,
    selected_collection_key: str | None = None,
    title_choice: str | None = None,
    attribute_choices: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    return {
        "entry_key": entry_key,
        "action": action,
        "selected_collection_key": selected_collection_key,
        "title_choice": title_choice,
        "attribute_choices": [
            dict(choice) for choice in attribute_choices
        ],
    }


def _copy_candidate(
    candidate: BulkCollectionImportWorkflowCandidate,
) -> BulkCollectionImportReviewFormCandidate:
    if not isinstance(
        candidate,
        BulkCollectionImportWorkflowCandidate,
    ):
        raise BulkCollectionImportReviewFormError(
            "Workflow candidate has an invalid type."
        )
    return BulkCollectionImportReviewFormCandidate(
        collection_key=_require_text(
            candidate.collection_key,
            "candidate collection_key",
        ),
        title=_require_text(candidate.title, "candidate title"),
        authors=tuple(
            _require_text(author, "candidate author")
            for author in candidate.authors
        ),
    )


def _copy_conflicts(
    conflicts: Sequence[BulkCollectionImportWorkflowConflict],
) -> tuple[BulkCollectionImportReviewFormConflict, ...]:
    result = []
    for conflict in conflicts:
        if not isinstance(
            conflict,
            BulkCollectionImportWorkflowConflict,
        ):
            raise BulkCollectionImportReviewFormError(
                "Workflow conflict has an invalid type."
            )
        result.append(
            BulkCollectionImportReviewFormConflict(
                field=_require_text(
                    conflict.field,
                    "conflict field",
                ),
                existing_value=_freeze_json(
                    conflict.existing_value
                ),
                imported_value=_freeze_json(
                    conflict.imported_value
                ),
            )
        )
    return tuple(result)


def _validate_unique_conflict_fields(
    conflicts: tuple[BulkCollectionImportReviewFormConflict, ...],
) -> None:
    fields = tuple(conflict.field for conflict in conflicts)
    if len(fields) != len(set(fields)):
        raise BulkCollectionImportReviewFormError(
            "Metadata conflicts must have unique field names."
        )


def _require_exact_selection_keys(
    selection: Mapping[str, Any],
    expected: tuple[str, ...],
    entry_key: str,
) -> None:
    if set(selection) != set(expected):
        raise BulkCollectionImportReviewFormError(
            f"Selection fields for {entry_key} do not match "
            f"the {selection.get('action')!r} contract."
        )


def _require_form(form: Any) -> None:
    if not isinstance(form, BulkCollectionImportReviewForm):
        raise TypeError("form must be BulkCollectionImportReviewForm")
    if form.schema != REVIEW_FORM_SCHEMA:
        raise BulkCollectionImportReviewFormError(
            "Review form schema is not supported."
        )
    if form.version != REVIEW_FORM_VERSION:
        raise BulkCollectionImportReviewFormError(
            "Review form version is not supported."
        )


def _validate_generated_review_document(
    document: Mapping[str, Any],
) -> None:
    if not isinstance(document, Mapping):
        raise TypeError("document must be a mapping")

    expected = {
        "schema",
        "version",
        "import_id",
        "source_sha256",
        "decisions",
    }
    if set(document) != expected:
        raise BulkCollectionImportReviewFormError(
            "Review document fields do not match the existing contract."
        )
    if document["schema"] != REVIEW_DECISION_SCHEMA:
        raise BulkCollectionImportReviewFormError(
            "Review document schema is not supported."
        )
    if document["version"] != REVIEW_DECISION_VERSION:
        raise BulkCollectionImportReviewFormError(
            "Review document version is not supported."
        )
    _require_text(document["import_id"], "review import_id")
    _require_sha256(
        document["source_sha256"],
        "review source_sha256",
    )
    if not isinstance(document["decisions"], list):
        raise BulkCollectionImportReviewFormError(
            "Review decisions must be a list."
        )


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportReviewFormError(
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
        raise BulkCollectionImportReviewFormError(
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
    "REVIEW_FORM_SCHEMA",
    "REVIEW_FORM_VERSION",
    "REVIEW_KIND_AMBIGUOUS_IDENTITY",
    "REVIEW_KIND_HARD_IDENTITY_CONFLICT",
    "REVIEW_KIND_METADATA",
    "REVIEW_SELECTION_ACTIONS",
    "CONFLICT_CHOICES",
    "REVIEW_DECISION_SCHEMA",
    "REVIEW_DECISION_VERSION",
    "BulkCollectionImportReviewFormError",
    "BulkCollectionImportReviewFormCandidate",
    "BulkCollectionImportReviewFormConflict",
    "BulkCollectionImportReviewFormItem",
    "BulkCollectionImportReviewForm",
    "build_bulk_collection_import_review_form",
    "bulk_collection_import_review_form_to_document",
    "build_bulk_collection_import_review_document",
    "serialize_bulk_collection_import_review_document",
]
