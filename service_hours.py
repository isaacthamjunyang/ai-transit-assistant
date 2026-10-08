"""Is a bus service running at a stop at a given time? One shared answer for every place that picks or lists buses.

Data: the cached LTA BusRoutes rows. Each row (service, direction, stop) has the first and last bus at that stop for
three day types: WD_FirstBus / WD_LastBus (Monday to Friday), SAT_FirstBus / SAT_LastBus, SUN_FirstBus / SUN_LastBus
(Sunday and public holidays). Values are "HHMM" text, or "-" when the service does not run on that day type.
A last bus earlier than the first bus (for example 0500 to 0030) crosses midnight into the next calendar day.

Rules:
- The time is the time the user would BOARD (Singapore time), not the time of the request. Callers work it out.
- A bus is running from its first bus to its last bus plus a small grace (LAST_BUS_GRACE_MINUTES), because the
  published last time is when the last bus leaves that stop and it can be a few minutes late.
- Live data wins: a bus that live arrivals show coming is in service whatever the schedule says.
- Missing hours (no row, or no readable time) mean "eligible", and are counted so a test can see how often.
"""

from datetime import date, datetime, timedelta, timezone

from pathlib import Path

from config import PUBLIC_HOLIDAYS, PUBLIC_HOLIDAYS_YEAR
from lta_static import CACHE_DIR, ROUTES_FILENAME

SGT = timezone(timedelta(hours=8))
LAST_BUS_GRACE_MINUTES = 5
BUS_DATA_MAX_AGE_DAYS = 30
LIVE_MAX_AGE_SECONDS = 120  # a live arrival overrides the schedule only while the lookup is this recent
PLAN_AHEAD_MINUTES = 60  # an arrive-by boarding time this much later than the shown one means "planning ahead"
NO_SERVICE = "no_service"

_FIELDS = {"WD": ("WD_FirstBus", "WD_LastBus"), "SAT": ("SAT_FirstBus", "SAT_LastBus"), "SUN": ("SUN_FirstBus", "SUN_LastBus")}
_INDEX_ATTRIBUTE = "_service_hours_index"

_missing_hours = {"count": 0}


def missing_hours_count() -> int:
    """How many checks found no usable hours and so treated the service as eligible."""
    return _missing_hours["count"]


def reset_missing_hours_count() -> None:
    _missing_hours["count"] = 0


def bus_data_date(cache_dir: Path | None = None) -> str | None:
    """The Singapore date (YYYY-MM-DD) the cached BusRoutes file was written, or None when it is missing."""
    path = (cache_dir or CACHE_DIR) / ROUTES_FILENAME
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None
    return datetime.fromtimestamp(stamp, SGT).date().isoformat()


def data_status(cache_dir: Path | None = None) -> dict:
    """What the menu shows: how far the holiday list reaches and when the bus data was written. No input, no place."""
    return {"holidays_year": PUBLIC_HOLIDAYS_YEAR, "bus_data_date": bus_data_date(cache_dir)}


def startup_warning(today: date, cache_dir: Path | None = None) -> str | None:
    """One sentence when the bus data is older than 30 days or the holiday list does not reach this year."""
    problems = []
    written = bus_data_date(cache_dir)
    if written is not None:
        age = (today - date.fromisoformat(written)).days
        if age > BUS_DATA_MAX_AGE_DAYS:
            problems.append(f"the bus data is {age} days old (written {written})")
    if today.year > PUBLIC_HOLIDAYS_YEAR:
        problems.append(f"the public holiday list ends in {PUBLIC_HOLIDAYS_YEAR} but it is now {today.year}")
    if not problems:
        return None
    return "Out of date: " + "; ".join(problems) + "."


def day_type(day: date) -> str:
    """WD (Monday to Friday), SAT, or SUN. A public holiday counts as SUN."""
    if day in PUBLIC_HOLIDAYS:
        return "SUN"
    weekday = day.weekday()
    if weekday == 5:
        return "SAT"
    if weekday == 6:
        return "SUN"
    return "WD"


def service_runs_at(
    cache,
    service_no: str,
    stop_code: str,
    when: datetime,
    direction: int | None = None,
    live: bool = False,
) -> bool:
    """True when the service runs at this stop at `when` (a Singapore time), or when its hours are unknown."""
    if live:
        return True
    moment = _as_sgt(when)
    rows = _rows(cache, str(service_no).strip(), str(stop_code).strip(), direction)
    verdicts = [_row_verdict(row, moment) for row in rows]
    known = [verdict for verdict in verdicts if verdict is not None]
    if not known:
        _missing_hours["count"] += 1
        return True
    return any(known)


