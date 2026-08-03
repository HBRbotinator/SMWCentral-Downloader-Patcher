"""HTTP contracts for snapshot and Python-authored spin state."""

from __future__ import annotations

import copy
import http.client
import json
import threading
import unittest
from datetime import datetime, timezone

from wheel_runtime_browser import (
    WHEEL_RUNTIME_BROWSER_PATH,
    WHEEL_RUNTIME_BROWSER_SCRIPT_PATH,
    WHEEL_RUNTIME_BROWSER_STYLE_PATH,
)
from wheel_runtime_contract import build_wheel_runtime_snapshot
from wheel_runtime_http import (
    WHEEL_RUNTIME_HEALTH_PATH,
    WHEEL_RUNTIME_SNAPSHOT_PATH,
    WHEEL_RUNTIME_SPIN_PATH,
    WheelRuntimeHttpService,
)
from wheel_runtime_snapshot_provider import (
    WheelRuntimeSnapshotProvider,
)
from wheel_runtime_spin import WheelRuntimeSpinCoordinator


GENERATED_AT = datetime(
    2026,
    8,
    3,
    17,
    30,
    tzinfo=timezone.utc,
)
SPIN_TIME = datetime(
    2026,
    8,
    3,
    17,
    31,
    tzinfo=timezone.utc,
)


def make_snapshot():
    return build_wheel_runtime_snapshot(
        [
            {"id": "one", "title": "One"},
            {"id": "two", "title": "Two"},
        ],
        generated_at=GENERATED_AT,
        source_revision="revision-1",
    )


class StaticSource:
    def __init__(self, document):
        self.document = copy.deepcopy(document)

    def __call__(self):
        return copy.deepcopy(self.document)


class SequenceIds:
    def __init__(self, *values):
        self.values = list(values)
        self.index = 0

    def __call__(self):
        value = self.values[self.index]
        self.index += 1
        return value


def request(service, method, path):
    host, port = service.address
    connection = http.client.HTTPConnection(host, port, timeout=5)
    try:
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        return response, body
    finally:
        connection.close()


