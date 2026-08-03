"""Integration contracts between Collection Wheel and runtime schema."""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone

from collection_wheel_model import CollectionWheelModel
from wheel_runtime_contract import serialize_wheel_runtime_snapshot


GENERATED_AT = datetime(
    2026,
    8,
    3,
    16,
    0,
    tzinfo=timezone.utc,
)


class RecordingPlannerStore:
    def __init__(self, *, entries=None, lists=None):
        self._entries = copy.deepcopy(entries or {})
        self._lists = copy.deepcopy(lists or [])
        self.unsaved_changes = False
        self.reload_calls = 0
        self.save_calls = 0

    def get_entries(self):
        return copy.deepcopy(self._entries)

    def get_lists(self):
        return copy.deepcopy(self._lists)

    def reload(self):
        self.reload_calls += 1

    def save(self):
        self.save_calls += 1
        raise AssertionError("runtime_snapshot must never save Planner state")


class RecordingProjection:
    def __init__(self, projected_records):
        self.projected_records = copy.deepcopy(projected_records)
        self.calls = []

    def project_collection(self, collection_records):
        self.calls.append(collection_records)
        return copy.deepcopy(self.projected_records)


class ForbiddenQuery:
    def available_filters(self, _records):
        raise AssertionError("runtime_snapshot must not calculate UI filters")

    def query_collection(self, *_args, **_kwargs):
        raise AssertionError("runtime_snapshot must not build a filtered pool")


class ForbiddenSelectionService:
    def snapshot(self, _records):
        raise AssertionError("runtime_snapshot must not create a spin pool")

    def select(self, *_args, **_kwargs):
        raise AssertionError("runtime_snapshot must not select a winner")


def build_model(projected_records, *, entries=None, lists=None):
    store = RecordingPlannerStore(entries=entries, lists=lists)
    projection = RecordingProjection(projected_records)
    model = CollectionWheelModel(
        planner_store=store,
        projection=projection,
        query=ForbiddenQuery(),
        selection_service=ForbiddenSelectionService(),
    )
    return model, store, projection


