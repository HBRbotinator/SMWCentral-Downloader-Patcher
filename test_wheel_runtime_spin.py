"""Contracts for Python-authored Wheel runtime spin instructions."""

from __future__ import annotations

import copy
import json
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from wheel_runtime_contract import build_wheel_runtime_snapshot
from wheel_runtime_spin import (
    WHEEL_RUNTIME_SPIN_SCHEMA,
    WHEEL_RUNTIME_SPIN_SCHEMA_VERSION,
    WheelRuntimeSpinContractError,
    WheelRuntimeSpinCoordinator,
    WheelRuntimeSpinUnavailableError,
    build_wheel_runtime_spin,
    serialize_wheel_runtime_spin,
    validate_wheel_runtime_spin,
)


SNAPSHOT_TIME = datetime(
    2026,
    8,
    3,
    17,
    45,
    tzinfo=timezone.utc,
)
SPIN_TIME = datetime(
    2026,
    8,
    3,
    17,
    46,
    12,
    987654,
    tzinfo=timezone.utc,
)


def make_snapshot():
    return build_wheel_runtime_snapshot(
        [
            {"id": "alpha", "title": "Alpha"},
            {"id": "beta", "title": "Beta"},
            {"id": "gamma", "title": "Gamma"},
        ],
        generated_at=SNAPSHOT_TIME,
        source_revision="collection-24",
    )


class SnapshotProvider:
    def __init__(self, snapshot):
        self.snapshot = copy.deepcopy(snapshot)
        self.calls = 0

    def current_snapshot(self):
        self.calls += 1
        return copy.deepcopy(self.snapshot)


class SequenceIds:
    def __init__(self, *values):
        self.values = list(values)
        self.index = 0

    def __call__(self):
        value = self.values[self.index]
        self.index += 1
        return value


