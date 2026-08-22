"""Read-only final application preview for v5.1 bulk Collection imports."""

from __future__ import annotations

from typing import Any, Mapping

from bulk_collection_import_application import (
    BulkCollectionImportApplicationPlan,
    bulk_collection_import_application_plan_to_document,
    serialize_bulk_collection_import_application_plan,
)
from bulk_collection_import_collection_adapter import (
    bulk_collection_import_collection_records_to_documents,
    project_bulk_collection_import_collection,
    project_bulk_collection_import_hack_data_manager,
)
from bulk_collection_import_key_allocation import (
    build_v5_1_bulk_collection_import_application_plan,
)
from bulk_collection_import_resolution import (
    BulkCollectionImportResolutionPlan,
    bulk_collection_import_resolution_plan_to_document,
)


class BulkCollectionImportApplicationPreviewError(ValueError):
    """Raised when a final read-only application preview is unsafe."""


def build_bulk_collection_import_application_preview(
    resolution_plan: BulkCollectionImportResolutionPlan,
    collection: Mapping[str, Mapping[str, Any]],
) -> BulkCollectionImportApplicationPlan:
    """Build the final application plan from detached Collection data."""

    _require_fully_resolved(resolution_plan)

    try:
        projection = project_bulk_collection_import_collection(
            collection
        )
        collection_records = (
            bulk_collection_import_collection_records_to_documents(
                projection
            )
        )
        resolution_document = (
            bulk_collection_import_resolution_plan_to_document(
                resolution_plan
            )
        )
        return build_v5_1_bulk_collection_import_application_plan(
            resolution_document,
            collection_records,
        )
    except BulkCollectionImportApplicationPreviewError:
        raise
    except Exception as error:
        raise BulkCollectionImportApplicationPreviewError(
            "Unable to build the final bulk-import application "
            f"preview safely: {error}"
        ) from error


def build_v5_1_bulk_collection_import_application_preview(
    resolution_plan: BulkCollectionImportResolutionPlan,
    data_manager: Any,
) -> BulkCollectionImportApplicationPlan:
    """Build the final preview against the live v5.1 HackDataManager."""

    _require_fully_resolved(resolution_plan)

    try:
        projection = project_bulk_collection_import_hack_data_manager(
            data_manager
        )
        collection_records = (
            bulk_collection_import_collection_records_to_documents(
                projection
            )
        )
        resolution_document = (
            bulk_collection_import_resolution_plan_to_document(
                resolution_plan
            )
        )
        return build_v5_1_bulk_collection_import_application_plan(
            resolution_document,
            collection_records,
        )
    except BulkCollectionImportApplicationPreviewError:
        raise
    except Exception as error:
        raise BulkCollectionImportApplicationPreviewError(
            "Unable to build the final live Collection application "
            f"preview safely: {error}"
        ) from error


def bulk_collection_import_application_preview_to_document(
    preview: BulkCollectionImportApplicationPlan,
) -> dict[str, Any]:
    """Project the immutable final preview to detached canonical JSON."""

    return bulk_collection_import_application_plan_to_document(
        preview
    )


def serialize_bulk_collection_import_application_preview(
    preview: BulkCollectionImportApplicationPlan,
) -> str:
    """Serialize the final read-only preview deterministically."""

    return serialize_bulk_collection_import_application_plan(
        preview
    )


def _require_fully_resolved(
    resolution_plan: BulkCollectionImportResolutionPlan,
) -> None:
    if not isinstance(
        resolution_plan,
        BulkCollectionImportResolutionPlan,
    ):
        raise TypeError(
            "resolution_plan must be BulkCollectionImportResolutionPlan"
        )

    try:
        review_count = resolution_plan.summary["review_required"]
    except Exception as error:
        raise BulkCollectionImportApplicationPreviewError(
            "Resolution plan is missing its review_required summary."
        ) from error

    if type(review_count) is not int or review_count < 0:
        raise BulkCollectionImportApplicationPreviewError(
            "Resolution review_required summary must be "
            "a non-negative integer."
        )

    actual_review_count = sum(
        item.action == "review_required"
        for item in resolution_plan.items
    )
    if review_count != actual_review_count:
        raise BulkCollectionImportApplicationPreviewError(
            "Resolution review_required summary does not match "
            "its items."
        )
    if review_count:
        raise BulkCollectionImportApplicationPreviewError(
            "All bulk-import review rounds must be complete before "
            "the application preview is built."
        )


__all__ = [
    "BulkCollectionImportApplicationPreviewError",
    "build_bulk_collection_import_application_preview",
    "build_v5_1_bulk_collection_import_application_preview",
    "bulk_collection_import_application_preview_to_document",
    "serialize_bulk_collection_import_application_preview",
]
