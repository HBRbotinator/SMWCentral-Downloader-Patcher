"""Contracts for exact-pool Collection Wheel runtime handoff."""

from __future__ import annotations

import copy
import http.client
import json
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from wheel_runtime_bridge import (
    CollectionWheelRuntimeBridge,
    WheelRuntimeBridgeNotRunningError,
)
from wheel_runtime_contract import build_wheel_runtime_snapshot
from wheel_runtime_http import (
    WHEEL_RUNTIME_SNAPSHOT_PATH,
    WHEEL_RUNTIME_SPIN_PATH,
)


SNAPSHOT_TIME_ONE = datetime(
    2026,
    8,
    3,
    19,
    0,
    tzinfo=timezone.utc,
)
SNAPSHOT_TIME_TWO = datetime(
    2026,
    8,
    3,
    19,
    1,
    tzinfo=timezone.utc,
)
SPIN_TIME = datetime(
    2026,
    8,
    3,
    19,
    2,
    tzinfo=timezone.utc,
)


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class SequenceIds:
    def __init__(self, *values):
        self.values = list(values)
        self.index = 0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            value = self.values[self.index]
            self.index += 1
            return value


class RecordingModel:
    def __init__(self):
        self.calls = []
        self.fail_title = None

    def runtime_snapshot(
        self,
        records,
        *,
        generated_at,
        source_revision,
    ):
        detached = copy.deepcopy(list(records))
        self.calls.append(detached)
        if any(
            record.get("title") == self.fail_title
            for record in detached
        ):
            raise RuntimeError("Projected pool failed")

        candidates = [
            {
                "id": str(record["id"]),
                "title": str(record["title"]),
                "authors": copy.deepcopy(record.get("authors", [])),
                "type": str(record.get("type", "")),
                "difficulty": str(record.get("difficulty", "")),
                "completed": bool(record.get("completed", False)),
                "downloaded": bool(record.get("downloaded", False)),
                "smwc_rating": record.get("smwc_rating"),
                "release_year": record.get("release_year"),
                "planner": {
                    "lifecycle": "",
                    "horizon": "",
                    "list_ids": [],
                    "next_position": None,
                },
            }
            for record in detached
        ]
        return build_wheel_runtime_snapshot(
            candidates,
            generated_at=generated_at,
            source_revision=source_revision,
        )


def request(bridge, path):
    url = bridge.browser_url.removeprefix("http://")
    authority = url.split("/", 1)[0]
    host, port_text = authority.rsplit(":", 1)
    connection = http.client.HTTPConnection(
        host,
        int(port_text),
        timeout=5,
    )
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response, response.read()
    finally:
        connection.close()


