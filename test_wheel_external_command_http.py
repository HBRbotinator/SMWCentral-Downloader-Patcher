"""Tests for the authenticated loopback Wheel command service."""

from __future__ import annotations

import http.client
import json
import threading
import unittest

from wheel_external_command_http import (
    WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
    WHEEL_EXTERNAL_CONTROL_STATUS_PATH,
    WheelExternalCommandHttpService,
)
from wheel_external_command_queue import WheelExternalCommandQueue


TOKEN = "test-token-0123456789abcdef-0123456789"


def command_document(
    command_id: str = "streamerbot:wheel:0001",
    action: str = "spin",
):
    return {
        "schema": "smwc-wheel-command",
        "version": 1,
        "command_id": command_id,
        "action": action,
    }


def request(
    service,
    method,
    path,
    *,
    token=TOKEN,
    document=None,
    body=None,
    headers=None,
):
    host, port = service.address
    connection = http.client.HTTPConnection(host, port, timeout=5)
    request_headers = dict(headers or {})
    if token is not None:
        request_headers["Authorization"] = f"Bearer {token}"
    if document is not None:
        body = json.dumps(document).encode("utf-8")
        request_headers.setdefault(
            "Content-Type",
            "application/json",
        )
    connection.request(
        method,
        path,
        body=body,
        headers=request_headers,
    )
    response = connection.getresponse()
    payload = response.read()
    connection.close()
    return response, payload


