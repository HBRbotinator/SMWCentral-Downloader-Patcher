"""Validated editing operations for the separate Planner state."""

from __future__ import annotations

import copy
from datetime import datetime


_UNSET = object()


class PlannerEditor:
    """Apply consistent Planner edits without writing until explicitly saved."""

    def __init__(self, planner_store, now_provider=None):
        self.planner_store = planner_store
        self.now_provider = now_provider or self._current_timestamp

    def update_entry(
        self,
        hack_id,
        *,
        lifecycle_status=_UNSET,
        planning_horizon=_UNSET,
        list_ids=_UNSET,
    ):
        """Update one Planner entry and return its normalized state."""
        entries = self.update_entries(
            [hack_id],
            lifecycle_status=lifecycle_status,
            planning_horizon=planning_horizon,
            list_ids=list_ids,
        )
        return entries[0]

    def update_entries(
        self,
        hack_ids,
        *,
        lifecycle_status=_UNSET,
        planning_horizon=_UNSET,
        list_ids=_UNSET,
    ):
        """Apply one atomic Planner edit to multiple hacks in memory."""
        normalized_ids = self._normalize_hack_ids(hack_ids)
        changes = self._requested_changes(
            lifecycle_status=lifecycle_status,
            planning_horizon=planning_horizon,
            list_ids=list_ids,
        )
        if not changes:
            raise ValueError("At least one Planner field must be supplied")

        previous_state = copy.deepcopy(self.planner_store.state)
        previous_unsaved = self.planner_store.unsaved_changes
        timestamp = self._timestamp()
        updated_entries = []

        try:
            for hack_id in normalized_ids:
                entry_changes = self._entry_changes(
                    hack_id,
                    changes,
                    timestamp,
                )
                updated_entries.append(
                    self.planner_store.update_entry(
                        hack_id,
                        **entry_changes,
                    )
                )
        except Exception:
            self.planner_store.state = previous_state
            self.planner_store.unsaved_changes = previous_unsaved
            raise

        return updated_entries

    def move_next(self, hack_id, position):
        """Move one Next entry to a one-based queue position."""
        hack_id = self._normalize_hack_ids([hack_id])[0]
        queue = self.planner_store.get_next_queue()
        if hack_id not in queue:
            raise ValueError(f"Planner entry is not in the Next queue: {hack_id}")
        if isinstance(position, bool) or not isinstance(position, int):
            raise ValueError("Next queue position must be an integer")
        if position < 1 or position > len(queue):
            raise ValueError(
                f"Next queue position must be between 1 and {len(queue)}"
            )

        queue.remove(hack_id)
        queue.insert(position - 1, hack_id)
        return self.planner_store.set_next_queue(queue)

    def remove_entry(self, hack_id):
        """Remove explicit Planner state while retaining the core collection."""
        normalized = self._normalize_hack_ids([hack_id])[0]
        return self.planner_store.remove_entry(normalized)

    def save(self):
        """Persist all pending Planner edits."""
        return self.planner_store.save()

    def _entry_changes(self, hack_id, requested, timestamp):
        current = self.planner_store.get_entry(hack_id)
        changes = copy.deepcopy(requested)

        if not current["planned_at"]:
            changes["planned_at"] = timestamp

        lifecycle_status = changes.get("lifecycle_status")
        if lifecycle_status == "Playing":
            if not current["started_at"]:
                changes["started_at"] = timestamp
            changes["last_played_at"] = timestamp
        elif lifecycle_status == "Beaten":
            if not current["beaten_at"]:
                changes["beaten_at"] = timestamp
            changes["last_played_at"] = timestamp
        elif lifecycle_status == "Completed":
            if not current["beaten_at"]:
                changes["beaten_at"] = timestamp
            if not current["completed_at"]:
                changes["completed_at"] = timestamp
            changes["last_played_at"] = timestamp

        return changes

    @staticmethod
    def _requested_changes(
        *,
        lifecycle_status,
        planning_horizon,
        list_ids,
    ):
        changes = {}
        if lifecycle_status is not _UNSET:
            changes["lifecycle_status"] = lifecycle_status
        if planning_horizon is not _UNSET:
            changes["planning_horizon"] = planning_horizon
        if list_ids is not _UNSET:
            changes["list_ids"] = list_ids
        return changes

    @staticmethod
    def _normalize_hack_ids(hack_ids):
        if isinstance(hack_ids, (str, int)):
            hack_ids = [hack_ids]
        if not isinstance(hack_ids, (list, tuple)):
            raise ValueError("hack_ids must be a hack ID, list, or tuple")

        normalized = []
        for hack_id in hack_ids:
            if not isinstance(hack_id, (str, int)):
                raise ValueError("Hack IDs must be text or integers")
            value = str(hack_id).strip()
            if not value:
                raise ValueError("Hack IDs cannot be empty")
            if value not in normalized:
                normalized.append(value)
        if not normalized:
            raise ValueError("At least one hack ID is required")
        return normalized

    def _timestamp(self):
        value = self.now_provider()
        if isinstance(value, datetime):
            value = value.astimezone().replace(microsecond=0).isoformat()
        if not isinstance(value, str) or not value.strip():
            raise ValueError("The Planner clock must return a timestamp")
        return value.strip()

    @staticmethod
    def _current_timestamp():
        return datetime.now().astimezone().replace(microsecond=0).isoformat()