class CollectionWheelRuntimeBridgeTest(unittest.TestCase):
    def setUp(self):
        self.model = RecordingModel()
        self.revision = "revision-1"
        self.snapshot_clock = MutableClock(SNAPSHOT_TIME_ONE)
        self.bridge = CollectionWheelRuntimeBridge(
            self.model,
            source_revision_supplier=lambda: self.revision,
            snapshot_clock=self.snapshot_clock,
            spin_clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds(
                "spin-1",
                "spin-2",
                "spin-3",
                "spin-4",
            ),
            port=0,
        )

    def tearDown(self):
        self.bridge.stop()

    def test_bridge_starts_stopped_with_no_staged_pool(self):
        status = self.bridge.status()

        self.assertFalse(self.bridge.running)
        self.assertEqual(status["active_pool_size"], 0)
        self.assertFalse(status["snapshot"]["ready"])
        with self.assertRaises(WheelRuntimeBridgeNotRunningError):
            _ = self.bridge.browser_url

    def test_stage_pool_is_detached_and_does_not_publish(self):
        source = [{"id": "one", "title": "One"}]

        staged = self.bridge.stage_pool(source)
        source[0]["title"] = "Changed source"
        staged[0]["title"] = "Changed return"

        status = self.bridge.status()
        self.assertEqual(status["active_pool_size"], 1)
        self.assertFalse(status["snapshot"]["ready"])
        self.assertEqual(self.model.calls, [])

    def test_start_publishes_exact_staged_pool_in_order(self):
        pool = [
            {"id": "two", "title": "Two"},
            {"id": "one", "title": "One"},
        ]

        url = self.bridge.start(pool)
        response, body = request(
            self.bridge,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )

        self.assertTrue(url.endswith("/wheel/"))
        self.assertEqual(response.status, 200)
        document = json.loads(body)
        self.assertEqual(
            [item["id"] for item in document["candidates"]],
            ["two", "one"],
        )
        self.assertEqual(self.bridge.status()["active_pool_size"], 2)

    def test_start_is_idempotent_without_republishing_pool(self):
        self.bridge.start([{"id": "one", "title": "One"}])
        calls = len(self.model.calls)

        first = self.bridge.browser_url
        second = self.bridge.start(
            [{"id": "ignored", "title": "Ignored"}]
        )

        self.assertEqual(first, second)
        self.assertEqual(len(self.model.calls), calls)
        response, body = request(
            self.bridge,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            json.loads(body)["candidates"][0]["id"],
            "one",
        )

    def test_refresh_pool_updates_exact_live_pool(self):
        self.bridge.start([{"id": "one", "title": "One"}])
        self.revision = "revision-2"
        self.snapshot_clock.value = SNAPSHOT_TIME_TWO

        refreshed = self.bridge.refresh_pool(
            [
                {"id": "three", "title": "Three"},
                {"id": "two", "title": "Two"},
            ]
        )
        response, body = request(
            self.bridge,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )

        self.assertEqual(refreshed["source"]["revision"], "revision-2")
        self.assertEqual(
            [item["id"] for item in json.loads(body)["candidates"]],
            ["three", "two"],
        )
        self.assertEqual(self.bridge.status()["active_pool_size"], 2)

    def test_refresh_requires_running_runtime(self):
        with self.assertRaises(WheelRuntimeBridgeNotRunningError):
            self.bridge.refresh_pool(
                [{"id": "one", "title": "One"}]
            )

    def test_publish_selection_refreshes_pool_before_spin(self):
        self.bridge.start([{"id": "old", "title": "Old"}])
        pool = [
            {"id": "one", "title": "One"},
            {"id": "two", "title": "Two"},
            {"id": "three", "title": "Three"},
        ]

        publication = self.bridge.publish_selection(
            pool,
            "two",
            duration_ms=1800,
            turns=5,
            landing_offset=0.5,
        )
        snapshot_response, snapshot_body = request(
            self.bridge,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )
        spin_response, spin_body = request(
            self.bridge,
            WHEEL_RUNTIME_SPIN_PATH,
        )

        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(spin_response.status, 200)
        self.assertEqual(
            json.loads(snapshot_body),
            publication["snapshot"],
        )
        self.assertEqual(
            json.loads(spin_body),
            publication["spin"],
        )
        self.assertEqual(
            publication["spin"]["winner"],
            {"id": "two", "title": "Two", "index": 1},
        )
        self.assertEqual(
            publication["spin"]["snapshot"]["candidate_count"],
            3,
        )

    def test_reroll_pool_can_exclude_previous_result(self):
        self.bridge.start(
            [
                {"id": "one", "title": "One"},
                {"id": "two", "title": "Two"},
                {"id": "three", "title": "Three"},
            ]
        )
        self.bridge.publish_selection(
            [
                {"id": "one", "title": "One"},
                {"id": "two", "title": "Two"},
                {"id": "three", "title": "Three"},
            ],
            "one",
        )

        reroll = self.bridge.publish_selection(
            [
                {"id": "two", "title": "Two"},
                {"id": "three", "title": "Three"},
            ],
            "three",
        )

        self.assertEqual(
            [item["id"] for item in reroll["snapshot"]["candidates"]],
            ["two", "three"],
        )
        self.assertEqual(
            reroll["spin"]["winner"]["index"],
            1,
        )
        self.assertEqual(
            reroll["spin"]["snapshot"]["candidate_count"],
            2,
        )

    def test_invalid_winner_preserves_prior_spin_on_new_valid_pool(self):
        self.bridge.start(
            [
                {"id": "one", "title": "One"},
                {"id": "two", "title": "Two"},
            ]
        )
        first = self.bridge.publish_selection(
            [
                {"id": "one", "title": "One"},
                {"id": "two", "title": "Two"},
            ],
            "one",
        )

        with self.assertRaisesRegex(
            ValueError,
            "is not in the snapshot",
        ):
            self.bridge.publish_selection(
                [{"id": "two", "title": "Two"}],
                "missing",
            )

        snapshot_response, snapshot_body = request(
            self.bridge,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )
        spin_response, spin_body = request(
            self.bridge,
            WHEEL_RUNTIME_SPIN_PATH,
        )

        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(
            [item["id"] for item in json.loads(snapshot_body)["candidates"]],
            ["two"],
        )
        self.assertEqual(spin_response.status, 200)
        self.assertEqual(json.loads(spin_body), first["spin"])

    def test_failed_refresh_rolls_back_staged_pool_and_cached_snapshot(self):
        original = [{"id": "one", "title": "One"}]
        self.bridge.start(original)
        self.model.fail_title = "Broken"

        with self.assertRaisesRegex(
            RuntimeError,
            "Projected pool failed",
        ):
            self.bridge.refresh_pool(
                [{"id": "broken", "title": "Broken"}]
            )

        response, body = request(
            self.bridge,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            [item["id"] for item in json.loads(body)["candidates"]],
            ["one"],
        )
        self.assertEqual(self.bridge.status()["active_pool_size"], 1)

    def test_concurrent_publications_are_serialized(self):
        pool = [
            {"id": "one", "title": "One"},
            {"id": "two", "title": "Two"},
        ]
        self.bridge.start(pool)
        publications = []
        failures = []

        def publish(winner_id):
            try:
                publications.append(
                    self.bridge.publish_selection(pool, winner_id)
                )
            except Exception as error:
                failures.append(error)

        threads = [
            threading.Thread(target=publish, args=(winner_id,))
            for winner_id in ("one", "two", "one")
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(
            sorted(item["spin"]["sequence"] for item in publications),
            [1, 2, 3],
        )
        self.assertEqual(
            self.bridge.status()["spin"]["successful_publications"],
            3,
        )

    def test_stop_is_repeatable_and_live_operations_fail_after_stop(self):
        self.bridge.start([{"id": "one", "title": "One"}])
        self.bridge.stop()
        self.bridge.stop()

        self.assertFalse(self.bridge.running)
        with self.assertRaises(WheelRuntimeBridgeNotRunningError):
            self.bridge.publish_selection(
                [{"id": "one", "title": "One"}],
                "one",
            )

    def test_pool_input_contract_is_strict(self):
        for invalid in (None, "pool", {"id": "one"}, 42):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.bridge.stage_pool(invalid)

        with self.assertRaisesRegex(
            TypeError,
            "record 1 must be a mapping",
        ):
            self.bridge.stage_pool(
                [{"id": "one", "title": "One"}, "bad"]
            )

    def test_bridge_does_not_select_persist_or_open_browser(self):
        source = Path("wheel_runtime_bridge.py").read_text(
            encoding="utf-8"
        )

        for forbidden in (
            "random.choice",
            ".select(",
            "selection_service",
            "open(",
            "write_text(",
            "write_bytes(",
            "webbrowser.open",
            "os.startfile",
            "subprocess",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
