"""The sample world the demo is captured in: the app's own real static data (cache/bus_stops.json, cache/bus_routes.json,
cache/bus_services.json, cache/rail_timetable.json) and ONE sample trip, from a made-up phone position near Lakeside to a made-up
saved place "School" next to Jurong East. Stop names, stop codes, bus services, MRT line and station codes and every marker position
are the real ones. Only the phone's position, the two saved places (Home, School), the live bus arrivals and the train alert are
scripted. OneMap is scripted too (no network call); LTA is scripted.

It reuses the existing test harness (tests/page_runner.py, tests/onemap_stub.py) without editing it."""

import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import httpx  # noqa: E402
import onemap_stub as stub  # noqa: E402
import page_runner  # noqa: E402
from lta_static import load_cache  # noqa: E402

SGT = timezone(timedelta(hours=8))
CACHE = load_cache()
STOPS = {s["BusStopCode"]: s for s in CACHE.stops}
RAIL = json.loads((ROOT / "cache" / "rail_timetable.json").read_text(encoding="utf-8"))
ROUTES: dict[tuple[str, int], list[str]] = {}
for _row in sorted(CACHE.routes, key=lambda r: (r["ServiceNo"], r["Direction"], r["StopSequence"])):
    ROUTES.setdefault((_row["ServiceNo"], _row["Direction"]), []).append(_row["BusStopCode"])

# ---- the sample trip (all real codes) -----------------------------------------------------------------------------------------------
BOARD = "28389"  # Opp Blk 515
BUS_SERVICE = "335"  # Opp Blk 515 -> ... -> Bef Jurong East Stn (9 stops) -> Jurong East Int
BUS_ALIGHT = "28211"  # Bef Jurong East Stn
FEEDER_SERVICE = "49"  # Opp Blk 515 -> Lakeside Stn (1 stop), for the bus-then-MRT itinerary
FEEDER_ALIGHT = "28091"  # Lakeside Stn (bus stop, 93 m from the station)
RAIL_FROM, RAIL_TO = "EW26", "EW24"  # Lakeside -> Chinese Garden (EW25) -> Jurong East (EW24, also NS1)

LAT, LON = STOPS[BOARD]["Latitude"], STOPS[BOARD]["Longitude"]  # the boarding stop: the scenes measure the phone from here
PHONE = (LAT + 230 / 111195, LON)  # the sample phone: 230 m north of the stop
SCHOOL = (1.33370, 103.74300)  # the sample saved place "School": 98 m from Jurong East MRT, 147 m from Opp Jem
PLACES = [
    {"id": "v1", "name": "Home", "address": "Jurong West St 51", "latitude": PHONE[0], "longitude": PHONE[1]},
    {"id": "v2", "name": "School", "address": "Jurong Gateway Rd", "latitude": SCHOOL[0], "longitude": SCHOOL[1]},
]


def hav(a, b, c, d) -> float:
    r = 6371000.0
    p1, p2 = math.radians(a), math.radians(c)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(d - b) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _point(code: str) -> tuple[float, float]:
    if code in RAIL["stations"]:
        s = RAIL["stations"][code]
        return s["latitude"], s["longitude"]
    s = STOPS[code]
    return s["Latitude"], s["Longitude"]


# ---- OneMap, scripted from the real data --------------------------------------------------------------------------------------------

def _bus_stop(code):
    return stub.stop(STOPS[code]["Description"].upper(), code, _point(code))


def _station(code):
    return stub.stop(RAIL["stations"][code]["name"].upper() + " MRT STATION", code, _point(code))


def _walk(t0, a, b):
    """A walk leg from a to b ({"name","lat","lon"} dicts); returns (leg, minutes)."""
    metres = max(5.0, hav(a["lat"], a["lon"], b["lat"], b["lon"]))
    minutes = max(1.0, metres / 78.0)
    return stub.walk(t0, t0 + minutes, metres, origin=a, target=b), minutes