class WheelExternalCommandHttpServiceTest(unittest.TestCase):
    def setUp(self):
        self.queue = WheelExternalCommandQueue(
            capacity=4,
            remembered_ids=8,
        )
        self.service = WheelExternalCommandHttpService(
            self.queue,
            TOKEN,
            port=0,
        )
        self.service.start()

    def tearDown(self):
        self.service.stop()

    def test_service_is_separate_loopback_surface(self):
        self.assertTrue(self.service.running)
        self.assertTrue(
            self.service.command_url.endswith(
                WHEEL_EXTERNAL_CONTROL_COMMAND_PATH
            )
        )
        self.assertTrue(
            self.service.status_url.endswith(
                WHEEL_EXTERNAL_CONTROL_STATUS_PATH
            )
        )
        self.assertEqual(self.service.address[0], "127.0.0.1")

    def test_status_requires_authentication(self):
        response, body = request(
            self.service,
            "GET",
            WHEEL_EXTERNAL_CONTROL_STATUS_PATH,
            token=None,
        )

        self.assertEqual(response.status, 401)
        self.assertEqual(
            response.getheader("WWW-Authenticate"),
            'Bearer realm="smwc-wheel-control"',
        )
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "unauthorized",
        )

    def test_status_reports_only_queue_metadata(self):
        self.queue.submit(
            __import__(
                "wheel_external_command"
            ).parse_wheel_external_command(
                command_document("queued")
            )
        )

        response, body = request(
            self.service,
            "GET",
            WHEEL_EXTERNAL_CONTROL_STATUS_PATH,
        )
        document = json.loads(body)

        self.assertEqual(response.status, 200)
        self.assertTrue(document["authenticated"])
        self.assertEqual(
            document["queue"],
            {
                "closed": False,
                "pending_count": 1,
                "capacity": 4,
            },
        )
        serialized = json.dumps(document).lower()
        for forbidden in (
            "token",
            "winner",
            "candidate",
            "landing_offset",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_status_head_has_headers_without_body(self):
        response, body = request(
            self.service,
            "HEAD",
            WHEEL_EXTERNAL_CONTROL_STATUS_PATH,
        )

        self.assertEqual(response.status, 200)
        self.assertEqual(body, b"")
        self.assertGreater(
            int(response.getheader("Content-Length")),
            0,
        )

    def test_valid_command_is_only_enqueued(self):
        response, body = request(
            self.service,
            "POST",
            WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
            document=command_document(),
        )
        result = json.loads(body)

        self.assertEqual(response.status, 202)
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["pending_count"], 1)
        self.assertEqual(self.queue.pending_count, 1)
        queued = self.queue.snapshot()[0]
        self.assertEqual(queued.action, "spin")
        self.assertEqual(
            queued.command_id,
            "streamerbot:wheel:0001",
        )

    def test_duplicate_is_idempotent_and_never_enqueues_twice(self):
        first, _body = request(
            self.service,
            "POST",
            WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
            document=command_document("same"),
        )
        duplicate, body = request(
            self.service,
            "POST",
            WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
            document=command_document("same"),
        )

        self.assertEqual(first.status, 202)
        self.assertEqual(duplicate.status, 200)
        self.assertEqual(
            json.loads(body)["status"],
            "duplicate",
        )
        self.assertEqual(self.queue.pending_count, 1)

    def test_full_and_closed_queue_have_explicit_responses(self):
        small_queue = WheelExternalCommandQueue(
            capacity=1,
            remembered_ids=2,
        )
        service = WheelExternalCommandHttpService(
            small_queue,
            TOKEN,
            port=0,
        )
        service.start()
        try:
            accepted, _body = request(
                service,
                "POST",
                WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
                document=command_document("first"),
            )
            full, full_body = request(
                service,
                "POST",
                WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
                document=command_document("second"),
            )
            small_queue.close()
            closed, closed_body = request(
                service,
                "POST",
                WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
                document=command_document("third"),
            )
        finally:
            service.stop()

        self.assertEqual(accepted.status, 202)
        self.assertEqual(full.status, 429)
        self.assertEqual(full.getheader("Retry-After"), "1")
        self.assertEqual(json.loads(full_body)["status"], "full")
        self.assertEqual(closed.status, 503)
        self.assertEqual(json.loads(closed_body)["status"], "closed")

    def test_wrong_or_malformed_authorization_is_rejected(self):
        for token in (
            "",
            "wrong-token-0123456789abcdef-0123456789",
            None,
        ):
            with self.subTest(token=token):
                response, body = request(
                    self.service,
                    "POST",
                    WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
                    token=token,
                    document=command_document("unauthorized"),
                )
                self.assertEqual(response.status, 401)
                self.assertEqual(
                    json.loads(body)["error"]["code"],
                    "unauthorized",
                )

        response, body = request(
            self.service,
            "POST",
            WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
            token=None,
            document=command_document("basic-auth"),
            headers={"Authorization": "Basic abc123"},
        )
        self.assertEqual(response.status, 401)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "unauthorized",
        )
        self.assertEqual(self.queue.pending_count, 0)

    def test_content_type_json_and_size_are_enforced(self):
        response, body = request(
            self.service,
            "POST",
            WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
            body=b"{}",
            headers={"Content-Type": "text/plain"},
        )
        self.assertEqual(response.status, 415)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "unsupported_media_type",
        )

        oversized = b"{" + (b"x" * 5000) + b"}"
        response, body = request(
            self.service,
            "POST",
            WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
            body=oversized,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(response.status, 413)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "body_too_large",
        )

    def test_invalid_json_and_command_contract_are_distinct(self):
        invalid_json, body = request(
            self.service,
            "POST",
            WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
            body=b"{not-json",
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(invalid_json.status, 400)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "invalid_json",
        )

        invalid_command, body = request(
            self.service,
            "POST",
            WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
            document={
                **command_document("bad-command"),
                "winner_id": "forbidden",
            },
        )
        self.assertEqual(invalid_command.status, 422)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "invalid_command",
        )
        self.assertEqual(self.queue.pending_count, 0)

    def test_route_methods_are_narrow_and_no_cors_is_added(self):
        cases = (
            (
                "GET",
                WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
                "POST",
            ),
            (
                "POST",
                WHEEL_EXTERNAL_CONTROL_STATUS_PATH,
                "GET, HEAD",
            ),
            (
                "PUT",
                WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
                "POST",
            ),
            (
                "OPTIONS",
                WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
                "POST",
            ),
        )
        for method, path, allow in cases:
            with self.subTest(method=method, path=path):
                response, body = request(
                    self.service,
                    method,
                    path,
                    body=b"",
                )
                self.assertEqual(response.status, 405)
                self.assertEqual(response.getheader("Allow"), allow)
                self.assertIsNone(
                    response.getheader(
                        "Access-Control-Allow-Origin"
                    )
                )
                self.assertEqual(
                    json.loads(body)["error"]["code"],
                    "method_not_allowed",
                )

    def test_unknown_path_returns_json_404(self):
        response, body = request(
            self.service,
            "GET",
            "/api/v1/winner",
        )

        self.assertEqual(response.status, 404)
        self.assertEqual(
            json.loads(body)["error"]["code"],
            "not_found",
        )

    def test_concurrent_duplicate_requests_accept_exactly_once(self):
        statuses = []
        failures = []

        def submit():
            try:
                response, _body = request(
                    self.service,
                    "POST",
                    WHEEL_EXTERNAL_CONTROL_COMMAND_PATH,
                    document=command_document("concurrent"),
                )
                statuses.append(response.status)
            except Exception as error:
                failures.append(error)

        threads = [threading.Thread(target=submit) for _ in range(16)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(failures, [])
        self.assertEqual(statuses.count(202), 1)
        self.assertEqual(statuses.count(200), 15)
        self.assertEqual(self.queue.pending_count, 1)

    def test_start_stop_and_configuration_are_strict(self):
        address = self.service.address
        self.assertEqual(self.service.start(), address)
        self.service.stop()
        self.service.stop()
        self.assertFalse(self.service.running)

        for host in ("0.0.0.0", "192.168.1.5", "::1", ""):
            with self.subTest(host=host):
                with self.assertRaises(ValueError):
                    WheelExternalCommandHttpService(
                        WheelExternalCommandQueue(),
                        TOKEN,
                        host=host,
                        port=0,
                    )

        for token in ("short", " contains whitespace "):
            with self.subTest(token=token):
                with self.assertRaises(ValueError):
                    WheelExternalCommandHttpService(
                        WheelExternalCommandQueue(),
                        token,
                        port=0,
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