class WheelRuntimeHttpServiceTest(unittest.TestCase):
    def setUp(self):
        self.provider = WheelRuntimeSnapshotProvider(
            StaticSource(make_snapshot())
        )
        self.coordinator = WheelRuntimeSpinCoordinator(
            self.provider,
            clock=lambda: SPIN_TIME,
            spin_id_supplier=SequenceIds("spin-1", "spin-2"),
        )
        self.service = WheelRuntimeHttpService(
            self.provider,
            spin_coordinator=self.coordinator,
            port=0,
        )
        self.service.start()

    def tearDown(self):
        self.service.stop()

    def test_health_reports_snapshot_and_spin_readiness(self):
        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_HEALTH_PATH,
        )

        self.assertEqual(response.status, 200)
        document = json.loads(body)
        self.assertTrue(document["read_only"])
        self.assertFalse(document["snapshot"]["ready"])
        self.assertTrue(document["spin"]["configured"])
        self.assertFalse(document["spin"]["ready"])
        self.assertEqual(
            document["spin"]["successful_publications"],
            0,
        )

    def test_unconfigured_service_reports_spin_boundary(self):
        service = WheelRuntimeHttpService(self.provider, port=0)
        service.start()
        try:
            health_response, health_body = request(
                service,
                "GET",
                WHEEL_RUNTIME_HEALTH_PATH,
            )
            spin_response, spin_body = request(
                service,
                "GET",
                WHEEL_RUNTIME_SPIN_PATH,
            )
        finally:
            service.stop()

        self.assertEqual(health_response.status, 200)
        self.assertFalse(
            json.loads(health_body)["spin"]["configured"]
        )
        self.assertEqual(spin_response.status, 503)
        self.assertEqual(
            json.loads(spin_body)["error"]["code"],
            "spin_runtime_unavailable",
        )

    def test_spin_returns_503_until_python_publishes_winner(self):
        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_SPIN_PATH,
        )

        self.assertEqual(response.status, 503)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "spin_unavailable",
        )

    def test_spin_returns_exact_coordinator_json_after_publication(self):
        self.provider.refresh()
        published = self.coordinator.publish_winner("two")

        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_SPIN_PATH,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body), published)
        self.assertEqual(body.decode("utf-8"), self.coordinator.current_json())
        self.assertTrue(body.endswith(b"\n"))

    def test_spin_head_returns_headers_without_body(self):
        self.provider.refresh()
        self.coordinator.publish_winner("one")

        response, body = request(
            self.service,
            "HEAD",
            WHEEL_RUNTIME_SPIN_PATH,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(int(response.getheader("Content-Length")), 0)

    def test_health_reflects_latest_published_spin(self):
        self.provider.refresh()
        self.coordinator.publish_winner("two")

        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_HEALTH_PATH,
        )

        spin = json.loads(body)["spin"]
        self.assertTrue(spin["ready"])
        self.assertEqual(spin["sequence"], 1)
        self.assertEqual(spin["spin_id"], "spin-1")
        self.assertEqual(spin["winner_id"], "two")
        self.assertEqual(spin["winner_title"], "Two")

    def test_get_requests_never_publish_or_change_spin_state(self):
        self.provider.refresh()
        self.coordinator.publish_winner("one")
        before = self.coordinator.current_json()

        for path in (
            WHEEL_RUNTIME_HEALTH_PATH,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
            WHEEL_RUNTIME_SPIN_PATH,
            WHEEL_RUNTIME_BROWSER_PATH,
        ):
            response, _body = request(self.service, "GET", path)
            self.assertEqual(response.status, 200)

        self.assertEqual(self.coordinator.current_json(), before)
        self.assertEqual(
            self.coordinator.status()["successful_publications"],
            1,
        )

    def test_snapshot_routes_remain_unchanged(self):
        unavailable, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )
        self.assertEqual(unavailable.status, 503)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "snapshot_unavailable",
        )

        expected = self.provider.refresh()
        available, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )
        self.assertEqual(available.status, 200)
        self.assertEqual(json.loads(body), expected)

    def test_browser_page_and_assets_remain_available(self):
        expected = {
            WHEEL_RUNTIME_BROWSER_PATH: "text/html; charset=utf-8",
            WHEEL_RUNTIME_BROWSER_STYLE_PATH: "text/css; charset=utf-8",
            WHEEL_RUNTIME_BROWSER_SCRIPT_PATH: (
                "text/javascript; charset=utf-8"
            ),
        }
        for path, content_type in expected.items():
            with self.subTest(path=path):
                response, body = request(self.service, "GET", path)
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.getheader("Content-Type"),
                    content_type,
                )
                self.assertGreater(len(body), 100)

    def test_mutating_methods_are_rejected_for_every_surface(self):
        for path in (
            WHEEL_RUNTIME_SNAPSHOT_PATH,
            WHEEL_RUNTIME_SPIN_PATH,
            WHEEL_RUNTIME_BROWSER_PATH,
        ):
            for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
                with self.subTest(path=path, method=method):
                    response, body = request(
                        self.service,
                        method,
                        path,
                    )
                    self.assertEqual(response.status, 405)
                    self.assertEqual(
                        response.getheader("Allow"),
                        "GET, HEAD",
                    )
                    self.assertEqual(
                        json.loads(body)["error"]["code"],
                        "method_not_allowed",
                    )

    def test_all_state_responses_disable_caching(self):
        self.provider.refresh()
        self.coordinator.publish_winner("one")

        for path in (
            WHEEL_RUNTIME_HEALTH_PATH,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
            WHEEL_RUNTIME_SPIN_PATH,
        ):
            with self.subTest(path=path):
                response, _body = request(
                    self.service,
                    "GET",
                    path,
                )
                self.assertEqual(
                    response.getheader("Cache-Control"),
                    "no-store",
                )
                self.assertEqual(
                    response.getheader("X-Content-Type-Options"),
                    "nosniff",
                )

    def test_concurrent_spin_readers_receive_complete_json(self):
        self.provider.refresh()
        expected = self.coordinator.publish_winner("two")
        documents = []
        failures = []

        def read_spin():
            try:
                response, body = request(
                    self.service,
                    "GET",
                    WHEEL_RUNTIME_SPIN_PATH,
                )
                if response.status != 200:
                    raise AssertionError(response.status)
                documents.append(json.loads(body))
            except Exception as error:
                failures.append(error)

        threads = [
            threading.Thread(target=read_spin)
            for _ in range(12)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(documents, [expected] * 12)

    def test_unknown_path_returns_json_404(self):
        response, body = request(
            self.service,
            "GET",
            "/api/v1/spins",
        )

        self.assertEqual(response.status, 404)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "not_found",
        )

    def test_start_and_stop_remain_repeatable(self):
        first = self.service.address
        self.assertEqual(self.service.start(), first)
        self.service.stop()
        self.service.stop()
        self.assertFalse(self.service.running)

    def test_service_rejects_invalid_spin_coordinator(self):
        for coordinator in (object(), "spin", 17):
            with self.subTest(coordinator=coordinator):
                with self.assertRaises(TypeError):
                    WheelRuntimeHttpService(
                        self.provider,
                        spin_coordinator=coordinator,
                        port=0,
                    )

    def test_service_still_rejects_non_loopback_bindings(self):
        for host in ("0.0.0.0", "192.168.1.10", "", "::1"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    WheelRuntimeHttpService(
                        self.provider,
                        spin_coordinator=self.coordinator,
                        host=host,
                        port=0,
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
