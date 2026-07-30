"""Composable filtering and ordering for Planner-enriched collections."""

from __future__ import annotations

import copy

from planner_store import LIFECYCLE_STATUSES, PLANNING_HORIZONS


LIST_MATCH_MODES = ("any", "all")
PLANNER_SORT_MODES = ("collection", "planning", "title")


class PlannerCollectionQuery:
    """Filter projected collection records without adding wheel-only state."""

    def query_collection(
        self,
        hacks,
        *,
        text="",
        lifecycle_statuses=None,
        planning_horizons=None,
        list_ids=None,
        list_match="any",
        difficulties=None,
        hack_types=None,
        downloaded=None,
        include_obsolete=False,
        sort_mode="planning",
    ):
        """Return copied records matching all supplied filter groups.

        Values within one group are combined with OR. Separate groups are
        combined with AND. Custom lists may instead require every selected
        membership by using ``list_match="all"``.
        """
        records = self._records(hacks)
        criteria = self._criteria(
            text=text,
            lifecycle_statuses=lifecycle_statuses,
            planning_horizons=planning_horizons,
            list_ids=list_ids,
            list_match=list_match,
            difficulties=difficulties,
            hack_types=hack_types,
            downloaded=downloaded,
            include_obsolete=include_obsolete,
            sort_mode=sort_mode,
        )

        matching = [
            copy.deepcopy(record)
            for record in records
            if self._matches(record, criteria)
        ]
        return self._sort(matching, criteria["sort_mode"])

    def available_filters(self, hacks):
        """Return stable filter choices represented by projected records."""
        records = self._records(hacks)
        represented_statuses = {
            record["planner_lifecycle_status"] for record in records
        }
        represented_horizons = {
            record["planner_horizon"] for record in records
        }

        list_names = {}
        for record in records:
            list_ids = self._record_strings(record, "planner_list_ids")
            names = self._record_strings(record, "planner_list_names")
            for index, list_id in enumerate(list_ids):
                name = names[index] if index < len(names) else list_id
                list_names.setdefault(list_id, name)

        return {
            "lifecycle_statuses": [
                status
                for status in LIFECYCLE_STATUSES
                if status in represented_statuses
            ],
            "planning_horizons": [
                horizon
                for horizon in PLANNING_HORIZONS
                if horizon in represented_horizons
            ],
            "lists": [
                {"id": list_id, "name": list_names[list_id]}
                for list_id in sorted(
                    list_names,
                    key=lambda item: (list_names[item].casefold(), item),
                )
            ],
            "difficulties": self._sorted_record_values(records, "difficulty"),
            "hack_types": self._sorted_hack_types(records),
        }

    def _criteria(
        self,
        *,
        text,
        lifecycle_statuses,
        planning_horizons,
        list_ids,
        list_match,
        difficulties,
        hack_types,
        downloaded,
        include_obsolete,
        sort_mode,
    ):
        if not isinstance(text, str):
            raise ValueError("Planner search text must be a string")
        if list_match not in LIST_MATCH_MODES:
            raise ValueError(
                "Custom-list matching must be 'any' or 'all'"
            )
        if sort_mode not in PLANNER_SORT_MODES:
            raise ValueError(f"Unknown Planner sort mode: {sort_mode}")
        if downloaded not in (None, True, False):
            raise ValueError("downloaded must be True, False, or None")
        if not isinstance(include_obsolete, bool):
            raise ValueError("include_obsolete must be a boolean")

        statuses = self._filter_values(
            lifecycle_statuses,
            "lifecycle_statuses",
        )
        unknown_statuses = statuses - set(LIFECYCLE_STATUSES)
        if unknown_statuses:
            raise ValueError(
                "Unknown lifecycle status filter(s): "
                + ", ".join(sorted(unknown_statuses))
            )

        horizons = self._filter_values(
            planning_horizons,
            "planning_horizons",
        )
        unknown_horizons = horizons - set(PLANNING_HORIZONS)
        if unknown_horizons:
            raise ValueError(
                "Unknown planning horizon filter(s): "
                + ", ".join(sorted(unknown_horizons))
            )

        return {
            "text_terms": [
                term.casefold()
                for term in text.split()
                if term.strip()
            ],
            "lifecycle_statuses": statuses,
            "planning_horizons": horizons,
            "list_ids": self._filter_values(list_ids, "list_ids"),
            "list_match": list_match,
            "difficulties": {
                value.casefold()
                for value in self._filter_values(
                    difficulties,
                    "difficulties",
                )
            },
            "hack_types": {
                value.casefold()
                for value in self._filter_values(
                    hack_types,
                    "hack_types",
                )
            },
            "downloaded": downloaded,
            "include_obsolete": include_obsolete,
            "sort_mode": sort_mode,
        }

    def _matches(self, record, criteria):
        if not criteria["include_obsolete"] and bool(
            record.get("obsolete", False)
        ):
            return False

        statuses = criteria["lifecycle_statuses"]
        if statuses and record["planner_lifecycle_status"] not in statuses:
            return False

        horizons = criteria["planning_horizons"]
        if horizons and record["planner_horizon"] not in horizons:
            return False

        selected_lists = criteria["list_ids"]
        if selected_lists:
            memberships = set(
                self._record_strings(record, "planner_list_ids")
            )
            if criteria["list_match"] == "all":
                if not selected_lists.issubset(memberships):
                    return False
            elif memberships.isdisjoint(selected_lists):
                return False

        difficulties = criteria["difficulties"]
        if difficulties:
            difficulty = str(record.get("difficulty", "")).strip().casefold()
            if difficulty not in difficulties:
                return False

        selected_types = criteria["hack_types"]
        if selected_types:
            record_types = {
                value.casefold() for value in self._hack_types(record)
            }
            if record_types.isdisjoint(selected_types):
                return False

        downloaded = criteria["downloaded"]
        if downloaded is not None and self._has_recorded_download(record) != downloaded:
            return False

        if criteria["text_terms"]:
            haystack = self._search_text(record)
            if not all(term in haystack for term in criteria["text_terms"]):
                return False

        return True

    def _sort(self, records, sort_mode):
        if sort_mode == "collection":
            return records
        if sort_mode == "title":
            return sorted(records, key=self._title_key)

        horizon_order = {
            horizon: index
            for index, horizon in enumerate(
                ("Next", "Soon", "Someday")
            )
        }
        status_order = {
            status: index
            for index, status in enumerate(LIFECYCLE_STATUSES)
        }

        def planning_key(record):
            horizon = record["planner_horizon"]
            position = record.get("planner_next_position")
            if horizon != "Next" or not isinstance(position, int):
                position = float("inf")
            return (
                horizon_order.get(horizon, len(horizon_order)),
                position,
                status_order.get(
                    record["planner_lifecycle_status"],
                    len(status_order),
                ),
                *self._title_key(record),
            )

        return sorted(records, key=planning_key)

    def _records(self, hacks):
        if not isinstance(hacks, (list, tuple)):
            raise ValueError("Planner collection must be a list or tuple")
        records = list(hacks)
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Planner collection records must be dictionaries")
            hack_id = str(record.get("id", "")).strip()
            if not hack_id:
                raise ValueError("Planner collection records must include an ID")
            if record.get("planner_lifecycle_status") not in LIFECYCLE_STATUSES:
                raise ValueError(
                    f"Record {hack_id} has no valid projected lifecycle status"
                )
            if record.get("planner_horizon") not in PLANNING_HORIZONS:
                raise ValueError(
                    f"Record {hack_id} has no valid projected planning horizon"
                )
        return records

    @staticmethod
    def _filter_values(values, label):
        if values is None:
            return set()
        if isinstance(values, (str, int)):
            values = [values]
        if not isinstance(values, (list, tuple, set, frozenset)):
            raise ValueError(f"{label} must be a value or collection of values")

        normalized = set()
        for value in values:
            if not isinstance(value, (str, int)):
                raise ValueError(f"{label} values must be text or integers")
            value = str(value).strip()
            if value:
                normalized.add(value)
        return normalized

    @staticmethod
    def _record_strings(record, field):
        values = record.get(field, [])
        if not isinstance(values, (list, tuple)):
            return []
        result = []
        for value in values:
            if not isinstance(value, (str, int)):
                continue
            value = str(value).strip()
            if value:
                result.append(value)
        return result

    def _search_text(self, record):
        values = [
            record.get("id", ""),
            record.get("title", ""),
            record.get("notes", ""),
            record.get("difficulty", ""),
            *self._record_strings(record, "authors"),
            *self._record_strings(record, "planner_list_names"),
            *self._hack_types(record),
        ]
        return "\n".join(str(value) for value in values).casefold()

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

    def _hack_types(self, record):
        values = self._record_strings(record, "hack_types")
        if not values:
            hack_type = record.get("hack_type", "")
            if isinstance(hack_type, str) and hack_type.strip():
                values = [hack_type.strip()]
        return values

    @staticmethod
    def _title_key(record):
        return (
            str(record.get("title", "")).casefold(),
            str(record.get("id", "")),
        )

    @staticmethod
    def _sorted_record_values(records, field):
        values = {
            str(record.get(field, "")).strip()
            for record in records
            if str(record.get(field, "")).strip()
        }
        return sorted(values, key=str.casefold)

    def _sorted_hack_types(self, records):
        values = {
            hack_type
            for record in records
            for hack_type in self._hack_types(record)
        }
        return sorted(values, key=str.casefold)
