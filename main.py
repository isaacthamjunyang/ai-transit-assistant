from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import math
import re

import httpx

import access_log_filter
from arrivals import ArrivalUnavailable, fetch_arrivals, fetch_stop_arrivals, peek_arrivals
import demo
from config import LEG2_REACH_RANGE_FRACTION, PAGE_CONSTANTS, TRANSFER_BUS_SPEED_MPS, WALK_SPEED_DEFAULT_MPS
from explain import (
    ai_explanation_enabled,
    build_poll_explanation,
    handle_explain_request,
    chosen_action,
    handle_option_explain_request,
    seconds_until_leave_by,
    _scored_journey_bus,
)
from catch_heuristic import normalize_location_timestamp
from destination_stops import list_destination_stops
from journey import build_journey, bus_arrival_window, miss_line, parse_journey_time, planning_warning
from journey_plan import plan_journey
from lta_static import load_static_data
from nearby import BOARDING_RADIUS_M, haversine_m, nearby_boarding_stops
from pace import is_near_stop
from reroute import (
    SGT,
    _reaching_services,
    apply_active_target,
    closest_alternate_stops,
    log_scored_poll,
    plan_options,
    plan_reroute,
    resolve_pinned_target,
)
from route_plan import (
    plan_route,
    projected_transfer_epoch,
    reroute_enabled,
    schedule_headway_minutes,
    suggest_alternate_boarding,
)
from onemap import (
    DestinationUnavailable,
    OneMapSession,
    ONEMAP_TIMEOUT_SECONDS,
    REVERSE_TIMEOUT_SECONDS,
    read_onemap_credentials,
    reverse_geocode,
    search_destinations,
)
from walk_speed import resolve_walk_speed, response_fields

access_log_filter.install()


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.onemap_session = OneMapSession()
    app.state.lta_static = load_static_data()
    yield


app = FastAPI(title="Bus Catch Assistant", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"


def _walk_speed(walk_speed, walk_speed_source) -> tuple[float, str]:
    """The speed used for this request. Demo Mode ignores the client value so its fixtures stay fixed."""
    return resolve_walk_speed(walk_speed, walk_speed_source, demo=demo.demo_enabled())


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """The usual 422 with each error's type, loc and msg, but without the offending value.

    FastAPI's default response also carries `input` (the value the client sent) and `ctx`. A bad latitude or
    longitude would be echoed back, so they are left out. No validator or validation rule changes.
    """
    errors = [
        {"type": error.get("type"), "loc": list(error.get("loc", ())), "msg": error.get("msg")}
        for error in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


@app.get("/")
def home() -> HTMLResponse:
    page = INDEX_PATH.read_text(encoding="utf-8")
    flag = "true" if ai_explanation_enabled() else "false"
    page = page.replace(
        "var AI_EXPLANATION_ENABLED = true;",
        "var AI_EXPLANATION_ENABLED = " + flag + ";",
        1,
    )
    for name, value in PAGE_CONSTANTS.items():
        page = re.sub(rf"var {name} = [0-9.]+;", f"var {name} = {value};", page, count=1)
    return HTMLResponse(page)


@app.get("/theme.css")
def theme_css() -> FileResponse:
    return FileResponse(STATIC_DIR / "theme.css", media_type="text/css")


@app.get("/components.css")
def components_css() -> FileResponse:
    return FileResponse(STATIC_DIR / "components.css", media_type="text/css")


@app.get("/theme-boot.js")
def theme_boot_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "theme-boot.js", media_type="text/javascript")


@app.get("/format-distance.js")
def format_distance_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "format-distance.js", media_type="text/javascript")


@app.get("/sw.js")
def service_worker_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", media_type="text/javascript")


@app.get("/walk-speed.js")
def walk_speed_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "walk-speed.js", media_type="text/javascript")


@app.get("/place-icons.js")
def place_icons_js() -> FileResponse:
    return FileResponse(STATIC_DIR / "place-icons.js", media_type="text/javascript")


@app.get("/api/demo", response_model=None)
def demo_status() -> dict:
    return demo.public_status()


@app.post("/api/demo/run", response_model=None)
def demo_run(body: Annotated[dict, Body()]) -> dict | JSONResponse:
    if not demo.demo_enabled():
        return JSONResponse(status_code=404, content={"detail": "Not found."})
    name = body.get("scenario") if isinstance(body, dict) else None
    if not isinstance(name, str) or not demo.run_scenario(name):
        return JSONResponse(status_code=422, content={"detail": "Unknown scenario."})
    return demo.public_status()


@app.post("/api/demo/reset", response_model=None)
def demo_reset() -> dict:
    demo.reset_to_live()
    return demo.public_status()


@app.get("/api/stops/nearby", response_model=None)
def nearby_stops(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    radius: Annotated[float | None, Query(ge=0, le=800)] = None,
) -> list[dict] | JSONResponse:
    cache = getattr(app.state, "lta_static", None)
    if cache is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "detail": "Static stop data is unavailable.",
            },
        )
    return nearby_boarding_stops(
        cache,
        lat,
        lon,
        BOARDING_RADIUS_M if radius is None else radius,
    )


