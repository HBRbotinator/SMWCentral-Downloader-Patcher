"""Immutable second-round metadata review for bulk Collection imports."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from bulk_collection_import_resolution import (
    BULK_COLLECTION_IMPORT_RESOLUTION_ACTIONS,
    BULK_COLLECTION_IMPORT_RESOLUTION_SCHEMA,
    BULK_COLLECTION_IMPORT_RESOLUTION_VERSION,
    BulkCollectionImportResolutionAttributeChange,
    BulkCollectionImportResolutionConflict,
    BulkCollectionImportResolutionItem,
    BulkCollectionImportResolutionPlan,
    BulkCollectionImportResolutionSourceReference,
    bulk_collection_import_resolution_plan_to_document,
)


SECOND_REVIEW_FORM_SCHEMA = (
    "smwc-bulk-collection-second-review-form"
)
SECOND_REVIEW_FORM_VERSION = 1
SECOND_REVIEW_DECISION_SCHEMA = (
    "smwc-bulk-collection-second-review-decisions"
)
SECOND_REVIEW_DECISION_VERSION = 1

SECOND_REVIEW_ACTIONS = (
    "resolve_metadata",
    "skip",
)
SECOND_REVIEW_CONFLICT_CHOICES = (
    "keep_existing",
    "use_imported",
)

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class BulkCollectionImportSecondReviewError(ValueError):
    """Raised when follow-up metadata review cannot be handled safely."""


@dataclass(frozen=True, slots=True)
class BulkCollectionImportSecondReviewSourceReference:
    """One safe source-reference addition already planned in round one."""

    source: str
    external_id: str


@dataclass(frozen=True, slots=True)
class BulkCollectionImportSecondReviewAttributeChange:
    """One safe shared-metadata addition already planned in round one."""

    field: str
    value: Any


@dataclass(frozen=True, slots=True)
class BulkCollectionImportSecondReviewConflict:
    """One newly exposed metadata conflict requiring an explicit choice."""

    field: str
    existing_value: Any
    imported_value: Any
    selected_choice: str | None = None


@dataclass(frozen=True, slots=True)
class BulkCollectionImportSecondReviewItem:
    """One selected existing record blocked by newly exposed metadata."""

    entry_key: str
    collection_key: str
    allowed_actions: tuple[str, ...]
    source_reference_additions: tuple[
        BulkCollectionImportSecondReviewSourceReference,
        ...,
    ]
    attribute_changes: tuple[
        BulkCollectionImportSecondReviewAttributeChange,
        ...,
    ]
    conflicts: tuple[
        BulkCollectionImportSecondReviewConflict,
        ...,
    ]
    selected_action: str | None = None


@dataclass(frozen=True, slots=True)
class BulkCollectionImportSecondReviewForm:
    """Immutable second-round requirements bound to one resolution state."""

    schema: str
    version: int
    import_id: str
    source_sha256: str
    resolution_review_sha256: str
    items: tuple[BulkCollectionImportSecondReviewItem, ...]


def build_bulk_collection_import_second_review_form(
    resolution_plan: BulkCollectionImportResolutionPlan,
) -> BulkCollectionImportSecondReviewForm:
    """Project newly blocked resolution rows into metadata-only review."""

    _require_resolution_plan(resolution_plan)

    blocked = tuple(
        item
        for item in resolution_plan.items
        if item.action == "review_required"
    )
    if len(blocked) != resolution_plan.summary["review_required"]:
        raise BulkCollectionImportSecondReviewError(
            "Resolution summary does not match review-required rows."
        )

    items = tuple(_build_form_item(item) for item in blocked)
    fingerprint = _resolution_review_sha256(resolution_plan)

    return BulkCollectionImportSecondReviewForm(
        schema=SECOND_REVIEW_FORM_SCHEMA,
        version=SECOND_REVIEW_FORM_VERSION,
        import_id=_require_text(
            resolution_plan.import_id,
            "resolution import_id",
        ),
        source_sha256=_require_sha256(
            resolution_plan.source_sha256,
            "resolution source_sha256",
        ),
        resolution_review_sha256=fingerprint,
        items=items,
    )


def bulk_collection_import_second_review_form_to_document(
    form: BulkCollectionImportSecondReviewForm,
) -> dict[str, Any]:
    """Project immutable follow-up requirements to detached UI state."""

    _require_form(form)

    return {
        "schema": form.schema,
        "version": form.version,
        "import_id": form.import_id,
        "source_sha256": form.source_sha256,
        "resolution_review_sha256": form.resolution_review_sha256,
        "items": [
            {
                "entry_key": item.entry_key,
                "collection_key": item.collection_key,
                "allowed_actions": list(item.allowed_actions),
                "source_reference_additions": [
                    {
                        "source": reference.source,
                        "external_id": reference.external_id,
                    }
                    for reference
                    in item.source_reference_additions
                ],
                "attribute_changes": [
                    {
                        "field": change.field,
                        "value": _thaw_json(change.value),
                    }
                    for change in item.attribute_changes
                ],
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
            }
            for item in form.items
        ],
    }


def build_bulk_collection_import_second_review_document(
    form: BulkCollectionImportSecondReviewForm,
    selections: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate explicit follow-up choices and bind them to the form."""

    _require_form(form)
    if not isinstance(selections, Mapping):
        raise BulkCollectionImportSecondReviewError(
            "selections must be a mapping keyed by entry_key."
        )

    expected_keys = tuple(item.entry_key for item in form.items)
    if set(selections) != set(expected_keys):
        missing = sorted(set(expected_keys) - set(selections))
        unexpected = sorted(set(selections) - set(expected_keys))
        detail = _coverage_detail(missing, unexpected)
        raise BulkCollectionImportSecondReviewError(
            "Second-round selections must cover every blocked row "
            f"exactly once{detail}."
        )

    decisions = [
        _build_decision(item, selections[item.entry_key])
        for item in form.items
    ]

    return {
        "schema": SECOND_REVIEW_DECISION_SCHEMA,
        "version": SECOND_REVIEW_DECISION_VERSION,
        "import_id": form.import_id,
        "source_sha256": form.source_sha256,
        "resolution_review_sha256": form.resolution_review_sha256,
        "decisions": decisions,
    }


