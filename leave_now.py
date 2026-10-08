"""Step 10 leave-now timing and delivery facts.

notification_time = leave_by - 60s. This module does not change the
Step 9 leave-by formula, does not score probability, and does not call
LTA, OneMap, or OpenAI.
"""

from datetime import datetime, timedelta, timezone

from journey import parse_journey_time

SGT = timezone(timedelta(hours=8))
LEAVE_NOW_MARGIN_S = 60
RANGE_HIGH_MINIMUM = 40


def notification_time_from_leave_by(leave_by: datetime) -> datetime:
    """The 60s margin applies only here. It is not part of leave-by."""
    return leave_by - timedelta(seconds=LEAVE_NOW_MARGIN_S)


def notification_time_iso(leave_by_iso: str | None) -> str | None:
    if not isinstance(leave_by_iso, str) or not leave_by_iso.strip():
        return None
    parsed = parse_journey_time(leave_by_iso)
    notified = notification_time_from_leave_by(parsed)
    return notified.astimezone(SGT).replace(microsecond=0).isoformat()


def leave_now_notice(
    buses: list[dict],
    *,
    service_no: str,
    stop_code: str,
    stop_name: str,
    leave_by_iso: str | None,
    notification_time: str | None,
    arrival_status: str = "ok",
) -> dict:
    """Facts for one primary bus. The browser still decides permission and staleness."""
    primary = _primary_bus(buses)
    bus_id = None
    if primary is not None and isinstance(primary.get("position"), str) and primary["position"]:
        bus_id = f"{service_no}|{stop_code}|{primary['position']}"
    chance = primary.get("probability") if isinstance(primary, dict) else None
    point = _percent(chance, "point")
    range_low = _percent(chance, "range_low")
    range_high = _percent(chance, "range_high")
    quality = chance.get("data_quality") if isinstance(chance, dict) else None
    missed = bool(primary.get("is_missed")) if isinstance(primary, dict) else True
    eligible = (
        arrival_status == "ok"
        and primary is not None
        and not missed
        and leave_by_iso is not None
        and notification_time is not None
        and point is not None
        and range_low is not None
        and range_high is not None
        and range_high >= RANGE_HIGH_MINIMUM
        and quality != "location uncertain"
        and not (isinstance(chance, dict) and chance.get("at_stop") is True)  # nothing to walk to
        and bool(service_no)
        and bool(stop_code)
        and bool(stop_name)
    )
    title = None
    body = None
    if eligible and point is not None and range_low is not None and range_high is not None:
        title = f"Leave Now — Bus {service_no}"
        # the range is shown only when it differs from the point's own band (low and high are not the same number)
        chance_text = (
            f"Catch probability: about {point}%."
            if range_low == range_high
            else f"Catch probability: {point}% ({range_low}–{range_high}%)."
        )
        body = f"Walk to {stop_name} ({stop_code}) now to catch Bus {service_no}. " + chance_text
    return {
        "bus_id": bus_id,
        "eligible": eligible,
        "title": title,
        "body": body,
        "range_high": range_high,
    }


def _primary_bus(buses: list[dict]) -> dict | None:
    for bus in buses:
        if bus.get("is_primary") and not bus.get("is_missed"):
            return bus
    return None


def _percent(chance: object, key: str) -> int | None:
    if not isinstance(chance, dict):
        return None
    value = chance.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value