@app.get("/api/arrivals", response_model=None)
def arrivals(
    stop_code: Annotated[str, Query(min_length=1)],
    service_no: Annotated[str, Query(min_length=1)],
    lat: Annotated[float | None, Query()] = None,
    lon: Annotated[float | None, Query()] = None,
    accuracy: Annotated[float | None, Query()] = None,
    location_timestamp: Annotated[float | None, Query()] = None,
    destination_stop_code: Annotated[str | None, Query()] = None,
    dest_lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
    dest_lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    arrive_by: Annotated[str | None, Query()] = None,
    last_reroute_at: Annotated[str | None, Query()] = None,
    pinned_eta: Annotated[float | None, Query()] = None,
    explanation_rendered: Annotated[int | None, Query()] = None,
    last_explained_range_low: Annotated[int | None, Query()] = None,
    last_explained_range_high: Annotated[int | None, Query()] = None,
    explained_action: Annotated[str | None, Query()] = None,
    explained_advice: Annotated[str | None, Query(max_length=200)] = None,
    explanation_in_flight: Annotated[int | None, Query()] = None,
    route_type: Annotated[str | None, Query()] = None,
    leg_index: Annotated[int | None, Query()] = None,
    leg2_service_no: Annotated[str | None, Query()] = None,
    leg2_direction: Annotated[int | None, Query()] = None,
    leg2_stop_code: Annotated[str | None, Query()] = None,
    leg1_ride_minutes: Annotated[float | None, Query()] = None,
    leg2_ride_minutes: Annotated[float | None, Query()] = None,
    leg1_direction: Annotated[int | None, Query()] = None,
    reroute: Annotated[int | None, Query()] = None,
    walk_speed: Annotated[str | None, Query()] = None,
    walk_speed_source: Annotated[str | None, Query()] = None,
) -> dict | JSONResponse:
    speed, speed_source = _walk_speed(walk_speed, walk_speed_source)
    stop_code = stop_code.strip()
    service_no = service_no.strip()
    if not stop_code or not service_no:
        return JSONResponse(
            status_code=422,
            content={"detail": "stop_code and service_no are required."},
        )
    if location_timestamp is not None:
        try:
            normalize_location_timestamp(location_timestamp)
        except ValueError:
            return JSONResponse(
                status_code=422,
                content={
                    "detail": "location_timestamp must be a finite non-negative number.",
                },
            )
    if pinned_eta is not None and not math.isfinite(pinned_eta):
        return JSONResponse(
            status_code=422,
            content={"detail": "pinned_eta must be a finite epoch timestamp."},
        )
    destination_code = None
    parsed_arrive_by = None
    parsed_reroute_at = None
    if destination_stop_code is not None:
        destination_code = destination_stop_code.strip()
        if not destination_code:
            return JSONResponse(
                status_code=422,
                content={"detail": "destination_stop_code must be a non-empty string."},
            )
        coordinates = (lat, lon, accuracy, dest_lat, dest_lon)
        if any(value is None or not math.isfinite(value) for value in coordinates):
            return JSONResponse(
                status_code=422,
                content={"detail": "A reroute check needs finite user and destination coordinates."},
            )
        if accuracy < 0:
            return JSONResponse(
                status_code=422,
                content={"detail": "accuracy must be a non-negative number."},
            )
        try:
            parsed_arrive_by = None if arrive_by is None else parse_journey_time(arrive_by)
            parsed_reroute_at = None if last_reroute_at is None else parse_journey_time(last_reroute_at)
        except ValueError:
            return JSONResponse(
                status_code=422,
                content={"detail": "arrive_by and last_reroute_at must be ISO timestamps."},
            )
    cache = getattr(app.state, "lta_static", None)
    moment = datetime.now(SGT)
    accuracy, location_timestamp = demo.scoring_location(accuracy, location_timestamp, moment)
    demo.begin_arrival_poll(stop_code, service_no)
    on_vehicle = route_type == "one_transfer" and leg_index == 2
    try:
        payload = fetch_arrivals(
            stop_code,
            service_no,
            user_lat=lat,
            user_lon=lon,
            accuracy=accuracy,
            location_timestamp=location_timestamp,
            cache=cache,
            reach_speed_m_s=TRANSFER_BUS_SPEED_MPS if on_vehicle else None,
            reach_range_fraction=LEG2_REACH_RANGE_FRACTION,
            walk_speed_m_s=speed,
        )
    except ArrivalUnavailable:
        content = {
            "status": "unavailable",
            "detail": "Live arrival data is unavailable.",
        }
        if demo.timeout_is_active():
            content["simulated"] = True
        return JSONResponse(status_code=503, content=content)
    payload.update(response_fields(speed, speed_source))
    payload["near_stop"] = False if on_vehicle else _near_stop(cache, stop_code, lat, lon)
    if on_vehicle:
        payload["reach_stop"] = _reach_window(cache, stop_code, lat, lon, moment)
    if demo.apply_stale(payload, moment):
        return payload
    if demo.arrival_is_simulated():
        payload["simulated"] = True
    target = None
    if pinned_eta is not None:
        target, updated_pin = resolve_pinned_target(payload.get("buses") or [], pinned_eta, moment)
        apply_active_target(
            payload,
            target,
            user_lat=lat,
            user_lon=lon,
            cache=cache,
            now=moment,
            walk_speed_m_s=speed,
        )
        payload["pinned_eta_timestamp"] = updated_pin
    fired = False
    reason = ""
    if (
        destination_code is not None
        and cache is not None
        and lat is not None
        and lon is not None
        and reroute_enabled(route_type, leg_index)
        and reroute != 0  # Page C is open: the page asks the server to skip this evaluation. Nothing else changes.
    ):
        load_alternate = _alternate_loader(cache, lat, lon, accuracy, location_timestamp, moment, destination_code, speed)

        evaluation = payload
        if target is not None:
            evaluation = dict(payload)
            evaluation["buses"] = [
                {**bus, "is_primary": bus is target} for bus in payload.get("buses") or []
            ]
        decision = plan_reroute(
            cache=cache,
            current=evaluation,
            user_lat=lat,
            user_lon=lon,
            accuracy_m=accuracy,
            location_timestamp=location_timestamp,
            destination_stop_code=destination_code,
            place_lat=dest_lat,
            place_lon=dest_lon,
            arrive_by=parsed_arrive_by,
            last_reroute_at=parsed_reroute_at,
            now=moment,
            loader=load_alternate,
            write_observation=False,
            walk_speed_m_s=speed,
        )
        payload["reroute"] = decision
        fired = bool(decision.get("switched"))
        reroute = decision.get("reroute") if fired else None
        if isinstance(reroute, dict):
            reason = reroute.get("reroute_reason") or ""
    payload["chosen_action"] = _poll_action(payload, moment, fired)
    log_scored_poll(
        cache=cache,
        current=payload,
        bus=target if target is not None else _scored_primary(payload.get("buses") or []),
        user_lat=lat,
        user_lon=lon,
        accuracy_m=accuracy,
        now=moment,
        reroute_fired=fired,
        reroute_reason=reason,
        destination_stop_code=destination_code,
    )
    if explanation_rendered is not None:
        pack = build_poll_explanation(
            payload,
            now=moment,
            cache=cache,
            user_lat=lat,
            user_lon=lon,
            stop_code=stop_code,
            explained_action=explained_action,
            explained_advice=explained_advice,
            in_flight=explanation_in_flight == 1,
            reroute_fired=fired,
            reach_distance_m=(payload.get("reach_stop") or {}).get("distance_m") if on_vehicle else None,
            walk_speed_m_s=speed,
        )
        if pack is not None:
            payload["explanation"] = pack
    _attach_leg2_schedule(
        payload,
        cache=cache,
        route_type=route_type,
        leg_index=leg_index,
        leg2_service_no=leg2_service_no,
        leg2_direction=leg2_direction,
        leg2_stop_code=leg2_stop_code,
        leg1_ride_minutes=leg1_ride_minutes,
    )
    _attach_arrival_estimate(
        payload,
        cache=cache,
        now=moment,
        user_lat=lat,
        user_lon=lon,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        destination_stop_code=destination_code,
        boarding_stop_code=stop_code,
        service_no=service_no,
        arrive_by=parsed_arrive_by,
        route_type=route_type,
        leg_index=leg_index,
        leg1_ride_minutes=leg1_ride_minutes,
        leg2_ride_minutes=leg2_ride_minutes,
        leg1_direction=leg1_direction,
        walk_speed_m_s=speed,
    )
    return payload


