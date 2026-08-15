"""Immutable review decisions for bulk Collection imports."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Mapping

from bulk_collection_import_merge import (
    BulkCollectionImportMergeItem,
    BulkCollectionImportMergePlan,
)


BULK_COLLECTION_IMPORT_REVIEW_SCHEMA = (
    "smwc-bulk-collection-review-decisions"
)
BULK_COLLECTION_IMPORT_REVIEW_VERSION = 1

BULK_COLLECTION_IMPORT_REVIEW_ACTIONS = (
    "resolve_metadata",
    "select_existing",
    "create_new",
    "skip",
)
BULK_COLLECTION_IMPORT_REVIEW_CONFLICT_CHOICES = (
    "keep_existing",
    "use_imported",
)

BULK_COLLECTION_IMPORT_REVIEW_DOCUMENT_KEYS = (
    "schema",
    "version",
    "import_id",
    "source_sha256",
    "decisions",
)
BULK_COLLECTION_IMPORT_REVIEW_DECISION_KEYS = (
    "entry_key",
    "action",
    "selected_collection_key",
    "title_choice",
    "attribute_choices",
)
BULK_COLLECTION_IMPORT_REVIEW_ATTRIBUTE_CHOICE_KEYS = (
    "field",
    "choice",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class BulkCollectionImportReviewError(ValueError):
    """Raised when review decisions do not match a merge plan."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportReviewAttributeChoice:
    """One explicit choice for a conflicting shared-metadata field."""

    field: str
    choice: str


@dataclass(frozen=True, slots=True)
class BulkCollectionImportReviewDecision:
    """One immutable decision for a review-required merge item."""

    entry_key: str
    action: str
    selected_collection_key: str | None
    title_choice: str | None
    attribute_choices: tuple[
        BulkCollectionImportReviewAttributeChoice,
        ...,
    ]


@dataclass(frozen=True, slots=True)
class BulkCollectionImportReviewDecisions:
    """Detached immutable review decisions for one exact source file."""

    schema: str
    version: int
    import_id: str
    source_sha256: str
    decisions: tuple[BulkCollectionImportReviewDecision, ...]


def parse_bulk_collection_import_review_decisions(
    document: Mapping[str, Any],
    merge_plan: BulkCollectionImportMergePlan,
    source_sha256: str,
) -> BulkCollectionImportReviewDecisions:
    """Validate and freeze decisions for all review-required rows."""

    if not isinstance(merge_plan, BulkCollectionImportMergePlan):
        raise TypeError(
            "merge_plan must be a BulkCollectionImportMergePlan"
        )

    expected_sha256 = _require_sha256(
        source_sha256,
        "source_sha256",
    )
    _require_exact_mapping(
        document,
        BULK_COLLECTION_IMPORT_REVIEW_DOCUMENT_KEYS,
        "review document",
    )

    if document["schema"] != BULK_COLLECTION_IMPORT_REVIEW_SCHEMA:
        raise BulkCollectionImportReviewError(
            "Review document schema is not supported."
        )
    if (
        type(document["version"]) is not int
        or document["version"]
        != BULK_COLLECTION_IMPORT_REVIEW_VERSION
    ):
        raise BulkCollectionImportReviewError(
            "Review document version is not supported."
        )
    if document["import_id"] != merge_plan.import_id:
        raise BulkCollectionImportReviewError(
            "Review document import_id does not match the merge plan."
        )

    document_sha256 = _require_sha256(
        document["source_sha256"],
        "review document source_sha256",
    )
    if document_sha256 != expected_sha256:
        raise BulkCollectionImportReviewError(
            "Review decisions belong to a different source file."
        )

    review_items = tuple(
        item
        for item in merge_plan.items
        if item.action == "review_required"
    )
    raw_decisions = document["decisions"]
    if not isinstance(raw_decisions, list):
        raise BulkCollectionImportReviewError(
            "review document decisions must be a JSON array."
        )
    if len(raw_decisions) != len(review_items):
        raise BulkCollectionImportReviewError(
            "Every review-required merge item must have exactly "
            "one decision."
        )

    expected_entry_keys = tuple(
        item.entry_key for item in review_items
    )
    actual_entry_keys = tuple(
        _decision_entry_key(value, index)
        for index, value in enumerate(raw_decisions)
    )
    if actual_entry_keys != expected_entry_keys:
        raise BulkCollectionImportReviewError(
            "Review decisions must cover review-required items "
            "exactly once and in merge-plan order."
        )

    decisions = tuple(
        _parse_decision(value, item, index)
        for index, (value, item) in enumerate(
            zip(raw_decisions, review_items, strict=True)
        )
    )

    return BulkCollectionImportReviewDecisions(
        schema=BULK_COLLECTION_IMPORT_REVIEW_SCHEMA,
        version=BULK_COLLECTION_IMPORT_REVIEW_VERSION,
        import_id=merge_plan.import_id,
        source_sha256=expected_sha256,
        decisions=decisions,
    )


