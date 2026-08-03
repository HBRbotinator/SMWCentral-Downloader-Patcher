"""Bridge the active Collection Wheel pool into the browser runtime."""

from __future__ import annotations

import copy
import threading
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from wheel_runtime_controller import (
    WheelRuntimeController,
    build_managed_wheel_runtime,
)
from wheel_runtime_http import (
    WHEEL_RUNTIME_DEFAULT_HOST,
    WHEEL_RUNTIME_DEFAULT_PORT,
)
from wheel_runtime_spin import (
    WHEEL_RUNTIME_DEFAULT_DURATION_MS,
    WHEEL_RUNTIME_DEFAULT_LANDING_OFFSET,
    WHEEL_RUNTIME_DEFAULT_TURNS,
)


class WheelRuntimeBridgeNotRunningError(RuntimeError):
    """Raised when a live-runtime operation requires a running service."""


class CollectionWheelRuntimeBridge:
    """Synchronize exact eligible pools and predetermined winners."""

    def __init__(
        self,
        model: Any,
        *,
        controller_factory=build_managed_wheel_runtime,
        source_revision_supplier=None,
        snapshot_clock=None,
        spin_clock=None,
        spin_id_supplier=None,
        host: str = WHEEL_RUNTIME_DEFAULT_HOST,
        port: int = WHEEL_RUNTIME_DEFAULT_PORT,
    ) -> None:
        if not callable(controller_factory):
            raise TypeError("controller_factory must be callable")

        self._lock = threading.RLock()
        self._active_pool: list[dict[str, Any]] = []
        self._controller: WheelRuntimeController = controller_factory(
            model,
            self._supply_active_pool,
            source_revision_supplier=source_revision_supplier,
            snapshot_clock=snapshot_clock,
            spin_clock=spin_clock,
            spin_id_supplier=spin_id_supplier,
            host=host,
            port=port,
        )
        _require_controller(self._controller)

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._controller.running)

    @property
    def browser_url(self) -> str:
        with self._lock:
            if not self._controller.running:
                raise WheelRuntimeBridgeNotRunningError(
                    "Wheel browser runtime is not running"
                )
            return self._controller.browser_url

    def stage_pool(
        self,
        pool: Iterable[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        """Stage one detached eligible pool without publishing it."""

        normalized = _normalize_pool(pool)
        with self._lock:
            self._active_pool = normalized
            return copy.deepcopy(normalized)

    def start(
        self,
        pool: Iterable[Mapping[str, Any]] | None = None,
    ) -> str:
        """Start the runtime using the supplied or previously staged pool."""

        with self._lock:
            if pool is not None:
                self._active_pool = _normalize_pool(pool)
            return self._controller.start()

    def stop(self) -> None:
        """Stop the managed runtime; repeated calls are harmless."""

        with self._lock:
            self._controller.stop()

    def refresh_pool(
        self,
        pool: Iterable[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Publish a new exact eligible pool while preserving failure safety."""

        normalized = _normalize_pool(pool)
        with self._lock:
            self._require_running()
            previous = self._active_pool
            self._active_pool = normalized
            try:
                return self._controller.refresh_snapshot()
            except Exception:
                self._active_pool = previous
                raise

    def publish_selection(
        self,
        pool: Iterable[Mapping[str, Any]],
        winner_id: Any,
        *,
        duration_ms: int = WHEEL_RUNTIME_DEFAULT_DURATION_MS,
        turns: int = WHEEL_RUNTIME_DEFAULT_TURNS,
        landing_offset: float = (
            WHEEL_RUNTIME_DEFAULT_LANDING_OFFSET
        ),
    ) -> dict[str, Any]:
        """Publish an already-selected winner against the exact eligible pool."""

        normalized = _normalize_pool(pool)
        with self._lock:
            self._require_running()
            previous = self._active_pool
            self._active_pool = normalized
            try:
                snapshot = self._controller.refresh_snapshot()
            except Exception:
                self._active_pool = previous
                raise

            spin = self._controller.publish_winner(
                winner_id,
                duration_ms=duration_ms,
                turns=turns,
                landing_offset=landing_offset,
            )
            return {
                "snapshot": copy.deepcopy(snapshot),
                "spin": copy.deepcopy(spin),
            }

    def status(self) -> dict[str, Any]:
        """Return runtime status plus the staged pool size, never its records."""

        with self._lock:
            status = self._controller.status()
            return {
                **copy.deepcopy(status),
                "active_pool_size": len(self._active_pool),
            }

    def _supply_active_pool(self) -> list[dict[str, Any]]:
        with self._lock:
            return copy.deepcopy(self._active_pool)

    def _require_running(self) -> None:
        if not self._controller.running:
            raise WheelRuntimeBridgeNotRunningError(
                "Wheel browser runtime is not running"
            )

    def __enter__(self) -> "CollectionWheelRuntimeBridge":
        self.start()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop()


def _normalize_pool(
    pool: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if pool is None:
        raise ValueError("Wheel runtime pool is required")
    if isinstance(pool, (str, bytes, Mapping)):
        raise TypeError(
            "Wheel runtime pool must be an iterable of record mappings"
        )

    try:
        records = list(pool)
    except TypeError as error:
        raise TypeError(
            "Wheel runtime pool must be iterable"
        ) from error

    normalized = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise TypeError(
                f"Wheel runtime pool record {index} must be a mapping"
            )
        normalized.append(copy.deepcopy(dict(record)))
    return normalized


def _require_controller(controller: Any) -> None:
    required = (
        "start",
        "stop",
        "refresh_snapshot",
        "publish_winner",
        "status",
    )
    for name in required:
        if not callable(getattr(controller, name, None)):
            raise TypeError(
                f"controller_factory must return an object with {name}()"
            )
    if not hasattr(controller, "running"):
        raise TypeError(
            "controller_factory must return an object with running"
        )
    if not hasattr(type(controller), "browser_url"):
        raise TypeError(
            "controller_factory must return an object with browser_url"
        )


__all__ = [
    "CollectionWheelRuntimeBridge",
    "WheelRuntimeBridgeNotRunningError",
]
