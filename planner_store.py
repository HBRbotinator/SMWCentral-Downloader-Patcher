"""Persistent Planner data kept separate from the core collection file."""

from __future__ import annotations

import copy
import json
import os
import shutil
import uuid
from pathlib import Path


PLANNER_SCHEMA_VERSION = 1
LIFECYCLE_STATUSES = (
    "Planned",
    "Playing",
    "Paused",
    "Beaten",
    "Completed",
    "Dropped",
    "Archived",
)
PLANNING_HORIZONS = ("Someday", "Soon", "Next")
PLANNER_ENTRY_FIELDS = (
    "lifecycle_status",
    "planning_horizon",
    "list_ids",
    "planned_at",
    "started_at",
    "beaten_at",
    "completed_at",
    "last_played_at",
)
TIMESTAMP_FIELDS = (
    "planned_at",
    "started_at",
    "beaten_at",
    "completed_at",
    "last_played_at",
)


def default_planner_entry():
    """Return a new default Planner entry."""
    return {
        "lifecycle_status": "Planned",
        "planning_horizon": "Someday",
        "list_ids": [],
        "planned_at": "",
        "started_at": "",
        "beaten_at": "",
        "completed_at": "",
        "last_played_at": "",
    }


def default_planner_state():
    """Return a new empty Planner state document."""
    return {
        "schema_version": PLANNER_SCHEMA_VERSION,
        "entries": {},
        "lists": [],
        "next_queue": [],
    }


