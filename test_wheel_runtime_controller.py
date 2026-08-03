"""Contracts for the application-managed Wheel runtime lifecycle."""

from __future__ import annotations

import copy
import http.client
import json
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path

from wheel_runtime_controller import (
    WheelRuntimeController,
    build_managed_wheel_runtime,
)
from wheel_runtime_http import (
    WHEEL_RUNTIME_HEALTH_PATH,
    WHEEL_RUNTIME_SNAPSHOT_PATH,
    WHEEL_RUNTIME_SPIN_PATH,
)


SNAPSHOT_TIME_ONE = datetime(
    2026,
    8,
    3,
    18,
    0,
    tzinfo=timezone.utc,
)
SNAPSHOT_TIME_TWO = datetime(
    2026,
    8,
    3,
    18,
    1,
    tzinfo=timezone.utc,
)
SPIN_TIME = datetime(
    2026,
    8,
    3,
    18,
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

    def __call__(self):
        value = self.values[self.index]
        self.index += 1
        return value


class RecordingModel:
    def __init__(self):
        self.calls = []

    def runtime_snapshot(
        self,
        records,
        *,
        generated_at,
        source_revision,
    ):
        self.calls.append(
            {
                "records": copy.deepcopy(records),
                "generated_at": generated_at,
                "source_revision": source_revision,
            }
        )
        candidates = []
        for record in records:
            candidates.append(
                {
                    "id": str(record["id"]),
                    "title": str(record["title"]),
                    "authors": [],
                    "type": "",
                    "difficulty": "",
                    "completed": False,
                    "downloaded": False,
                    "smwc_rating": None,
                    "release_year": None,
                    "planner": {
                        "lifecycle": "",
                        "horizon": "",
                        "list_ids": [],
                        "next_position": None,
                    },
                }
            )
        timestamp = (
            generated_at.astimezone(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
        return {
            "schema": "smwc-wheel-runtime",
            "schema_version": 1,
            "generated_at": timestamp,
            "source": {
                "kind": "collection_snapshot",
                "revision": source_revision,
            },
            "planner": {
                "available": False,
                "lists": [],
            },
            "candidates": candidates,
        }


def request(controller, path):
    url = controller.browser_url.removeprefix("http://")
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
        body = response.read()
        return response, body
    finally:
        connection.close()


class ManagedWheelRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.records = [
            {"id": "one", "title": "One"},
            {"id": "two", "title": "Two"},
        ]
        self.revision = "revision-1"
        self.model = RecordingModel()
        self.snapshot_clock = MutableClock(SNAPSHOT_TIME_ONE)
        self.controller = build_managed_wheel_runtime(
            self.model,
            lambda: copy.deepcopy(self.records),
            source_revision_supplier=lambda: self.revision,
            snapshot_clock=self.snapshot_clock,
            spin_clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds("spin-1", "spin-2"),
            port=0,
        )

    def tearDown(self):
        self.controller.stop()

    def test_runtime_starts_stopped_with_detached_status(self):
        status = self.controller.status()

        self.assertFalse(self.controller.running)
        self.assertFalse(status["running"])
        self.assertIsNone(status["browser_url"])
        self.assertFalse(status["snapshot"]["ready"])
        self.assertFalse(status["spin"]["ready"])
        status["snapshot"]["candidate_count"] = 999
        self.assertEqual(
            self.controller.status()["snapshot"]["candidate_count"],
            0,
        )
        with self.assertRaisesRegex(RuntimeError, "is not running"):
            _ = self.controller.browser_url

    def test_start_refreshes_before_serving_browser(self):
        browser_url = self.controller.start()

        self.assertTrue(self.controller.running)
        self.assertEqual(browser_url, self.controller.browser_url)
        self.assertTrue(browser_url.endswith("/wheel/"))
        self.assertEqual(len(self.model.calls), 1)

        health_response, health_body = request(
            self.controller,
            WHEEL_RUNTIME_HEALTH_PATH,
        )
        snapshot_response, snapshot_body = request(
            self.controller,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )

        self.assertEqual(health_response.status, 200)
        self.assertTrue(
            json.loads(health_body)["snapshot"]["ready"]
        )
        self.assertEqual(snapshot_response.status, 200)
        self.assertEqual(
            [
                item["id"]
                for item in json.loads(snapshot_body)["candidates"]
            ],
            ["one", "two"],
        )

    def test_start_is_idempotent_without_duplicate_refresh(self):
        first = self.controller.start()
        second = self.controller.start()

        self.assertEqual(first, second)
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(
            self.controller.status()["snapshot"]["successful_refreshes"],
            1,
        )

    def test_failed_initial_refresh_does_not_start_service(self):
        class FailingModel:
            def runtime_snapshot(self, *_args, **_kwargs):
                raise RuntimeError("Collection unavailable")

        controller = build_managed_wheel_runtime(
            FailingModel(),
            lambda: [],
            snapshot_clock=lambda: SNAPSHOT_TIME_ONE,
            port=0,
        )
        try:
            with self.assertRaisesRegex(
                RuntimeError,
                "Collection unavailable",
            ):
                controller.start()
            self.assertFalse(controller.running)
        finally:
            controller.stop()

    def test_explicit_refresh_updates_live_snapshot(self):
        self.controller.start()
        self.records = [{"id": "three", "title": "Three"}]
        self.revision = "revision-2"
        self.snapshot_clock.value = SNAPSHOT_TIME_TWO

        refreshed = self.controller.refresh_snapshot()
        response, body = request(
            self.controller,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )

        self.assertEqual(refreshed["source"]["revision"], "revision-2")
        self.assertEqual(
            refreshed["generated_at"],
            "2026-08-03T18:01:00Z",
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(
            json.loads(body)["candidates"][0]["id"],
            "three",
        )

    def test_publish_winner_exposes_python_authored_spin(self):
        self.controller.start()

        published = self.controller.publish_winner(
            "two",
            duration_ms=7200,
            turns=8,
            landing_offset=0.4,
        )
        response, body = request(
            self.controller,
            WHEEL_RUNTIME_SPIN_PATH,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body), published)
        self.assertEqual(published["winner"]["id"], "two")
        self.assertEqual(published["winner"]["index"], 1)
        self.assertEqual(published["animation"]["turns"], 8)

    def test_publish_does_not_refresh_or_select_again(self):
        self.controller.start()
        calls_before = len(self.model.calls)

        first = self.controller.publish_winner("one")
        second = self.controller.publish_winner("two")

        self.assertEqual(len(self.model.calls), calls_before)
        self.assertEqual(first["sequence"], 1)
        self.assertEqual(second["sequence"], 2)

    def test_unknown_winner_preserves_prior_publication(self):
        self.controller.start()
        first = self.controller.publish_winner("one")

        with self.assertRaisesRegex(ValueError, "is not in the snapshot"):
            self.controller.publish_winner("missing")

        response, body = request(
            self.controller,
            WHEEL_RUNTIME_SPIN_PATH,
        )
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body), first)

    def test_stop_is_repeatable_and_hides_browser_url(self):
        self.controller.start()
        self.controller.stop()
        self.controller.stop()

        self.assertFalse(self.controller.running)
        self.assertIsNone(self.controller.status()["browser_url"])
        with self.assertRaises(RuntimeError):
            _ = self.controller.browser_url

    def test_context_manager_controls_complete_lifecycle(self):
        controller = build_managed_wheel_runtime(
            self.model,
            lambda: copy.deepcopy(self.records),
            snapshot_clock=lambda: SNAPSHOT_TIME_ONE,
            spin_clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds("context-spin"),
            port=0,
        )

        with controller as managed:
            self.assertIs(managed, controller)
            self.assertTrue(controller.running)
            response, _body = request(
                controller,
                WHEEL_RUNTIME_HEALTH_PATH,
            )
            self.assertEqual(response.status, 200)

        self.assertFalse(controller.running)

    def test_concurrent_status_reads_are_complete(self):
        self.controller.start()
        self.controller.publish_winner("one")
        statuses = []
        failures = []

        def read_status():
            try:
                statuses.append(self.controller.status())
            except Exception as error:
                failures.append(error)

        threads = [
            threading.Thread(target=read_status)
            for _ in range(12)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(len(statuses), 12)
        self.assertTrue(all(item["running"] for item in statuses))
        self.assertTrue(
            all(
                item["spin"]["winner_id"] == "one"
                for item in statuses
            )
        )

    def test_controller_does_not_select_persist_or_launch_browser(self):
        source = Path("wheel_runtime_controller.py").read_text(
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
            "subprocess",
            "os.startfile",
        ):
            self.assertNotIn(forbidden, source)

    def test_constructor_rejects_missing_collaborator_contracts(self):
        with self.assertRaises(TypeError):
            WheelRuntimeController(
                object(),
                object(),
                object(),
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
