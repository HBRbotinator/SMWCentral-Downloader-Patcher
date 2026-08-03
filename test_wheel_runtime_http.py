"""HTTP contracts including the read-only browser preview."""

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
    30,
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

    def test_browser_url_uses_actual_bound_address(self):
        self.assertEqual(
            self.service.browser_url,
            self.service.base_url + "/wheel/",
        )

    def test_browser_short_path_redirects_to_canonical_page(self):
        response, body = request(self.service, "GET", "/wheel")

        self.assertEqual(response.status, 308)
        self.assertEqual(response.getheader("Location"), "/wheel/")
        self.assertEqual(body, b"")

    def test_browser_page_and_assets_use_correct_content_types(self):
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

    def test_browser_assets_have_strict_obs_compatible_csp(self):
        response, _body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_BROWSER_PATH,
        )

        csp = response.getheader("Content-Security-Policy")
        self.assertIn("default-src 'none'", csp)
        self.assertIn("script-src 'self'", csp)
        self.assertIn("connect-src 'self'", csp)
        self.assertIn("frame-ancestors *", csp)
        self.assertIsNone(response.getheader("X-Frame-Options"))

    def test_browser_head_returns_headers_without_body(self):
        response, body = request(
            self.service,
            "HEAD",
            WHEEL_RUNTIME_BROWSER_SCRIPT_PATH,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(int(response.getheader("Content-Length")), 100)

    def test_health_is_available_before_snapshot_refresh(self):
        response, body = request(
            self.service,
            "GET",
            WHEEL_RUNTIME_HEALTH_PATH,
        )

        self.assertEqual(response.status, 200)
        document = json.loads(body)
        self.assertFalse(document["snapshot"]["ready"])

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

    def test_mutating_methods_are_rejected_for_api_and_browser(self):
        for path in (
            WHEEL_RUNTIME_SNAPSHOT_PATH,
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

    def test_unknown_path_returns_json_404(self):
        response, body = request(
            self.service,
            "GET",
            "/wheel/missing.js",
        )

        self.assertEqual(response.status, 404)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "not_found",
        )

    def test_all_responses_disable_caching_and_sniffing(self):
        for path in (
            WHEEL_RUNTIME_HEALTH_PATH,
            WHEEL_RUNTIME_BROWSER_PATH,
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

    def test_start_is_idempotent_and_stop_is_repeatable(self):
        first = self.service.address
        self.assertEqual(self.service.start(), first)
        self.service.stop()
        self.service.stop()
        self.assertFalse(self.service.running)

    def test_concurrent_browser_and_snapshot_readers_are_complete(self):
        self.provider.refresh()
        results = []
        failures = []

        def read_path(path):
            try:
                response, body = request(self.service, "GET", path)
                results.append((path, response.status, len(body)))
            except Exception as error:
                failures.append(error)

        paths = [
            WHEEL_RUNTIME_BROWSER_PATH,
            WHEEL_RUNTIME_BROWSER_SCRIPT_PATH,
            WHEEL_RUNTIME_SNAPSHOT_PATH,
        ] * 4
        threads = [
            threading.Thread(target=read_path, args=(path,))
            for path in paths
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(len(results), len(paths))
        self.assertTrue(
            all(status == 200 and length > 0 for _, status, length in results)
        )

    def test_service_rejects_non_loopback_bindings(self):
        for host in ("0.0.0.0", "192.168.1.10", "", "::1"):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    WheelRuntimeHttpService(
                        self.provider,
                        host=host,
                        port=0,
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
