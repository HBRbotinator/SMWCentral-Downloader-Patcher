"""Application-managed lifecycle for the local Wheel browser runtime."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from wheel_runtime_http import (
    WHEEL_RUNTIME_DEFAULT_HOST,
    WHEEL_RUNTIME_DEFAULT_PORT,
    WheelRuntimeHttpService,
)
from wheel_runtime_snapshot_provider import (
    CollectionWheelRuntimeSnapshotSource,
    WheelRuntimeSnapshotProvider,
)
from wheel_runtime_spin import (
    WHEEL_RUNTIME_DEFAULT_DURATION_MS,
    WHEEL_RUNTIME_DEFAULT_LANDING_OFFSET,
    WHEEL_RUNTIME_DEFAULT_TURNS,
    WheelRuntimeSpinCoordinator,
)


class WheelRuntimeController:
    """Coordinate runtime lifecycle without owning winner selection."""

    def __init__(
        self,
        snapshot_provider: WheelRuntimeSnapshotProvider,
        spin_coordinator: WheelRuntimeSpinCoordinator,
        http_service: WheelRuntimeHttpService,
    ) -> None:
        _require_callable(
            snapshot_provider,
            "refresh",
            "snapshot_provider",
        )
        _require_callable(
            snapshot_provider,
            "status",
            "snapshot_provider",
        )
        _require_callable(
            spin_coordinator,
            "publish_winner",
            "spin_coordinator",
        )
        _require_callable(
            spin_coordinator,
            "status",
            "spin_coordinator",
        )
        _require_callable(http_service, "start", "http_service")
        _require_callable(http_service, "stop", "http_service")

        self._snapshot_provider = snapshot_provider
        self._spin_coordinator = spin_coordinator
        self._http_service = http_service
        self._lock = threading.RLock()

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._http_service.running)

    @property
    def browser_url(self) -> str:
        with self._lock:
            if not self._http_service.running:
                raise RuntimeError(
                    "Wheel browser runtime is not running"
                )
            return self._http_service.browser_url

    def start(self) -> str:
        """Publish an initial snapshot, then start the loopback service."""

        with self._lock:
            if self._http_service.running:
                return self._http_service.browser_url

            self._snapshot_provider.refresh()
            self._http_service.start()
            return self._http_service.browser_url

    def stop(self) -> None:
        """Stop the managed HTTP service; repeated calls are harmless."""

        with self._lock:
            self._http_service.stop()

    def refresh_snapshot(self) -> dict[str, Any]:
        """Replace the runtime snapshot from current application data."""

        return self._snapshot_provider.refresh()

    def publish_winner(
        self,
        winner_id: Any,
        *,
        duration_ms: int = WHEEL_RUNTIME_DEFAULT_DURATION_MS,
        turns: int = WHEEL_RUNTIME_DEFAULT_TURNS,
        landing_offset: float = (
            WHEEL_RUNTIME_DEFAULT_LANDING_OFFSET
        ),
    ) -> dict[str, Any]:
        """Publish a winner already selected by the application."""

        return self._spin_coordinator.publish_winner(
            winner_id,
            duration_ms=duration_ms,
            turns=turns,
            landing_offset=landing_offset,
        )

    def status(self) -> dict[str, Any]:
        """Return detached managed-runtime health metadata."""

        with self._lock:
            running = bool(self._http_service.running)
            browser_url = (
                self._http_service.browser_url
                if running
                else None
            )

        return {
            "running": running,
            "browser_url": browser_url,
            "snapshot": copy.deepcopy(
                self._snapshot_provider.status()
            ),
            "spin": copy.deepcopy(
                self._spin_coordinator.status()
            ),
        }

    def __enter__(self) -> "WheelRuntimeController":
        self.start()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.stop()


def build_managed_wheel_runtime(
    model: Any,
    collection_supplier: Callable[[], Any],
    *,
    source_revision_supplier: Callable[[], Any] | None = None,
    snapshot_clock: Callable[[], datetime] | None = None,
    spin_clock: Callable[[], datetime] | None = None,
    spin_id_supplier: Callable[[], Any] | None = None,
    host: str = WHEEL_RUNTIME_DEFAULT_HOST,
    port: int = WHEEL_RUNTIME_DEFAULT_PORT,
) -> WheelRuntimeController:
    """Compose one application-managed loopback Wheel runtime."""

    source = CollectionWheelRuntimeSnapshotSource(
        model,
        collection_supplier,
        source_revision_supplier=source_revision_supplier,
        clock=snapshot_clock,
    )
    provider = WheelRuntimeSnapshotProvider(source)
    coordinator = WheelRuntimeSpinCoordinator(
        provider,
        clock=spin_clock,
        spin_id_supplier=spin_id_supplier,
    )
    service = WheelRuntimeHttpService(
        provider,
        spin_coordinator=coordinator,
        host=host,
        port=port,
    )
    return WheelRuntimeController(
        provider,
        coordinator,
        service,
    )


def _require_callable(
    value: Any,
    name: str,
    label: str,
) -> None:
    if not callable(getattr(value, name, None)):
        raise TypeError(
            f"{label} must provide callable {name}()"
        )


__all__ = [
    "WheelRuntimeController",
    "build_managed_wheel_runtime",
]