def live_is_recent(fetched_at, now: datetime) -> bool:
    """True when the live lookup is known and at most LIVE_MAX_AGE_SECONDS old. Unknown age is not recent."""
    if not isinstance(fetched_at, str):
        return False
    try:
        fetched = _as_sgt(datetime.fromisoformat(fetched_at.replace("Z", "+00:00")))
    except ValueError:
        return False
    return abs((_as_sgt(now) - fetched).total_seconds()) <= LIVE_MAX_AGE_SECONDS


def boarding_times(
    moment: datetime,
    walk_minutes: float,
    wait_minutes: float,
    after_boarding_minutes: float | None,
    arrive_by: datetime | None,
) -> list[datetime]:
    """The times the first leg must be running at. One rule for every path that picks buses.

    - The shown time: now plus the walk plus the expected wait. This is the boarding the card's "Arrive about" uses.
    - With an arrive-by time, also the time that works back from it (never earlier than the shown time). When that is
      more than PLAN_AHEAD_MINUTES after the shown time the user is planning ahead and is not boarding now, so only
      the arrive-by time is checked."""
    now = _as_sgt(moment)
    shown = now + timedelta(minutes=walk_minutes + wait_minutes)
    if arrive_by is None or after_boarding_minutes is None:
        return [shown]
    target = _as_sgt(arrive_by)
    derived = max(now + timedelta(minutes=walk_minutes), target - timedelta(minutes=after_boarding_minutes))
    if derived - shown > timedelta(minutes=PLAN_AHEAD_MINUTES):
        return [derived]
    return [shown, max(derived, shown)]


def legs_run_at(cache, legs: list[dict], board_at: datetime, transfer_wait_minutes: float = 0.0) -> bool:
    """Every leg of a route runs when the user would board it. Leg 1 boards at `board_at`; each later leg boards after
    the earlier rides and the transfer wait."""
    boarding = _as_sgt(board_at)
    for leg in legs:
        if not service_runs_at(
            cache, leg.get("service_no", ""), leg.get("boarding_stop_code", ""), boarding, leg.get("direction")
        ):
            return False
        ride = leg.get("ride_minutes")
        boarding = boarding + timedelta(minutes=(ride if isinstance(ride, (int, float)) else 0.0) + transfer_wait_minutes)
    return True


def _rows(cache, service: str, stop: str, direction: int | None) -> list[dict]:
    index = getattr(cache, _INDEX_ATTRIBUTE, None)
    if index is None:
        index = {}
        for route in getattr(cache, "routes", None) or []:
            key = (str(route.get("ServiceNo", "")).strip(), str(route.get("BusStopCode", "")).strip())
            index.setdefault(key, []).append(route)
        try:
            setattr(cache, _INDEX_ATTRIBUTE, index)
        except AttributeError:
            pass
    rows = index.get((service, stop), [])
    if direction is None:
        return rows
    return [row for row in rows if row.get("Direction") == direction]


def _row_verdict(row: dict, moment: datetime) -> bool | None:
    """True or False when the row's hours say so; None when it has no usable hours for the days involved."""
    answers = []
    for offset in (0, -1):  # a window that began today, and one that began yesterday and crosses midnight
        day = moment.date() + timedelta(days=offset)
        window = _window(row, day)
        if window is False:  # "-": no service that day type
            answers.append(False)
            continue
        if window is None:
            continue
        start, end = window
        if start <= moment <= end + timedelta(minutes=LAST_BUS_GRACE_MINUTES):
            return True
        answers.append(False)
    if not answers:
        return None
    return False


def _window(row: dict, day: date):
    """(start, end) datetimes of the window that begins on `day`; False for "-"; None when unreadable or absent."""
    first_key, last_key = _FIELDS[day_type(day)]
    first = row.get(first_key)
    last = row.get(last_key)
    if first is None and last is None:
        return None
    if str(first).strip() == "-" and str(last).strip() == "-":
        # All three day types "-" is no data at all, not "never runs".
        if all(str(row.get(field, "-")).strip() == "-" for pair in _FIELDS.values() for field in pair):
            return None
        return False
    start_minutes = _minutes(first)
    end_minutes = _minutes(last)
    if start_minutes is None or end_minutes is None:
        return None
    if end_minutes < start_minutes:
        end_minutes += 24 * 60
    midnight = datetime(day.year, day.month, day.day, tzinfo=SGT)
    return midnight + timedelta(minutes=start_minutes), midnight + timedelta(minutes=end_minutes)


def _minutes(value) -> int | None:
    text = str(value).strip()
    if len(text) != 4 or not text.isdigit():
        return None
    hours, minutes = int(text[:2]), int(text[2:])
    if minutes > 59 or hours > 29:
        return None
    return hours * 60 + minutes


def _as_sgt(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=SGT)
    return value.astimezone(SGT)