def _near_stop(cache, stop_code, lat, lon) -> bool:
    """True when the user is inside the 30 m rule that hides pace guidance (pace.is_near_stop)."""
    stop = cache.stop_by_code(stop_code) if cache is not None else None
    if not isinstance(stop, dict) or lat is None or lon is None:
        return False
    try:
        distance = haversine_m(lat, lon, float(stop["Latitude"]), float(stop["Longitude"]))
    except (KeyError, TypeError, ValueError):
        return False
    return is_near_stop(distance)


def _reach_window(cache, stop_code, lat, lon, now) -> dict | None:
    """Leg 2 display: now plus the time to reach the stop by vehicle, with its range."""
    stop = cache.stop_by_code(stop_code) if cache is not None else None
    if not isinstance(stop, dict) or lat is None or lon is None:
        return None
    try:
        distance = haversine_m(lat, lon, float(stop["Latitude"]), float(stop["Longitude"]))
    except (KeyError, TypeError, ValueError):
        return None
    seconds = distance / TRANSFER_BUS_SPEED_MPS

    def at(factor: float) -> str:
        return (now + timedelta(seconds=seconds * factor)).replace(microsecond=0).isoformat()

    return {
        "point": at(1),
        "low": at(1 - LEG2_REACH_RANGE_FRACTION),
        "high": at(1 + LEG2_REACH_RANGE_FRACTION),
        "distance_m": int(distance + 0.5),
    }