class PlannerStore:
    """Manage Planner state without modifying ``processed.json``."""

    def __init__(self, path=None, logger=None):
        if path is None:
            from utils import get_user_data_path

            path = get_user_data_path("planner_state.json")

        self.path = Path(path)
        self.logger = logger
        self.state = self._load_state()
        self.unsaved_changes = False

    def _log(self, message, level="Information"):
        if self.logger:
            self.logger.log(message, level)

    def _load_state(self):
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except FileNotFoundError:
            return default_planner_state()
        except (json.JSONDecodeError, OSError) as error:
            self._log(
                f"Could not load Planner state '{self.path}': {error}",
                "Warning",
            )
            return default_planner_state()

        if not isinstance(loaded, dict):
            self._log("Planner state root is not an object", "Warning")
            return default_planner_state()

        loaded.setdefault("schema_version", PLANNER_SCHEMA_VERSION)
        if not isinstance(loaded.get("entries"), dict):
            loaded["entries"] = {}
        if not isinstance(loaded.get("lists"), list):
            loaded["lists"] = []
        if not isinstance(loaded.get("next_queue"), list):
            loaded["next_queue"] = []
        return loaded

    def reload(self):
        """Reload Planner state from disk and discard unsaved changes."""
        self.state = self._load_state()
        self.unsaved_changes = False

    def has_entry(self, hack_id):
        """Return whether an explicit Planner entry exists for a hack."""
        return str(hack_id) in self.state["entries"]

    def get_entry(self, hack_id):
        """Return a normalized copy of one Planner entry."""
        hack_id = str(hack_id)
        raw_entry = self.state["entries"].get(hack_id, {})
        if not isinstance(raw_entry, dict):
            raw_entry = {}

        entry = copy.deepcopy(raw_entry)
        defaults = default_planner_entry()
        for field, value in defaults.items():
            entry.setdefault(field, copy.deepcopy(value))

        if entry["lifecycle_status"] not in LIFECYCLE_STATUSES:
            entry["lifecycle_status"] = defaults["lifecycle_status"]
        if entry["planning_horizon"] not in PLANNING_HORIZONS:
            entry["planning_horizon"] = defaults["planning_horizon"]
        if not isinstance(entry["list_ids"], list):
            entry["list_ids"] = []
        else:
            entry["list_ids"] = self._unique_strings(entry["list_ids"])
        for field in TIMESTAMP_FIELDS:
            if not isinstance(entry[field], str):
                entry[field] = ""
        return entry

    def get_entries(self):
        """Return normalized copies of all explicitly stored entries."""
        return {
            hack_id: self.get_entry(hack_id)
            for hack_id in self.state["entries"]
        }

    def update_entry(self, hack_id, **changes):
        """Update one Planner entry in memory after validating its fields."""
        hack_id = self._required_identifier(hack_id, "hack ID")
        unknown_fields = set(changes) - set(PLANNER_ENTRY_FIELDS)
        if unknown_fields:
            fields = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unknown Planner field(s): {fields}")

        current = self.get_entry(hack_id)
        updated = copy.deepcopy(current)

        if "lifecycle_status" in changes:
            value = changes["lifecycle_status"]
            if value not in LIFECYCLE_STATUSES:
                raise ValueError(f"Unknown lifecycle status: {value}")
            updated["lifecycle_status"] = value

        if "planning_horizon" in changes:
            value = changes["planning_horizon"]
            if value not in PLANNING_HORIZONS:
                raise ValueError(f"Unknown planning horizon: {value}")
            updated["planning_horizon"] = value

        if "list_ids" in changes:
            value = changes["list_ids"]
            if not isinstance(value, (list, tuple)):
                raise ValueError("list_ids must be a list or tuple")
            list_ids = self._unique_strings(value)
            known_ids = {item["id"] for item in self.get_lists()}
            missing = [list_id for list_id in list_ids if list_id not in known_ids]
            if missing:
                raise ValueError(
                    "Unknown custom list ID(s): " + ", ".join(missing)
                )
            updated["list_ids"] = list_ids

        for field in TIMESTAMP_FIELDS:
            if field in changes:
                value = changes[field]
                if not isinstance(value, str):
                    raise ValueError(f"{field} must be a string")
                updated[field] = value

        raw_entry = self.state["entries"].get(hack_id, {})
        if not isinstance(raw_entry, dict):
            raw_entry = {}
        raw_entry.update(updated)
        self.state["entries"][hack_id] = raw_entry

        if updated["planning_horizon"] == "Next":
            queue = self._clean_queue(self.state["next_queue"])
            if hack_id not in queue:
                queue.append(hack_id)
            self.state["next_queue"] = queue
        else:
            self.state["next_queue"] = [
                item
                for item in self._clean_queue(self.state["next_queue"])
                if item != hack_id
            ]

        self.unsaved_changes = True
        return self.get_entry(hack_id)

    def remove_entry(self, hack_id):
        """Remove one Planner entry without touching the core collection."""
        hack_id = str(hack_id)
        removed = self.state["entries"].pop(hack_id, None)
        self.state["next_queue"] = [
            item
            for item in self._clean_queue(self.state["next_queue"])
            if item != hack_id
        ]
        if removed is not None:
            self.unsaved_changes = True
            return True
        return False

    def get_lists(self):
        """Return valid custom-list definitions in stored order."""
        lists = []
        seen_ids = set()
        for item in self.state["lists"]:
            if not isinstance(item, dict):
                continue
            list_id = item.get("id")
            name = item.get("name")
            if not isinstance(list_id, str) or not list_id.strip():
                continue
            if not isinstance(name, str) or not name.strip():
                continue
            list_id = list_id.strip()
            if list_id in seen_ids:
                continue
            seen_ids.add(list_id)
            copied = copy.deepcopy(item)
            copied["id"] = list_id
            copied["name"] = name.strip()
            lists.append(copied)
        return lists

    def create_list(self, name, list_id=None):
        """Create a custom list and return its stable definition."""
        name = self._required_identifier(name, "list name")
        self._ensure_unique_list_name(name)
        if list_id is None:
            list_id = uuid.uuid4().hex
        list_id = self._required_identifier(list_id, "list ID")
        if any(item["id"] == list_id for item in self.get_lists()):
            raise ValueError(f"Custom list ID already exists: {list_id}")

        item = {"id": list_id, "name": name}
        self.state["lists"].append(item)
        self.unsaved_changes = True
        return copy.deepcopy(item)

    def rename_list(self, list_id, name):
        """Rename a custom list without changing its stable ID."""
        list_id = self._required_identifier(list_id, "list ID")
        name = self._required_identifier(name, "list name")
        self._ensure_unique_list_name(name, excluding_id=list_id)

        for item in self.state["lists"]:
            if isinstance(item, dict) and item.get("id") == list_id:
                item["name"] = name
                self.unsaved_changes = True
                return copy.deepcopy(item)
        raise KeyError(f"Custom list not found: {list_id}")

    def delete_list(self, list_id):
        """Delete a custom list and remove its memberships."""
        list_id = self._required_identifier(list_id, "list ID")
        original_length = len(self.state["lists"])
        self.state["lists"] = [
            item
            for item in self.state["lists"]
            if not isinstance(item, dict) or item.get("id") != list_id
        ]
        if len(self.state["lists"]) == original_length:
            return False

        for raw_entry in self.state["entries"].values():
            if not isinstance(raw_entry, dict):
                continue
            memberships = raw_entry.get("list_ids", [])
            if isinstance(memberships, list):
                raw_entry["list_ids"] = [
                    item for item in memberships if item != list_id
                ]
        self.unsaved_changes = True
        return True

    def get_next_queue(self):
        """Return all Next entries in their explicit queue order."""
        next_ids = {
            hack_id
            for hack_id in self.state["entries"]
            if self.get_entry(hack_id)["planning_horizon"] == "Next"
        }
        ordered = [
            hack_id
            for hack_id in self._clean_queue(self.state["next_queue"])
            if hack_id in next_ids
        ]
        for hack_id in self.state["entries"]:
            if hack_id in next_ids and hack_id not in ordered:
                ordered.append(hack_id)
        return ordered

    def set_next_queue(self, hack_ids):
        """Prioritize supplied Next entries and retain any omitted ones."""
        if not isinstance(hack_ids, (list, tuple)):
            raise ValueError("Next queue must be a list or tuple")
        requested = self._unique_strings(hack_ids)
        invalid = [
            hack_id
            for hack_id in requested
            if hack_id not in self.state["entries"]
            or self.get_entry(hack_id)["planning_horizon"] != "Next"
        ]
        if invalid:
            raise ValueError(
                "Queue entries must use the Next horizon: "
                + ", ".join(invalid)
            )

        current = self.get_next_queue()
        self.state["next_queue"] = requested + [
            hack_id for hack_id in current if hack_id not in requested
        ]
        self.unsaved_changes = True
        return list(self.state["next_queue"])

    def save(self):
        """Atomically save Planner state and preserve a previous backup."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_name(f".{self.path.name}.tmp")
        try:
            with temporary_path.open("w", encoding="utf-8", newline="\n") as handle:
                json.dump(self.state, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())

            if self.path.exists():
                shutil.copy2(self.path, self.path.with_suffix(self.path.suffix + ".backup"))
            os.replace(temporary_path, self.path)
            self.unsaved_changes = False
            return True
        except OSError as error:
            self._log(
                f"Could not save Planner state '{self.path}': {error}",
                "Error",
            )
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
            return False

    def _ensure_unique_list_name(self, name, excluding_id=None):
        normalized = name.casefold()
        for item in self.get_lists():
            if item["id"] == excluding_id:
                continue
            if item["name"].casefold() == normalized:
                raise ValueError(f"Custom list name already exists: {name}")

    @staticmethod
    def _required_identifier(value, label):
        if not isinstance(value, (str, int)):
            raise ValueError(f"{label} must be text or an integer")
        normalized = str(value).strip()
        if not normalized:
            raise ValueError(f"{label} cannot be empty")
        return normalized

    @staticmethod
    def _unique_strings(values):
        result = []
        for value in values:
            if not isinstance(value, (str, int)):
                continue
            normalized = str(value).strip()
            if normalized and normalized not in result:
                result.append(normalized)
        return result

    @classmethod
    def _clean_queue(cls, values):
        if not isinstance(values, list):
            return []
        return cls._unique_strings(values)
