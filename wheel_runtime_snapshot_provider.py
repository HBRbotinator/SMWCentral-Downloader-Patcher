"""Thread-safe in-memory cache for validated Wheel runtime snapshots."""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any

from wheel_runtime_contract import (
    serialize_wheel_runtime_snapshot,
    validate_wheel_runtime_snapshot,
)


class WheelRuntimeSnapshotUnavailableError(RuntimeError):
    """Raised when no valid runtime snapshot has been cached."""


class CollectionWheelRuntimeSnapshotSource:
    """Adapt the live Collection Wheel model to a zero-argument source."""

    def __init__(
        self,
        model: Any,
        collection_supplier: Callable[[], Any],
        *,
        source_revision_supplier: Callable[[], Any] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(getattr(model, "runtime_snapshot", None)):
            raise TypeError("model must provide runtime_snapshot(...)")
        if not callable(collection_supplier):
            raise TypeError("collection_supplier must be callable")
        if (
            source_revision_supplier is not None
            and not callable(source_revision_supplier)
        ):
            raise TypeError(
                "source_revision_supplier must be callable or None"
            )
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable or None")

        self._model = model
        self._collection_supplier = collection_supplier
        self._source_revision_supplier = source_revision_supplier
        self._clock = clock or _utc_now

    def __call__(self) -> dict[str, Any]:
        records = self._collection_supplier()
        revision = (
            self._source_revision_supplier()
            if self._source_revision_supplier is not None
            else None
        )
        return self._model.runtime_snapshot(
            records,
            generated_at=self._clock(),
            source_revision=revision,
        )


class WheelRuntimeSnapshotProvider:
    """Validate and atomically cache one read-only runtime document."""

    def __init__(
        self,
        snapshot_source: Callable[[], Mapping[str, Any]],
    ) -> None:
        if not callable(snapshot_source):
            raise TypeError("snapshot_source must be callable")

        self._snapshot_source = snapshot_source
        self._lock = threading.RLock()
        self._snapshot: dict[str, Any] | None = None
        self._serialized: str | None = None
        self._successful_refreshes = 0
        self._last_error: str | None = None

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._snapshot is not None

    def refresh(self) -> dict[str, Any]:
        """Refresh atomically and preserve the prior cache on failure."""

        try:
            supplied = self._snapshot_source()
            validated = validate_wheel_runtime_snapshot(supplied)
            serialized = serialize_wheel_runtime_snapshot(validated)
        except Exception as error:
            with self._lock:
                self._last_error = _format_error(error)
            raise

        with self._lock:
            self._snapshot = validated
            self._serialized = serialized
            self._successful_refreshes += 1
            self._last_error = None
            return copy.deepcopy(validated)

    def current_snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self._snapshot is None:
                raise WheelRuntimeSnapshotUnavailableError(
                    "No Wheel runtime snapshot has been cached"
                )
            return copy.deepcopy(self._snapshot)

    def current_json(self) -> str:
        with self._lock:
            if self._serialized is None:
                raise WheelRuntimeSnapshotUnavailableError(
                    "No Wheel runtime snapshot has been cached"
                )
            return self._serialized

    def status(self) -> dict[str, Any]:
        with self._lock:
            snapshot = self._snapshot
            return {
                "ready": snapshot is not None,
                "successful_refreshes": self._successful_refreshes,
                "generated_at": (
                    snapshot["generated_at"] if snapshot else None
                ),
                "source_revision": (
                    snapshot["source"]["revision"] if snapshot else None
                ),
                "candidate_count": (
                    len(snapshot["candidates"]) if snapshot else 0
                ),
                "planner_available": (
                    snapshot["planner"]["available"] if snapshot else False
                ),
                "last_error": self._last_error,
            }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _format_error(error: Exception) -> str:
    name = type(error).__name__
    message = str(error).strip()
    return f"{name}: {message}" if message else name


__all__ = [
    "CollectionWheelRuntimeSnapshotSource",
    "WheelRuntimeSnapshotProvider",
    "WheelRuntimeSnapshotUnavailableError",
]
