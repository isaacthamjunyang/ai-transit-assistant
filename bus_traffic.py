"""The one place bus ride minutes are adjusted for traffic (a documented assumption, see config.BUS_PEAK_FACTOR).

Every caller that has bus minutes (the OneMap parser, the planner's totals, the static planner, the destination
estimate, the search seed) goes through bus_ride_minutes(). It is never applied to rail, walking, waiting or the live
arrival at the boarding stop. The factor is chosen by the time the bus leg starts, in Singapore time."""

from datetime import datetime, timedelta, timezone

import config

SGT = timezone(timedelta(hours=8))


def _singapore(moment: datetime) -> datetime:
    return moment.replace(tzinfo=SGT) if moment.tzinfo is None else moment.astimezone(SGT)


def bus_factor(start: datetime) -> float:
    """BUS_PEAK_FACTOR when `start` is inside a weekday peak window (start inclusive, end exclusive), else 1.0.
    Weekends and public holidays are always 1.0."""
    moment = _singapore(start)
    if moment.weekday() >= 5 or moment.date() in config.PUBLIC_HOLIDAYS:
        return 1.0
    clock = moment.time()
    for opens, closes in config.BUS_PEAK_WINDOWS:
        if opens <= clock < closes:
            return config.BUS_PEAK_FACTOR
    return 1.0


def bus_ride_minutes(base_minutes: float | None, start: datetime) -> float | None:
    """The minutes a bus leg takes with the traffic factor of its start time. None stays None."""
    if base_minutes is None:
        return None
    return base_minutes * bus_factor(start)
