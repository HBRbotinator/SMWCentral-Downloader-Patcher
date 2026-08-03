"""Contracts for the loopback-only read-only Wheel runtime API."""

from __future__ import annotations

import copy
import http.client
import json
import threading
import unittest
from datetime import datetime, timezone

from wheel_runtime_contract import build_wheel_runtime_snapshot
from wheel_runtime_http import (
    WHEEL_RUNTIME_HEALTH_PATH,
    WHEEL_RUNTIME_SNAPSHOT_PATH,
    WheelRuntimeHttpService,
)
from wheel_runtime_snapshot_provider import (
    WheelRuntimeSnapshotProvider,
)


GENERATED_AT = datetime(
    2026,
    8,
    3,
    17,
    0,
    tzinfo=timezone.utc,
)


def make_snapshot(candidate_id="one", title="One"):
    return build_wheel_runtime_snapshot(
        [{"id": candidate_id, "title": title}],
        generated_at=GENERATED_AT,
        source_revision="revision-1",
    )


class StaticSource:
    def __init__(self, document):
        self.document = copy.deepcopy(document)

    def __call__(self):
        return copy.deepcopy(self.document)


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
        self.service = WheelRuntimeHttpService(
            self.provider,
            port=0,
        )
        self.service.start()

    def tearDown(self):
        self.service.stop()

    def test_health_is_available_before_snapshot_refresh(self):
        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_HEALTH_PATH,
        )

        self.assertEqual(response.status, 200)
        document = json.loads(body)
        self.assertEqual(document["service"], "smwc-wheel-runtime")
        self.assertEqual(document["api_version"], 1)
        self.assertTrue(document["read_only"])
        self.assertFalse(document["snapshot"]["ready"])
        self.assertEqual(document["snapshot"]["candidate_count"], 0)

    def test_snapshot_returns_503_until_provider_is_ready(self):
        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )

        self.assertEqual(response.status, 503)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "snapshot_unavailable",
        )

    def test_snapshot_returns_provider_json_after_refresh(self):
        expected = self.provider.refresh()

        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body), expected)
        self.assertTrue(body.endswith(b"\n"))

    def test_health_reflects_refreshed_provider_status(self):
        self.provider.refresh()

        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_HEALTH_PATH + "?ignored=yes",
        )

        self.assertEqual(response.status, 200)
        status = json.loads(body)["snapshot"]
        self.assertTrue(status["ready"])
        self.assertEqual(status["candidate_count"], 1)
        self.assertEqual(status["source_revision"], "revision-1")

    def test_head_returns_headers_without_body(self):
        self.provider.refresh()

        response, body = request(
            self.service,
            "HEAD",
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(int(response.getheader("Content-Length")), 0)

    def test_unknown_path_returns_json_404(self):
        response, body = request(
            self.service,
            "GET",
            "/not-a-runtime-route",
        )

        self.assertEqual(response.status, 404)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "not_found",
        )

    def test_mutating_methods_are_rejected(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            with self.subTest(method=method):
                response, body = request(
                    self.service,
                    method,
                    WHEEL_RUNTIME_SNAPSHOT_PATH,
                )
                self.assertEqual(response.status, 405)
                self.assertEqual(response.getheader("Allow"), "GET, HEAD")
                self.assertEqual(
                    json.loads(body)["error"]["code"],
                    "method_not_allowed",
                )

    def test_all_responses_disable_caching_and_sniffing(self):
        response, _body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_HEALTH_PATH,
        )

        self.assertEqual(response.getheader("Cache-Control"), "no-store")
        self.assertEqual(response.getheader("Pragma"), "no-cache")
        self.assertEqual(
            response.getheader("X-Content-Type-Options"),
            "nosniff",
        )
        self.assertEqual(
            response.getheader("Content-Type"),
            "application/json; charset=utf-8",
        )

    def test_start_is_idempotent_and_stop_is_repeatable(self):
        first = self.service.address
        second = self.service.start()

        self.assertEqual(first, second)
        self.service.stop()
        self.service.stop()
        self.assertFalse(self.service.running)

    def test_context_manager_controls_lifecycle(self):
        service = WheelRuntimeHttpService(self.provider, port=0)

        with service:
            self.assertTrue(service.running)
            self.assertTrue(service.base_url.startswith("http://127.0.0.1:"))

        self.assertFalse(service.running)

    def test_concurrent_snapshot_readers_receive_complete_json(self):
        self.provider.refresh()
        documents = []
        failures = []

        def read_snapshot():
            try:
                response, body = request(
                    self.service,
                    "GET",
                    WHEEL_RUNTIME_SNAPSHOT_PATH,
                )
                self.assertEqual(response.status, 200)
                documents.append(json.loads(body))
            except Exception as error:
                failures.append(error)

        threads = [
            threading.Thread(target=read_snapshot)
            for _ in range(10)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(len(documents), 10)
        self.assertTrue(
            all(
                document["candidates"][0]["title"] == "One"
                for document in documents
            )
        )

    def test_service_rejects_non_loopback_or_invalid_bindings(self):
        for host in ("0.0.0.0", "192.168.1.10", "", "::1"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    WheelRuntimeHttpService(
                        self.provider,
                        host=host,
                        port=0,
                    )

        for port in (-1, 65536):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    WheelRuntimeHttpService(
                        self.provider,
                        port=port,
                    )

        for port in (True, "8765"):
            with self.subTest(port=port):
                with self.assertRaises(TypeError):
                    WheelRuntimeHttpService(
                        self.provider,
                        port=port,
                    )

    def test_provider_contract_is_required(self):
        for provider in (object(), None):
            with self.subTest(provider=provider):
                with self.assertRaises(TypeError):
                    WheelRuntimeHttpService(provider, port=0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