def bulk_collection_import_review_decisions_to_document(
    decisions: BulkCollectionImportReviewDecisions,
) -> dict[str, Any]:
    """Project review decisions to a detached canonical document."""

    if not isinstance(
        decisions,
        BulkCollectionImportReviewDecisions,
    ):
        raise TypeError(
            "decisions must be BulkCollectionImportReviewDecisions"
        )

    return {
        "schema": decisions.schema,
        "version": decisions.version,
        "import_id": decisions.import_id,
        "source_sha256": decisions.source_sha256,
        "decisions": [
            {
                "entry_key": item.entry_key,
                "action": item.action,
                "selected_collection_key": (
                    item.selected_collection_key
                ),
                "title_choice": item.title_choice,
                "attribute_choices": [
                    {
                        "field": choice.field,
                        "choice": choice.choice,
                    }
                    for choice in item.attribute_choices
                ],
            }
            for item in decisions.decisions
        ],
    }


def serialize_bulk_collection_import_review_decisions(
    decisions: BulkCollectionImportReviewDecisions,
) -> str:
    """Serialize review decisions as deterministic compact JSON."""

    return json.dumps(
        bulk_collection_import_review_decisions_to_document(
            decisions
        ),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _decision_entry_key(value: Any, index: int) -> str:
    label = f"decisions[{index}]"
    _require_exact_mapping(
        value,
        BULK_COLLECTION_IMPORT_REVIEW_DECISION_KEYS,
        label,
    )
    entry_key = value["entry_key"]
    if not isinstance(entry_key, str) or not entry_key:
        raise BulkCollectionImportReviewError(
            f"{label}.entry_key must be a non-empty string."
        )
    return entry_key


def _parse_decision(
    value: Mapping[str, Any],
    item: BulkCollectionImportMergeItem,
    index: int,
) -> BulkCollectionImportReviewDecision:
    label = f"decisions[{index}]"
    action = value["action"]
    if action not in BULK_COLLECTION_IMPORT_REVIEW_ACTIONS:
        raise BulkCollectionImportReviewError(
            f"{label}.action is not supported."
        )

    selected_key = _optional_text(
        value["selected_collection_key"],
        f"{label}.selected_collection_key",
    )
    title_choice = _optional_choice(
        value["title_choice"],
        f"{label}.title_choice",
    )
    attribute_choices = _parse_attribute_choices(
        value["attribute_choices"],
        label,
    )

    if _is_identity_review(item):
        _validate_identity_review(
            action,
            selected_key,
            title_choice,
            attribute_choices,
            item,
            label,
        )
    else:
        _validate_metadata_review(
            action,
            selected_key,
            title_choice,
            attribute_choices,
            item,
            label,
        )

    return BulkCollectionImportReviewDecision(
        entry_key=item.entry_key,
        action=action,
        selected_collection_key=selected_key,
        title_choice=title_choice,
        attribute_choices=attribute_choices,
    )


def _is_identity_review(
    item: BulkCollectionImportMergeItem,
) -> bool:
    return (
        "identity_review_required" in item.warnings
        or (
            item.title_decision is None
            and not item.attribute_decisions
        )
    )


def _validate_identity_review(
    action: str,
    selected_key: str | None,
    title_choice: str | None,
    attribute_choices: tuple[
        BulkCollectionImportReviewAttributeChoice,
        ...,
    ],
    item: BulkCollectionImportMergeItem,
    label: str,
) -> None:
    if title_choice is not None or attribute_choices:
        raise BulkCollectionImportReviewError(
            f"{label} identity decisions cannot contain metadata "
            "conflict choices."
        )

    if action == "select_existing":
        if selected_key not in item.collection_keys:
            raise BulkCollectionImportReviewError(
                f"{label}.selected_collection_key must be one "
                "of the merge-plan identity candidates."
            )
        return

    if action in ("create_new", "skip"):
        if selected_key is not None:
            raise BulkCollectionImportReviewError(
                f"{label} {action} decisions cannot select an "
                "existing Collection record."
            )
        return

    raise BulkCollectionImportReviewError(
        f"{label} identity review must select_existing, "
        "create_new, or skip."
    )


def _validate_metadata_review(
    action: str,
    selected_key: str | None,
    title_choice: str | None,
    attribute_choices: tuple[
        BulkCollectionImportReviewAttributeChoice,
        ...,
    ],
    item: BulkCollectionImportMergeItem,
    label: str,
) -> None:
    if action == "skip":
        if (
            selected_key is not None
            or title_choice is not None
            or attribute_choices
        ):
            raise BulkCollectionImportReviewError(
                f"{label} skip decisions cannot carry a target "
                "or conflict choices."
            )
        return

    if action != "resolve_metadata":
        raise BulkCollectionImportReviewError(
            f"{label} metadata review must resolve_metadata or skip."
        )

    if len(item.collection_keys) != 1:
        raise BulkCollectionImportReviewError(
            f"{label} metadata review must have exactly one "
            "matched Collection record."
        )
    if selected_key != item.collection_keys[0]:
        raise BulkCollectionImportReviewError(
            f"{label}.selected_collection_key must preserve the "
            "matched Collection record."
        )

    title_conflict = (
        item.title_decision is not None
        and item.title_decision.action == "review_conflict"
    )
    if title_conflict:
        if title_choice is None:
            raise BulkCollectionImportReviewError(
                f"{label}.title_choice is required for the "
                "conflicting title."
            )
    elif title_choice is not None:
        raise BulkCollectionImportReviewError(
            f"{label}.title_choice is only allowed for a "
            "conflicting title."
        )

    expected_fields = tuple(
        decision.field
        for decision in item.attribute_decisions
        if decision.action == "review_conflict"
    )
    actual_fields = tuple(
        choice.field for choice in attribute_choices
    )
    if actual_fields != expected_fields:
        raise BulkCollectionImportReviewError(
            f"{label}.attribute_choices must cover every "
            "conflicting field exactly once and in plan order."
        )


def _parse_attribute_choices(
    value: Any,
    decision_label: str,
) -> tuple[BulkCollectionImportReviewAttributeChoice, ...]:
    if not isinstance(value, list):
        raise BulkCollectionImportReviewError(
            f"{decision_label}.attribute_choices must be a JSON "
            "array."
        )

    result = []
    seen = set()
    for index, item in enumerate(value):
        label = (
            f"{decision_label}.attribute_choices[{index}]"
        )
        _require_exact_mapping(
            item,
            BULK_COLLECTION_IMPORT_REVIEW_ATTRIBUTE_CHOICE_KEYS,
            label,
        )
        field = item["field"]
        if (
            not isinstance(field, str)
            or not field
            or field != field.strip()
        ):
            raise BulkCollectionImportReviewError(
                f"{label}.field must be a non-empty trimmed string."
            )
        if field in seen:
            raise BulkCollectionImportReviewError(
                f"{decision_label}.attribute_choices contains "
                f"a duplicate field: {field}"
            )
        seen.add(field)

        choice = _require_conflict_choice(
            item["choice"],
            f"{label}.choice",
        )
        result.append(
            BulkCollectionImportReviewAttributeChoice(
                field=field,
                choice=choice,
            )
        )

    return tuple(result)


def _optional_text(value: Any, label: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportReviewError(
            f"{label} must be null or a non-empty trimmed string."
        )
    return value


def _optional_choice(value: Any, label: str) -> str | None:
    if value is None:
        return None
    return _require_conflict_choice(value, label)


def _require_conflict_choice(value: Any, label: str) -> str:
    if value not in BULK_COLLECTION_IMPORT_REVIEW_CONFLICT_CHOICES:
        raise BulkCollectionImportReviewError(
            f"{label} must be keep_existing or use_imported."
        )
    return value


def _require_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or _SHA256_PATTERN.fullmatch(value) is None
    ):
        raise BulkCollectionImportReviewError(
            f"{label} must be a lowercase 64-character SHA-256."
        )
    return value


def _require_exact_mapping(
    value: Any,
    expected_keys: tuple[str, ...],
    label: str,
) -> None:
    if not isinstance(value, dict):
        raise BulkCollectionImportReviewError(
            f"{label} must be a JSON object."
        )

    expected = set(expected_keys)
    actual = set(value)
    if actual == expected:
        return

    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    details = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unexpected:
        details.append("unexpected: " + ", ".join(unexpected))
    raise BulkCollectionImportReviewError(
        f"{label} fields must match the review contract "
        f"({'; '.join(details)})."
    )


__all__ = [
    "BULK_COLLECTION_IMPORT_REVIEW_SCHEMA",
    "BULK_COLLECTION_IMPORT_REVIEW_VERSION",
    "BULK_COLLECTION_IMPORT_REVIEW_ACTIONS",
    "BULK_COLLECTION_IMPORT_REVIEW_CONFLICT_CHOICES",
    "BULK_COLLECTION_IMPORT_REVIEW_DOCUMENT_KEYS",
    "BULK_COLLECTION_IMPORT_REVIEW_DECISION_KEYS",
    "BULK_COLLECTION_IMPORT_REVIEW_ATTRIBUTE_CHOICE_KEYS",
    "BulkCollectionImportReviewError",
    "BulkCollectionImportReviewAttributeChoice",
    "BulkCollectionImportReviewDecision",
    "BulkCollectionImportReviewDecisions",
    "parse_bulk_collection_import_review_decisions",
    "bulk_collection_import_review_decisions_to_document",
    "serialize_bulk_collection_import_review_decisions",
]
