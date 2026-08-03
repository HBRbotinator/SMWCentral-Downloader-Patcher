"""Pure geometry and timing helpers for the graphical Collection Wheel."""

from __future__ import annotations

import copy
import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WheelSegment:
    """One equal candidate segment in Collection order."""

    candidate_id: str
    title: str
    start_angle: float
    extent: float
    center_angle: float
    show_label: bool


@dataclass(frozen=True)
class WheelLayout:
    """Detached geometry for one candidate pool."""

    segments: tuple[WheelSegment, ...]
    selected_id: str | None
    selected_index: int | None

    @property
    def size(self) -> int:
        """Return the represented candidate count."""

        return len(self.segments)


def build_wheel_layout(
    candidates: Iterable[Mapping[str, Any]],
    *,
    selected_id: Any | None = None,
    max_labels: int = 18,
) -> WheelLayout:
    """Build equal detached segments while limiting only visible labels."""

    if isinstance(candidates, (str, bytes, Mapping)):
        raise TypeError("Wheel candidates must be an iterable of mappings")
    if isinstance(max_labels, bool) or not isinstance(max_labels, int):
        raise TypeError("max_labels must be an integer")
    if max_labels < 0:
        raise ValueError("max_labels cannot be negative")

    records = []
    seen_ids = set()
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, Mapping):
            raise TypeError(
                f"Wheel candidate at index {index} must be a mapping"
            )
        candidate_id = str(candidate.get("id", "")).strip()
        if not candidate_id:
            raise ValueError(
                f"Wheel candidate at index {index} requires an id"
            )
        if candidate_id in seen_ids:
            raise ValueError(
                f"Wheel candidate id '{candidate_id}' appears more than once"
            )
        title = str(candidate.get("title", "")).strip() or candidate_id
        records.append(
            {
                "id": candidate_id,
                "title": title,
            }
        )
        seen_ids.add(candidate_id)

    normalized_selected = None
    selected_index = None
    if selected_id is not None:
        normalized_selected = str(selected_id).strip()
        if not normalized_selected:
            raise ValueError("selected_id cannot be empty")
        try:
            selected_index = next(
                index
                for index, record in enumerate(records)
                if record["id"] == normalized_selected
            )
        except StopIteration as error:
            raise ValueError(
                "selected_id must exist in the represented candidate pool"
            ) from error

    count = len(records)
    if count == 0:
        return WheelLayout(
            segments=(),
            selected_id=normalized_selected,
            selected_index=None,
        )

    labeled_indices = _label_indices(
        count,
        max_labels=max_labels,
        selected_index=selected_index,
    )
    extent = 360.0 / count
    segments = tuple(
        WheelSegment(
            candidate_id=record["id"],
            title=record["title"],
            start_angle=index * extent,
            extent=extent,
            center_angle=(index + 0.5) * extent,
            show_label=index in labeled_indices,
        )
        for index, record in enumerate(copy.deepcopy(records))
    )
    return WheelLayout(
        segments=segments,
        selected_id=normalized_selected,
        selected_index=selected_index,
    )


def build_spin_frames(
    layout: WheelLayout,
    *,
    turns: int = 5,
    frame_count: int = 61,
    pointer_angle: float = 90.0,
) -> tuple[float, ...]:
    """Return deterministic ease-out rotation frames landing on the winner."""

    if not isinstance(layout, WheelLayout):
        raise TypeError("layout must be a WheelLayout")
    if layout.selected_index is None:
        raise ValueError("Spin frames require a selected segment")
    if isinstance(turns, bool) or not isinstance(turns, int) or turns < 1:
        raise ValueError("turns must be a positive integer")
    if (
        isinstance(frame_count, bool)
        or not isinstance(frame_count, int)
        or frame_count < 2
    ):
        raise ValueError("frame_count must be an integer of at least 2")
    pointer_angle = _finite_number(pointer_angle, "pointer_angle")

    selected = layout.segments[layout.selected_index]
    landing_offset = (
        pointer_angle - selected.center_angle
    ) % 360.0
    total_rotation = turns * 360.0 + landing_offset

    step_count = frame_count - 1
    total_weight = step_count * (step_count + 1) / 2
    cumulative_weight = 0.0
    frames = [0.0]
    for weight in range(step_count, 0, -1):
        cumulative_weight += weight
        frames.append(total_rotation * cumulative_weight / total_weight)

    frames[-1] = total_rotation
    return tuple(frames)


def _label_indices(count, *, max_labels, selected_index):
    if max_labels == 0:
        return {selected_index} if selected_index is not None else set()
    if count <= max_labels:
        return set(range(count))

    indices = {
        math.floor(index * count / max_labels)
        for index in range(max_labels)
    }
    if selected_index is not None and selected_index not in indices:
        removable = max(
            indices,
            key=lambda index: _circular_distance(
                index,
                selected_index,
                count,
            ),
        )
        indices.remove(removable)
        indices.add(selected_index)
    return indices


def _circular_distance(first, second, count):
    direct = abs(first - second)
    return min(direct, count - direct)


def _finite_number(value, label):
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    return number


__all__ = [
    "WheelLayout",
    "WheelSegment",
    "build_spin_frames",
    "build_wheel_layout",
]
