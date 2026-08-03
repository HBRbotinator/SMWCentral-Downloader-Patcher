"""Application model for the Collection-owned Wheel."""

from __future__ import annotations

import copy
import math
from datetime import datetime

from collection_wheel import CollectionWheelSelectionService
from planner_collection import PlannerCollectionProjection
from planner_query import PlannerCollectionQuery
from planner_store import PlannerStore


SMWC_RATING_THRESHOLDS = (1.0, 2.0, 3.0, 4.0, 4.5, 5.0)


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
        """Return whether explicit Planner entries or lists exist."""

        return bool(
            self.planner_store.get_entries()
            or self.planner_store.get_lists()
        )

    def reload_planner_state(self):
        """Refresh saved Planner data when this model has no staged edits."""

        if not self.planner_store.unsaved_changes:
            self.planner_store.reload()

    def available_filters(self, collection_records):
        """Return stable choices represented by the full Collection."""

        projected = self._project(collection_records)
        choices = copy.deepcopy(self.query.available_filters(projected))
        choices["lists"] = copy.deepcopy(self.planner_store.get_lists())

        completion_states = {
            bool(record.get("completed", False))
            for record in projected
        }
        ratings = [self._smwc_rating(record) for record in projected]
        release_years = {
            year
            for record in projected
            if (year := self._release_year(record)) is not None
        }
        download_states = {
            self._has_recorded_download(record)
            for record in projected
        }

        choices.update(
            {
                "completion_states": [
                    value
                    for value in (False, True)
                    if value in completion_states
                ],
                "smwc_rating_thresholds": list(SMWC_RATING_THRESHOLDS),
                "has_unrated_smwc_rating": any(
                    rating is None for rating in ratings
                ),
                "release_years": sorted(release_years),
                "download_states": [
                    value
                    for value in (False, True)
                    if value in download_states
                ],
            }
        )
        return copy.deepcopy(choices)

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
        completed=None,
        smwc_rating_min=None,
        smwc_rating_unrated=False,
        release_year_from=None,
        release_year_to=None,
    ):
        """Return a detached filtered pool in full-Collection order."""

        criteria = self._wheel_criteria(
            completed=completed,
            smwc_rating_min=smwc_rating_min,
            smwc_rating_unrated=smwc_rating_unrated,
            release_year_from=release_year_from,
            release_year_to=release_year_to,
        )
        projected = self._project(collection_records)
        base_pool = self.query.query_collection(
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
        return [
            copy.deepcopy(record)
            for record in base_pool
            if self._matches_wheel_criteria(record, criteria)
        ]

    def snapshot(self, collection_records, **filters):
        """Capture one reusable snapshot of the current Wheel pool."""

        return self.selection_service.snapshot(
            self.build_pool(collection_records, **filters)
        )

    def select_from_pool(self, collection_pool, *, excluded_ids=None):
        """Select from one already-built detached Collection pool."""

        snapshot = self.selection_service.snapshot(collection_pool)
        return self.selection_service.select(
            snapshot,
            excluded_ids=excluded_ids,
        )

    def spin(
        self,
        collection_records,
        *,
        excluded_ids=None,
        **filters,
    ):
        """Select one result from the current Collection-owned Wheel pool."""

        pool = self.build_pool(collection_records, **filters)
        return self.select_from_pool(
            pool,
            excluded_ids=excluded_ids,
        )

    def _project(self, collection_records):
        if collection_records is None:
            raise ValueError("Collection records are required")
        return self.projection.project_collection(collection_records)

    def _wheel_criteria(
        self,
        *,
        completed,
        smwc_rating_min,
        smwc_rating_unrated,
        release_year_from,
        release_year_to,
    ):
        if completed not in (None, True, False):
            raise ValueError("completed must be True, False, or None")
        if not isinstance(smwc_rating_unrated, bool):
            raise ValueError("smwc_rating_unrated must be a boolean")

        rating_min = self._optional_number(
            smwc_rating_min,
            "smwc_rating_min",
        )
        if rating_min is not None and not 0 < rating_min <= 5:
            raise ValueError("smwc_rating_min must be greater than 0 and at most 5")
        if rating_min is not None and smwc_rating_unrated:
            raise ValueError(
                "SMWC rating threshold and Unrated cannot be combined"
            )

        year_from = self._optional_year(
            release_year_from,
            "release_year_from",
        )
        year_to = self._optional_year(
            release_year_to,
            "release_year_to",
        )
        if (
            year_from is not None
            and year_to is not None
            and year_from > year_to
        ):
            raise ValueError(
                "Release year From cannot be later than Through"
            )

        return {
            "completed": completed,
            "smwc_rating_min": rating_min,
            "smwc_rating_unrated": smwc_rating_unrated,
            "release_year_from": year_from,
            "release_year_to": year_to,
        }

    def _matches_wheel_criteria(self, record, criteria):
        completed = criteria["completed"]
        if completed is not None and bool(
            record.get("completed", False)
        ) != completed:
            return False

        rating = self._smwc_rating(record)
        if criteria["smwc_rating_unrated"]:
            if rating is not None:
                return False
        elif criteria["smwc_rating_min"] is not None:
            if rating is None or rating < criteria["smwc_rating_min"]:
                return False

        year_from = criteria["release_year_from"]
        year_to = criteria["release_year_to"]
        if year_from is not None or year_to is not None:
            release_year = self._release_year(record)
            if release_year is None:
                return False
            if year_from is not None and release_year < year_from:
                return False
            if year_to is not None and release_year > year_to:
                return False

        return True

    @staticmethod
    def _optional_number(value, label):
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError(f"{label} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} must be numeric") from error
        if not math.isfinite(number):
            raise ValueError(f"{label} must be finite")
        return number

    @staticmethod
    def _optional_year(value, label):
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError(f"{label} must be a four-digit year")
        try:
            year = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{label} must be a four-digit year") from error
        if not 1000 <= year <= 9999:
            raise ValueError(f"{label} must be a four-digit year")
        return year

    @staticmethod
    def _smwc_rating(record):
        value = record.get("rating")
        if value is None or isinstance(value, bool):
            return None
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(rating) or rating <= 0:
            return None
        return rating

    @staticmethod
    def _release_year(record):
        date_text = record.get("date")
        if isinstance(date_text, str):
            date_text = date_text.strip()
            if len(date_text) >= 4 and date_text[:4].isdigit():
                year = int(date_text[:4])
                if 1000 <= year <= 9999:
                    return year

        timestamp = record.get("time")
        if timestamp is None or isinstance(timestamp, bool):
            return None
        try:
            timestamp = float(timestamp)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(timestamp) or timestamp <= 0:
            return None
        try:
            return datetime.fromtimestamp(timestamp).year
        except (OSError, OverflowError, ValueError):
            return None

    @staticmethod
    def _has_recorded_download(record):
        file_path = record.get("file_path")
        if isinstance(file_path, str) and file_path.strip():
            return True

        files = record.get("files", [])
        if not isinstance(files, list):
            return False
        return any(
            isinstance(item, dict)
            and isinstance(item.get("path"), str)
            and bool(item["path"].strip())
            for item in files
        )




__all__ = ["CollectionWheelModel", "SMWC_RATING_THRESHOLDS"]
