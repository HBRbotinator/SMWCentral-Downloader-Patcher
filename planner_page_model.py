"""Presentation and editing model for the Planner page."""

from __future__ import annotations

import copy

from planner_collection import PlannerCollectionProjection
from planner_editor import PlannerEditor
from planner_query import PlannerCollectionQuery


class PlannerPageModel:
    """Prepare, edit, and persist Planner-enriched collection data."""

    def __init__(
        self,
        data_manager,
        planner_store,
        projection=None,
        query=None,
        editor=None,
    ):
        self.data_manager = data_manager
        self.planner_store = planner_store
        self.projection = projection or PlannerCollectionProjection(
            planner_store
        )
        self.query = query or PlannerCollectionQuery()
        self.editor = editor or PlannerEditor(planner_store)
        self.projected_hacks = []

    @property
    def has_unsaved_changes(self):
        """Return whether Planner edits are waiting to be saved."""
        return bool(self.planner_store.unsaved_changes)

    def refresh(self):
        """Rebuild the projection from current in-memory source data."""
        hacks = self.data_manager.get_all_hacks(include_obsolete=True)
        self.projected_hacks = self.projection.project_collection(hacks)
        return copy.deepcopy(self.projected_hacks)

    def reload_planner(self):
        """Discard unsaved Planner edits and reload persistence."""
        self.planner_store.reload()
        return self.refresh()

    def save(self):
        """Persist pending Planner edits and refresh the projection."""
        saved = self.editor.save()
        if saved:
            self.refresh()
        return saved

    def custom_lists(self):
        """Return current custom-list definitions in their stored order."""
        return self.planner_store.get_lists()

    def create_list(self, name, list_id=None):
        """Stage creation of one custom list."""
        previous_state = copy.deepcopy(self.planner_store.state)
        previous_unsaved = self.planner_store.unsaved_changes
        try:
            created = self.planner_store.create_list(name, list_id=list_id)
        except Exception:
            self.planner_store.state = previous_state
            self.planner_store.unsaved_changes = previous_unsaved
            raise
        self.refresh()
        return created

    def rename_list(self, list_id, name):
        """Stage a custom-list rename while retaining its stable ID."""
        previous_state = copy.deepcopy(self.planner_store.state)
        previous_unsaved = self.planner_store.unsaved_changes
        try:
            renamed = self.planner_store.rename_list(list_id, name)
        except Exception:
            self.planner_store.state = previous_state
            self.planner_store.unsaved_changes = previous_unsaved
            raise
        self.refresh()
        return renamed

    def delete_list(self, list_id):
        """Stage deletion of one list and all of its memberships."""
        previous_state = copy.deepcopy(self.planner_store.state)
        previous_unsaved = self.planner_store.unsaved_changes
        try:
            deleted = self.planner_store.delete_list(list_id)
            if not deleted:
                raise ValueError(f"Custom list not found: {list_id}")
        except Exception:
            self.planner_store.state = previous_state
            self.planner_store.unsaved_changes = previous_unsaved
            raise
        self.refresh()
        return True

    def apply_list_membership(self, hack_ids, list_id, mode):
        """Add or remove one custom-list membership for selected rows."""
        list_id = str(list_id).strip()
        known_ids = {item["id"] for item in self.planner_store.get_lists()}
        if not list_id or list_id not in known_ids:
            raise ValueError(f"Unknown custom list ID: {list_id}")

        mode = str(mode).strip().casefold()
        if mode not in ("add", "remove"):
            raise ValueError("List membership mode must be 'add' or 'remove'")

        normalized_ids = self._selected_ids(hack_ids)
        projected_by_id = {
            str(record["id"]): record for record in self.projected_hacks
        }
        missing = [
            hack_id
            for hack_id in normalized_ids
            if hack_id not in projected_by_id
        ]
        if missing:
            raise ValueError(
                "Selected collection entries are no longer available: "
                + ", ".join(missing)
            )

        previous_state = copy.deepcopy(self.planner_store.state)
        previous_unsaved = self.planner_store.unsaved_changes
        changed_ids = []
        try:
            for hack_id in normalized_ids:
                projected = projected_by_id[hack_id]
                memberships = self._list_ids(
                    projected.get("planner_list_ids", [])
                )
                if mode == "add":
                    if list_id in memberships:
                        continue
                    memberships.append(list_id)
                else:
                    if list_id not in memberships:
                        continue
                    memberships = [
                        item for item in memberships if item != list_id
                    ]

                self._seed_explicit_entry(hack_id, projected)
                self.editor.update_entry(hack_id, list_ids=memberships)
                changed_ids.append(hack_id)
        except Exception:
            self.planner_store.state = previous_state
            self.planner_store.unsaved_changes = previous_unsaved
            raise

        if changed_ids:
            self.refresh()
        return changed_ids

    def apply_updates(
        self,
        hack_ids,
        *,
        lifecycle_status="",
        planning_horizon="",
    ):
        """Stage one status and/or horizon edit for selected collection rows."""
        if not lifecycle_status and not planning_horizon:
            raise ValueError("Choose a lifecycle status or planning horizon")

        normalized_ids = self._selected_ids(hack_ids)
        projected_by_id = {
            str(record["id"]): record for record in self.projected_hacks
        }
        missing = [
            hack_id
            for hack_id in normalized_ids
            if hack_id not in projected_by_id
        ]
        if missing:
            raise ValueError(
                "Selected collection entries are no longer available: "
                + ", ".join(missing)
            )

        previous_state = copy.deepcopy(self.planner_store.state)
        previous_unsaved = self.planner_store.unsaved_changes
        try:
            for hack_id in normalized_ids:
                projected = projected_by_id[hack_id]
                self._seed_explicit_entry(hack_id, projected)
                changes = {}
                if lifecycle_status:
                    changes["lifecycle_status"] = lifecycle_status
                if planning_horizon:
                    changes["planning_horizon"] = planning_horizon
                self.editor.update_entry(hack_id, **changes)
        except Exception:
            self.planner_store.state = previous_state
            self.planner_store.unsaved_changes = previous_unsaved
            raise

        self.refresh()
        return [self.planner_store.get_entry(item) for item in normalized_ids]

    def move_next(self, hack_id, offset):
        """Move one Next entry by a relative queue offset."""
        hack_id = self._selected_ids([hack_id])[0]
        if isinstance(offset, bool) or not isinstance(offset, int) or offset == 0:
            raise ValueError("Next queue movement must be a non-zero integer")

        queue = self.planner_store.get_next_queue()
        if hack_id not in queue:
            raise ValueError("Select one entry in the Next planning horizon")
        current_position = queue.index(hack_id) + 1
        target_position = max(1, min(len(queue), current_position + offset))
        if target_position != current_position:
            self.editor.move_next(hack_id, target_position)
        self.refresh()
        return target_position

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

    def _seed_explicit_entry(self, hack_id, projected):
        if self.planner_store.has_entry(hack_id):
            return
        self.planner_store.update_entry(
            hack_id,
            lifecycle_status=projected["planner_lifecycle_status"],
            planning_horizon=projected["planner_horizon"],
            list_ids=projected.get("planner_list_ids", []),
        )

    @staticmethod
    def _list_ids(values):
        if not isinstance(values, (list, tuple)):
            return []
        result = []
        for value in values:
            value = str(value).strip()
            if value and value not in result:
                result.append(value)
        return result

    @staticmethod
    def _selected_ids(hack_ids):
        if isinstance(hack_ids, (str, int)):
            hack_ids = [hack_ids]
        if not isinstance(hack_ids, (list, tuple)):
            raise ValueError("Selected hack IDs must be a list or tuple")
        result = []
        for hack_id in hack_ids:
            value = str(hack_id).strip()
            if value and value not in result:
                result.append(value)
        if not result:
            raise ValueError("Select at least one collection entry")
        return result

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
