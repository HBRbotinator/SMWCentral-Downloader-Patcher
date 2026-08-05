"""Thread-safe bounded inbox for validated external Wheel commands."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass

from wheel_external_command import WheelExternalCommand


WHEEL_EXTERNAL_COMMAND_QUEUE_STATUSES = (
    "accepted",
    "duplicate",
    "full",
    "closed",
)


class WheelExternalCommandQueueError(ValueError):
    """Raised when the command queue configuration is invalid."""


@dataclass(frozen=True, slots=True)
class WheelExternalCommandSubmission:
    """Detached result of attempting to enqueue one command."""

    status: str
    command_id: str
    pending_count: int

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


class WheelExternalCommandQueue:
    """Bounded FIFO inbox with idempotent command submission."""

    def __init__(
        self,
        *,
        capacity: int = 32,
        remembered_ids: int = 256,
    ) -> None:
        self._capacity = _positive_int(capacity, "capacity")
        self._remembered_ids = _positive_int(
            remembered_ids,
            "remembered_ids",
        )
        if self._remembered_ids < self._capacity:
            raise WheelExternalCommandQueueError(
                "remembered_ids must be at least capacity."
            )

        self._pending: deque[WheelExternalCommand] = deque()
        self._remembered_order: deque[str] = deque()
        self._remembered_set: set[str] = set()
        self._closed = False
        self._lock = threading.Lock()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def remembered_ids(self) -> int:
        return self._remembered_ids

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def closed(self) -> bool:
        with self._lock:
            return self._closed

    def submit(
        self,
        command: WheelExternalCommand,
    ) -> WheelExternalCommandSubmission:
        """Enqueue one validated command without executing it."""

        if not isinstance(command, WheelExternalCommand):
            raise TypeError("command must be a WheelExternalCommand")

        with self._lock:
            if command.command_id in self._remembered_set:
                return self._submission("duplicate", command.command_id)

            if self._closed:
                return self._submission("closed", command.command_id)

            if len(self._pending) >= self._capacity:
                return self._submission("full", command.command_id)

            self._pending.append(command)
            self._remember(command.command_id)
            return self._submission("accepted", command.command_id)

    def take_next(self) -> WheelExternalCommand | None:
        """Remove and return the oldest pending command."""

        with self._lock:
            if not self._pending:
                return None
            return self._pending.popleft()

    def snapshot(self) -> tuple[WheelExternalCommand, ...]:
        """Return an immutable detached view of the pending FIFO."""

        with self._lock:
            return tuple(self._pending)

    def close(self) -> int:
        """Stop accepting commands and discard all pending work."""

        with self._lock:
            self._closed = True
            cleared = len(self._pending)
            self._pending.clear()
            return cleared

    def _submission(
        self,
        status: str,
        command_id: str,
    ) -> WheelExternalCommandSubmission:
        return WheelExternalCommandSubmission(
            status=status,
            command_id=command_id,
            pending_count=len(self._pending),
        )

    def _remember(self, command_id: str) -> None:
        self._remembered_order.append(command_id)
        self._remembered_set.add(command_id)

        while len(self._remembered_order) > self._remembered_ids:
            expired = self._remembered_order.popleft()
            self._remembered_set.remove(expired)


def _positive_int(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WheelExternalCommandQueueError(
            f"{label} must be a positive integer."
        )
    if value <= 0:
        raise WheelExternalCommandQueueError(
            f"{label} must be a positive integer."
        )
    return value


__all__ = [
    "WHEEL_EXTERNAL_COMMAND_QUEUE_STATUSES",
    "WheelExternalCommandQueueError",
    "WheelExternalCommandSubmission",
    "WheelExternalCommandQueue",
]
