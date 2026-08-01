"""Read-only projection of Planner state onto core collection records."""

from __future__ import annotations

import copy


class PlannerCollectionProjection:
    """Combine collection records with Planner state without mutating either."""

    def __init__(self, planner_store):
        self.planner_store = planner_store

    def project_hack(self, hack):
        """Return one collection record enriched with Planner display fields."""
        queue_positions = self._queue_positions()
        list_names = self._list_names()
        return self._project_hack(hack, queue_positions, list_names)

    def project_collection(self, hacks):
        """Return Planner-enriched copies of collection records in input order."""
        queue_positions = self._queue_positions()
        list_names = self._list_names()
        return [
            self._project_hack(hack, queue_positions, list_names)
            for hack in hacks
        ]

    def _project_hack(self, hack, queue_positions, list_names):
        if not isinstance(hack, dict):
            raise ValueError("Collection records must be dictionaries")

        hack_id = str(hack.get("id", "")).strip()
        if not hack_id:
            raise ValueError("Collection records must include an ID")

        projected = copy.deepcopy(hack)
        explicit = self.planner_store.has_entry(hack_id)
        planner_entry = self.planner_store.get_entry(hack_id)

        lifecycle_status = planner_entry["lifecycle_status"]
        if not explicit and bool(hack.get("completed", False)):
            lifecycle_status = "Completed"

        list_ids = list(planner_entry["list_ids"])
        projected.update(
            {
                "planner_explicit": explicit,
                "planner_lifecycle_status": lifecycle_status,
                "planner_horizon": planner_entry["planning_horizon"],
                "planner_list_ids": list_ids,
                "planner_list_names": [
                    list_names[list_id]
                    for list_id in list_ids
                    if list_id in list_names
                ],
                "planner_next_position": queue_positions.get(hack_id),
                "planner_timestamps": {
                    "planned_at": planner_entry["planned_at"],
                    "started_at": planner_entry["started_at"],
                    "beaten_at": planner_entry["beaten_at"],
                    "completed_at": planner_entry["completed_at"],
                    "last_played_at": planner_entry["last_played_at"],
                },
            }
        )
        return projected

    def _queue_positions(self):
        return {
            hack_id: position
            for position, hack_id in enumerate(
                self.planner_store.get_next_queue(),
                start=1,
            )
        }

    def _list_names(self):
        return {
            item["id"]: item["name"]
            for item in self.planner_store.get_lists()
        }