class _StopLoader:
    """BusArrival lookups for the reroute search, one call per stop for all its services.

    Calling the loader with (stop, service) returns that service scored and logged the same way
    as a poll. prefetch() fetches the listed stops once each, in parallel (one thread per stop,
    so the current stop and up to two alternate stops make three calls), and a later call for any
    of their services is served from that result. Without a prefetch a call falls back to the
    single-service lookup.
    """

    def __init__(
        self, cache, lat, lon, accuracy, location_timestamp, moment, destination_code,
        walk_speed_m_s=WALK_SPEED_DEFAULT_MPS,
    ):
        self.walk_speed_m_s = walk_speed_m_s
        self.cache = cache
        self.lat = lat
        self.lon = lon
        self.accuracy = accuracy
        self.location_timestamp = location_timestamp
        self.moment = moment
        self.destination_code = destination_code
        self.stops: dict[str, dict | ArrivalUnavailable] = {}
        self._logged: set[tuple[str, str]] = set()

    def _fetch_stop(self, code: str, services: list[str]):
        try:
            return fetch_stop_arrivals(
                code,
                services,
                now=self.moment,
                user_lat=self.lat,
                user_lon=self.lon,
                accuracy=self.accuracy,
                location_timestamp=self.location_timestamp,
                cache=self.cache,
                walk_speed_m_s=self.walk_speed_m_s,
            )
        except ArrivalUnavailable as exc:
            return exc

    def prefetch(self, plan) -> None:
        todo = {}
        for code, services in plan:
            if code not in self.stops:
                todo[code] = list(dict.fromkeys(services))
        if not todo:
            return
        if len(todo) == 1 or demo.lta_script_active():
            for code, services in todo.items():
                self.stops[code] = self._fetch_stop(code, services)
            return
        with ThreadPoolExecutor(max_workers=len(todo)) as pool:
            futures = {code: pool.submit(self._fetch_stop, code, services) for code, services in todo.items()}
            for code, future in futures.items():
                self.stops[code] = future.result()

    def get(self, code: str, service: str, *, log: bool = True) -> dict:
        entry = self.stops.get(code)
        if entry is None:
            alternate = fetch_arrivals(
                code,
                service,
                user_lat=self.lat,
                user_lon=self.lon,
                accuracy=self.accuracy,
                location_timestamp=self.location_timestamp,
                cache=self.cache,
                walk_speed_m_s=self.walk_speed_m_s,
            )
        elif isinstance(entry, ArrivalUnavailable):
            raise entry
        else:
            alternate = entry.get(service) or {
                "status": "ok",
                "stop_code": code,
                "service_no": service,
                "fetched_at": self.moment.replace(microsecond=0).isoformat(),
                "buses": [],
            }
        if log and (code, service) not in self._logged:
            self._logged.add((code, service))
            log_scored_poll(
                cache=self.cache,
                current=alternate,
                bus=_scored_primary(alternate.get("buses") or []),
                user_lat=self.lat,
                user_lon=self.lon,
                accuracy_m=self.accuracy,
                now=self.moment,
                reroute_fired=False,
                reroute_reason="",
                destination_stop_code=self.destination_code,
            )
        return alternate

    def __call__(self, code: str, service: str) -> dict:
        return self.get(code, service)


def _alternate_loader(
    cache, lat, lon, accuracy, location_timestamp, moment, destination_code, walk_speed_m_s=WALK_SPEED_DEFAULT_MPS
):
    """One BusArrival lookup per stop, scored and logged the same way as a poll."""
    return _StopLoader(
        cache, lat, lon, accuracy, location_timestamp, moment, destination_code, walk_speed_m_s
    )


