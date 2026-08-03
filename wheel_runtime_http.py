"""Loopback-only read-only HTTP surface for the Wheel runtime."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from wheel_runtime_snapshot_provider import (
    WheelRuntimeSnapshotUnavailableError,
)


WHEEL_RUNTIME_HTTP_API_VERSION = 1
WHEEL_RUNTIME_HEALTH_PATH = "/api/v1/health"
WHEEL_RUNTIME_SNAPSHOT_PATH = "/api/v1/snapshot"
WHEEL_RUNTIME_DEFAULT_HOST = "127.0.0.1"
WHEEL_RUNTIME_DEFAULT_PORT = 8765

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})


class WheelRuntimeHttpService:
    """Own a small loopback-only HTTP server around a snapshot provider."""

    def __init__(
        self,
        provider: Any,
        *,
        host: str = WHEEL_RUNTIME_DEFAULT_HOST,
        port: int = WHEEL_RUNTIME_DEFAULT_PORT,
    ) -> None:
        _validate_provider(provider)
        self._host = _validate_host(host)
        self._port = _validate_port(port)
        self._provider = provider
        self._lock = threading.RLock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._server is not None

    @property
    def address(self) -> tuple[str, int]:
        with self._lock:
            if self._server is None:
                raise RuntimeError("Wheel runtime HTTP service is not running")
            host, port = self._server.server_address[:2]
            return str(host), int(port)

    @property
    def base_url(self) -> str:
        host, port = self.address
        display_host = (
            "127.0.0.1"
            if host in {"0.0.0.0", ""}
            else host
        )
        return f"http://{display_host}:{port}"

    def start(self) -> tuple[str, int]:
        """Start once and return the actual bound loopback address."""

        with self._lock:
            if self._server is not None:
                return self.address

            handler_class = _handler_for(self._provider)
            server = ThreadingHTTPServer(
                (self._host, self._port),
                handler_class,
            )
            server.daemon_threads = True
            server.allow_reuse_address = True

            thread = threading.Thread(
                target=server.serve_forever,
                name="WheelRuntimeHttpService",
                daemon=True,
            )
            self._server = server
            self._thread = thread
            thread.start()
            return self.address

    def stop(self) -> None:
        """Stop safely; repeated calls are harmless."""

        with self._lock:
            server = self._server
            thread = self._thread
            self._server = None
            self._thread = None

        if server is None:
            return

        server.shutdown()
        server.server_close()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=5.0)

    def __enter__(self) -> "WheelRuntimeHttpService":
        self.start()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop()


def _handler_for(provider: Any) -> type[BaseHTTPRequestHandler]:
    class WheelRuntimeRequestHandler(BaseHTTPRequestHandler):
        server_version = "SMWCWheelRuntime/1"
        sys_version = ""

        def do_GET(self) -> None:
            self._dispatch(include_body=True)

        def do_HEAD(self) -> None:
            self._dispatch(include_body=False)

        def do_POST(self) -> None:
            self._method_not_allowed()

        def do_PUT(self) -> None:
            self._method_not_allowed()

        def do_PATCH(self) -> None:
            self._method_not_allowed()

        def do_DELETE(self) -> None:
            self._method_not_allowed()

        def do_OPTIONS(self) -> None:
            self._method_not_allowed()

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _dispatch(self, *, include_body: bool) -> None:
            path = urlsplit(self.path).path
            if path == WHEEL_RUNTIME_HEALTH_PATH:
                self._send_json(
                    200,
                    _health_document(provider),
                    include_body=include_body,
                )
                return

            if path == WHEEL_RUNTIME_SNAPSHOT_PATH:
                try:
                    body = provider.current_json()
                except WheelRuntimeSnapshotUnavailableError as error:
                    self._send_json(
                        503,
                        _error_document(
                            "snapshot_unavailable",
                            str(error),
                        ),
                        include_body=include_body,
                    )
                    return
                except Exception:
                    self._send_json(
                        500,
                        _error_document(
                            "snapshot_error",
                            "The Wheel runtime snapshot could not be read",
                        ),
                        include_body=include_body,
                    )
                    return

                self._send_bytes(
                    200,
                    body.encode("utf-8"),
                    include_body=include_body,
                )
                return

            self._send_json(
                404,
                _error_document(
                    "not_found",
                    "The requested Wheel runtime resource was not found",
                ),
                include_body=include_body,
            )

        def _method_not_allowed(self) -> None:
            payload = _json_bytes(
                _error_document(
                    "method_not_allowed",
                    "This Wheel runtime API is read-only",
                )
            )
            self.send_response(405)
            self.send_header("Allow", "GET, HEAD")
            self._common_headers(len(payload))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(
            self,
            status: int,
            document: dict[str, Any],
            *,
            include_body: bool,
        ) -> None:
            self._send_bytes(
                status,
                _json_bytes(document),
                include_body=include_body,
            )

        def _send_bytes(
            self,
            status: int,
            payload: bytes,
            *,
            include_body: bool,
        ) -> None:
            self.send_response(status)
            self._common_headers(len(payload))
            self.end_headers()
            if include_body:
                self.wfile.write(payload)

        def _common_headers(self, content_length: int) -> None:
            self.send_header(
                "Content-Type",
                "application/json; charset=utf-8",
            )
            self.send_header("Content-Length", str(content_length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")

    return WheelRuntimeRequestHandler


def _health_document(provider: Any) -> dict[str, Any]:
    try:
        status = provider.status()
    except Exception:
        status = {
            "ready": False,
            "successful_refreshes": 0,
            "generated_at": None,
            "source_revision": None,
            "candidate_count": 0,
            "planner_available": False,
            "last_error": "Snapshot provider status is unavailable",
        }

    return {
        "service": "smwc-wheel-runtime",
        "api_version": WHEEL_RUNTIME_HTTP_API_VERSION,
        "read_only": True,
        "snapshot": status,
    }


def _error_document(code: str, message: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
        }
    }


def _json_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _validate_provider(provider: Any) -> None:
    for name in ("status", "current_json"):
        if not callable(getattr(provider, name, None)):
            raise TypeError(
                f"provider must provide callable {name}()"
            )


def _validate_host(host: str) -> str:
    if not isinstance(host, str):
        raise TypeError("host must be a string")
    normalized = host.strip().casefold()
    if normalized not in _ALLOWED_HOSTS:
        raise ValueError(
            "Wheel runtime HTTP service may bind only to "
            "127.0.0.1 or localhost"
        )
    return normalized


def _validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int):
        raise TypeError("port must be an integer")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    return port


__all__ = [
    "WHEEL_RUNTIME_HTTP_API_VERSION",
    "WHEEL_RUNTIME_HEALTH_PATH",
    "WHEEL_RUNTIME_SNAPSHOT_PATH",
    "WHEEL_RUNTIME_DEFAULT_HOST",
    "WHEEL_RUNTIME_DEFAULT_PORT",
    "WheelRuntimeHttpService",
]
