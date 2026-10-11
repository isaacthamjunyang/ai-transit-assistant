"""OneMap public transport routing: client, parser and call budget.

The browser never calls OneMap. The token stays in memory (the OneMapSession of onemap.py) and is never
logged or returned. A request carries only public coordinates: the nearest stop or station to the user, and the
chosen place. The user's own position is used here only to pick that stop and is never sent.

OneMap routing is depart-at only (arriveBy is ignored) and has no live data, so every leg is a schedule.
"""

import copy
import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx

import onemap
from nearby import haversine_m
from onemap import DestinationUnavailable, OneMapSession, _AuthRejected, format_place_name
from service_hours import CIRCLE_WORDS, rail_circle_direction, rail_direction, rail_platform

ROUTE_URL = "https://www.onemap.gov.sg/api/public/routingsvc/route"
ROUTE_TIMEOUT_SECONDS = 10
SGT = timezone(timedelta(hours=8))

MODE_TRANSIT = "TRANSIT"
MODE_BUS = "BUS"
MODE_RAIL = "RAIL"
MODES = (MODE_TRANSIT, MODE_BUS, MODE_RAIL)

PLAN_CALL_LIMIT = 1
EXTENDED_CALL_LIMIT = 3  # arrive-by search or a priority that needs a second mode
CACHE_TTL_SECONDS = 300
CACHE_MAX_ENTRIES = 64
CACHE_BUCKET_SECONDS = 300
MIN_BUS_RIDE_SECONDS = 60
SNAP_TOLERANCE_M = 300  # OneMap moves a point that is off its network; a bigger move is not our trip
ARRIVE_BY_START_MARGIN_MINUTES = 10
ARRIVE_BY_RETRY_MARGIN_MINUTES = 5

STATUS_OK = "ok"
STATUS_NO_ROUTE = "no_route"
STATUS_NO_TRANSIT = "no_transit"  # OneMap found only a walk: nothing is running, or it is too short

KIND_WALK = "walk"
KIND_BUS = "bus"
KIND_RAIL = "rail"
RAIL_MODES = frozenset({"SUBWAY", "TRAM", "RAIL", "FUNICULAR", "GONDOLA"})


class RouteUnavailable(Exception):
    """OneMap routing could not be used (network, 5xx, 429, or a token that stays rejected)."""

    def __init__(self, reason: str = "unavailable") -> None:
        super().__init__("Route service unavailable")
        self.status = "unavailable"
        self.reason = reason


class RouteRejected(Exception):
    """OneMap answered 400. The request was wrong, which is our bug, not a trip with no route."""

    def __init__(self, message: str = "") -> None:
        super().__init__(message or "Route request rejected")
        self.message = message


class BudgetExhausted(Exception):
    """The planning request has used all of its routing calls."""


@dataclass(frozen=True)
class Place:
    """A public point that may be sent to OneMap: a stop, a station or the chosen place."""

    kind: str  # "stop", "station" or "place"
    code: str
    name: str
    latitude: float
    longitude: float

    def param(self) -> str:
        return f"{self.latitude:.5f},{self.longitude:.5f}"


class CallBudget:
    """Routing calls one planning request may make. A cache hit is free. A 401 retry is free (once)."""

    def __init__(self, limit: int = PLAN_CALL_LIMIT) -> None:
        self.limit = limit
        self.used = 0

    def spend(self) -> None:
        if self.used >= self.limit:
            raise BudgetExhausted
        self.used += 1

    @classmethod
    def single(cls) -> "CallBudget":
        return cls(PLAN_CALL_LIMIT)

    @classmethod
    def extended(cls) -> "CallBudget":
        return cls(EXTENDED_CALL_LIMIT)


def stop_place(cache, stop_code: str) -> Place | None:
    """A bus stop of the LTA cache as a Place, or None when the code or its coordinates are unknown."""
    stop = cache.stop_by_code(stop_code)
    if stop is None:
        return None
    lat, lon = stop.get("Latitude"), stop.get("Longitude")
    if not _finite(lat) or not _finite(lon):
        return None
    return Place("stop", stop["BusStopCode"], str(stop.get("Description", "")), float(lat), float(lon))