class WheelRuntimeSpinContractTest(unittest.TestCase):
    def test_schema_identity_is_explicit_and_versioned(self):
        self.assertEqual(WHEEL_RUNTIME_SPIN_SCHEMA, "smwc-wheel-spin")
        self.assertEqual(WHEEL_RUNTIME_SPIN_SCHEMA_VERSION, 1)

    def test_spin_binds_winner_to_exact_snapshot_position(self):
        spin = build_wheel_runtime_spin(
            make_snapshot(),
            "beta",
            spin_id="spin-1",
            sequence=7,
            issued_at=SPIN_TIME,
            duration_ms=7200,
            turns=8,
            landing_offset=0.42,
        )

        self.assertEqual(
            spin,
            {
                "schema": "smwc-wheel-spin",
                "schema_version": 1,
                "spin_id": "spin-1",
                "sequence": 7,
                "issued_at": "2026-08-03T17:46:12Z",
                "snapshot": {
                    "generated_at": "2026-08-03T17:45:00Z",
                    "source_revision": "collection-24",
                    "candidate_count": 3,
                },
                "winner": {
                    "id": "beta",
                    "title": "Beta",
                    "index": 1,
                },
                "animation": {
                    "duration_ms": 7200,
                    "turns": 8,
                    "landing_offset": 0.42,
                },
            },
        )

    def test_winner_must_exist_in_snapshot(self):
        with self.assertRaisesRegex(
            WheelRuntimeSpinContractError,
            "is not in the snapshot",
        ):
            build_wheel_runtime_spin(
                make_snapshot(),
                "missing",
                spin_id="spin-1",
                sequence=1,
                issued_at=SPIN_TIME,
            )

    def test_validation_rejects_unknown_fields_and_versions(self):
        spin = build_wheel_runtime_spin(
            make_snapshot(),
            "alpha",
            spin_id="spin-1",
            sequence=1,
            issued_at=SPIN_TIME,
        )

        wrong_version = copy.deepcopy(spin)
        wrong_version["schema_version"] = 2
        with self.assertRaisesRegex(
            WheelRuntimeSpinContractError,
            "Unsupported Wheel spin schema version",
        ):
            validate_wheel_runtime_spin(wrong_version)

        leaked = copy.deepcopy(spin)
        leaked["winner"]["file_path"] = r"C:\Private\alpha.sfc"
        with self.assertRaisesRegex(
            WheelRuntimeSpinContractError,
            "unexpected file_path",
        ):
            validate_wheel_runtime_spin(leaked)

    def test_animation_parameters_are_bounded(self):
        cases = (
            {"duration_ms": 999},
            {"duration_ms": 30001},
            {"turns": 0},
            {"turns": 21},
            {"landing_offset": 0},
            {"landing_offset": 1},
            {"landing_offset": float("nan")},
        )
        for options in cases:
            with self.subTest(options=options):
                with self.assertRaises(WheelRuntimeSpinContractError):
                    build_wheel_runtime_spin(
                        make_snapshot(),
                        "alpha",
                        spin_id="spin-1",
                        sequence=1,
                        issued_at=SPIN_TIME,
                        **options,
                    )

    def test_serialization_is_stable_unicode_json(self):
        snapshot = build_wheel_runtime_snapshot(
            [{"id": "one", "title": "Äventyret"}],
            generated_at=SNAPSHOT_TIME,
        )
        spin = build_wheel_runtime_spin(
            snapshot,
            "one",
            spin_id="spin-1",
            sequence=1,
            issued_at=SPIN_TIME,
        )

        first = serialize_wheel_runtime_spin(spin)
        second = serialize_wheel_runtime_spin(spin)

        self.assertEqual(first, second)
        self.assertTrue(first.endswith("\n"))
        self.assertIn("Äventyret", first)
        self.assertEqual(json.loads(first), spin)

    def test_validation_and_serialization_are_detached(self):
        spin = build_wheel_runtime_spin(
            make_snapshot(),
            "alpha",
            spin_id="spin-1",
            sequence=1,
            issued_at=SPIN_TIME,
        )
        validated = validate_wheel_runtime_spin(spin)
        validated["winner"]["title"] = "Changed"

        self.assertEqual(spin["winner"]["title"], "Alpha")


