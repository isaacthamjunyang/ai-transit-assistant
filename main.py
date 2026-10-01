from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

import math

import httpx

from arrivals import ArrivalUnavailable, fetch_arrivals
import demo
from explain import ai_explanation_enabled, build_poll_explanation, handle_explain_request
from catch_heuristic import normalize_location_timestamp
from destination_stops import list_destination_stops
from journey import build_journey, parse_journey_time
from lta_static import load_static_data
from nearby import BOARDING_RADIUS_M, nearby_boarding_stops
from reroute import SGT, apply_active_target, log_scored_poll, plan_reroute, resolve_pinned_target
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
    read_onemap_credentials,
    search_destinations,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.onemap_session = OneMapSession()
    app.state.lta_static = load_static_data()
    yield


app = FastAPI(title="Bus Catch Assistant", lifespan=lifespan)

STATIC_DIR = Path(__file__).resolve().parent / "static"
INDEX_PATH = STATIC_DIR / "index.html"


@app.get("/")
def home() -> HTMLResponse:
    page = INDEX_PATH.read_text(encoding="utf-8")
    flag = "true" if ai_explanation_enabled() else "false"
    page = page.replace(
        "var AI_EXPLANATION_ENABLED = false;",
        "var AI_EXPLANATION_ENABLED = " + flag + ";",
        1,
    )
    return HTMLResponse(page)


@app.get("/theme.css")
def theme_css() -> FileResponse:
    return FileResponse(STATIC_DIR / "theme.css", media_type="text/css")


@app.get("/components.css")
def components_css() -> FileResponse:
    return FileResponse(STATIC_DIR / "components.css", media_type="text/css")


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
    explanation_in_flight: Annotated[int | None, Query()] = None,
    route_type: Annotated[str | None, Query()] = None,
    leg_index: Annotated[int | None, Query()] = None,
    leg2_service_no: Annotated[str | None, Query()] = None,
    leg2_direction: Annotated[int | None, Query()] = None,
    leg2_stop_code: Annotated[str | None, Query()] = None,
    leg1_ride_minutes: Annotated[float | None, Query()] = None,
) -> dict | JSONResponse:
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
    try:
        payload = fetch_arrivals(
            stop_code,
            service_no,
            user_lat=lat,
            user_lon=lon,
            accuracy=accuracy,
            location_timestamp=location_timestamp,
            cache=cache,
        )
    except ArrivalUnavailable:
        content = {
            "status": "unavailable",
            "detail": "Live arrival data is unavailable.",
        }
        if demo.timeout_is_active():
            content["simulated"] = True
        return JSONResponse(status_code=503, content=content)
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
    ):
        def load_alternate(code: str, service: str) -> dict:
            alternate = fetch_arrivals(
                code,
                service,
                user_lat=lat,
                user_lon=lon,
                accuracy=accuracy,
                location_timestamp=location_timestamp,
                cache=cache,
            )
            log_scored_poll(
                cache=cache,
                current=alternate,
                bus=_scored_primary(alternate.get("buses") or []),
                user_lat=lat,
                user_lon=lon,
                accuracy_m=accuracy,
                now=moment,
                reroute_fired=False,
                reroute_reason="",
                destination_stop_code=destination_code,
            )
            return alternate

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
        )
        payload["reroute"] = decision
        fired = bool(decision.get("switched"))
        reroute = decision.get("reroute") if fired else None
        if isinstance(reroute, dict):
            reason = reroute.get("reroute_reason") or ""
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
            rendered=explanation_rendered == 1,
            last_low=last_explained_range_low,
            last_high=last_explained_range_high,
            in_flight=explanation_in_flight == 1,
            reroute_fired=fired,
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
) -> dict | JSONResponse:
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
    return list_destination_stops(
        cache,
        dest_lat,
        dest_lon,
        user_lat,
        user_lon,
        boarding_stop_code=boarding,
        service_no=service,
    )


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
) -> dict | JSONResponse:
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
    return build_journey(
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
    )


@app.get("/api/route-plan", response_model=None)
def route_plan(
    boarding_stop_code: Annotated[str, Query(min_length=1)],
    destination_stop_code: Annotated[str, Query(min_length=1)],
    user_lat: Annotated[float, Query(ge=-90, le=90)],
    user_lon: Annotated[float, Query(ge=-180, le=180)],
    dest_lat: Annotated[float, Query(ge=-90, le=90)],
    dest_lon: Annotated[float, Query(ge=-180, le=180)],
    alternate_stops: Annotated[str | None, Query()] = None,
) -> dict | JSONResponse:
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
    alternates = [] if alternate_stops is None else alternate_stops.split(",")
    return suggest_alternate_boarding(
        cache,
        origin,
        destination,
        user_lat,
        user_lon,
        dest_lat,
        dest_lon,
        alternates,
        now=datetime.now(SGT),
    )
