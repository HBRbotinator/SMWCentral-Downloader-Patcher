"""Contracts for the versioned Wheel runtime snapshot."""

from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone

from wheel_runtime_contract import (
    WHEEL_RUNTIME_SCHEMA,
    WHEEL_RUNTIME_SCHEMA_VERSION,
    WheelRuntimeContractError,
    build_wheel_runtime_snapshot,
    serialize_wheel_runtime_snapshot,
    validate_wheel_runtime_snapshot,
)


GENERATED_AT = datetime(
    2026,
    8,
    3,
    15,
    30,
    45,
    987654,
    tzinfo=timezone.utc,
)


class WheelRuntimeContractTest(unittest.TestCase):
    def test_schema_identity_is_explicit_and_versioned(self):
        self.assertEqual(WHEEL_RUNTIME_SCHEMA, "smwc-wheel-runtime")
        self.assertEqual(WHEEL_RUNTIME_SCHEMA_VERSION, 1)

    def test_snapshot_normalizes_filter_and_display_metadata(self):
        snapshot = build_wheel_runtime_snapshot(
            [
                {
                    "id": 40226,
                    "title": "!Uppipe",
                    "authors": [
                        {"username": "ExampleMaker"},
                        {"name": "Second Maker"},
                        {"username": "examplemaker"},
                    ],
                    "type": "Kaizo",
                    "difficulty": "Intermediate",
                    "completed": True,
                    "file_path": r"C:\ROMs\Uppipe.sfc",
                    "rating": "4.5",
                    "date": "2025-07-14 12:00:00",
                    "planner_lifecycle": "Playing",
                    "planning_horizon": "Soon",
                    "planner_list_ids": ["stream", "stream"],
                    "planner_next_position": "2",
                }
            ],
            planner_lists=[
                {"id": "stream", "name": "Stream candidates"}
            ],
            generated_at=GENERATED_AT,
            source_revision="collection-17",
        )

        self.assertEqual(
            snapshot,
            {
                "schema": "smwc-wheel-runtime",
                "schema_version": 1,
                "generated_at": "2026-08-03T15:30:45Z",
                "source": {
                    "kind": "collection_snapshot",
                    "revision": "collection-17",
                },
                "planner": {
                    "available": True,
                    "lists": [
                        {
                            "id": "stream",
                            "name": "Stream candidates",
                        }
                    ],
                },
                "candidates": [
                    {
                        "id": "40226",
                        "title": "!Uppipe",
                        "authors": [
                            "ExampleMaker",
                            "Second Maker",
                        ],
                        "type": "Kaizo",
                        "difficulty": "Intermediate",
                        "completed": True,
                        "downloaded": True,
                        "smwc_rating": 4.5,
                        "release_year": 2025,
                        "planner": {
                            "lifecycle": "Playing",
                            "horizon": "Soon",
                            "list_ids": ["stream"],
                            "next_position": 2,
                        },
                    }
                ],
            },
        )

    def test_collection_only_snapshot_is_valid_without_planner(self):
        snapshot = build_wheel_runtime_snapshot(
            (
                {
                    "hack_id": "local-1",
                    "name": "Local Hack",
                    "download_status": "Not downloaded",
                    "rating": 0,
                    "personal_rating": 5,
                }
                for _ in range(1)
            ),
            generated_at="2026-08-03T17:30:45+02:00",
        )

        self.assertFalse(snapshot["planner"]["available"])
        self.assertEqual(snapshot["planner"]["lists"], [])
        self.assertEqual(
            snapshot["generated_at"],
            "2026-08-03T15:30:45Z",
        )
        candidate = snapshot["candidates"][0]
        self.assertFalse(candidate["downloaded"])
        self.assertIsNone(candidate["smwc_rating"])
        self.assertEqual(
            candidate["planner"],
            {
                "lifecycle": "",
                "horizon": "",
                "list_ids": [],
                "next_position": None,
            },
        )

    def test_snapshot_is_detached_from_inputs_and_consumers(self):
        candidate = {
            "id": "1",
            "title": "Detached",
            "authors": ["Maker"],
        }
        planner_list = {"id": "later", "name": "Later"}
        snapshot = build_wheel_runtime_snapshot(
            [candidate],
            planner_lists=[planner_list],
            planner_available=True,
            generated_at=GENERATED_AT,
        )

        candidate["title"] = "Mutated source"
        candidate["authors"].append("Other")
        planner_list["name"] = "Mutated list"
        snapshot["candidates"][0]["title"] = "Mutated snapshot"

        rebuilt = build_wheel_runtime_snapshot(
            [{"id": "1", "title": "Detached", "authors": ["Maker"]}],
            planner_lists=[{"id": "later", "name": "Later"}],
            planner_available=True,
            generated_at=GENERATED_AT,
        )
        validated = validate_wheel_runtime_snapshot(rebuilt)
        validated["candidates"][0]["title"] = "Mutated validation copy"

        self.assertEqual(rebuilt["candidates"][0]["title"], "Detached")
        self.assertEqual(rebuilt["planner"]["lists"][0]["name"], "Later")

    def test_contract_omits_paths_urls_notes_and_internal_payloads(self):
        snapshot = build_wheel_runtime_snapshot(
            [
                {
                    "id": "secret-safe",
                    "title": "Safe Candidate",
                    "file_path": r"C:\Users\Name\ROMs\safe.sfc",
                    "files": [
                        {"path": r"D:\Private\safe.sfc"}
                    ],
                    "save_path": r"C:\Saves\safe.srm",
                    "download_url": "https://example.invalid/private.zip",
                    "notes": "private note",
                    "description": "large catalogue text",
                    "raw_fields": {
                        "difficulty": "Expert",
                        "secret": "do not expose",
                    },
                    "personal_rating": 5,
                    "rating": 4.0,
                }
            ],
            generated_at=GENERATED_AT,
        )

        serialized = json.dumps(snapshot)
        for forbidden in (
            "C:\\Users",
            "D:\\Private",
            "C:\\Saves",
            "example.invalid",
            "private note",
            "large catalogue text",
            "do not expose",
            "personal_rating",
        ):
            self.assertNotIn(forbidden, serialized)

        candidate = snapshot["candidates"][0]
        self.assertTrue(candidate["downloaded"])
        self.assertEqual(candidate["difficulty"], "Expert")
        self.assertEqual(candidate["smwc_rating"], 4.0)

    def test_planner_availability_cannot_contradict_planner_data(self):
        with self.assertRaisesRegex(
            WheelRuntimeContractError,
            "planner_available cannot be false",
        ):
            build_wheel_runtime_snapshot(
                [
                    {
                        "id": "1",
                        "title": "Planned",
                        "planner_lifecycle": "Planned",
                    }
                ],
                planner_available=False,
                generated_at=GENERATED_AT,
            )

    def test_candidate_ids_are_required_and_unique(self):
        with self.assertRaisesRegex(
            WheelRuntimeContractError,
            "no stable ID",
        ):
            build_wheel_runtime_snapshot(
                [{"title": "Missing ID"}],
                generated_at=GENERATED_AT,
            )

        with self.assertRaisesRegex(
            WheelRuntimeContractError,
            "Duplicate candidate ID",
        ):
            build_wheel_runtime_snapshot(
                [
                    {"id": 7, "title": "First"},
                    {"id": "7", "title": "Second"},
                ],
                generated_at=GENERATED_AT,
            )

    def test_planner_lists_are_stable_and_referentially_valid(self):
        with self.assertRaisesRegex(
            WheelRuntimeContractError,
            "Duplicate Planner list ID",
        ):
            build_wheel_runtime_snapshot(
                [{"id": "1", "title": "Candidate"}],
                planner_lists=[
                    {"id": "same", "name": "One"},
                    {"id": "same", "name": "Two"},
                ],
                generated_at=GENERATED_AT,
            )

        with self.assertRaisesRegex(
            WheelRuntimeContractError,
            "unknown Planner list IDs",
        ):
            build_wheel_runtime_snapshot(
                [
                    {
                        "id": "1",
                        "title": "Candidate",
                        "planner_list_ids": ["missing"],
                    }
                ],
                planner_lists=[],
                generated_at=GENERATED_AT,
            )

    def test_generated_at_requires_timezone_and_is_canonical_utc(self):
        with self.assertRaisesRegex(
            WheelRuntimeContractError,
            "must include a timezone",
        ):
            build_wheel_runtime_snapshot(
                [],
                generated_at=datetime(2026, 8, 3, 15, 30),
            )

        local_time = GENERATED_AT.astimezone(
            timezone(timedelta(hours=2))
        )
        snapshot = build_wheel_runtime_snapshot(
            [],
            generated_at=local_time,
        )
        self.assertEqual(
            snapshot["generated_at"],
            "2026-08-03T15:30:45Z",
        )

    def test_validation_rejects_unknown_or_versioned_fields(self):
        snapshot = build_wheel_runtime_snapshot(
            [{"id": "1", "title": "Candidate"}],
            generated_at=GENERATED_AT,
        )

        wrong_version = copy.deepcopy(snapshot)
        wrong_version["schema_version"] = 2
        with self.assertRaisesRegex(
            WheelRuntimeContractError,
            "Unsupported Wheel runtime schema version",
        ):
            validate_wheel_runtime_snapshot(wrong_version)

        leaked_field = copy.deepcopy(snapshot)
        leaked_field["candidates"][0]["file_path"] = r"C:\ROMs\hack.sfc"
        with self.assertRaisesRegex(
            WheelRuntimeContractError,
            "unexpected file_path",
        ):
            validate_wheel_runtime_snapshot(leaked_field)

    def test_validation_returns_a_detached_document(self):
        snapshot = build_wheel_runtime_snapshot(
            [{"id": "1", "title": "Candidate"}],
            generated_at=GENERATED_AT,
        )

        validated = validate_wheel_runtime_snapshot(snapshot)
        validated["candidates"][0]["title"] = "Mutated"

        self.assertEqual(
            snapshot["candidates"][0]["title"],
            "Candidate",
        )

    def test_serialization_is_stable_unicode_json_with_final_newline(self):
        snapshot = build_wheel_runtime_snapshot(
            [
                {
                    "id": "1",
                    "title": "Äventyret",
                    "authors": ["Skapare"],
                }
            ],
            generated_at=GENERATED_AT,
        )

        first = serialize_wheel_runtime_snapshot(snapshot)
        second = serialize_wheel_runtime_snapshot(snapshot)

        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        self.assertIn("Äventyret", first)
        self.assertEqual(json.loads(first), snapshot)

    def test_serialization_rejects_invalid_indent(self):
        snapshot = build_wheel_runtime_snapshot(
            [],
            generated_at=GENERATED_AT,
        )

        for invalid in (True, -1, "2"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(TypeError):
                    serialize_wheel_runtime_snapshot(
                        snapshot,
                        indent=invalid,
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