def destination_place(name: str, latitude: float, longitude: float) -> Place:
    """The chosen destination (public: it is a search result, not the user's position)."""
    return Place("place", "", name, float(latitude), float(longitude))


def nearest_origin_place(
    cache, user_lat: float, user_lon: float, stations: list[dict] | None = None, max_m: float = 1000.0
) -> Place | None:
    """The nearest stop or station to the user. The user's coordinates stay here: only the Place is sent.

    `stations` is a list of {code, name, latitude, longitude} (none until the rail table exists)."""
    best: tuple[float, Place] | None = None
    for stop in getattr(cache, "stops", []):
        lat, lon = stop.get("Latitude"), stop.get("Longitude")
        if not _finite(lat) or not _finite(lon):
            continue
        distance = haversine_m(user_lat, user_lon, float(lat), float(lon))
        if best is None or distance < best[0]:
            best = (distance, Place("stop", stop["BusStopCode"], str(stop.get("Description", "")),
                                    float(lat), float(lon)))
    for station in stations or []:
        lat, lon = station.get("latitude"), station.get("longitude")
        if not _finite(lat) or not _finite(lon):
            continue
        distance = haversine_m(user_lat, user_lon, float(lat), float(lon))
        if best is None or distance < best[0]:
            best = (distance, Place("station", str(station.get("code", "")), str(station.get("name", "")),
                                    float(lat), float(lon)))
    if best is None or best[0] > max_m:
        return None
    return best[1]


