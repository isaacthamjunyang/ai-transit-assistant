"""Synthetic OneMap routing answers for the browser tests, laid out around the test app's own stops.

The test app (page_runner.running_app) has one origin stop at (1.3, 103.8) and a destination stop 2 km north. The times
are relative to the moment the stub is asked, so the planner sees trains and buses a few minutes ahead of "now".
Nothing here is real OneMap data and nothing here calls OneMap."""

import time

from page_runner import DEST, LAT, LON, ORIGIN, north

FAR = north(2000)


def encode_polyline(points, precision=5):
    """Google's encoded polyline (what OneMap sends in legGeometry.points)."""
    factor = 10 ** precision
    out, last_lat, last_lon = [], 0, 0
    for lat, lon in points:
        values = (round(lat * factor) - last_lat, round(lon * factor) - last_lon)
        last_lat, last_lon = round(lat * factor), round(lon * factor)
        for value in values:
            value = ~(value << 1) if value < 0 else value << 1
            while value >= 0x20:
                out.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            out.append(chr(value + 63))
    return "".join(out)


def _geometry(points):
    return {"points": encode_polyline(points), "length": len(points)}


def _ms(minutes: float) -> int:
    return int((time.time() + minutes * 60) * 1000)


def stop(name: str, code: str, point: tuple[float, float]) -> dict:
    return {"name": name, "stopCode": code, "stopId": f"FERRY:{code}", "lat": point[0], "lon": point[1]}


def walk(start: float, end: float, metres: float, origin: dict | None = None, target: dict | None = None) -> dict:
    origin_point = origin or {"lat": LAT, "lon": LON}
    target_point = target or {"lat": FAR[0], "lon": FAR[1]}
    return {
        "mode": "WALK", "transitLeg": False, "route": "", "startTime": _ms(start), "endTime": _ms(end),
        "duration": int((end - start) * 60), "distance": metres, "realTime": False,
        "from": origin or {"name": "Origin", "lat": LAT, "lon": LON},
        "to": target or {"name": "Destination", "lat": FAR[0], "lon": FAR[1]},
        "legGeometry": _geometry([(origin_point["lat"], origin_point["lon"]), (target_point["lat"], target_point["lon"])]),
    }


def ride(mode: str, route: str, long_name: str, start: float, end: float, origin: dict, target: dict,
         between: int = 3) -> dict:
    steps = []
    for index in range(between):
        fraction = (index + 1) / (between + 1)
        steps.append(stop(f"STOP {index + 1}", f"{route}{index + 1:02d}",
                          (origin["lat"] + (target["lat"] - origin["lat"]) * fraction,
                           origin["lon"] + (target["lon"] - origin["lon"]) * fraction)))
    return {
        "mode": mode, "transitLeg": True, "route": route, "routeShortName": route, "routeLongName": long_name,
        "startTime": _ms(start), "endTime": _ms(end), "duration": int((end - start) * 60),
        "distance": 5000.0, "realTime": False, "from": origin, "to": target, "intermediateStops": steps,
        "legGeometry": _geometry([(origin["lat"], origin["lon"])] + [(s["lat"], s["lon"]) for s in steps]
                                 + [(target["lat"], target["lon"])]),
    }


def itinerary(*legs: dict) -> dict:
    return {
        "startTime": legs[0]["startTime"], "endTime": legs[-1]["endTime"],
        "duration": int((legs[-1]["endTime"] - legs[0]["startTime"]) / 1000),
        "walkDistance": sum(leg["distance"] for leg in legs if leg["mode"] == "WALK"),
        "walkTime": 0, "waitingTime": 0, "transfers": 0, "legs": list(legs),
    }


def answer(*itineraries: dict) -> dict:
    return {"plan": {"from": {"name": "Origin", "lat": LAT, "lon": LON},
                     "to": {"name": "Destination", "lat": FAR[0], "lon": FAR[1]}, "itineraries": list(itineraries)}}


ORIGIN_STOP = stop("ORIGIN", ORIGIN, (LAT, LON))
DEST_STOP = stop("DESTINATION", DEST, FAR)


def bus_only() -> dict:
    """One direct bus 18 from the origin stop to the destination stop."""
    return answer(itinerary(
        walk(0, 1, 40, target=ORIGIN_STOP),
        ride("BUS", "18", "SBST BUS 18", 8, 28, ORIGIN_STOP, DEST_STOP),
        walk(28, 31, 220, origin=DEST_STOP)))


