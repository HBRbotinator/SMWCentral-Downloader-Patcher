"""Safe varied landing positions for browser Wheel animations."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from typing import Any


BROWSER_LANDING_EARLY_BAND = (0.18, 0.34)
BROWSER_LANDING_CENTER_BAND = (0.42, 0.58)
BROWSER_LANDING_LATE_BAND = (0.66, 0.82)
BROWSER_LANDING_EDGE_ZONE_SHARE = 0.42

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

    if zone_draw < BROWSER_LANDING_EDGE_ZONE_SHARE:
        band = BROWSER_LANDING_EARLY_BAND
    elif zone_draw < BROWSER_LANDING_EDGE_ZONE_SHARE * 2:
        band = BROWSER_LANDING_LATE_BAND
    else:
        band = BROWSER_LANDING_CENTER_BAND

    lower, upper = band
    return round(
        lower + (upper - lower) * position_draw,
        6,
    )


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
    "BROWSER_LANDING_EARLY_BAND",
    "BROWSER_LANDING_CENTER_BAND",
    "BROWSER_LANDING_LATE_BAND",
    "BROWSER_LANDING_EDGE_ZONE_SHARE",
    "build_browser_landing_offset",
]
