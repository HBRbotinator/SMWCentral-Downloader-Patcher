"""Contracts for the in-memory Wheel runtime snapshot provider."""

from __future__ import annotations

import copy
import json
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from wheel_runtime_contract import build_wheel_runtime_snapshot
from wheel_runtime_snapshot_provider import (
    CollectionWheelRuntimeSnapshotSource,
    WheelRuntimeSnapshotProvider,
    WheelRuntimeSnapshotUnavailableError,
)


FIRST_TIME = datetime(2026, 8, 3, 16, 30, tzinfo=timezone.utc)
SECOND_TIME = datetime(2026, 8, 3, 16, 31, tzinfo=timezone.utc)


def make_snapshot(
    candidate_id="one",
    *,
    title="One",
    generated_at=FIRST_TIME,
    revision="revision-1",
    planner_available=False,
):
    return build_wheel_runtime_snapshot(
        [{"id": candidate_id, "title": title}],
        planner_available=planner_available,
        generated_at=generated_at,
        source_revision=revision,
    )


class RecordingModel:
    def __init__(self, result):
        self.result = copy.deepcopy(result)
        self.calls = []

    def runtime_snapshot(self, records, **options):
        self.calls.append((records, options))
        return copy.deepcopy(self.result)


class SequenceSource:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        if isinstance(outcome, BaseException):
            raise outcome
        return copy.deepcopy(outcome)


class SnapshotSourceTest(unittest.TestCase):
    def test_source_reads_live_inputs_once(self):
        expected = make_snapshot()
        model = RecordingModel(expected)
        collection_calls = []
        revision_calls = []
        source = CollectionWheelRuntimeSnapshotSource(
            model,
            lambda: collection_calls.append(1) or [{"id": "raw"}],
            source_revision_supplier=lambda: (
                revision_calls.append(1) or "processed-42"
            ),
            clock=lambda: SECOND_TIME,
        )

        self.assertEqual(source(), expected)
        self.assertEqual(collection_calls, [1])
        self.assertEqual(revision_calls, [1])
        self.assertEqual(
            model.calls[0][1],
            {
                "generated_at": SECOND_TIME,
                "source_revision": "processed-42",
            },
        )

    def test_source_validates_dependencies(self):
        with self.assertRaises(TypeError):
            CollectionWheelRuntimeSnapshotSource(object(), lambda: [])
        with self.assertRaises(TypeError):
            CollectionWheelRuntimeSnapshotSource(
                RecordingModel(make_snapshot()),
                [],
            )
        with self.assertRaises(TypeError):
            CollectionWheelRuntimeSnapshotSource(
                RecordingModel(make_snapshot()),
                lambda: [],
                source_revision_supplier="bad",
            )