class WheelRuntimeSpinCoordinatorTest(unittest.TestCase):
    def test_coordinator_starts_unavailable(self):
        coordinator = WheelRuntimeSpinCoordinator(
            SnapshotProvider(make_snapshot())
        )

        self.assertFalse(coordinator.ready)
        self.assertEqual(
            coordinator.status(),
            {
                "ready": False,
                "successful_publications": 0,
                "sequence": None,
                "spin_id": None,
                "issued_at": None,
                "winner_id": None,
                "winner_title": None,
                "snapshot_generated_at": None,
                "source_revision": None,
                "last_error": None,
            },
        )
        with self.assertRaises(WheelRuntimeSpinUnavailableError):
            coordinator.current_spin()
        with self.assertRaises(WheelRuntimeSpinUnavailableError):
            coordinator.current_json()

    def test_publish_uses_provider_and_injected_python_metadata(self):
        provider = SnapshotProvider(make_snapshot())
        coordinator = WheelRuntimeSpinCoordinator(
            provider,
            clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds("spin-a"),
        )

        spin = coordinator.publish_winner(
            "gamma",
            duration_ms=8000,
            turns=9,
            landing_offset=0.37,
        )

        self.assertEqual(provider.calls, 1)
        self.assertEqual(spin["spin_id"], "spin-a")
        self.assertEqual(spin["sequence"], 1)
        self.assertEqual(spin["winner"]["id"], "gamma")
        self.assertEqual(spin["winner"]["index"], 2)
        self.assertEqual(spin["animation"]["turns"], 9)

    def test_publications_are_monotonic_and_replace_atomically(self):
        coordinator = WheelRuntimeSpinCoordinator(
            SnapshotProvider(make_snapshot()),
            clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds("spin-a", "spin-b"),
        )

        first = coordinator.publish_winner("alpha")
        second = coordinator.publish_winner("beta")

        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)
        self.assertEqual(
            coordinator.current_spin()["winner"]["id"],
            "beta",
        )
        self.assertEqual(
            json.loads(coordinator.current_json()),
            coordinator.current_spin(),
        )
        self.assertEqual(
            coordinator.status()["successful_publications"],
            2,
        )

    def test_reads_are_detached(self):
        coordinator = WheelRuntimeSpinCoordinator(
            SnapshotProvider(make_snapshot()),
            clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds("spin-a"),
        )
        coordinator.publish_winner("alpha")

        first = coordinator.current_spin()
        first["winner"]["title"] = "Mutated"

        self.assertEqual(
            coordinator.current_spin()["winner"]["title"],
            "Alpha",
        )

    def test_failed_publication_preserves_last_valid_spin(self):
        coordinator = WheelRuntimeSpinCoordinator(
            SnapshotProvider(make_snapshot()),
            clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds("spin-a", "spin-b"),
        )
        first = coordinator.publish_winner("alpha")
        first_json = coordinator.current_json()

        with self.assertRaises(WheelRuntimeSpinContractError):
            coordinator.publish_winner("missing")

        self.assertEqual(coordinator.current_spin(), first)
        self.assertEqual(coordinator.current_json(), first_json)
        self.assertEqual(
            coordinator.status()["successful_publications"],
            1,
        )
        self.assertIn(
            "WheelRuntimeSpinContractError",
            coordinator.status()["last_error"],
        )

    def test_success_clears_previous_error(self):
        coordinator = WheelRuntimeSpinCoordinator(
            SnapshotProvider(make_snapshot()),
            clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds(
                "spin-bad",
                "spin-good",
            ),
        )

        with self.assertRaises(WheelRuntimeSpinContractError):
            coordinator.publish_winner("missing")
        coordinator.publish_winner("alpha")

        self.assertIsNone(coordinator.status()["last_error"])
        self.assertEqual(
            coordinator.current_spin()["sequence"],
            1,
        )

    def test_concurrent_publishers_keep_complete_monotonic_state(self):
        identifiers = [f"spin-{index}" for index in range(12)]
        coordinator = WheelRuntimeSpinCoordinator(
            SnapshotProvider(make_snapshot()),
            clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds(*identifiers),
        )
        results = []
        failures = []

        def publish(winner_id):
            try:
                results.append(
                    coordinator.publish_winner(winner_id)
                )
            except Exception as error:
                failures.append(error)

        winners = ["alpha", "beta", "gamma"] * 4
        threads = [
            threading.Thread(target=publish, args=(winner_id,))
            for winner_id in winners
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(
            sorted(item["sequence"] for item in results),
            list(range(1, 13)),
        )
        self.assertEqual(
            coordinator.status()["successful_publications"],
            12,
        )
        self.assertEqual(
            coordinator.current_spin()["sequence"],
            12,
        )

    def test_coordinator_does_not_select_persist_or_serve(self):
        source = Path("wheel_runtime_spin.py").read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "random.choice",
            ".select(",
            "selection_service",
            "open(",
            "write_text(",
            "write_bytes(",
            "HTTPServer",
            "serve_forever",
            "WebSocket",
        ):
            self.assertNotIn(forbidden, source)

    def test_dependencies_are_validated(self):
        with self.assertRaises(TypeError):
            WheelRuntimeSpinCoordinator(object())
        with self.assertRaises(TypeError):
            WheelRuntimeSpinCoordinator(
                SnapshotProvider(make_snapshot()),
                clock=SPIN_TIME,
            )
        with self.assertRaises(TypeError):
            WheelRuntimeSpinCoordinator(
                SnapshotProvider(make_snapshot()),
                spin_id_supplier="spin",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