@app.get("/api/reroute-options", response_model=None)
def reroute_options(
    stop_code: Annotated[str, Query(min_length=1)],
    service_no: Annotated[str, Query(min_length=1)],
    lat: Annotated[float, Query()],
    lon: Annotated[float, Query()],
    accuracy: Annotated[float, Query(ge=0)],
    destination_stop_code: Annotated[str, Query(min_length=1)],
    dest_lat: Annotated[float, Query(ge=-90, le=90)],
    dest_lon: Annotated[float, Query(ge=-180, le=180)],
    location_timestamp: Annotated[float | None, Query()] = None,
    arrive_by: Annotated[str | None, Query()] = None,
    missed_eta: Annotated[float | None, Query()] = None,
    entry: Annotated[str, Query()] = "recommended",
    walk_speed: Annotated[str | None, Query()] = None,
    walk_speed_source: Annotated[str | None, Query()] = None,
) -> dict | JSONResponse:
    """On-demand options (the missed entry and the unlikely entry). Same candidates and calls as the automatic search.

    entry is "recommended" (after "No, I missed it") or "better" (the unlikely entry). It only names the
    card's heading chip. Both choose from all eligible options and ignore the improvement rule."""
    if entry not in ("recommended", "better"):
        return JSONResponse(status_code=422, content={"detail": "entry must be recommended or better."})
    cache = getattr(app.state, "lta_static", None)
    if cache is None or not all(math.isfinite(value) for value in (lat, lon, accuracy, dest_lat, dest_lon)):
        return JSONResponse(status_code=422, content={"detail": "A reroute search needs the static cache and finite coordinates."})
    if missed_eta is not None and not math.isfinite(missed_eta):
        return JSONResponse(status_code=422, content={"detail": "missed_eta must be a finite epoch timestamp."})
    try:
        parsed_arrive_by = None if arrive_by is None else parse_journey_time(arrive_by)
    except ValueError:
        return JSONResponse(status_code=422, content={"detail": "arrive_by must be an ISO timestamp."})
    moment = datetime.now(SGT)
    speed, speed_source = _walk_speed(walk_speed, walk_speed_source)
    destination_code = destination_stop_code.strip()
    loader = _alternate_loader(cache, lat, lon, accuracy, location_timestamp, moment, destination_code, speed)
    current_stop = stop_code.strip()
    current_service = service_no.strip()
    # The current stop (every reaching service, one call) and the alternate stops are fetched together.
    here = [current_service] + [
        service for service in _reaching_services(cache, current_stop, destination_code) if service != current_service
    ]
    plan = [(current_stop, here)]
    for stop in closest_alternate_stops(cache, lat, lon, current_stop, destination_code):
        plan.append((stop["BusStopCode"], _reaching_services(cache, stop["BusStopCode"], destination_code)))
    loader.prefetch(plan)
    try:
        current = loader.get(current_stop, current_service, log=False)
    except ArrivalUnavailable:
        return JSONResponse(status_code=503, content={"status": "unavailable", "detail": "Live arrival data is unavailable."})
    options = plan_options(
        cache=cache,
        current=current,
        user_lat=lat,
        user_lon=lon,
        destination_stop_code=destination_code,
        place_lat=dest_lat,
        place_lon=dest_lon,
        arrive_by=parsed_arrive_by,
        now=moment,
        loader=loader,
        missed_eta_epoch=missed_eta,
        entry=entry,
        walk_speed_m_s=speed,
    )
    return {
        **response_fields(speed, speed_source),
        "status": "ok",
        "stop_code": current.get("stop_code"),
        "service_no": current.get("service_no"),
        "fetched_at": current.get("fetched_at"),
        "no_buses": not (current.get("buses") or []),
        "options": options,
    }


@app.post("/api/explain-option", response_model=None)
def explain_option(body: Annotated[dict, Body()]) -> dict | JSONResponse:
    """The Page C clause for the recommended option. The model sees the reason code and the action only."""
    status, payload = handle_option_explain_request(body)
    if status != 200:
        return JSONResponse(status_code=status, content=payload)
    return payload


@app.post("/api/explain", response_model=None)
def explain(body: Annotated[dict, Body()]) -> dict | JSONResponse:
    status, payload = handle_explain_request(body)
    if status != 200:
        return JSONResponse(status_code=status, content=payload)
    if demo.explanation_is_simulated():
        payload = dict(payload)
        payload["simulated"] = True
    return payload


def _poll_action(payload: dict, now: datetime, reroute_fired: bool) -> str | None:
    """The Python action for the tracked bus (the one behind the AI clause and the Leave by tile)."""
    bus = _scored_journey_bus(payload.get("buses") or [])
    chance = bus.get("probability") if isinstance(bus, dict) else None
    if not isinstance(chance, dict):
        return None
    quality = chance.get("data_quality")
    high = chance.get("range_high")
    if not isinstance(quality, str) or type(high) is not int:
        return None
    return chosen_action(
        reroute_fired_this_poll=reroute_fired,
        data_quality=quality,
        range_high=high,
        leave_by_seconds=seconds_until_leave_by(payload.get("leave_by"), now),
    )


def _live_eta(bus: dict | None, now: datetime) -> datetime | None:
    """The tracked bus's arrival time when it is a live (monitored) arrival, else None."""
    if not isinstance(bus, dict) or bus.get("monitored") is not True:
        return None
    arrival = bus.get("arrival_time")
    if not isinstance(arrival, str) or not arrival.strip():
        return None
    try:
        return parse_journey_time(arrival)
    except ValueError:
        return None