def train_first() -> dict:
    """A train first (NS17 to NS22), and a direct bus as the second choice."""
    station = stop("BISHAN MRT STATION", "NS17", north(80))
    far = stop("ORCHARD MRT STATION", "NS22", north(1900))
    train = itinerary(
        walk(0, 3, 200, target=station),
        ride("SUBWAY", "NS", "NORTH SOUTH LINE", 8, 22, station, far, between=4),
        walk(22, 24, 90, origin=far))
    return answer(train, bus_only()["plan"]["itineraries"][0])


def mixed() -> dict:
    """Bus 18, then NS, a change of code at Raffles Place, EW, a walk to the Bukit Panjang LRT, and the LRT."""
    transfer = stop("BEF TOH GUAN RD", "28059", north(700))
    ns_board = stop("BISHAN MRT STATION", "NS17", north(760))
    ns_alight = stop("RAFFLES PLACE MRT STATION", "NS26", north(1200))
    ew_board = stop("RAFFLES PLACE MRT STATION", "EW14", north(1210))
    ew_alight = stop("JURONG EAST MRT STATION", "EW24", north(1500))
    lrt_board = stop("BUKIT PANJANG LRT STATION", "BP6", north(1560))
    lrt_alight = stop("SEGAR LRT STATION", "BP11", north(1900))
    return answer(itinerary(
        walk(0, 1, 40, target=ORIGIN_STOP),
        ride("BUS", "18", "SBST BUS 18", 6, 14, ORIGIN_STOP, transfer),
        walk(14, 16, 130, origin=transfer, target=ns_board),
        ride("SUBWAY", "NS", "NORTH SOUTH LINE", 18, 30, ns_board, ns_alight, between=5),
        ride("SUBWAY", "EW", "EAST WEST LINE", 33, 48, ew_board, ew_alight, between=6),
        walk(48, 51, 261, origin=ew_alight, target=lrt_board),
        ride("TRAM", "BP", "BUKIT PANJANG LRT SYSTEM", 54, 60, lrt_board, lrt_alight, between=2),
        walk(60, 63, 150, origin=lrt_alight)))


def train_transfer() -> dict:
    """NS from the first station, a change to EW at Raffles Place, then a walk to the destination."""
    ns_board = stop("BISHAN MRT STATION", "NS17", north(80))
    ns_alight = stop("RAFFLES PLACE MRT STATION", "NS26", north(1200))
    ew_board = stop("RAFFLES PLACE MRT STATION", "EW14", north(1210))
    ew_alight = stop("TANJONG PAGAR MRT STATION", "EW15", north(1900))
    return answer(itinerary(
        walk(0, 3, 200, target=ns_board),
        ride("SUBWAY", "NS", "NORTH SOUTH LINE", 8, 20, ns_board, ns_alight, between=4),
        walk(20, 22, 90, origin=ns_alight, target=ew_board),
        ride("SUBWAY", "EW", "EAST WEST LINE", 26, 34, ew_board, ew_alight, between=3),
        walk(34, 36, 90, origin=ew_alight)))


def casings() -> dict:
    """Bus 18, then CC, NE, DT and TE: the lines that need a casing in one theme or the other."""
    cc_a, cc_b = stop("PROMENADE MRT STATION", "CC4", north(700)), stop("BISHAN MRT STATION", "CC15", north(900))
    ne_a, ne_b = stop("DHOBY GHAUT MRT STATION", "NE6", north(950)), stop("SERANGOON MRT STATION", "NE12", north(1200))
    dt_a, dt_b = stop("BUGIS MRT STATION", "DT14", north(1250)), stop("BAYFRONT MRT STATION", "DT16", north(1500))
    te_a, te_b = stop("CALDECOTT MRT STATION", "TE9", north(1550)), stop("ORCHARD MRT STATION", "TE14", north(1900))
    bus_end = stop("BEF TOH GUAN RD", "28059", north(650))
    return answer(itinerary(
        walk(0, 1, 40, target=ORIGIN_STOP),
        ride("BUS", "18", "SBST BUS 18", 6, 14, ORIGIN_STOP, bus_end),
        walk(14, 15, 60, origin=bus_end, target=cc_a),
        ride("SUBWAY", "CC", "CIRCLE LINE", 17, 24, cc_a, cc_b),
        ride("SUBWAY", "NE", "NORTH EAST LINE", 26, 33, ne_a, ne_b),
        ride("SUBWAY", "DT", "DOWNTOWN LINE", 35, 41, dt_a, dt_b),
        ride("SUBWAY", "TE", "THOMSON EAST COAST LINE", 43, 50, te_a, te_b),
        walk(50, 52, 100, origin=te_b)))


def by_mode(table: dict):
    """A stub for running_app(onemap=...): table maps TRANSIT / BUS / RAIL to a builder (or None for a 404)."""
    def stub(mode):
        builder = table.get(mode)
        return builder() if builder else None
    return stub
