"""Weighted safe landing positions for browser Wheel animations."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Any


BROWSER_LANDING_HAIRLINE_EARLY_BAND = (0.025, 0.055)
BROWSER_LANDING_EXTREME_EARLY_BAND = (0.07, 0.13)
BROWSER_LANDING_EARLY_BAND = (0.18, 0.32)
BROWSER_LANDING_INNER_EARLY_BAND = (0.36, 0.46)
BROWSER_LANDING_CENTER_BAND = (0.47, 0.53)
BROWSER_LANDING_INNER_LATE_BAND = (0.54, 0.64)
BROWSER_LANDING_LATE_BAND = (0.68, 0.82)
BROWSER_LANDING_EXTREME_LATE_BAND = (0.87, 0.93)
BROWSER_LANDING_HAIRLINE_LATE_BAND = (0.945, 0.975)

BROWSER_LANDING_WEIGHTED_BANDS = (
    (BROWSER_LANDING_HAIRLINE_EARLY_BAND, 0.08),
    (BROWSER_LANDING_EXTREME_EARLY_BAND, 0.14),
    (BROWSER_LANDING_EARLY_BAND, 0.15),
    (BROWSER_LANDING_INNER_EARLY_BAND, 0.10),
    (BROWSER_LANDING_CENTER_BAND, 0.06),
    (BROWSER_LANDING_INNER_LATE_BAND, 0.10),
    (BROWSER_LANDING_LATE_BAND, 0.15),
    (BROWSER_LANDING_EXTREME_LATE_BAND, 0.14),
    (BROWSER_LANDING_HAIRLINE_LATE_BAND, 0.08),
)

_SYSTEM_RANDOM = random.SystemRandom()


def build_browser_landing_offset(
    unit_supplier: Callable[[], Any] | None = None,
) -> float:
    """Return a safe weighted point inside the predetermined winner segment."""

    supplier = unit_supplier or _SYSTEM_RANDOM.random
    if not callable(supplier):
        raise TypeError("unit_supplier must be callable or None")

    zone_draw = _unit_value(supplier(), "zone draw")
    position_draw = _unit_value(supplier(), "position draw")
    lower, upper = _landing_band(zone_draw)
    return round(lower + (upper - lower) * position_draw, 6)


def _landing_band(zone_draw: float) -> tuple[float, float]:
    cumulative = 0.0
    for band, weight in BROWSER_LANDING_WEIGHTED_BANDS:
        cumulative += weight
        if zone_draw < cumulative:
            return band

    return BROWSER_LANDING_WEIGHTED_BANDS[-1][0]


def _unit_value(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric in [0, 1)")

    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be numeric in [0, 1)") from error

    if not math.isfinite(number) or not 0.0 <= number < 1.0:
        raise ValueError(f"{label} must be numeric in [0, 1)")
    return number


__all__ = [
    "BROWSER_LANDING_HAIRLINE_EARLY_BAND",
    "BROWSER_LANDING_EXTREME_EARLY_BAND",
    "BROWSER_LANDING_EARLY_BAND",
    "BROWSER_LANDING_INNER_EARLY_BAND",
    "BROWSER_LANDING_CENTER_BAND",
    "BROWSER_LANDING_INNER_LATE_BAND",
    "BROWSER_LANDING_LATE_BAND",
    "BROWSER_LANDING_EXTREME_LATE_BAND",
    "BROWSER_LANDING_HAIRLINE_LATE_BAND",
    "BROWSER_LANDING_WEIGHTED_BANDS",
    "build_browser_landing_offset",
]
