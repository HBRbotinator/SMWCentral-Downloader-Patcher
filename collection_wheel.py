"""Selection primitives for the Collection-owned Wheel."""

from __future__ import annotations

import copy
import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any


class CollectionWheelError(ValueError):
    """Base exception for invalid Wheel pools or selections."""


class InvalidWheelCandidateError(CollectionWheelError):
    """Raised when a Wheel candidate has no usable stable identity."""


class EmptyWheelPoolError(CollectionWheelError):
    """Raised when selection is requested from an empty Collection pool."""


class ExhaustedWheelPoolError(CollectionWheelError):
    """Raised when exclusions remove every candidate from a non-empty pool."""


def _normalize_candidate_id(value: Any) -> str:
    if value is None:
        raise InvalidWheelCandidateError(
            "Wheel candidates require a non-empty 'id' value."
        )

    candidate_id = str(value).strip()
    if not candidate_id:
        raise InvalidWheelCandidateError(
            "Wheel candidates require a non-empty 'id' value."
        )
    return candidate_id


def _normalize_excluded_ids(excluded_ids: Iterable[Any] | None) -> tuple[str, ...]:
    if excluded_ids is None:
        return ()

    if isinstance(excluded_ids, (str, bytes)):
        excluded_ids = [excluded_ids]

    normalized = {
        str(candidate_id).strip()
        for candidate_id in excluded_ids
        if candidate_id is not None and str(candidate_id).strip()
    }
    return tuple(sorted(normalized))


class WheelPoolSnapshot:
    """Detached snapshot of one filtered Collection candidate pool."""

    __slots__ = ("_candidate_ids", "_records")

    def __init__(self, candidates: Iterable[Mapping[str, Any]]):
        if isinstance(candidates, (str, bytes, Mapping)):
            raise TypeError(
                "Wheel candidates must be an iterable of mapping records."
            )

        candidate_ids: list[str] = []
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, Mapping):
                raise TypeError(
                    "Wheel candidate at index "
                    f"{index} must be a mapping record."
                )
            if "id" not in candidate:
                raise InvalidWheelCandidateError(
                    f"Wheel candidate at index {index} has no 'id' field."
                )

            candidate_id = _normalize_candidate_id(candidate["id"])
            if candidate_id in seen_ids:
                raise InvalidWheelCandidateError(
                    f"Wheel candidate id '{candidate_id}' appears more than once."
                )

            record = copy.deepcopy(dict(candidate))
            record["id"] = candidate_id

            candidate_ids.append(candidate_id)
            records.append(record)
            seen_ids.add(candidate_id)

        self._candidate_ids = tuple(candidate_ids)
        self._records = tuple(records)

    @property
    def size(self) -> int:
        """Return the number of captured Collection candidates."""

        return len(self._records)

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        """Return candidate identities in the supplied Collection order."""

        return self._candidate_ids

    def candidates(self) -> list[dict[str, Any]]:
        """Return detached copies of all candidates."""

        return copy.deepcopy(list(self._records))

    def eligible_candidates(
        self,
        excluded_ids: Iterable[Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return detached candidates not removed by this spin's exclusions."""

        excluded = set(_normalize_excluded_ids(excluded_ids))
        return copy.deepcopy(
            [
                record
                for candidate_id, record in zip(
                    self._candidate_ids,
                    self._records,
                    strict=True,
                )
                if candidate_id not in excluded
            ]
        )


@dataclass(frozen=True)
class WheelSelection:
    """Detached result metadata for one Wheel selection."""

    candidate_id: str
    pool_size: int
    eligible_size: int
    excluded_ids: tuple[str, ...]
    _candidate: dict[str, Any] = field(repr=False, compare=False)

    @property
    def candidate(self) -> dict[str, Any]:
        """Return a detached copy of the selected Collection record."""

        return copy.deepcopy(self._candidate)


class CollectionWheelSelectionService:
    """Select from a supplied Collection pool without UI or persistence."""

    def __init__(
        self,
        *,
        seed: Any | None = None,
        rng: Any | None = None,
    ):
        if seed is not None and rng is not None:
            raise ValueError("Pass either seed or rng, not both.")

        self._rng = rng if rng is not None else random.Random(seed)
        if not callable(getattr(self._rng, "randrange", None)):
            raise TypeError("Wheel rng must expose randrange(stop).")

    @staticmethod
    def snapshot(
        candidates: Iterable[Mapping[str, Any]],
    ) -> WheelPoolSnapshot:
        """Capture one detached, reusable Collection pool."""

        return WheelPoolSnapshot(candidates)

    def select(
        self,
        pool: WheelPoolSnapshot | Iterable[Mapping[str, Any]],
        *,
        excluded_ids: Iterable[Any] | None = None,
    ) -> WheelSelection:
        """Select one eligible candidate from a snapshot or candidate iterable."""

        snapshot = (
            pool
            if isinstance(pool, WheelPoolSnapshot)
            else self.snapshot(pool)
        )
        normalized_exclusions = _normalize_excluded_ids(excluded_ids)

        if snapshot.size == 0:
            raise EmptyWheelPoolError(
                "Cannot select a Wheel result from an empty Collection pool."
            )

        eligible = snapshot.eligible_candidates(normalized_exclusions)
        if not eligible:
            raise ExhaustedWheelPoolError(
                "Every Collection Wheel candidate is excluded from this spin."
            )

        selected = eligible[self._rng.randrange(len(eligible))]
        candidate_id = _normalize_candidate_id(selected["id"])

        return WheelSelection(
            candidate_id=candidate_id,
            pool_size=snapshot.size,
            eligible_size=len(eligible),
            excluded_ids=normalized_exclusions,
            _candidate=copy.deepcopy(selected),
        )


__all__ = [
    "CollectionWheelError",
    "CollectionWheelSelectionService",
    "EmptyWheelPoolError",
    "ExhaustedWheelPoolError",
    "InvalidWheelCandidateError",
    "WheelPoolSnapshot",
    "WheelSelection",
]
