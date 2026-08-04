"""Safe varied landing positions for browser Wheel animations."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Any


BROWSER_LANDING_EXTREME_EARLY_BAND = (0.06, 0.12)
BROWSER_LANDING_EARLY_BAND = (0.18, 0.34)
BROWSER_LANDING_CENTER_BAND = (0.40, 0.60)
BROWSER_LANDING_LATE_BAND = (0.66, 0.82)
BROWSER_LANDING_EXTREME_LATE_BAND = (0.88, 0.94)

BROWSER_LANDING_EXTREME_ZONE_SHARE = 0.26
BROWSER_LANDING_NEAR_ZONE_SHARE = 0.19
BROWSER_LANDING_CENTER_ZONE_SHARE = 0.10

_SYSTEM_RANDOM = random.SystemRandom()


def build_browser_landing_offset(
    unit_supplier: Callable[[], Any] | None = None,
) -> float:
    """Return a safe varied point inside the predetermined winner segment."""

    supplier = unit_supplier or _SYSTEM_RANDOM.random
    if not callable(supplier):
        raise TypeError("unit_supplier must be callable or None")

    zone_draw = _unit_value(supplier(), "zone draw")
    position_draw = _unit_value(supplier(), "position draw")
    band = _landing_band(zone_draw)

    lower, upper = band
    return round(
        lower + (upper - lower) * position_draw,
        6,
    )


def _landing_band(zone_draw: float) -> tuple[float, float]:
    extreme = BROWSER_LANDING_EXTREME_ZONE_SHARE
    near = BROWSER_LANDING_NEAR_ZONE_SHARE
    center = BROWSER_LANDING_CENTER_ZONE_SHARE

    extreme_early_end = extreme
    early_end = extreme_early_end + near
    center_end = early_end + center
    late_end = center_end + near

    if zone_draw < extreme_early_end:
        return BROWSER_LANDING_EXTREME_EARLY_BAND
    if zone_draw < early_end:
        return BROWSER_LANDING_EARLY_BAND
    if zone_draw < center_end:
        return BROWSER_LANDING_CENTER_BAND
    if zone_draw < late_end:
        return BROWSER_LANDING_LATE_BAND
    return BROWSER_LANDING_EXTREME_LATE_BAND


def _unit_value(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric in [0, 1)")

    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{label} must be numeric in [0, 1)"
        ) from error

    if not math.isfinite(number) or not 0.0 <= number < 1.0:
        raise ValueError(f"{label} must be numeric in [0, 1)")
    return number


__all__ = [
    "BROWSER_LANDING_EXTREME_EARLY_BAND",
    "BROWSER_LANDING_EARLY_BAND",
    "BROWSER_LANDING_CENTER_BAND",
    "BROWSER_LANDING_LATE_BAND",
    "BROWSER_LANDING_EXTREME_LATE_BAND",
    "BROWSER_LANDING_EXTREME_ZONE_SHARE",
    "BROWSER_LANDING_NEAR_ZONE_SHARE",
    "BROWSER_LANDING_CENTER_ZONE_SHARE",
    "build_browser_landing_offset",
]