def _bus_ride(t0, service, direction, from_code, to_code):
    seq = ROUTES[(service, direction)]
    codes = seq[seq.index(from_code):seq.index(to_code) + 1]
    minutes = 2.0 + 1.4 * (len(codes) - 1)
    a, b = _bus_stop(from_code), _bus_stop(to_code)
    leg = stub.ride("BUS", service, f"SBST BUS {service}", t0, t0 + minutes, a, b, between=0)
    inner = [_bus_stop(c) for c in codes[1:-1]]
    leg["intermediateStops"] = inner
    leg["legGeometry"] = stub._geometry([(s["lat"], s["lon"]) for s in [a] + inner + [b]])
    return leg, minutes


def _train_ride(t0, line, from_code, to_code):
    pattern = RAIL["patterns"][line]["Pasir Ris"]
    i, j = pattern.index(from_code), pattern.index(to_code)
    codes = pattern[i:j + 1] if i <= j else pattern[j:i + 1][::-1]
    minutes = 2.0 + 2.2 * (len(codes) - 1)
    a, b = _station(from_code), _station(to_code)
    leg = stub.ride("SUBWAY", line, RAIL["lines"][line]["name"].upper().replace("-", " "), t0, t0 + minutes, a, b, between=0)
    inner = [_station(c) for c in codes[1:-1]]
    leg["intermediateStops"] = inner
    leg["legGeometry"] = stub._geometry([(s["lat"], s["lon"]) for s in [a] + inner + [b]])
    return leg, minutes


def _here(point, name):
    return {"name": name, "lat": point[0], "lon": point[1]}


def _chain(start, steps):
    """Legs one after the other from the phone. A step is ("walk", target) | ("wait", minutes) | ("bus", service, dir, from, to) |
    ("rail", line, from, to)."""
    legs, t, at = [], 0.0, _here(start, "Origin")
    for step in steps:
        if step[0] == "wait":
            t += step[1]
            continue
        if step[0] == "walk":
            leg, minutes = _walk(t, at, step[1])
            at = step[1]
        elif step[0] == "bus":
            leg, minutes = _bus_ride(t, step[1], step[2], step[3], step[4])
            at = _bus_stop(step[4])
        else:
            leg, minutes = _train_ride(t, step[1], step[2], step[3])
            at = _station(step[3])
        legs.append(leg)
        t += minutes
    return stub.itinerary(*legs)


def _answer(start, end, *itineraries):
    """An OneMap answer that echoes both points it routed between (the app drops an answer that was snapped far from the request)."""
    body = stub._answer_to(end, *itineraries)
    body["plan"]["from"] = {"name": "Origin", "lat": start[0], "lon": start[1]}
    return body


def journeys(mode, params):
    start = tuple(float(v) for v in str(params["start"]).split(","))
    end = stub._end_point(params)
    place = {"name": "Destination", "lat": end[0], "lon": end[1]}
    o_stop, lakeside_stn = _bus_stop(BOARD), _station(RAIL_FROM)
    route = ROUTES[(BUS_SERVICE, 1)]
    on_route = route[route.index(BOARD) + 1:]

    # asked to end AT a real stop or station: ride to it, nothing after
    for code in on_route:
        if hav(end[0], end[1], *_point(code)) <= 40:
            body = _chain(start, [("walk", o_stop), ("wait", 6), ("bus", BUS_SERVICE, 1, BOARD, code)])
            return _answer(start, end, body) if mode in ("TRANSIT", "BUS") else None
    if hav(end[0], end[1], *_point(RAIL_TO)) <= 40:
        body = _chain(start, [("walk", lakeside_stn), ("wait", 4), ("rail", "EW", RAIL_FROM, RAIL_TO)])
        return _answer(start, end, body) if mode in ("TRANSIT", "RAIL") else None

    # the place itself: the bus, the bus-then-MRT trip and the MRT trip, each ending with the walk to the place
    bus = _chain(start, [("walk", o_stop), ("wait", 6), ("bus", BUS_SERVICE, 1, BOARD, BUS_ALIGHT), ("walk", place)])
    mixed = _chain(start, [("walk", o_stop), ("wait", 6), ("bus", FEEDER_SERVICE, 1, BOARD, FEEDER_ALIGHT), ("walk", lakeside_stn), ("wait", 2),
                           ("rail", "EW", RAIL_FROM, RAIL_TO), ("walk", place)])
    train = _chain(start, [("walk", lakeside_stn), ("wait", 4), ("rail", "EW", RAIL_FROM, RAIL_TO), ("walk", place)])
    pool = {"TRANSIT": [bus, mixed], "BUS": [bus], "RAIL": [train]}.get(mode)
    return _answer(start, end, *pool) if pool else None