class PtRouter:
    """The routing client. One instance per process holds the 5 minute cache."""

    def __init__(self) -> None:
        self._cache: dict[tuple, tuple[float, dict]] = {}

    def clear_cache(self) -> None:
        self._cache.clear()

    def route(
        self,
        origin: Place,
        destination: Place,
        depart: datetime,
        mode: str = MODE_TRANSIT,
        *,
        session: OneMapSession,
        client: httpx.Client,
        budget: CallBudget,
        lta_cache=None,
        rail_table: dict | None = None,
        token: str = "",
        email: str = "",
        password: str = "",
        now: float | None = None,
    ) -> dict:
        """One depart-at search. Returns the normalised result (see parse_response)."""
        if mode not in MODES:
            raise ValueError("mode must be TRANSIT, BUS or RAIL")
        moment = time.time() if now is None else now
        depart_sgt = _as_sgt(depart)
        key = (origin.param(), destination.param(), mode, int(depart_sgt.timestamp() // CACHE_BUCKET_SECONDS))
        cached = self._cache.get(key)
        if cached is not None and moment - cached[0] < CACHE_TTL_SECONDS:
            return {**copy.deepcopy(cached[1]), "from_cache": True}
        budget.spend()
        params = {
            "start": origin.param(),
            "end": destination.param(),
            "routeType": "pt",
            "date": depart_sgt.strftime("%m-%d-%Y"),
            "time": depart_sgt.strftime("%H:%M:%S"),
            "mode": mode,
            "numItineraries": 3,
        }
        status, payload = _request(session, client, params, token, email, password, moment)
        result = parse_response(status, payload, origin, destination, lta_cache, rail_table)
        result["mode"] = mode
        result["from_cache"] = False
        self._store(key, moment, copy.deepcopy(result))
        return result

    def _store(self, key: tuple, moment: float, result: dict) -> None:
        if len(self._cache) >= CACHE_MAX_ENTRIES:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            del self._cache[oldest]
        self._cache[key] = (moment, result)


def search_arrive_by(
    router: PtRouter,
    origin: Place,
    destination: Place,
    target: datetime,
    *,
    estimate_minutes: float,
    earliest: datetime,
    mode: str = MODE_TRANSIT,
    budget: CallBudget | None = None,
    **client_args,
) -> dict:
    """Depart-at calls until an itinerary ends at or before `target` (at most the budget, 3 by default).

    OneMap has no arrive-by. Step 1 asks for a departure of target - estimate - 10 minutes. If every itinerary
    ends late, the next call moves earlier by the overshoot plus 5 minutes. Stops when a try is clamped at
    `earliest` (no earlier departure exists) or when OneMap has no route."""
    spend = budget if budget is not None else CallBudget.extended()
    target_sgt = _as_sgt(target)
    floor = _as_sgt(earliest)
    depart = max(floor, target_sgt - timedelta(minutes=estimate_minutes + ARRIVE_BY_START_MARGIN_MINUTES))
    last: dict | None = None
    calls = 0
    while True:
        try:
            result = router.route(origin, destination, depart, mode, budget=spend, **client_args)
        except BudgetExhausted:
            break
        calls += 1
        last = result
        if result["status"] != STATUS_OK:
            return {**result, "target_met": False, "calls": calls}
        in_time = [it for it in result["itineraries"] if _as_sgt(datetime.fromisoformat(it["arrive"])) <= target_sgt]
        if in_time:
            pick = max(in_time, key=lambda it: it["depart"])
            return {**result, "itineraries": [pick] + [it for it in in_time if it is not pick],
                    "target_met": True, "calls": calls}
        overshoot = min(_as_sgt(datetime.fromisoformat(it["arrive"])) for it in result["itineraries"]) - target_sgt
        next_depart = depart - overshoot - timedelta(minutes=ARRIVE_BY_RETRY_MARGIN_MINUTES)
        if depart <= floor:
            break  # already the earliest departure allowed
        depart = max(floor, next_depart)
    if last is None:
        raise BudgetExhausted
    return {**last, "target_met": False, "calls": calls}


# ---- HTTP -------------------------------------------------------------------------------------------------


def _request(session, client, params, manual, email, password, moment) -> tuple[int, dict]:
    manual = manual.strip()
    mail = email.strip()
    secret = password.strip()
    refreshed = False
    for _attempt in range(2):
        current = onemap._usable_token(session, manual, moment)
        if current is None:
            if not refreshed and (not mail or not secret):
                raise RouteUnavailable("no_credentials")
            if refreshed:
                raise RouteUnavailable("auth")
            _refresh(session, client, mail, secret)
            refreshed = True
            current = onemap._usable_token(session, manual, moment)
            if current is None:
                raise RouteUnavailable("auth")
        try:
            status, payload = _route_once(client, current, params)
        except _AuthRejected:
            onemap._invalidate(session)
            if refreshed or not mail or not secret:
                raise RouteUnavailable("auth")
            _refresh(session, client, mail, secret)
            refreshed = True
            continue
        if session.token != current:
            session.token = current
            session.expiry = None
        return status, payload
    raise RouteUnavailable("auth")


def _refresh(session, client, mail: str, secret: str) -> None:
    try:
        onemap._generate_token(session, client, mail, secret)
    except DestinationUnavailable as exc:
        cause = exc.__cause__
        if isinstance(cause, httpx.TimeoutException):
            raise RouteUnavailable("timeout") from exc
        if isinstance(cause, httpx.HTTPError):
            raise RouteUnavailable("network") from exc
        raise RouteUnavailable("auth") from exc


def _route_once(client: httpx.Client, token: str, params: dict) -> tuple[int, dict]:
    try:
        response = client.get(ROUTE_URL, params=params, headers={"Authorization": token},
                              timeout=ROUTE_TIMEOUT_SECONDS)
    except httpx.TimeoutException as exc:
        raise RouteUnavailable("timeout") from exc
    except httpx.HTTPError as exc:
        raise RouteUnavailable("network") from exc
    code = response.status_code
    if code == 401:
        raise _AuthRejected
    if code == 429:
        raise RouteUnavailable("rate_limited")
    body = _json_dict(response)
    if code == 400:
        raise RouteRejected(_error_text(body))
    if code == 404:
        return 404, body
    if code != 200:
        raise RouteUnavailable("http_error")
    if onemap._is_auth_message(_error_text(body)):
        raise _AuthRejected
    return 200, body


def _json_dict(response: httpx.Response) -> dict:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _error_text(body: dict) -> str:
    for key in ("error", "message"):
        value = body.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


# ---- Parser -----------------------------------------------------------------------------------------------


def parse_response(
    status: int, payload: dict, origin: Place, destination: Place, lta_cache=None, rail_table: dict | None = None
) -> dict:
    """Normalise one OneMap answer.

    {"status": "ok" | "no_route" | "no_transit", "reason": str, "itineraries": [...], "dropped": {...}}
    - 404 and an empty plan are "no_route".
    - Only walking itineraries are "no_transit" (nothing runs now, or the trip is too short to ride).
    - An origin or destination that OneMap moved more than SNAP_TOLERANCE_M is "no_route": the point was off its
      network and the route belongs to a different trip.
    - An itinerary with a bus leg under 60 seconds is dropped and counted in dropped["short_bus"].
    - With the rail table, a rail leg gets its headsign ("Marina South Pier") and direction id; without it, None."""
    dropped = {"short_bus": 0, "walk_only": 0, "malformed": 0}
    if status == 404:
        return _result(STATUS_NO_ROUTE, "not_found", [], dropped)
    plan = payload.get("plan") if isinstance(payload, dict) else None
    if not isinstance(plan, dict):
        if _error_text(payload):
            raise RouteUnavailable("bad_answer")
        return _result(STATUS_NO_ROUTE, "empty", [], dropped)
    shifts = [d for d in (_snap_distance(plan.get("from"), origin), _snap_distance(plan.get("to"), destination))
              if d is not None]
    moved = max(shifts) if shifts else None
    if moved is not None and moved > SNAP_TOLERANCE_M:
        return _result(STATUS_NO_ROUTE, "snapped", [], dropped, snapped_m=int(round(moved)))
    raw = plan.get("itineraries")
    if not isinstance(raw, list) or not raw:
        return _result(STATUS_NO_ROUTE, "empty", [], dropped)
    index = _bus_index(lta_cache) if lta_cache is not None else None
    itineraries = []
    for item in raw:
        parsed = _itinerary(item, lta_cache, index, rail_table)
        if parsed is None:
            dropped["malformed"] += 1
        elif not any(leg["kind"] != KIND_WALK for leg in parsed["legs"]):
            dropped["walk_only"] += 1
        elif any(leg["kind"] == KIND_BUS and leg["duration_s"] < MIN_BUS_RIDE_SECONDS for leg in parsed["legs"]):
            dropped["short_bus"] += 1
        else:
            itineraries.append(parsed)
    if itineraries:
        return _result(STATUS_OK, "", itineraries, dropped)
    if dropped["short_bus"]:
        return _result(STATUS_NO_ROUTE, "short_bus_only", [], dropped)
    if dropped["walk_only"]:
        return _result(STATUS_NO_TRANSIT, "walk_only", [], dropped)
    return _result(STATUS_NO_ROUTE, "empty", [], dropped)


def _result(status: str, reason: str, itineraries: list, dropped: dict, **extra) -> dict:
    return {"status": status, "reason": reason, "itineraries": itineraries, "dropped": dropped, **extra}


def _snap_distance(point: object, place: Place) -> float | None:
    if not isinstance(point, dict):
        return None
    lat, lon = point.get("lat"), point.get("lon")
    if not _finite(lat) or not _finite(lon):
        return None
    return haversine_m(place.latitude, place.longitude, float(lat), float(lon))


def _itinerary(item: object, lta_cache, index, rail_table=None) -> dict | None:
    if not isinstance(item, dict) or not isinstance(item.get("legs"), list) or not item["legs"]:
        return None
    legs = []
    for raw in item["legs"]:
        leg = _leg(raw, lta_cache, index, rail_table)
        if leg is None:
            return None
        legs.append(leg)
    transit = [leg for leg in legs if leg["kind"] != KIND_WALK]
    start, end = _epoch(item.get("startTime")), _epoch(item.get("endTime"))
    if start is None or end is None:
        return None
    return {
        "depart": start.isoformat(),
        "arrive": end.isoformat(),
        "minutes": round((end - start).total_seconds() / 60, 1),
        "walk_m": _number(item.get("walkDistance")),
        "walk_s": _number(item.get("walkTime")),
        "wait_s": _number(item.get("waitingTime")),
        "transfers": max(len(transit) - 1, 0),
        "route_type": _route_type(transit),
        "first_transit_kind": transit[0]["kind"] if transit else None,
        "legs": legs,
    }


def _route_type(transit: list[dict]) -> str:
    if len(transit) == 1:
        return "direct"
    if len(transit) == 2 and all(leg["kind"] == KIND_BUS for leg in transit):
        return "one_transfer"
    return "multi_leg"


def _leg(raw: object, lta_cache, index, rail_table=None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    start, end = _epoch(raw.get("startTime")), _epoch(raw.get("endTime"))
    origin, target = raw.get("from"), raw.get("to")
    if start is None or end is None or not isinstance(origin, dict) or not isinstance(target, dict):
        return None
    mode = str(raw.get("mode", "")).upper()
    base = {
        "depart": start.isoformat(),
        "arrive": end.isoformat(),
        "duration_s": _number(raw.get("duration")),
        "distance_m": _number(raw.get("distance")),
        "path": decode_polyline((raw.get("legGeometry") or {}).get("points", "")),
    }
    if mode == "WALK" or not raw.get("transitLeg"):
        return {**base, "kind": KIND_WALK, "from_name": _name(origin), "to_name": _name(target)}
    stops = [origin, *(raw.get("intermediateStops") or []), target]
    ridden = max(len(stops) - 1, 1)
    minutes = base["duration_s"] / 60
    if mode == "BUS":
        return {**base, **_bus_fields(raw, origin, target, stops, ridden, minutes, lta_cache, index)}
    if mode in RAIL_MODES:
        line = str(raw.get("routeShortName") or raw.get("route") or "").strip()
        board, alight = str(origin.get("stopCode", "")), str(target.get("stopCode", ""))
        toward = rail_direction(rail_table, line, board, alight)
        headsign = toward[0] if toward else None
        loop = rail_circle_direction(rail_table, line, toward[1]) if toward else None
        return {
            **base,
            "kind": KIND_RAIL,
            "mode": mode,
            "line_code": line,
            "line_name": format_place_name(str(raw.get("routeLongName") or "")),
            "headsign": headsign,
            "direction": toward[1] if toward else None,
            "circle_direction": loop,  # "clockwise" or "anticlockwise" on a loop line, else None
            "terminus": None if headsign is None or headsign.casefold() in CIRCLE_WORDS else headsign,
            "platform": rail_platform(rail_table, board, headsign),
            "boarding_stop_code": board,
            "boarding_stop_name": format_place_name(str(origin.get("name", ""))),
            "alighting_stop_code": alight,
            "alighting_stop_name": format_place_name(str(target.get("name", ""))),
            "stop_count": ridden,
            "ride_minutes": round(minutes, 2),
            "stops": [_stop_row(s, None) for s in stops],
        }
    return None


def _bus_fields(raw, origin, target, stops, ridden, minutes, lta_cache, index) -> dict:
    service = str(raw.get("routeShortName") or raw.get("route") or "").strip()
    from_code, to_code = str(origin.get("stopCode", "")), str(target.get("stopCode", ""))
    codes = [str(s.get("stopCode", "")) for s in stops]
    known = lta_cache is not None and all(lta_cache.stop_by_code(code) is not None for code in codes)
    direction, matched = _match_direction(index, service, from_code, to_code) if index is not None else (None, False)
    return {
        "kind": KIND_BUS,
        "service_no": service,
        "direction": direction,
        "direction_matched": matched,
        "stop_codes_known": known,
        "operator": str(raw.get("agencyName") or ""),
        "boarding_stop_code": from_code,
        "boarding_stop_name": _bus_stop_name(lta_cache, origin),
        "alighting_stop_code": to_code,
        "alighting_stop_name": _bus_stop_name(lta_cache, target),
        "stop_count": ridden,
        "ride_minutes": round(minutes, 2),
        "stops": [_stop_row(s, lta_cache) for s in stops],
    }


def _bus_stop_name(lta_cache, stop: dict) -> str:
    known = lta_cache.stop_by_code(str(stop.get("stopCode", ""))) if lta_cache is not None else None
    if known is not None and known.get("Description"):
        return str(known["Description"])
    return format_place_name(str(stop.get("name", "")))


def _stop_row(stop: dict, lta_cache) -> dict:
    code = str(stop.get("stopCode", ""))
    name = _bus_stop_name(lta_cache, stop) if lta_cache is not None else format_place_name(str(stop.get("name", "")))
    return {"stop_code": code, "description": name, "latitude": stop.get("lat"), "longitude": stop.get("lon")}


def _name(point: dict) -> str:
    name = str(point.get("name", ""))
    return "" if name in ("Origin", "Destination") else format_place_name(name)


# ---- Bus stop code and direction match against the LTA cache ----------------------------------------------


def _bus_index(lta_cache) -> dict:
    """service -> direction -> stop code -> [stop sequence, ...]. Built once per cache object."""
    cached = getattr(lta_cache, "_pt_bus_index", None)
    if cached is not None:
        return cached
    index: dict = {}
    for row in lta_cache.routes:
        try:
            sequence = int(row["StopSequence"])
            direction = int(row["Direction"])
        except (KeyError, TypeError, ValueError):
            continue
        index.setdefault(str(row["ServiceNo"]), {}).setdefault(direction, {}).setdefault(
            str(row["BusStopCode"]), []
        ).append(sequence)
    lta_cache._pt_bus_index = index
    return index


def _match_direction(index: dict, service: str, from_code: str, to_code: str) -> tuple[int | None, bool]:
    """(direction, matched). matched is True when the service passes both stops in order in some direction.
    The direction is None when no direction fits or when two directions fit (a loop)."""
    fits = []
    for direction, stops in index.get(service, {}).items():
        before, after = stops.get(from_code), stops.get(to_code)
        if before and after and min(before) < max(after):
            fits.append(direction)
    if len(fits) == 1:
        return fits[0], True
    return None, bool(fits)


# ---- Polyline ---------------------------------------------------------------------------------------------


def decode_polyline(encoded: str, precision: int = 5) -> list[list[float]]:
    """Google encoded polyline (OneMap uses precision 5) to [[lat, lon], ...]."""
    if not isinstance(encoded, str) or not encoded:
        return []
    factor = 10 ** precision
    points: list[list[float]] = []
    lat = lon = index = 0
    try:
        while index < len(encoded):
            for axis in (0, 1):
                shift = result = 0
                while True:
                    chunk = ord(encoded[index]) - 63
                    index += 1
                    result |= (chunk & 0x1F) << shift
                    shift += 5
                    if chunk < 0x20:
                        break
                delta = ~(result >> 1) if result & 1 else result >> 1
                if axis == 0:
                    lat += delta
                else:
                    lon += delta
            points.append([round(lat / factor, precision), round(lon / factor, precision)])
    except IndexError:
        return []
    return points


# ---- Small helpers ----------------------------------------------------------------------------------------


def _epoch(value: object) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return datetime.fromtimestamp(value / 1000, SGT)


def _number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.0
    return float(value)


def _finite(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _as_sgt(value: datetime) -> datetime:
    return value.replace(tzinfo=SGT) if value.tzinfo is None else value.astimezone(SGT)