def refine_bulk_collection_import_resolution_plan(
    resolution_plan: BulkCollectionImportResolutionPlan,
    decision_document: Mapping[str, Any],
) -> BulkCollectionImportResolutionPlan:
    """Apply only bound metadata choices to an immutable resolution plan."""

    _require_resolution_plan(resolution_plan)
    document = _parse_decision_document(decision_document)

    if document["import_id"] != resolution_plan.import_id:
        raise BulkCollectionImportSecondReviewError(
            "Second-round decisions do not match resolution import_id."
        )
    if document["source_sha256"] != resolution_plan.source_sha256:
        raise BulkCollectionImportSecondReviewError(
            "Second-round decisions do not match resolution source."
        )

    expected_fingerprint = _resolution_review_sha256(
        resolution_plan
    )
    if (
        document["resolution_review_sha256"]
        != expected_fingerprint
    ):
        raise BulkCollectionImportSecondReviewError(
            "Second-round decisions are stale for the current "
            "resolution review state."
        )

    blocked = tuple(
        item
        for item in resolution_plan.items
        if item.action == "review_required"
    )
    expected_keys = tuple(item.entry_key for item in blocked)
    actual_keys = tuple(
        decision["entry_key"]
        for decision in document["decisions"]
    )
    if actual_keys != expected_keys:
        raise BulkCollectionImportSecondReviewError(
            "Second-round decisions must exactly cover newly blocked "
            "rows in resolution order."
        )

    decision_index = {
        decision["entry_key"]: decision
        for decision in document["decisions"]
    }

    refined_items = []
    for item in resolution_plan.items:
        if item.action != "review_required":
            refined_items.append(item)
            continue

        refined_items.append(
            _refine_item(
                item,
                decision_index[item.entry_key],
            )
        )

    summary_values = {
        action: sum(
            item.action == action
            for item in refined_items
        )
        for action in BULK_COLLECTION_IMPORT_RESOLUTION_ACTIONS
    }
    summary = MappingProxyType(
        {
            "total": len(refined_items),
            **summary_values,
        }
    )

    return BulkCollectionImportResolutionPlan(
        schema=resolution_plan.schema,
        version=resolution_plan.version,
        import_id=resolution_plan.import_id,
        source_sha256=resolution_plan.source_sha256,
        summary=summary,
        items=tuple(refined_items),
        groups=resolution_plan.groups,
    )


