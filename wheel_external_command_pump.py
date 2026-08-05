"""Desktop-thread pump for queued external Wheel commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from wheel_external_command import WheelExternalCommand
from wheel_external_command_queue import WheelExternalCommandQueue


class WheelExternalCommandPumpError(ValueError):
    """Raised when the desktop command pump is configured incorrectly."""


class WheelExternalCommandPump:
    """Dispatch one queued command at a time through an owner scheduler."""

    def __init__(
        self,
        *,
        command_queue: WheelExternalCommandQueue,
        schedule: Callable[[int, Callable[[], None]], Any],
        cancel: Callable[[Any], None],
        dispatch: Callable[[WheelExternalCommand], None],
        busy: Callable[[], bool],
        on_error: Callable[
            [WheelExternalCommand, Exception],
            None,
        ]
        | None = None,
        poll_interval_ms: int = 100,
    ) -> None:
        if not isinstance(command_queue, WheelExternalCommandQueue):
            raise TypeError(
                "command_queue must be a WheelExternalCommandQueue"
            )
        for value, label in (
            (schedule, "schedule"),
            (cancel, "cancel"),
            (dispatch, "dispatch"),
            (busy, "busy"),
        ):
            if not callable(value):
                raise TypeError(f"{label} must be callable")
        if on_error is not None and not callable(on_error):
            raise TypeError("on_error must be callable")
        if (
            isinstance(poll_interval_ms, bool)
            or not isinstance(poll_interval_ms, int)
            or poll_interval_ms <= 0
        ):
            raise WheelExternalCommandPumpError(
                "poll_interval_ms must be a positive integer."
            )

        self._command_queue = command_queue
        self._schedule = schedule
        self._cancel = cancel
        self._dispatch = dispatch
        self._busy = busy
        self._on_error = on_error
        self._poll_interval_ms = poll_interval_ms
        self._running = False
        self._scheduled_id = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def poll_interval_ms(self) -> int:
        return self._poll_interval_ms

    def start(self) -> bool:
        """Start polling without dispatching synchronously."""

        if self._running:
            return False
        self._running = True
        self._schedule_next()
        return True

    def stop(self) -> bool:
        """Stop polling and cancel the outstanding scheduled callback."""

        if not self._running and self._scheduled_id is None:
            return False

        self._running = False
        scheduled_id = self._scheduled_id
        self._scheduled_id = None
        if scheduled_id is not None:
            try:
                self._cancel(scheduled_id)
            except Exception:
                pass
        return True

    def poll_once(self) -> WheelExternalCommand | None:
        """Dispatch at most one command and schedule the next poll."""

        self._scheduled_id = None
        if not self._running:
            return None

        command = None
        if not self._busy():
            command = self._command_queue.take_next()
            if command is not None:
                try:
                    self._dispatch(command)
                except Exception as error:
                    if self._on_error is not None:
                        self._on_error(command, error)

        if self._running:
            self._schedule_next()
        return command

    def _schedule_next(self) -> None:
        self._scheduled_id = self._schedule(
            self._poll_interval_ms,
            self.poll_once,
        )


__all__ = [
    "WheelExternalCommandPumpError",
    "WheelExternalCommandPump",
]
