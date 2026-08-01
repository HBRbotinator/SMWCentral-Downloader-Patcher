"""Application model for the Collection-owned Wheel."""

from __future__ import annotations

import copy

from collection_wheel import CollectionWheelSelectionService
from planner_collection import PlannerCollectionProjection
from planner_query import PlannerCollectionQuery
from planner_store import PlannerStore


class CollectionWheelModel:
    """Build and select from Collection-owned Wheel pools."""

    def __init__(
        self,
        planner_store=None,
        *,
        projection=None,
        query=None,
        selection_service=None,
    ):
        self.planner_store = planner_store or PlannerStore()
        self.projection = projection or PlannerCollectionProjection(
            self.planner_store
        )
        self.query = query or PlannerCollectionQuery()
        self.selection_service = (
            selection_service or CollectionWheelSelectionService()
        )

    @property
    def planner_refinements_available(self):
        """Return whether saved/in-memory Planner data adds useful choices."""

        return bool(
            self.planner_store.get_entries()
            or self.planner_store.get_lists()
        )

    def available_filters(self, collection_records):
        """Return filter choices represented by the supplied Collection view."""

        projected = self._project(collection_records)
        return copy.deepcopy(self.query.available_filters(projected))

    def build_pool(
        self,
        collection_records,
        *,
        text="",
        lifecycle_statuses=None,
        planning_horizons=None,
        list_ids=None,
        list_match="any",
        difficulties=None,
        hack_types=None,
        downloaded=None,
        include_obsolete=True,
    ):
        """Return a detached Wheel pool in the supplied Collection order."""

        projected = self._project(collection_records)
        return self.query.query_collection(
            projected,
            text=text,
            lifecycle_statuses=lifecycle_statuses,
            planning_horizons=planning_horizons,
            list_ids=list_ids,
            list_match=list_match,
            difficulties=difficulties,
            hack_types=hack_types,
            downloaded=downloaded,
            include_obsolete=include_obsolete,
            sort_mode="collection",
        )

    def snapshot(self, collection_records, **filters):
        """Capture one reusable snapshot of the current Collection pool."""

        return self.selection_service.snapshot(
            self.build_pool(collection_records, **filters)
        )

    def spin(
        self,
        collection_records,
        *,
        excluded_ids=None,
        **filters,
    ):
        """Select one result from the current Collection-owned Wheel pool."""

        pool = self.snapshot(collection_records, **filters)
        return self.selection_service.select(
            pool,
            excluded_ids=excluded_ids,
        )

    def _project(self, collection_records):
        if collection_records is None:
            raise ValueError("Collection records are required")
        return self.projection.project_collection(collection_records)


__all__ = ["CollectionWheelModel"]
