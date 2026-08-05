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


def build_timed_spin_frames(
    layout: WheelLayout,
    *,
    turns: int,
    duration_ms: int,
    frame_delay_ms: int,
    pointer_angle: float = 90.0,
    landing_offset: float = 0.5,
    acceleration_end: float = 0.10,
    deceleration_start: float = 0.27,
    deceleration_bias: float = -0.35,
) -> tuple[float, ...]:
    """Sample the browser-style continuous motion for native rendering."""

    if not isinstance(layout, WheelLayout):
        raise TypeError("layout must be a WheelLayout")
    if layout.selected_index is None:
        raise ValueError("Spin frames require a selected segment")
    if isinstance(turns, bool) or not isinstance(turns, int) or turns < 1:
        raise ValueError("turns must be a positive integer")
    if (
        isinstance(duration_ms, bool)
        or not isinstance(duration_ms, int)
        or duration_ms < 1
    ):
        raise ValueError("duration_ms must be a positive integer")
    if (
        isinstance(frame_delay_ms, bool)
        or not isinstance(frame_delay_ms, int)
        or frame_delay_ms < 1
    ):
        raise ValueError("frame_delay_ms must be a positive integer")

    pointer_angle = _finite_number(pointer_angle, "pointer_angle")
    landing_offset = _unit_number(landing_offset, "landing_offset")
    acceleration_end = _unit_number(
        acceleration_end,
        "acceleration_end",
        inclusive_upper=False,
    )
    deceleration_start = _unit_number(
        deceleration_start,
        "deceleration_start",
        inclusive_upper=False,
    )
    deceleration_bias = _finite_number(
        deceleration_bias,
        "deceleration_bias",
    )
    if acceleration_end <= 0.0:
        raise ValueError("acceleration_end must be greater than zero")
    if deceleration_start <= acceleration_end:
        raise ValueError(
            "deceleration_start must be greater than acceleration_end"
        )

    selected = layout.segments[layout.selected_index]
    target_angle = (
        selected.start_angle + selected.extent * landing_offset
    )
    alignment = (pointer_angle - target_angle) % 360.0
    total_rotation = turns * 360.0 + alignment

    step_count = max(1, round(duration_ms / frame_delay_ms))
    frames = tuple(
        total_rotation
        * _continuous_spin_progress(
            step / step_count,
            acceleration_end=acceleration_end,
            deceleration_start=deceleration_start,
            deceleration_bias=deceleration_bias,
        )
        for step in range(step_count + 1)
    )
    return (*frames[:-1], total_rotation)


def _continuous_spin_progress(
    elapsed_share,
    *,
    acceleration_end,
    deceleration_start,
    deceleration_bias,
):
    elapsed = min(1.0, max(0.0, float(elapsed_share)))
    if elapsed >= 1.0:
        return 1.0

    acceleration_duration = acceleration_end
    cruise_duration = deceleration_start - acceleration_end
    deceleration_duration = 1.0 - deceleration_start
    deceleration_area = _deceleration_velocity_integral(
        1.0,
        deceleration_bias,
    )
    total_velocity_area = (
        acceleration_duration * 0.5
        + cruise_duration
        + deceleration_duration * deceleration_area
    )

    if elapsed <= acceleration_end:
        local = elapsed / acceleration_duration
        traveled_area = (
            acceleration_duration * _smooth_step_integral(local)
        )
    elif elapsed <= deceleration_start:
        traveled_area = (
            acceleration_duration * 0.5
            + elapsed
            - acceleration_end
        )
    else:
        local = (
            (elapsed - deceleration_start)
            / deceleration_duration
        )
        traveled_area = (
            acceleration_duration * 0.5
            + cruise_duration
            + deceleration_duration
            * _deceleration_velocity_integral(
                local,
                deceleration_bias,
            )
        )

    return traveled_area / total_velocity_area


def _smooth_step_integral(value):
    unit = min(1.0, max(0.0, float(value)))
    return unit ** 3 - 0.5 * unit ** 4


def _deceleration_velocity_integral(value, bias):
    unit = min(1.0, max(0.0, float(value)))
    return (
        unit
        + (-3.0 + bias) * unit ** 3 / 3.0
        + (2.0 - 2.0 * bias) * unit ** 4 / 4.0
        + bias * unit ** 5 / 5.0
    )


def _unit_number(value, label, *, inclusive_upper=True):
    number = _finite_number(value, label)
    upper_valid = number <= 1.0 if inclusive_upper else number < 1.0
    if number < 0.0 or not upper_valid:
        bracket = "[0, 1]" if inclusive_upper else "[0, 1)"
        raise ValueError(f"{label} must be in {bracket}")
    return number


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
    "build_timed_spin_frames",
    "build_wheel_layout",
]