class CollectionWheelRuntimeSnapshotTest(unittest.TestCase):
    def test_snapshot_captures_complete_projected_collection_in_order(self):
        records = [
            {
                "id": "second",
                "title": "Second in Collection",
            },
            {
                "id": "first",
                "title": "First by Name",
            },
        ]
        collection_input = [{"id": "raw"}]
        model, store, projection = build_model(records)

        snapshot = model.runtime_snapshot(
            collection_input,
            generated_at=GENERATED_AT,
            source_revision="processed-19",
        )

        self.assertEqual(
            [item["id"] for item in snapshot["candidates"]],
            ["second", "first"],
        )
        self.assertEqual(projection.calls, [collection_input])
        self.assertEqual(
            snapshot["source"]["revision"],
            "processed-19",
        )
        self.assertEqual(store.reload_calls, 0)
        self.assertEqual(store.save_calls, 0)

    def test_snapshot_maps_collection_filter_and_display_fields(self):
        model, _store, _projection = build_model(
            [
                {
                    "id": 40226,
                    "title": "!Uppipe",
                    "authors": [
                        {"username": "Maker One"},
                        {"name": "Maker Two"},
                    ],
                    "hack_types": ["Kaizo", "Standard"],
                    "difficulty": "Intermediate",
                    "completed": True,
                    "file_path": r"C:\Private\ROMs\uppipe.sfc",
                    "rating": "4.5",
                    "date": "2025-07-14 12:00:00",
                }
            ]
        )

        snapshot = model.runtime_snapshot(
            [{"id": 40226}],
            generated_at=GENERATED_AT,
        )
        candidate = snapshot["candidates"][0]

        self.assertEqual(
            candidate,
            {
                "id": "40226",
                "title": "!Uppipe",
                "authors": ["Maker One", "Maker Two"],
                "type": "Kaizo, Standard",
                "difficulty": "Intermediate",
                "completed": True,
                "downloaded": True,
                "smwc_rating": 4.5,
                "release_year": 2025,
                "planner": {
                    "lifecycle": "",
                    "horizon": "",
                    "list_ids": [],
                    "next_position": None,
                },
            },
        )
        self.assertNotIn("Private", json.dumps(snapshot))

    def test_snapshot_uses_raw_difficulty_and_single_hack_type_fallbacks(self):
        model, _store, _projection = build_model(
            [
                {
                    "id": "fallback",
                    "title": "Fallback",
                    "hack_type": "Kaizo",
                    "raw_fields": {"difficulty": "Expert"},
                    "files": [{"path": r"D:\ROMs\fallback.sfc"}],
                }
            ]
        )

        candidate = model.runtime_snapshot(
            [{"id": "fallback"}],
            generated_at=GENERATED_AT,
        )["candidates"][0]

        self.assertEqual(candidate["type"], "Kaizo")
        self.assertEqual(candidate["difficulty"], "Expert")
        self.assertTrue(candidate["downloaded"])

    def test_explicit_planner_state_and_lists_are_included(self):
        model, store, _projection = build_model(
            [
                {
                    "id": "planned",
                    "title": "Planned Hack",
                    "planner_lifecycle_status": "Playing",
                    "planner_horizon": "Soon",
                    "planner_list_ids": ["stream"],
                    "planner_next_position": 2,
                }
            ],
            entries={"planned": {"lifecycle": "Playing"}},
            lists=[
                {
                    "id": "stream",
                    "name": "Stream candidates",
                    "members": ["planned"],
                }
            ],
        )

        snapshot = model.runtime_snapshot(
            [{"id": "planned"}],
            generated_at=GENERATED_AT,
        )

        self.assertTrue(snapshot["planner"]["available"])
        self.assertEqual(
            snapshot["planner"]["lists"],
            [{"id": "stream", "name": "Stream candidates"}],
        )
        self.assertEqual(
            snapshot["candidates"][0]["planner"],
            {
                "lifecycle": "Playing",
                "horizon": "Soon",
                "list_ids": ["stream"],
                "next_position": 2,
            },
        )
        self.assertEqual(store.reload_calls, 0)
        self.assertEqual(store.save_calls, 0)

    def test_custom_lists_alone_make_planner_available(self):
        model, _store, _projection = build_model(
            [{"id": "one", "title": "One"}],
            lists=[{"id": "later", "name": "Later"}],
        )

        snapshot = model.runtime_snapshot(
            [{"id": "one"}],
            generated_at=GENERATED_AT,
        )

        self.assertTrue(snapshot["planner"]["available"])
        self.assertEqual(
            snapshot["planner"]["lists"],
            [{"id": "later", "name": "Later"}],
        )

    def test_legacy_inferred_planner_fields_are_suppressed_without_state(self):
        model, _store, _projection = build_model(
            [
                {
                    "id": "completed",
                    "title": "Completed Hack",
                    "completed": True,
                    "planner_lifecycle_status": "Completed",
                    "planner_horizon": "Now",
                    "planner_list_ids": ["legacy"],
                    "planner_next_position": 1,
                }
            ]
        )

        snapshot = model.runtime_snapshot(
            [{"id": "completed"}],
            generated_at=GENERATED_AT,
        )

        self.assertFalse(snapshot["planner"]["available"])
        self.assertEqual(snapshot["planner"]["lists"], [])
        self.assertEqual(
            snapshot["candidates"][0]["planner"],
            {
                "lifecycle": "",
                "horizon": "",
                "list_ids": [],
                "next_position": None,
            },
        )

    def test_snapshot_and_serialization_are_detached_from_application_data(self):
        projected = [
            {
                "id": "detached",
                "title": "Original",
                "authors": ["Maker"],
            }
        ]
        planner_lists = [{"id": "later", "name": "Later"}]
        model, store, projection = build_model(
            projected,
            lists=planner_lists,
        )

        snapshot = model.runtime_snapshot(
            [{"id": "detached"}],
            generated_at=GENERATED_AT,
        )
        snapshot["candidates"][0]["title"] = "Changed snapshot"
        snapshot["planner"]["lists"][0]["name"] = "Changed list"

        self.assertEqual(
            projection.projected_records[0]["title"],
            "Original",
        )
        self.assertEqual(store.get_lists()[0]["name"], "Later")

        fresh = model.runtime_snapshot(
            [{"id": "detached"}],
            generated_at=GENERATED_AT,
        )
        text = serialize_wheel_runtime_snapshot(fresh)
        self.assertEqual(json.loads(text), fresh)

    def test_empty_collection_produces_valid_collection_only_snapshot(self):
        model, _store, _projection = build_model([])

        snapshot = model.runtime_snapshot(
            [],
            generated_at=GENERATED_AT,
        )

        self.assertEqual(snapshot["candidates"], [])
        self.assertFalse(snapshot["planner"]["available"])

    def test_none_collection_still_fails_through_model_boundary(self):
        model, _store, _projection = build_model([])

        with self.assertRaisesRegex(
            ValueError,
            "Collection records are required",
        ):
            model.runtime_snapshot(
                None,
                generated_at=GENERATED_AT,
            )

    def test_invalid_projected_record_fails_before_contract_export(self):
        model, _store, _projection = build_model(["not a record"])

        with self.assertRaisesRegex(
            ValueError,
            "must be dictionaries",
        ):
            model.runtime_snapshot(
                [{"id": "raw"}],
                generated_at=GENERATED_AT,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
