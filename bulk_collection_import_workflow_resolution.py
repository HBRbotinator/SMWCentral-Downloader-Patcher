"""Fresh post-review resolution planning for v5.1 Collection imports."""

from __future__ import annotations

from typing import Any, Mapping

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
from bulk_collection_import_resolution import (
    BulkCollectionImportResolutionPlan,
    build_bulk_collection_import_resolution_plan,
)
from bulk_collection_import_review import (
    BULK_COLLECTION_IMPORT_REVIEW_SCHEMA,
    BULK_COLLECTION_IMPORT_REVIEW_VERSION,
)
from hack_data_manager import HackDataManager


class BulkCollectionImportWorkflowResolutionError(ValueError):
    """Raised when a validated review cannot be resolved safely."""


def resolve_v5_1_bulk_collection_import_review(
    path: str,
    data_manager: HackDataManager,
    review_document: Mapping[str, Any],
) -> BulkCollectionImportResolutionPlan:
    """Replan the source against live Collection state, then resolve review."""

    if not isinstance(data_manager, HackDataManager):
        raise TypeError("data_manager must be a HackDataManager")

    review = _validate_review_document(review_document)

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

    if review["import_id"] != planning.document.import_id:
        raise BulkCollectionImportWorkflowResolutionError(
            "The reviewed import_id no longer matches the selected file."
        )
    if review["source_sha256"] != planning.sha256:
        raise BulkCollectionImportWorkflowResolutionError(
            "The selected import file changed after the review preview "
            "was created."
        )

    import_document = bulk_collection_import_to_document(
        planning.document
    )
    merge_document = bulk_collection_import_merge_plan_to_document(
        planning.merge_plan
    )

    import_entries = {
        entry["entry_key"]: entry
        for entry in import_document["entries"]
    }

    try:
        return build_bulk_collection_import_resolution_plan(
            import_entries=import_entries,
            merge_items=merge_document["items"],
            review_decisions=review["decisions"],
            collection_records=records,
            groups=import_document["groups"],
            import_id=planning.document.import_id,
            source_sha256=planning.sha256,
        )
    except Exception as error:
        raise BulkCollectionImportWorkflowResolutionError(
            "The review no longer matches the fresh import/Collection "
            f"planning state: {error}"
        ) from error


def _validate_review_document(
    value: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise BulkCollectionImportWorkflowResolutionError(
            "review_document must be a mapping."
        )

    expected = {
        "schema",
        "version",
        "import_id",
        "source_sha256",
        "decisions",
    }
    if set(value) != expected:
        raise BulkCollectionImportWorkflowResolutionError(
            "review_document fields do not match the review contract."
        )
    if value["schema"] != BULK_COLLECTION_IMPORT_REVIEW_SCHEMA:
        raise BulkCollectionImportWorkflowResolutionError(
            "review_document schema is not supported."
        )
    if value["version"] != BULK_COLLECTION_IMPORT_REVIEW_VERSION:
        raise BulkCollectionImportWorkflowResolutionError(
            "review_document version is not supported."
        )

    import_id = _require_text(value["import_id"], "review import_id")
    source_sha256 = _require_sha256(
        value["source_sha256"],
        "review source_sha256",
    )
    decisions = value["decisions"]
    if not isinstance(decisions, list):
        raise BulkCollectionImportWorkflowResolutionError(
            "review decisions must be a list."
        )
    if any(not isinstance(item, Mapping) for item in decisions):
        raise BulkCollectionImportWorkflowResolutionError(
            "every review decision must be a mapping."
        )

    return {
        "schema": value["schema"],
        "version": value["version"],
        "import_id": import_id,
        "source_sha256": source_sha256,
        "decisions": [dict(item) for item in decisions],
    }


def _require_text(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
    ):
        raise BulkCollectionImportWorkflowResolutionError(
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
        raise BulkCollectionImportWorkflowResolutionError(
            f"{label} must be a lowercase 64-character SHA-256."
        )
    return text


__all__ = [
    "BulkCollectionImportWorkflowResolutionError",
    "resolve_v5_1_bulk_collection_import_review",
]
