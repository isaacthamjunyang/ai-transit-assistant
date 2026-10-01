"""Display-only walking-pace hint.

The catch-probability formula, leave-by, notification timing, reroute
choice, and chosen_action stay elsewhere. This module only classifies a
category for the chip next to the probability ring.
"""

PACE_HIDE_DISTANCE_M = 30
PACE_UNLIKELY_RANGE_HIGH = 40
PACE_FASTER_BELOW = 50
PACE_SLIGHTLY_FASTER_BELOW = 65
PACE_SLOWER_RANGE_LOW = 75
PACE_SLIGHTLY_SLOWER_AT = 80

_HIDDEN_QUALITY = frozenset({"stale", "unavailable"})
_SLOW = frozenset({"slower", "slightly_slower"})
_RANK = {
    "unlikely": 0,
    "faster": 1,
    "slightly_faster": 2,
    "steady": 3,
    "slightly_slower": 4,
    "slower": 5,
}


def pace_guidance(
    point,
    range_low,
    range_high,
    data_quality,
    location_uncertain,
    distance_to_stop_m,
    previous_category,
):
    """Return the threshold category, or None when the chip stays hidden.

    First match wins. ``previous_category`` does not change this result:
    a single previous value cannot remember that a slower category was
    already seen once. ``smooth_pace`` applies that two-poll rule.
    """
    del previous_category
    if data_quality in _HIDDEN_QUALITY or location_uncertain is True:
        return None
    if _closer_than_hide(distance_to_stop_m):
        return None
    if range_high < PACE_UNLIKELY_RANGE_HIGH:
        return "unlikely"
    if point < PACE_FASTER_BELOW:
        return "faster"
    if PACE_FASTER_BELOW <= point < PACE_SLIGHTLY_FASTER_BELOW:
        return "slightly_faster"
    if range_low >= PACE_SLOWER_RANGE_LOW and data_quality != "schedule":
        return "slower"
    if point >= PACE_SLIGHTLY_SLOWER_AT and data_quality != "schedule":
        return "slightly_slower"
    return "steady"


def smooth_pace(category, previous_category, pending):
    """Return ``(display, pending)`` after one poll.

    A move toward ``slower`` or ``slightly_slower`` from a faster or
    steadier category is kept back until that new category arrives on a
    second consecutive poll. A move to ``unlikely``, ``faster``,
    ``slightly_faster``, or ``steady``, and a hidden result, apply
    immediately. ``previous_category`` is the category on screen.
    """
    if category not in _SLOW:
        return category, None
    if previous_category is None or previous_category == category:
        return category, None
    if _RANK[previous_category] < _RANK[category]:
        if pending == category:
            return category, None
        return previous_category, category
    return category, None


class PaceSession:
    """Poll memory for the two-poll slower rule. Not stored in SQLite."""

    def __init__(self):
        self.display = None
        self.pending = None

    def reset(self):
        self.display = None
        self.pending = None

    def poll(
        self,
        point,
        range_low,
        range_high,
        data_quality,
        location_uncertain,
        distance_to_stop_m,
    ):
        raw = pace_guidance(
            point,
            range_low,
            range_high,
            data_quality,
            location_uncertain,
            distance_to_stop_m,
            self.display,
        )
        self.display, self.pending = smooth_pace(raw, self.display, self.pending)
        return self.display


def _closer_than_hide(distance_to_stop_m) -> bool:
    if isinstance(distance_to_stop_m, bool) or not isinstance(distance_to_stop_m, (int, float)):
        return False
    return distance_to_stop_m < PACE_HIDE_DISTANCE_M