def onemap(mode, params):
    return journeys(mode, params)


def walk_only(mode, params):
    start = tuple(float(v) for v in str(params["start"]).split(","))
    end = stub._end_point(params)
    return _answer(start, end, _chain(start, [("walk", _here(end, "Destination"))]))


# ---- LTA arrivals, scripted ---------------------------------------------------------------------------------------------------------

def freeze_clock(patches, hour=21, minute=0, second=0):
    """Freeze the app's server clock at today HH:MM:SS (Singapore time): every app module that reads datetime.now() sees that instant,
    and the OneMap stub's leg times start from it. Returns the instant. The page's own clock is frozen to the same instant by the scene
    (driver: h.freezeClock())."""
    import datetime as dt
    real = dt.datetime
    today = real.now(SGT).date()
    frozen = real(today.year, today.month, today.day, hour, minute, second, tzinfo=SGT)

    class Meta(type):
        def __instancecheck__(cls, obj):
            return isinstance(obj, real)

    class Frozen(real, metaclass=Meta):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz) if tz is not None else frozen.replace(tzinfo=None)

    for module in list(sys.modules.values()):
        path = str(getattr(module, "__file__", "") or "")
        if path and Path(path).resolve().is_relative_to(ROOT) and ".venv" not in path and "video" not in path.split(str(ROOT))[-1]:
            if getattr(module, "datetime", None) is real:
                patches.setattr(module, "datetime", Frozen)
    patches.setattr(stub, "_ms", lambda minutes: int((frozen.timestamp() + minutes * 60) * 1000))
    return frozen


def arrivals_patch(minutes: dict, loads: dict | None = None, fallback: float = 12.0):
    """Replacement for the harness's BusArrival answer: real service numbers, scripted minutes (and optional LTA Load codes)."""
    loads = loads or {}
    now_of = [None]

    def shaped(number, values):
        item = {"ServiceNo": number}
        for index, (name, mins) in enumerate(zip(("NextBus", "NextBus2", "NextBus3"), values)):
            base = now_of[0]() if now_of[0] else datetime.now(SGT)
            eta = (base + timedelta(minutes=mins)).replace(microsecond=0).isoformat()
            item[name] = {"EstimatedArrival": eta, "Monitored": 1, "Latitude": "", "Longitude": "", "OriginCode": "", "DestinationCode": ""}
            if number in loads and index < len(loads[number]):
                item[name]["Load"] = loads[number][index]
        return item

    def build(params):
        wanted = str((params or {}).get("ServiceNo") or "")
        numbers = [wanted] if wanted else sorted(minutes)
        return {"Services": [shaped(n, minutes.get(n, [fallback, fallback + 7, fallback + 15])) for n in numbers]}

    def install(patches, clock=None):
        prior = httpx.Client.get
        now_of[0] = clock

        def get(self, url, *args, **kwargs):
            if "/v3/BusArrival" in str(url):
                return httpx.Response(200, json=build(kwargs.get("params")))
            return prior(self, url, *args, **kwargs)

        patches.setattr(httpx.Client, "get", get)

    return install


def patch_runner() -> None:
    """The harness builds its own two-stop cache; hand it the real one (a module attribute it looks up when the app starts)."""
    page_runner.make_cache = lambda alt_stop=False: CACHE


def names() -> list[tuple[str, str]]:
    """Every real name and code the trip uses, for the report."""
    out = [(code, STOPS[code]["Description"]) for code in sorted({BOARD, BUS_ALIGHT, FEEDER_ALIGHT, "28009", "28199", "28061"})]
    out += [(code, RAIL["stations"][code]["name"]) for code in (RAIL_FROM, "EW25", RAIL_TO, "NS1")]
    return out