def _attach_arrival_estimate(
    payload: dict,
    *,
    cache,
    now: datetime,
    user_lat: float | None,
    user_lon: float | None,
    dest_lat: float | None,
    dest_lon: float | None,
    destination_stop_code: str | None,
    boarding_stop_code: str,
    service_no: str,
    arrive_by: datetime | None,
    route_type: str | None,
    leg_index: int | None,
    leg1_ride_minutes: float | None,
    leg2_ride_minutes: float | None,
    leg1_direction: int | None,
    walk_speed_m_s: float = WALK_SPEED_DEFAULT_MPS,
) -> None:
    """Step 9 window and the second-arrival line from data this poll already has."""
    if (
        cache is None
        or destination_stop_code is None
        or user_lat is None
        or user_lon is None
        or dest_lat is None
        or dest_lon is None
    ):
        return
    transfer = route_type == "one_transfer" and leg_index == 1
    built = build_journey(
        cache,
        dest_lat,
        dest_lon,
        user_lat,
        user_lon,
        destination_stop_code,
        boarding_stop_code=boarding_stop_code,
        service_no=service_no,
        arrive_by=arrive_by,
        now=now,
        transfer=transfer,
        leg1_ride_minutes=leg1_ride_minutes,
        leg2_ride_minutes=leg2_ride_minutes,
        leg1_service_no=service_no,
        leg1_direction=leg1_direction,
        walk_speed_m_s=walk_speed_m_s,
    )
    if built.get("arrival_point"):
        estimate = {
            "estimated_arrival": built["arrival_point"],
            "arrival_low": built["arrival_low"],
            "arrival_high": built["arrival_high"],
            "spare_minutes": built["spare_minutes"],
            "basis": built["arrival_basis"],
        }
        # The tracked bus's live arrival anchors the estimate; without one the planned basis stays.
        tracked = _scored_journey_bus(payload.get("buses") or [])
        eta = _live_eta(tracked, now)
        window = bus_arrival_window(
            now, built.get("arrival_terms"), eta, live=eta is not None, arrive_by=arrive_by,
            walk_speed_m_s=walk_speed_m_s,
        )
        if eta is not None and window is not None:
            estimate = {
                "estimated_arrival": window["estimated_arrival"].replace(microsecond=0).isoformat(),
                "arrival_low": window["arrival_low"].replace(microsecond=0).isoformat(),
                "arrival_high": window["arrival_high"].replace(microsecond=0).isoformat(),
                "spare_minutes": None if arrive_by is None else window["spare_minutes"],
                "basis": window["basis"],
            }
        payload["arrival_estimate"] = estimate
    else:
        payload["arrival_estimate"] = None
    payload["if_you_miss"] = miss_line(
        now,
        service_no,
        payload.get("buses") or [],
        built.get("arrival_terms"),
        arrive_by,
        tracked=_scored_journey_bus(payload.get("buses") or []),
        walk_speed_m_s=walk_speed_m_s,
    )


def _attach_leg2_schedule(
    payload: dict,
    *,
    cache,
    route_type: str | None,
    leg_index: int | None,
    leg2_service_no: str | None,
    leg2_direction: int | None,
    leg2_stop_code: str | None,
    leg1_ride_minutes: float | None,
) -> None:
    """Schedule-only headway for a future Leg 2. Does not fetch a second arrival."""
    if route_type != "one_transfer" or leg_index != 1 or cache is None:
        return
    if not leg2_service_no or leg2_direction is None or not leg2_stop_code:
        return
    if leg1_ride_minutes is None or not math.isfinite(leg1_ride_minutes):
        return
    primary = _scored_primary(payload.get("buses") or [])
    arrival = primary.get("arrival_time") if isinstance(primary, dict) else None
    if not isinstance(arrival, str) or not arrival.strip():
        return
    try:
        eta = parse_journey_time(arrival)
    except ValueError:
        return
    projected = projected_transfer_epoch(eta, leg1_ride_minutes)
    payload["leg2_projected_arrival"] = projected.replace(microsecond=0).isoformat()
    payload["leg2_schedule_headway_minutes"] = schedule_headway_minutes(
        cache,
        leg2_service_no.strip(),
        leg2_direction,
        leg2_stop_code.strip(),
        projected,
    )


def _scored_primary(buses: list[dict]) -> dict | None:
    for bus in buses:
        if bus.get("is_primary") and not bus.get("is_missed"):
            return bus
    return None


@app.post("/api/reverse-geocode", response_model=None)
def reverse_geocode_place(body: Annotated[dict | None, Body()] = None) -> dict:
    """Place name only. Coordinates are rounded and are not written or recorded."""
    empty = {"status": "ok", "name": "", "display_name": "", "full_name": ""}
    if not isinstance(body, dict):
        return empty
    raw_lat = body.get("lat")
    raw_lon = body.get("lon")
    if isinstance(raw_lat, bool) or isinstance(raw_lon, bool):
        return empty
    try:
        lat = float(raw_lat)
        lon = float(raw_lon)
    except (TypeError, ValueError):
        return empty
    if not math.isfinite(lat) or not math.isfinite(lon):
        return empty
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        return empty
    session = getattr(app.state, "onemap_session", None)
    if session is None:
        session = OneMapSession()
        app.state.onemap_session = session
    token, email, password = read_onemap_credentials()
    try:
        with httpx.Client(timeout=REVERSE_TIMEOUT_SECONDS) as client:
            return reverse_geocode(
                lat,
                lon,
                session=session,
                client=client,
                token=token,
                email=email,
                password=password,
            )
    except Exception:
        return empty


@app.get("/api/destinations", response_model=None)
def destinations(q: Annotated[str, Query()] = "") -> dict | JSONResponse:
    text = q.strip()
    if not text:
        return JSONResponse(
            status_code=400,
            content={"detail": "Enter a destination."},
        )
    session = getattr(app.state, "onemap_session", None)
    if session is None:
        session = OneMapSession()
        app.state.onemap_session = session
    token, email, password = read_onemap_credentials()
    try:
        with httpx.Client(timeout=ONEMAP_TIMEOUT_SECONDS) as client:
            return search_destinations(
                text,
                session=session,
                client=client,
                token=token,
                email=email,
                password=password,
            )
    except DestinationUnavailable:
        content = {
            "status": "unavailable",
            "detail": "Destination search unavailable",
        }
        if demo.destination_is_simulated():
            content["simulated"] = True
        return JSONResponse(status_code=503, content=content)


