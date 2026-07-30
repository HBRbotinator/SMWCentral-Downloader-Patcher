"""Read-only presentation model for the Planner page."""

from __future__ import annotations

import copy

from planner_collection import PlannerCollectionProjection
from planner_query import PlannerCollectionQuery


class PlannerPageModel:
    """Prepare collection and Planner data for a read-only table."""

    def __init__(
        self,
        data_manager,
        planner_store,
        projection=None,
        query=None,
    ):
        self.data_manager = data_manager
        self.planner_store = planner_store
        self.projection = projection or PlannerCollectionProjection(
            planner_store
        )
        self.query = query or PlannerCollectionQuery()
        self.projected_hacks = []

    def refresh(self):
        """Rebuild the projection from current in-memory source data."""
        hacks = self.data_manager.get_all_hacks(include_obsolete=True)
        self.projected_hacks = self.projection.project_collection(hacks)
        return copy.deepcopy(self.projected_hacks)

    def reload_planner(self):
        """Reload Planner persistence, then rebuild the projection."""
        self.planner_store.reload()
        return self.refresh()

    def available_filters(self):
        """Return filter choices represented by the current projection."""
        return self.query.available_filters(self.projected_hacks)

    def visible_hacks(
        self,
        *,
        text="",
        lifecycle_status="",
        planning_horizon="",
        list_id="",
        downloaded="any",
        sort_mode="planning",
    ):
        """Return table records matching the page's current controls."""
        download_filter = self._download_filter(downloaded)
        return self.query.query_collection(
            self.projected_hacks,
            text=text,
            lifecycle_statuses=self._optional_value(lifecycle_status),
            planning_horizons=self._optional_value(planning_horizon),
            list_ids=self._optional_value(list_id),
            downloaded=download_filter,
            sort_mode=sort_mode,
        )

    @staticmethod
    def table_values(record):
        """Convert one projected record into stable table display values."""
        position = record.get("planner_next_position")
        if record.get("planner_horizon") != "Next":
            position = ""
        elif isinstance(position, int):
            position = str(position)
        else:
            position = ""

        hack_types = record.get("hack_types", [])
        if not isinstance(hack_types, (list, tuple)):
            hack_types = []
        type_text = ", ".join(
            str(value).strip().title()
            for value in hack_types
            if str(value).strip()
        )
        if not type_text:
            type_text = str(record.get("hack_type", "")).strip().title()

        list_names = record.get("planner_list_names", [])
        if not isinstance(list_names, (list, tuple)):
            list_names = []

        return (
            position,
            str(record.get("title", "")),
            str(record.get("planner_lifecycle_status", "")),
            str(record.get("planner_horizon", "")),
            ", ".join(str(name) for name in list_names),
            str(record.get("difficulty", "")),
            type_text,
        )

    @staticmethod
    def _optional_value(value):
        value = str(value).strip()
        return [value] if value else None

    @staticmethod
    def _download_filter(value):
        normalized = str(value).strip().casefold()
        if normalized in ("", "any"):
            return None
        if normalized == "downloaded":
            return True
        if normalized == "not downloaded":
            return False
        raise ValueError(f"Unknown downloaded filter: {value}")