def serialize_bulk_collection_import_second_review_document(
    document: Mapping[str, Any],
) -> str:
    """Serialize one validated second-round decision document."""

    parsed = _parse_decision_document(document)
    return json.dumps(
        parsed,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _build_form_item(
    item: BulkCollectionImportResolutionItem,
) -> BulkCollectionImportSecondReviewItem:
    if item.action != "review_required":
        raise BulkCollectionImportSecondReviewError(
            "Second-round form items must be review_required."
        )

    entry_key = _require_text(item.entry_key, "entry_key")
    collection_key = _require_text(
        item.collection_key,
        f"{entry_key} collection_key",
    )
    if item.title_value is not None:
        raise BulkCollectionImportSecondReviewError(
            f"{entry_key} review-required row cannot already carry "
            "a title update."
        )
    if item.attributes:
        raise BulkCollectionImportSecondReviewError(
            f"{entry_key} review-required row cannot carry a create "
            "attribute payload."
        )
    if tuple(item.warnings) != ("metadata_conflict",):
        raise BulkCollectionImportSecondReviewError(
            f"{entry_key} second-round review must be metadata-only."
        )
    if not item.conflicts:
        raise BulkCollectionImportSecondReviewError(
            f"{entry_key} second-round review requires conflicts."
        )

    source_additions = tuple(
        _copy_source_reference(reference)
        for reference in item.source_reference_additions
    )
    attribute_changes = tuple(
        _copy_attribute_change(change)
        for change in item.attribute_changes
    )
    conflicts = tuple(
        _copy_conflict(conflict)
        for conflict in item.conflicts
    )

    conflict_fields = tuple(
        conflict.field for conflict in conflicts
    )
    if len(conflict_fields) != len(set(conflict_fields)):
        raise BulkCollectionImportSecondReviewError(
            f"{entry_key} conflict fields must be unique."
        )

    safe_fields = tuple(
        change.field for change in attribute_changes
    )
    if len(safe_fields) != len(set(safe_fields)):
        raise BulkCollectionImportSecondReviewError(
            f"{entry_key} pending attribute fields must be unique."
        )
    if set(safe_fields).intersection(conflict_fields):
        raise BulkCollectionImportSecondReviewError(
            f"{entry_key} cannot contain the same field as both a "
            "safe change and a conflict."
        )

    return BulkCollectionImportSecondReviewItem(
        entry_key=entry_key,
        collection_key=collection_key,
        allowed_actions=SECOND_REVIEW_ACTIONS,
        source_reference_additions=source_additions,
        attribute_changes=attribute_changes,
        conflicts=conflicts,
    )


def _build_decision(
    item: BulkCollectionImportSecondReviewItem,
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(selection, Mapping):
        raise BulkCollectionImportSecondReviewError(
            f"Selection for {item.entry_key} must be a mapping."
        )

    action = selection.get("action")
    if action not in item.allowed_actions:
        raise BulkCollectionImportSecondReviewError(
            f"Action {action!r} is not allowed for "
            f"{item.entry_key}."
        )

    if action == "skip":
        _require_exact_keys(
            selection,
            ("action",),
            f"{item.entry_key} skip selection",
        )
        return _decision(
            item,
            action="skip",
        )

    _require_exact_keys(
        selection,
        ("action", "choices"),
        f"{item.entry_key} metadata selection",
    )
    choices = selection["choices"]
    if not isinstance(choices, Mapping):
        raise BulkCollectionImportSecondReviewError(
            f"{item.entry_key} metadata choices must be a mapping."
        )

    expected_fields = tuple(
        conflict.field for conflict in item.conflicts
    )
    if set(choices) != set(expected_fields):
        missing = sorted(set(expected_fields) - set(choices))
        unexpected = sorted(set(choices) - set(expected_fields))
        detail = _coverage_detail(missing, unexpected)
        raise BulkCollectionImportSecondReviewError(
            f"{item.entry_key} must resolve every second-round "
            f"metadata conflict{detail}."
        )

    title_choice = None
    attribute_choices = []
    for conflict in item.conflicts:
        choice = choices[conflict.field]
        if choice not in SECOND_REVIEW_CONFLICT_CHOICES:
            raise BulkCollectionImportSecondReviewError(
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

    return _decision(
        item,
        action="resolve_metadata",
        title_choice=title_choice,
        attribute_choices=attribute_choices,
    )


def _decision(
    item: BulkCollectionImportSecondReviewItem,
    *,
    action: str,
    title_choice: str | None = None,
    attribute_choices: Sequence[Mapping[str, str]] = (),
) -> dict[str, Any]:
    return {
        "entry_key": item.entry_key,
        "action": action,
        "collection_key": item.collection_key,
        "title_choice": title_choice,
        "attribute_choices": [
            dict(value)
            for value in attribute_choices
        ],
    }


def _refine_item(
    item: BulkCollectionImportResolutionItem,
    decision: Mapping[str, Any],
) -> BulkCollectionImportResolutionItem:
    form_item = _build_form_item(item)

    if decision["collection_key"] != form_item.collection_key:
        raise BulkCollectionImportSecondReviewError(
            f"{item.entry_key} second-round decision changed the "
            "selected Collection target."
        )

    action = decision["action"]
    if action == "skip":
        return BulkCollectionImportResolutionItem(
            entry_key=item.entry_key,
            action="skip",
            collection_key=form_item.collection_key,
            title_value=None,
            source_reference_additions=(),
            attributes=MappingProxyType({}),
            attribute_changes=(),
            conflicts=(),
            warnings=item.warnings,
        )

    if action != "resolve_metadata":
        raise BulkCollectionImportSecondReviewError(
            f"Unsupported second-round action for {item.entry_key}."
        )

    title_choice = decision["title_choice"]
    attribute_choices = {
        value["field"]: value["choice"]
        for value in decision["attribute_choices"]
    }

    title_value = None
    changes = list(item.attribute_changes)
    expected_attribute_conflicts = []

    for conflict in item.conflicts:
        if conflict.field == "title":
            if title_choice == "use_imported":
                title_value = _require_text(
                    conflict.imported_value,
                    f"{item.entry_key} imported title",
                )
            elif title_choice != "keep_existing":
                raise BulkCollectionImportSecondReviewError(
                    f"{item.entry_key} title conflict requires an "
                    "explicit choice."
                )
            continue

        expected_attribute_conflicts.append(conflict.field)
        choice = attribute_choices.get(conflict.field)
        if choice == "use_imported":
            changes.append(
                BulkCollectionImportResolutionAttributeChange(
                    field=conflict.field,
                    value=conflict.imported_value,
                )
            )
        elif choice != "keep_existing":
            raise BulkCollectionImportSecondReviewError(
                f"{item.entry_key} conflict {conflict.field} "
                "requires an explicit choice."
            )

    if tuple(attribute_choices) != tuple(
        expected_attribute_conflicts
    ):
        raise BulkCollectionImportSecondReviewError(
            f"{item.entry_key} attribute choices must exactly "
            "follow conflict order."
        )

    has_update = bool(
        title_value is not None
        or item.source_reference_additions
        or item.attribute_changes
        or any(
            value["choice"] == "use_imported"
            for value in decision["attribute_choices"]
        )
    )

    return BulkCollectionImportResolutionItem(
        entry_key=item.entry_key,
        action="update_record" if has_update else "no_change",
        collection_key=form_item.collection_key,
        title_value=title_value,
        source_reference_additions=item.source_reference_additions,
        attributes=MappingProxyType({}),
        attribute_changes=tuple(changes),
        conflicts=(),
        warnings=(),
    )


def _resolution_review_sha256(
    resolution_plan: BulkCollectionImportResolutionPlan,
) -> str:
    document = bulk_collection_import_resolution_plan_to_document(
        resolution_plan
    )
    blocked = [
        item
        for item in document["items"]
        if item["action"] == "review_required"
    ]
    payload = {
        "resolution_schema": document["schema"],
        "resolution_version": document["version"],
        "import_id": document["import_id"],
        "source_sha256": document["source_sha256"],
        "items": blocked,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


def _parse_decision_document(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportSecondReviewError(
            "Second-round decision document must be a mapping."
        )

    _require_exact_keys(
        value,
        (
            "schema",
            "version",
            "import_id",
            "source_sha256",
            "resolution_review_sha256",
            "decisions",
        ),
        "second-round decision document",
    )
    if value["schema"] != SECOND_REVIEW_DECISION_SCHEMA:
        raise BulkCollectionImportSecondReviewError(
            "Second-round decision schema is not supported."
        )
    if value["version"] != SECOND_REVIEW_DECISION_VERSION:
        raise BulkCollectionImportSecondReviewError(
            "Second-round decision version is not supported."
        )

    import_id = _require_text(
        value["import_id"],
        "second-round import_id",
    )
    source_sha256 = _require_sha256(
        value["source_sha256"],
        "second-round source_sha256",
    )
    review_sha256 = _require_sha256(
        value["resolution_review_sha256"],
        "resolution_review_sha256",
    )

    raw_decisions = value["decisions"]
    if not isinstance(raw_decisions, list):
        raise BulkCollectionImportSecondReviewError(
            "Second-round decisions must be a list."
        )

    decisions = []
    seen = set()
    for raw in raw_decisions:
        if not isinstance(raw, Mapping):
            raise BulkCollectionImportSecondReviewError(
                "Every second-round decision must be a mapping."
            )
        _require_exact_keys(
            raw,
            (
                "entry_key",
                "action",
                "collection_key",
                "title_choice",
                "attribute_choices",
            ),
            "second-round decision",
        )

        entry_key = _require_text(
            raw["entry_key"],
            "second-round decision entry_key",
        )
        if entry_key in seen:
            raise BulkCollectionImportSecondReviewError(
                "Second-round decision entry keys must be unique."
            )
        seen.add(entry_key)

        action = raw["action"]
        if action not in SECOND_REVIEW_ACTIONS:
            raise BulkCollectionImportSecondReviewError(
                f"Unsupported second-round action: {action!r}"
            )

        collection_key = _require_text(
            raw["collection_key"],
            f"{entry_key} collection_key",
        )
        title_choice = raw["title_choice"]
        if (
            title_choice is not None
            and title_choice
            not in SECOND_REVIEW_CONFLICT_CHOICES
        ):
            raise BulkCollectionImportSecondReviewError(
                f"{entry_key} title_choice is not supported."
            )

        raw_attributes = raw["attribute_choices"]
        if not isinstance(raw_attributes, list):
            raise BulkCollectionImportSecondReviewError(
                f"{entry_key} attribute_choices must be a list."
            )
        attribute_choices = []
        attribute_fields = set()
        for raw_choice in raw_attributes:
            if not isinstance(raw_choice, Mapping):
                raise BulkCollectionImportSecondReviewError(
                    f"{entry_key} attribute choice must be a mapping."
                )
            _require_exact_keys(
                raw_choice,
                ("field", "choice"),
                f"{entry_key} attribute choice",
            )
            field = _require_text(
                raw_choice["field"],
                f"{entry_key} attribute choice field",
            )
            if field in attribute_fields:
                raise BulkCollectionImportSecondReviewError(
                    f"{entry_key} attribute choices must be unique."
                )
            attribute_fields.add(field)
            choice = raw_choice["choice"]
            if choice not in SECOND_REVIEW_CONFLICT_CHOICES:
                raise BulkCollectionImportSecondReviewError(
                    f"{entry_key} attribute choice is not supported."
                )
            attribute_choices.append(
                {
                    "field": field,
                    "choice": choice,
                }
            )

        if action == "skip":
            if title_choice is not None or attribute_choices:
                raise BulkCollectionImportSecondReviewError(
                    f"{entry_key} Skip cannot carry metadata choices."
                )

        decisions.append(
            {
                "entry_key": entry_key,
                "action": action,
                "collection_key": collection_key,
                "title_choice": title_choice,
                "attribute_choices": attribute_choices,
            }
        )

    return {
        "schema": SECOND_REVIEW_DECISION_SCHEMA,
        "version": SECOND_REVIEW_DECISION_VERSION,
        "import_id": import_id,
        "source_sha256": source_sha256,
        "resolution_review_sha256": review_sha256,
        "decisions": decisions,
    }


def _require_resolution_plan(
    plan: BulkCollectionImportResolutionPlan,
) -> None:
    if not isinstance(
        plan,
        BulkCollectionImportResolutionPlan,
    ):
        raise TypeError(
            "resolution_plan must be BulkCollectionImportResolutionPlan"
        )
    if plan.schema != BULK_COLLECTION_IMPORT_RESOLUTION_SCHEMA:
        raise BulkCollectionImportSecondReviewError(
            "Resolution plan schema is not supported."
        )
    if plan.version != BULK_COLLECTION_IMPORT_RESOLUTION_VERSION:
        raise BulkCollectionImportSecondReviewError(
            "Resolution plan version is not supported."
        )

    _require_text(plan.import_id, "resolution import_id")
    _require_sha256(
        plan.source_sha256,
        "resolution source_sha256",
    )

    item_keys = tuple(
        _require_text(item.entry_key, "resolution entry_key")
        for item in plan.items
    )
    if len(item_keys) != len(set(item_keys)):
        raise BulkCollectionImportSecondReviewError(
            "Resolution entry keys must be unique."
        )

    if plan.summary["total"] != len(plan.items):
        raise BulkCollectionImportSecondReviewError(
            "Resolution summary total does not match item count."
        )
    for action in BULK_COLLECTION_IMPORT_RESOLUTION_ACTIONS:
        expected = sum(
            item.action == action
            for item in plan.items
        )
        if plan.summary[action] != expected:
            raise BulkCollectionImportSecondReviewError(
                f"Resolution summary for {action} is inconsistent."
            )


def _require_form(form: BulkCollectionImportSecondReviewForm) -> None:
    if not isinstance(
        form,
        BulkCollectionImportSecondReviewForm,
    ):
        raise TypeError(
            "form must be BulkCollectionImportSecondReviewForm"
        )
    if form.schema != SECOND_REVIEW_FORM_SCHEMA:
        raise BulkCollectionImportSecondReviewError(
            "Second-review form schema is not supported."
        )
    if form.version != SECOND_REVIEW_FORM_VERSION:
        raise BulkCollectionImportSecondReviewError(
            "Second-review form version is not supported."
        )
    _require_text(form.import_id, "second-review form import_id")
    _require_sha256(
        form.source_sha256,
        "second-review form source_sha256",
    )
    _require_sha256(
        form.resolution_review_sha256,
        "resolution_review_sha256",
    )


def _copy_source_reference(
    value: BulkCollectionImportResolutionSourceReference,
) -> BulkCollectionImportSecondReviewSourceReference:
    if not isinstance(
        value,
        BulkCollectionImportResolutionSourceReference,
    ):
        raise BulkCollectionImportSecondReviewError(
            "Pending source reference has an invalid type."
        )
    return BulkCollectionImportSecondReviewSourceReference(
        source=_require_text(value.source, "source"),
        external_id=_require_text(
            value.external_id,
            "external_id",
        ),
    )


def _copy_attribute_change(
    value: BulkCollectionImportResolutionAttributeChange,
) -> BulkCollectionImportSecondReviewAttributeChange:
    if not isinstance(
        value,
        BulkCollectionImportResolutionAttributeChange,
    ):
        raise BulkCollectionImportSecondReviewError(
            "Pending attribute change has an invalid type."
        )
    return BulkCollectionImportSecondReviewAttributeChange(
        field=_require_text(value.field, "attribute field"),
        value=_freeze_json(value.value),
    )


def _copy_conflict(
    value: BulkCollectionImportResolutionConflict,
) -> BulkCollectionImportSecondReviewConflict:
    if not isinstance(
        value,
        BulkCollectionImportResolutionConflict,
    ):
        raise BulkCollectionImportSecondReviewError(
            "Resolution conflict has an invalid type."
        )
    return BulkCollectionImportSecondReviewConflict(
        field=_require_text(value.field, "conflict field"),
        existing_value=_freeze_json(value.existing_value),
        imported_value=_freeze_json(value.imported_value),
    )


def _coverage_detail(
    missing: Sequence[str],
    unexpected: Sequence[str],
) -> str:
    details = []
    if missing:
        details.append("missing: " + ", ".join(missing))
    if unexpected:
        details.append("unexpected: " + ", ".join(unexpected))
    return f" ({'; '.join(details)})" if details else ""


def _require_exact_keys(
    value: Mapping[str, Any],
    expected: Sequence[str],
    label: str,
) -> None:
    if set(value) != set(expected):
        raise BulkCollectionImportSecondReviewError(
            f"{label} fields do not match the contract."
        )


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportSecondReviewError(
            f"{label} must be a non-empty trimmed string."
        )
    return value


def _require_sha256(value: Any, label: str) -> str:
    text = _require_text(value, label)
    if not _SHA256_PATTERN.fullmatch(text):
        raise BulkCollectionImportSecondReviewError(
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
    "SECOND_REVIEW_FORM_SCHEMA",
    "SECOND_REVIEW_FORM_VERSION",
    "SECOND_REVIEW_DECISION_SCHEMA",
    "SECOND_REVIEW_DECISION_VERSION",
    "SECOND_REVIEW_ACTIONS",
    "SECOND_REVIEW_CONFLICT_CHOICES",
    "BulkCollectionImportSecondReviewError",
    "BulkCollectionImportSecondReviewSourceReference",
    "BulkCollectionImportSecondReviewAttributeChange",
    "BulkCollectionImportSecondReviewConflict",
    "BulkCollectionImportSecondReviewItem",
    "BulkCollectionImportSecondReviewForm",
    "build_bulk_collection_import_second_review_form",
    "bulk_collection_import_second_review_form_to_document",
    "build_bulk_collection_import_second_review_document",
    "refine_bulk_collection_import_resolution_plan",
    "serialize_bulk_collection_import_second_review_document",
]