@app.get("/api/destination-stops", response_model=None)
def destination_stops(
    dest_lat: Annotated[float, Query(ge=-90, le=90)],
    dest_lon: Annotated[float, Query(ge=-180, le=180)],
    user_lat: Annotated[float, Query(ge=-90, le=90)],
    user_lon: Annotated[float, Query(ge=-180, le=180)],
    boarding_stop_code: Annotated[str | None, Query()] = None,
    service_no: Annotated[str | None, Query()] = None,
    walk_speed: Annotated[str | None, Query()] = None,
    walk_speed_source: Annotated[str | None, Query()] = None,
) -> dict | JSONResponse:
    speed, speed_source = _walk_speed(walk_speed, walk_speed_source)
    coordinates = (dest_lat, dest_lon, user_lat, user_lon)
    if any(not math.isfinite(value) for value in coordinates):
        return JSONResponse(
            status_code=422,
            content={"detail": "Coordinates must be finite latitudes and longitudes."},
        )
    boarding = None
    if boarding_stop_code is not None:
        boarding = boarding_stop_code.strip()
        if not boarding:
            return JSONResponse(
                status_code=422,
                content={"detail": "boarding_stop_code must be a non-empty string."},
            )
    service = None
    if service_no is not None:
        service = service_no.strip()
        if not service:
            return JSONResponse(
                status_code=422,
                content={"detail": "service_no must be a non-empty string."},
            )
    cache = getattr(app.state, "lta_static", None)
    if cache is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "detail": "Static stop data is unavailable.",
            },
        )
    listed = list_destination_stops(
        cache,
        dest_lat,
        dest_lon,
        user_lat,
        user_lon,
        boarding_stop_code=boarding,
        service_no=service,
        walk_speed_m_s=speed,
    )
    return {**listed, **response_fields(speed, speed_source)}


@app.get("/api/journey", response_model=None)
def journey(
    dest_lat: Annotated[float, Query(ge=-90, le=90)],
    dest_lon: Annotated[float, Query(ge=-180, le=180)],
    user_lat: Annotated[float, Query(ge=-90, le=90)],
    user_lon: Annotated[float, Query(ge=-180, le=180)],
    destination_stop_code: Annotated[str, Query(min_length=1)],
    boarding_stop_code: Annotated[str | None, Query()] = None,
    service_no: Annotated[str | None, Query()] = None,
    arrive_by: Annotated[str | None, Query()] = None,
    eta: Annotated[str | None, Query()] = None,
    arrival_status: Annotated[str, Query()] = "ok",
    transfer: Annotated[int, Query()] = 0,
    leg1_ride_minutes: Annotated[float | None, Query()] = None,
    leg2_ride_minutes: Annotated[float | None, Query()] = None,
    leg1_service_no: Annotated[str | None, Query()] = None,
    leg1_direction: Annotated[int | None, Query()] = None,
    walk_speed: Annotated[str | None, Query()] = None,
    walk_speed_source: Annotated[str | None, Query()] = None,
) -> dict | JSONResponse:
    speed, speed_source = _walk_speed(walk_speed, walk_speed_source)
    coordinates = (dest_lat, dest_lon, user_lat, user_lon)
    if any(not math.isfinite(value) for value in coordinates):
        return JSONResponse(
            status_code=422,
            content={"detail": "Coordinates must be finite latitudes and longitudes."},
        )
    stop_code = destination_stop_code.strip()
    if not stop_code:
        return JSONResponse(
            status_code=422,
            content={"detail": "destination_stop_code must be a non-empty string."},
        )
    boarding = None
    if boarding_stop_code is not None:
        boarding = boarding_stop_code.strip()
        if not boarding:
            return JSONResponse(
                status_code=422,
                content={"detail": "boarding_stop_code must be a non-empty string."},
            )
    service = None
    if service_no is not None:
        service = service_no.strip()
        if not service:
            return JSONResponse(
                status_code=422,
                content={"detail": "service_no must be a non-empty string."},
            )
    if arrival_status not in ("ok", "stale", "unavailable"):
        return JSONResponse(
            status_code=422,
            content={"detail": "arrival_status must be ok, stale, or unavailable."},
        )
    try:
        parsed_arrive_by = None if arrive_by is None else parse_journey_time(arrive_by)
        parsed_eta = None if eta is None else parse_journey_time(eta)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"detail": "arrive_by and eta must be ISO timestamps."},
        )
    cache = getattr(app.state, "lta_static", None)
    if cache is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "detail": "Static stop data is unavailable.",
            },
        )
    built = build_journey(
        cache,
        dest_lat,
        dest_lon,
        user_lat,
        user_lon,
        stop_code,
        boarding_stop_code=boarding,
        service_no=service,
        arrive_by=parsed_arrive_by,
        eta=parsed_eta,
        arrival_status=arrival_status,
        transfer=transfer == 1,
        leg1_ride_minutes=leg1_ride_minutes,
        leg2_ride_minutes=leg2_ride_minutes,
        leg1_service_no=leg1_service_no,
        leg1_direction=leg1_direction,
        walk_speed_m_s=speed,
    )
    return {**built, **response_fields(speed, speed_source)}


