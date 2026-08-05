"""Authenticated loopback HTTP service for external Wheel commands."""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from wheel_external_command import (
    WheelExternalCommandError,
    parse_wheel_external_command,
)
from wheel_external_command_queue import WheelExternalCommandQueue


WHEEL_EXTERNAL_CONTROL_API_VERSION = 1
WHEEL_EXTERNAL_CONTROL_STATUS_PATH = "/api/v1/status"
WHEEL_EXTERNAL_CONTROL_COMMAND_PATH = "/api/v1/commands"
WHEEL_EXTERNAL_CONTROL_DEFAULT_HOST = "127.0.0.1"
WHEEL_EXTERNAL_CONTROL_DEFAULT_PORT = 8766
WHEEL_EXTERNAL_CONTROL_MAX_BODY_BYTES = 4096
WHEEL_EXTERNAL_CONTROL_MIN_TOKEN_LENGTH = 32
WHEEL_EXTERNAL_CONTROL_MAX_TOKEN_LENGTH = 256

_ALLOWED_HOSTS = frozenset({"127.0.0.1", "localhost"})


class WheelExternalCommandHttpService:
    """Own a separate authenticated loopback command server."""

    def __init__(
        self,
        command_queue: WheelExternalCommandQueue,
        token: str,
        *,
        host: str = WHEEL_EXTERNAL_CONTROL_DEFAULT_HOST,
        port: int = WHEEL_EXTERNAL_CONTROL_DEFAULT_PORT,
        max_body_bytes: int = WHEEL_EXTERNAL_CONTROL_MAX_BODY_BYTES,
    ) -> None:
        if not isinstance(command_queue, WheelExternalCommandQueue):
            raise TypeError(
                "command_queue must be a WheelExternalCommandQueue"
            )

        self._token = _validate_token(token)
        self._host = _validate_host(host)
        self._port = _validate_port(port)
        self._max_body_bytes = _validate_max_body_bytes(
            max_body_bytes
        )
        self._command_queue = command_queue
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
                raise RuntimeError(
                    "Wheel external command service is not running"
                )
            host, port = self._server.server_address[:2]
            return str(host), int(port)

    @property
    def base_url(self) -> str:
        host, port = self.address
        return f"http://{host}:{port}"

    @property
    def command_url(self) -> str:
        return self.base_url + WHEEL_EXTERNAL_CONTROL_COMMAND_PATH

    @property
    def status_url(self) -> str:
        return self.base_url + WHEEL_EXTERNAL_CONTROL_STATUS_PATH

    def start(self) -> tuple[str, int]:
        """Start once and return the actual bound loopback address."""

        with self._lock:
            if self._server is not None:
                return self.address

            handler_class = _handler_for(
                self._command_queue,
                self._token,
                self._max_body_bytes,
            )
            server = ThreadingHTTPServer(
                (self._host, self._port),
                handler_class,
            )
            server.daemon_threads = True
            server.allow_reuse_address = True

            thread = threading.Thread(
                target=server.serve_forever,
                name="WheelExternalCommandHttpService",
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

    def __enter__(self) -> "WheelExternalCommandHttpService":
        self.start()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop()


def _handler_for(
    command_queue: WheelExternalCommandQueue,
    token: str,
    max_body_bytes: int,
) -> type[BaseHTTPRequestHandler]:
    class WheelExternalCommandRequestHandler(
        BaseHTTPRequestHandler
    ):
        server_version = "SMWCWheelControl/1"
        sys_version = ""

        def do_GET(self) -> None:
            self._dispatch_read(include_body=True)

        def do_HEAD(self) -> None:
            self._dispatch_read(include_body=False)

        def do_POST(self) -> None:
            path = urlsplit(self.path).path
            if path != WHEEL_EXTERNAL_CONTROL_COMMAND_PATH:
                if path == WHEEL_EXTERNAL_CONTROL_STATUS_PATH:
                    self._method_not_allowed("GET, HEAD")
                else:
                    self._not_found()
                return

            if not self._authenticate():
                return

            document = self._read_json_document()
            if document is None:
                return

            try:
                command = parse_wheel_external_command(document)
            except WheelExternalCommandError as error:
                self._send_json(
                    422,
                    _error_document(
                        "invalid_command",
                        str(error),
                    ),
                )
                return

            submission = command_queue.submit(command)
            status_code = {
                "accepted": 202,
                "duplicate": 200,
                "full": 429,
                "closed": 503,
            }[submission.status]
            self._send_json(
                status_code,
                {
                    "service": "smwc-wheel-control",
                    "api_version": (
                        WHEEL_EXTERNAL_CONTROL_API_VERSION
                    ),
                    "status": submission.status,
                    "command_id": submission.command_id,
                    "pending_count": submission.pending_count,
                },
            )

        def do_PUT(self) -> None:
            self._reject_mutating_method()

        def do_PATCH(self) -> None:
            self._reject_mutating_method()

        def do_DELETE(self) -> None:
            self._reject_mutating_method()

        def do_OPTIONS(self) -> None:
            self._reject_mutating_method()

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _dispatch_read(self, *, include_body: bool) -> None:
            path = urlsplit(self.path).path
            if path == WHEEL_EXTERNAL_CONTROL_COMMAND_PATH:
                self._method_not_allowed("POST")
                return
            if path != WHEEL_EXTERNAL_CONTROL_STATUS_PATH:
                self._not_found(include_body=include_body)
                return
            if not self._authenticate(include_body=include_body):
                return

            self._send_json(
                200,
                {
                    "service": "smwc-wheel-control",
                    "api_version": (
                        WHEEL_EXTERNAL_CONTROL_API_VERSION
                    ),
                    "authenticated": True,
                    "queue": {
                        "closed": command_queue.closed,
                        "pending_count": (
                            command_queue.pending_count
                        ),
                        "capacity": command_queue.capacity,
                    },
                },
                include_body=include_body,
            )

        def _reject_mutating_method(self) -> None:
            path = urlsplit(self.path).path
            if path == WHEEL_EXTERNAL_CONTROL_COMMAND_PATH:
                self._method_not_allowed("POST")
                return
            if path == WHEEL_EXTERNAL_CONTROL_STATUS_PATH:
                self._method_not_allowed("GET, HEAD")
                return
            self._not_found()

        def _authenticate(
            self,
            *,
            include_body: bool = True,
        ) -> bool:
            authorization = self.headers.get("Authorization", "")
            prefix = "Bearer "
            supplied = (
                authorization[len(prefix):]
                if authorization.startswith(prefix)
                else ""
            )
            if not supplied or not secrets.compare_digest(
                supplied,
                token,
            ):
                payload = _json_bytes(
                    _error_document(
                        "unauthorized",
                        "A valid Bearer token is required",
                    )
                )
                self.send_response(401)
                self.send_header(
                    "WWW-Authenticate",
                    'Bearer realm="smwc-wheel-control"',
                )
                self._common_headers(len(payload))
                self.end_headers()
                if include_body:
                    self.wfile.write(payload)
                return False
            return True

        def _read_json_document(self) -> Any | None:
            content_type = self.headers.get("Content-Type", "")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type != "application/json":
                self._send_json(
                    415,
                    _error_document(
                        "unsupported_media_type",
                        "Content-Type must be application/json",
                    ),
                )
                return None

            transfer_encoding = self.headers.get(
                "Transfer-Encoding",
                "",
            )
            if transfer_encoding:
                self._send_json(
                    400,
                    _error_document(
                        "unsupported_transfer_encoding",
                        "Chunked request bodies are not supported",
                    ),
                )
                return None

            raw_length = self.headers.get("Content-Length")
            if raw_length is None:
                self._send_json(
                    411,
                    _error_document(
                        "length_required",
                        "Content-Length is required",
                    ),
                )
                return None

            try:
                content_length = int(raw_length)
            except ValueError:
                self._send_json(
                    400,
                    _error_document(
                        "invalid_content_length",
                        "Content-Length must be an integer",
                    ),
                )
                return None

            if content_length <= 0:
                self._send_json(
                    400,
                    _error_document(
                        "empty_body",
                        "A JSON command body is required",
                    ),
                )
                return None
            if content_length > max_body_bytes:
                self._send_json(
                    413,
                    _error_document(
                        "body_too_large",
                        "The command body exceeds the size limit",
                    ),
                )
                return None

            payload = self.rfile.read(content_length)
            if len(payload) != content_length:
                self._send_json(
                    400,
                    _error_document(
                        "incomplete_body",
                        "The command body was incomplete",
                    ),
                )
                return None

            try:
                return json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._send_json(
                    400,
                    _error_document(
                        "invalid_json",
                        "The command body must be valid UTF-8 JSON",
                    ),
                )
                return None

        def _method_not_allowed(self, allow: str) -> None:
            payload = _json_bytes(
                _error_document(
                    "method_not_allowed",
                    "The request method is not allowed for this route",
                )
            )
            self.send_response(405)
            self.send_header("Allow", allow)
            self._common_headers(len(payload))
            self.end_headers()
            self.wfile.write(payload)

        def _not_found(self, *, include_body: bool = True) -> None:
            self._send_json(
                404,
                _error_document(
                    "not_found",
                    "The requested Wheel control resource was not found",
                ),
                include_body=include_body,
            )

        def _send_json(
            self,
            status: int,
            document: dict[str, Any],
            *,
            include_body: bool = True,
        ) -> None:
            payload = _json_bytes(document)
            self.send_response(status)
            if status == 429:
                self.send_header("Retry-After", "1")
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

    return WheelExternalCommandRequestHandler


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


def _validate_token(token: str) -> str:
    if not isinstance(token, str):
        raise TypeError("token must be a string")
    if not (
        WHEEL_EXTERNAL_CONTROL_MIN_TOKEN_LENGTH
        <= len(token)
        <= WHEEL_EXTERNAL_CONTROL_MAX_TOKEN_LENGTH
    ):
        raise ValueError(
            "token must contain between 32 and 256 characters"
        )
    if token.strip() != token or any(character.isspace() for character in token):
        raise ValueError("token must not contain whitespace")
    return token


def _validate_host(host: str) -> str:
    if not isinstance(host, str):
        raise TypeError("host must be a string")
    normalized = host.strip().casefold()
    if normalized not in _ALLOWED_HOSTS:
        raise ValueError(
            "Wheel external command service may bind only to "
            "127.0.0.1 or localhost"
        )
    return normalized


def _validate_port(port: int) -> int:
    if isinstance(port, bool) or not isinstance(port, int):
        raise TypeError("port must be an integer")
    if not 0 <= port <= 65535:
        raise ValueError("port must be between 0 and 65535")
    return port


def _validate_max_body_bytes(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("max_body_bytes must be an integer")
    if value <= 0:
        raise ValueError("max_body_bytes must be positive")
    return value


__all__ = [
    "WHEEL_EXTERNAL_CONTROL_API_VERSION",
    "WHEEL_EXTERNAL_CONTROL_STATUS_PATH",
    "WHEEL_EXTERNAL_CONTROL_COMMAND_PATH",
    "WHEEL_EXTERNAL_CONTROL_DEFAULT_HOST",
    "WHEEL_EXTERNAL_CONTROL_DEFAULT_PORT",
    "WHEEL_EXTERNAL_CONTROL_MAX_BODY_BYTES",
    "WHEEL_EXTERNAL_CONTROL_MIN_TOKEN_LENGTH",
    "WHEEL_EXTERNAL_CONTROL_MAX_TOKEN_LENGTH",
    "WheelExternalCommandHttpService",
]
