"""The one walking-speed input for the whole server.

resolve_walk_speed turns what the page sent into the speed used. range_speeds gives the point,
slow and fast speeds from it. walk_minutes is the one place a walking distance becomes minutes.
The module reads no secrets, logs nothing and stores nothing.
"""

import math

from config import (
    RANGE_FAST_RATIO,
    RANGE_SLOW_RATIO,
    WALK_SPEED_DEFAULT_MPS,
    WALK_SPEED_MAX_MPS,
    WALK_SPEED_MIN_MPS,
)

SOURCE_DEFAULT = "default"
SOURCES = ("gps", "cadence", "remembered", SOURCE_DEFAULT)

# How a walking time is rounded. "raw" is a float. "round" is the nearest minute, half up. "display"
# is the same with a floor of 1 (what the overview and the AI sentence show). "ceil" is the existing sums.
MODES = ("raw", "round", "display", "ceil")


def resolve_walk_speed(value=None, source=None, *, demo: bool = False) -> tuple[float, str]:
    """(speed_used, source). Anything missing or unusable is the default with source "default".

    The value must be a finite number (a numeric string from a query is accepted). It is clamped
    to [WALK_SPEED_MIN_MPS, WALK_SPEED_MAX_MPS] and rounded to two decimals, so the number the
    page shows is the number every calculation used. In Demo Mode the client value is ignored.
    """
    fallback = (WALK_SPEED_DEFAULT_MPS, SOURCE_DEFAULT)
    if demo or not isinstance(source, str) or source not in SOURCES or source == SOURCE_DEFAULT:
        return fallback
    if isinstance(value, bool):
        return fallback
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return fallback
    if not isinstance(value, (int, float)):
        return fallback
    number = float(value)
    if not math.isfinite(number):
        return fallback
    clamped = min(WALK_SPEED_MAX_MPS, max(WALK_SPEED_MIN_MPS, number))
    return round(clamped, 2), source


def range_speeds(speed_m_s: float = WALK_SPEED_DEFAULT_MPS) -> tuple[float, float, float]:
    """(point, slow, fast). Slow is floored at the minimum; fast never goes beyond a normal walk."""
    slow = max(WALK_SPEED_MIN_MPS, speed_m_s * RANGE_SLOW_RATIO)
    fast = min(speed_m_s * RANGE_FAST_RATIO, WALK_SPEED_MAX_MPS)
    return speed_m_s, slow, fast


def walk_minutes(distance_m: float, speed_m_s: float = WALK_SPEED_DEFAULT_MPS, mode: str = "raw"):
    """Minutes to walk distance_m at speed_m_s, in the named rounding mode."""
    minutes = distance_m / speed_m_s / 60
    if mode == "raw":
        return minutes
    if mode == "ceil":
        return math.ceil(minutes)
    if mode == "round":
        return int(minutes + 0.5)
    if mode == "display":
        return max(1, int(math.floor(minutes + 0.5)))
    raise ValueError("unknown rounding mode: " + str(mode))


def response_fields(speed_m_s: float, source: str) -> dict:
    """The two fields every scored response carries."""
    return {"walk_speed_used": round(speed_m_s, 2), "walk_speed_source": source}