@app.get("/api/journey-plan", response_model=None)
def journey_plan(
    user_lat: Annotated[float, Query(ge=-90, le=90)],
    user_lon: Annotated[float, Query(ge=-180, le=180)],
    destination_stop_code: Annotated[str, Query(min_length=1)],
    dest_lat: Annotated[float, Query(ge=-90, le=90)],
    dest_lon: Annotated[float, Query(ge=-180, le=180)],
    arrive_by: Annotated[str | None, Query()] = None,
    walk_speed: Annotated[str | None, Query()] = None,
    walk_speed_source: Annotated[str | None, Query()] = None,
) -> dict | JSONResponse:
    """The app picks the boarding stop and the route. Static data only."""
    speed, speed_source = _walk_speed(walk_speed, walk_speed_source)
    coordinates = (user_lat, user_lon, dest_lat, dest_lon)
    if any(not math.isfinite(value) for value in coordinates):
        return JSONResponse(
            status_code=422,
            content={"detail": "Coordinates must be finite latitudes and longitudes."},
        )
    destination = destination_stop_code.strip()
    if not destination:
        return JSONResponse(
            status_code=422,
            content={"detail": "destination_stop_code must be a non-empty string."},
        )
    try:
        parsed_arrive_by = None if arrive_by is None else parse_journey_time(arrive_by)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"detail": "arrive_by must be an ISO timestamp."},
        )
    cache = getattr(app.state, "lta_static", None)
    if cache is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "detail": "Static stop data is unavailable.",
            },
        )
    planned = plan_journey(
        cache,
        user_lat=user_lat,
        user_lon=user_lon,
        destination_stop_code=destination,
        dest_lat=dest_lat,
        dest_lon=dest_lon,
        arrive_by=parsed_arrive_by,
        walk_speed_m_s=speed,
    )
    return {**planned, **response_fields(speed, speed_source)}


@app.get("/api/arrivals/peek", response_model=None)
def arrivals_peek(
    stop_code: Annotated[str, Query(min_length=1)],
    service_no: Annotated[str, Query(min_length=1)],
) -> dict | JSONResponse:
    """One raw lookup for the overview: no probability, no logging, no reroute, no notification."""
    stop = stop_code.strip()
    service = service_no.strip()
    if not stop or not service:
        return JSONResponse(
            status_code=422,
            content={"detail": "stop_code and service_no are required."},
        )
    try:
        payload = peek_arrivals(stop, service)
    except ArrivalUnavailable as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": str(exc), "simulated": demo.arrival_is_simulated()},
        )
    return {
        "status": "ok",
        "stop_code": stop,
        "service_no": service,
        "fetched_at": payload.get("fetched_at"),
        "buses": [
            {"arrival_time": bus.get("arrival_time"), "monitored": bus.get("monitored") is True}
            for bus in payload.get("buses") or []
        ],
        "simulated": demo.arrival_is_simulated(),
    }


@app.get("/api/route-plan", response_model=None)
def route_plan(
    boarding_stop_code: Annotated[str, Query(min_length=1)],
    destination_stop_code: Annotated[str, Query(min_length=1)],
    user_lat: Annotated[float, Query(ge=-90, le=90)],
    user_lon: Annotated[float, Query(ge=-180, le=180)],
    dest_lat: Annotated[float, Query(ge=-90, le=90)],
    dest_lon: Annotated[float, Query(ge=-180, le=180)],
    alternate_stops: Annotated[str | None, Query()] = None,
    arrive_by: Annotated[str | None, Query()] = None,
    walk_speed: Annotated[str | None, Query()] = None,
    walk_speed_source: Annotated[str | None, Query()] = None,
) -> dict | JSONResponse:
    speed, speed_source = _walk_speed(walk_speed, walk_speed_source)
    coordinates = (user_lat, user_lon, dest_lat, dest_lon)
    if any(not math.isfinite(value) for value in coordinates):
        return JSONResponse(
            status_code=422,
            content={"detail": "Coordinates must be finite latitudes and longitudes."},
        )
    origin = boarding_stop_code.strip()
    destination = destination_stop_code.strip()
    if not origin or not destination:
        return JSONResponse(
            status_code=422,
            content={"detail": "boarding_stop_code and destination_stop_code are required."},
        )
    cache = getattr(app.state, "lta_static", None)
    if cache is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "unavailable",
                "detail": "Static stop data is unavailable.",
            },
        )
    try:
        parsed_arrive_by = None if arrive_by is None else parse_journey_time(arrive_by)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"detail": "arrive_by must be an ISO timestamp."},
        )
    alternates = [] if alternate_stops is None else alternate_stops.split(",")
    moment = datetime.now(SGT)
    planned = suggest_alternate_boarding(
        cache,
        origin,
        destination,
        user_lat,
        user_lon,
        dest_lat,
        dest_lon,
        alternates,
        now=moment,
        walk_speed_m_s=speed,
    )
    options = planned.get("options") or []
    minutes = [option.get("generalized_time_minutes") for option in options]
    if planned.get("route_status") == "alternate_boarding":
        alternate = planned.get("alternate_stop") or {}
        minutes = [alternate.get("generalized_time_minutes")]
    planned["planning_warning"] = planning_warning(moment, parsed_arrive_by, minutes)
    planned.update(response_fields(speed, speed_source))
    return planned