class SnapshotProviderTest(unittest.TestCase):
    def test_provider_starts_unavailable(self):
        provider = WheelRuntimeSnapshotProvider(
            SequenceSource(make_snapshot())
        )
        self.assertFalse(provider.ready)
        self.assertEqual(provider.status()["candidate_count"], 0)
        with self.assertRaises(WheelRuntimeSnapshotUnavailableError):
            provider.current_snapshot()
        with self.assertRaises(WheelRuntimeSnapshotUnavailableError):
            provider.current_json()

    def test_refresh_caches_detached_snapshot_and_json(self):
        original = make_snapshot()
        provider = WheelRuntimeSnapshotProvider(SequenceSource(original))

        returned = provider.refresh()
        returned["candidates"][0]["title"] = "Changed"
        original["candidates"][0]["title"] = "Changed input"

        current = provider.current_snapshot()
        self.assertEqual(current["candidates"][0]["title"], "One")
        self.assertEqual(json.loads(provider.current_json()), current)
        self.assertTrue(provider.current_json().endswith("\n"))

    def test_each_snapshot_read_is_detached(self):
        provider = WheelRuntimeSnapshotProvider(
            SequenceSource(make_snapshot())
        )
        provider.refresh()
        first = provider.current_snapshot()
        first["candidates"][0]["title"] = "Mutated"
        self.assertEqual(
            provider.current_snapshot()["candidates"][0]["title"],
            "One",
        )

    def test_successful_refresh_replaces_cache_and_status(self):
        provider = WheelRuntimeSnapshotProvider(
            SequenceSource(
                make_snapshot(),
                make_snapshot(
                    "two",
                    title="Two",
                    generated_at=SECOND_TIME,
                    revision="revision-2",
                    planner_available=True,
                ),
            )
        )
        provider.refresh()
        provider.refresh()

        self.assertEqual(
            provider.current_snapshot()["candidates"][0]["id"],
            "two",
        )
        self.assertEqual(
            provider.status(),
            {
                "ready": True,
                "successful_refreshes": 2,
                "generated_at": "2026-08-03T16:31:00Z",
                "source_revision": "revision-2",
                "candidate_count": 1,
                "planner_available": True,
                "last_error": None,
            },
        )

    def test_failed_initial_refresh_remains_unavailable(self):
        provider = WheelRuntimeSnapshotProvider(
            SequenceSource(RuntimeError("source unavailable"))
        )
        with self.assertRaisesRegex(RuntimeError, "source unavailable"):
            provider.refresh()

        self.assertFalse(provider.ready)
        self.assertEqual(
            provider.status()["last_error"],
            "RuntimeError: source unavailable",
        )

    def test_failed_later_refresh_preserves_last_valid_cache(self):
        provider = WheelRuntimeSnapshotProvider(
            SequenceSource(
                make_snapshot(),
                RuntimeError("temporary failure"),
            )
        )
        first = provider.refresh()
        first_json = provider.current_json()

        with self.assertRaisesRegex(RuntimeError, "temporary failure"):
            provider.refresh()

        self.assertEqual(provider.current_snapshot(), first)
        self.assertEqual(provider.current_json(), first_json)
        self.assertEqual(provider.status()["successful_refreshes"], 1)

    def test_invalid_contract_never_replaces_cache(self):
        valid = make_snapshot()
        invalid = copy.deepcopy(valid)
        invalid["schema_version"] = 99
        provider = WheelRuntimeSnapshotProvider(
            SequenceSource(valid, invalid)
        )
        provider.refresh()

        with self.assertRaisesRegex(
            ValueError,
            "Unsupported Wheel runtime schema version",
        ):
            provider.refresh()

        self.assertEqual(
            provider.current_snapshot()["schema_version"],
            1,
        )

    def test_success_clears_previous_error(self):
        provider = WheelRuntimeSnapshotProvider(
            SequenceSource(RuntimeError("first"), make_snapshot())
        )
        with self.assertRaises(RuntimeError):
            provider.refresh()
        provider.refresh()
        self.assertIsNone(provider.status()["last_error"])

    def test_concurrent_readers_receive_consistent_documents(self):
        provider = WheelRuntimeSnapshotProvider(
            SequenceSource(make_snapshot())
        )
        provider.refresh()
        results = []
        failures = []

        def read():
            try:
                item = provider.current_snapshot()
                item["candidates"][0]["title"] = threading.current_thread().name
                results.append(
                    json.loads(provider.current_json())["candidates"][0]["title"]
                )
            except Exception as error:
                failures.append(error)

        threads = [
            threading.Thread(target=read, name=f"reader-{index}")
            for index in range(8)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(results, ["One"] * 8)

    def test_provider_has_no_file_or_server_side_effects(self):
        source = Path("wheel_runtime_snapshot_provider.py").read_text(
            encoding="utf-8"
        )
        for forbidden in (
            "open(",
            "write_text(",
            "write_bytes(",
            "HTTPServer",
            "socketserver",
            "serve_forever",
        ):
            self.assertNotIn(forbidden, source)

    def test_provider_requires_callable_source(self):
        with self.assertRaises(TypeError):
            WheelRuntimeSnapshotProvider(make_snapshot())


if __name__ == "__main__":
    unittest.main(verbosity=2)
