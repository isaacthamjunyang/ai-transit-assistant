"""Journey form calculations. Fixtures only — these tests do not call live APIs."""

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import lta_static
from arrivals import fetch_arrivals
from journey import build_journey, leave_by_time, parse_journey_time, resolve_leave_by
from lta_static import StopAndRouteCache, write_cache
from main import app
from nearby import EARTH_RADIUS_M, haversine_m

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
USER = (1.3, 103.8)
PLACE = (1.32, 103.8)


def _north(lat, lon, metres):
    return lat + math.degrees(metres / EARTH_RADIUS_M), lon


def _stop(code, lat, lon, name):
    return {
        "BusStopCode": code,
        "Description": name,
        "RoadName": "Orchard Rd",
        "Latitude": lat,
        "Longitude": lon,
    }


def _route(service, sequence, code, distance):
    return {
        "ServiceNo": service,
        "Direction": 1,
        "StopSequence": sequence,
        "BusStopCode": code,
        "Distance": distance,
    }


def _service(service, freq):
    return {
        "ServiceNo": service,
        "Direction": 1,
        "OriginCode": "A",
        "DestinationCode": "Z",
        "AM_Peak_Freq": freq,
        "AM_Offpeak_Freq": freq,
        "PM_Peak_Freq": freq,
        "PM_Offpeak_Freq": freq,
    }


def _usable_cache():
    return StopAndRouteCache(
        [
            _stop("B", *USER, "Boarding"),
            _stop("D", *PLACE, "Dest"),
        ],
        [_route("36", 1, "B", 1.0), _route("36", 4, "D", 3.5)],
        [_service("36", "10-10")],
    )


def _null_ride_cache():
    return StopAndRouteCache(
        [
            _stop("B", *USER, "Boarding"),
            _stop("D", *PLACE, "Dest"),
        ],
        [_route("36", 1, "B", 2.0), _route("36", 4, "D", 0.4)],
        [_service("36", "10-10")],
    )


def _journey(cache, **kwargs):
    values = {
        "boarding_stop_code": "B",
        "service_no": "36",
        "now": NOW,
    }
    values.update(kwargs)
    return build_journey(
        cache,
        PLACE[0],
        PLACE[1],
        USER[0],
        USER[1],
        "D",
        **values,
    )


def test_numeric_ride_compares_arrive_by_without_a_probability():
    ride_minutes = math.ceil(5 + (2.5 / 18) * 60)
    late = _journey(_usable_cache(), arrive_by=NOW + timedelta(minutes=10))
    assert late["ride_minutes"] == ride_minutes
    assert late["ride_label"] == f"Ride time: ~{ride_minutes} min"
    assert late["comparison_label"] == "Arrive-by check: Risk of delay"
    assert late["comparison_note"] == "Rough check: may miss arrive-by time."
    assert late["estimated_arrival"] is not None
    assert "probability" not in late
    early = _journey(_usable_cache(), arrive_by=NOW + timedelta(minutes=30))
    assert early["comparison_label"] == "Arrive-by check: On track"
    assert early["comparison_note"] == (
        "Estimated arrival is at or before your requested time."
    )
    assert early["ride_minutes"] == ride_minutes
    same_time = _journey(
        _usable_cache(),
        arrive_by=NOW + timedelta(minutes=ride_minutes),
    )
    assert same_time["comparison_label"] == "Arrive-by check: On track"
    assert same_time["comparison_note"] == (
        "Estimated arrival is at or before your requested time."
    )


def test_a_set_arrive_by_reaches_the_status_and_a_blank_skips_it():
    set_value = _journey(
        _usable_cache(),
        arrive_by=parse_journey_time("2099-01-01T18:00"),
    )
    assert set_value["comparison_label"] == "Arrive-by check: On track"
    blank = _journey(_usable_cache())
    assert blank["comparison_label"] == ""
    assert blank["comparison_note"] == ""
    assert blank["ride_minutes"] == set_value["ride_minutes"]


def _transfer_journey(arrive_by, leg1, leg2, user=None):
    lat, lon = USER if user is None else user
    return build_journey(
        _usable_cache(),
        PLACE[0],
        PLACE[1],
        lat,
        lon,
        "D",
        boarding_stop_code="B",
        service_no="36",
        arrive_by=arrive_by,
        now=NOW,
        transfer=True,
        leg1_ride_minutes=leg1,
        leg2_ride_minutes=leg2,
        leg1_service_no="36",
        leg1_direction=1,
    )


def _transfer_minutes(user):
    walk = haversine_m(user[0], user[1], USER[0], USER[1]) / 1.25 / 60
    return math.ceil(walk + 5 + 4 + 6)


def test_transfer_within_the_arrive_by_time_is_on_track():
    user = _north(*USER, 125)
    minutes = _transfer_minutes(user)
    body = _transfer_journey(NOW + timedelta(minutes=minutes), 4, 6, user)
    assert body["ride_minutes"] == minutes
    assert minutes == math.ceil(haversine_m(user[0], user[1], USER[0], USER[1]) / 1.25 / 60 + 15)
    assert body["comparison_label"] == "Arrive-by check: On track"
    assert body["comparison_note"] == "Estimated arrival is at or before your requested time."


def test_transfer_past_the_arrive_by_time_is_a_risk_of_delay():
    user = _north(*USER, 125)
    minutes = _transfer_minutes(user)
    body = _transfer_journey(NOW + timedelta(minutes=minutes - 1), 4, 6, user)
    assert body["comparison_label"] == "Arrive-by check: Risk of delay"
    assert body["comparison_note"] == "Rough check: may miss arrive-by time."
    assert body["ride_minutes"] == minutes


def test_transfer_with_one_null_ride_shows_the_locked_na_message():
    body = _transfer_journey(NOW + timedelta(hours=3), 4, None)
    assert body["ride_minutes"] is None
    assert body["comparison_label"] == "Arrive-by check: N/A"
    assert body["comparison_note"] == (
        "Destination ride duration unavailable; cannot verify target arrival time."
    )


def test_null_ride_duration_uses_the_exact_unavailable_labels():
    eta = NOW + timedelta(minutes=8)
    body = _journey(_null_ride_cache(), arrive_by=NOW + timedelta(minutes=5), eta=eta)
    assert body["ride_minutes"] is None
    assert body["ride_label"] == "Ride time: Unavailable"
    assert body["comparison_label"] == "Arrive-by check: N/A"
    assert body["comparison_note"] == (
        "Destination ride duration unavailable; cannot verify target arrival time."
    )
    assert body["estimated_arrival"] is None
    assert body["leave_by"] is not None


def test_leave_by_is_eta_minus_slow_walk_minus_45_seconds_only():
    eta = NOW + timedelta(minutes=8)
    distance_m = 110
    leave_by = leave_by_time(eta, distance_m)
    slow_walk_s = distance_m / 1.1
    assert leave_by == eta - timedelta(seconds=slow_walk_s + 45)
    assert leave_by != eta - timedelta(seconds=slow_walk_s + 45 + 60)
    resolved = resolve_leave_by(
        eta=eta,
        distance_m=distance_m,
        arrival_status="ok",
        now=NOW,
    )
    assert resolved == leave_by


def test_leave_by_does_not_depend_on_ride_duration():
    eta = NOW + timedelta(minutes=8)
    usable = _journey(_usable_cache(), eta=eta)
    missing = _journey(_null_ride_cache(), eta=eta)
    assert usable["ride_minutes"] is not None
    assert missing["ride_minutes"] is None
    assert usable["leave_by"] == missing["leave_by"]
    assert usable["leave_by"] == (eta - timedelta(seconds=45)).replace(microsecond=0).isoformat()


def test_a_later_eta_moves_leave_by_by_the_same_amount():
    first = NOW + timedelta(minutes=8)
    second = NOW + timedelta(minutes=20)
    early = resolve_leave_by(eta=first, distance_m=0, arrival_status="ok", now=NOW)
    late = resolve_leave_by(eta=second, distance_m=0, arrival_status="ok", now=NOW)
    assert late - early == timedelta(minutes=12)


def test_stale_or_unavailable_eta_has_no_leave_by_clock():
    eta = NOW + timedelta(minutes=8)
    assert resolve_leave_by(eta=eta, distance_m=50, arrival_status="stale", now=NOW) is None
    assert (
        resolve_leave_by(eta=eta, distance_m=50, arrival_status="unavailable", now=NOW)
        is None
    )
    assert resolve_leave_by(eta=None, distance_m=50, arrival_status="ok", now=NOW) is None
    missed = NOW - timedelta(seconds=31)
    assert resolve_leave_by(eta=missed, distance_m=50, arrival_status="ok", now=NOW) is None


def test_page_shows_the_journey_form():
    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="journey-panel"' in html
    assert 'id="arrive-by"' in html
    assert "Ride time:" not in html or "body.ride_label" in html
    assert "body.ride_label" in html
    assert "body.comparison_label" in html
    assert "body.comparison_note" in html
    assert "Leave-by: Unavailable" in html
    assert "showLocalNotification(notice.title, { body: notice.body })" in html
    assert "/ 1.1" not in html


def test_live_poll_recalculates_leave_by_from_the_latest_eta():
    cache = StopAndRouteCache([_stop("08057", *USER, "Boarding")], [], [])
    first_eta = "2026-09-29T14:58:00+08:00"
    second_eta = "2026-09-29T15:10:00+08:00"

    def _client(arrival):
        payload = {
            "BusStopCode": "08057",
            "Services": [
                {
                    "ServiceNo": "36",
                    "NextBus": {
                        "EstimatedArrival": arrival,
                        "Latitude": "1.3",
                        "Longitude": "103.8",
                        "Monitored": 1,
                    },
                }
            ],
        }

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=payload)

        return httpx.Client(transport=httpx.MockTransport(handler))

    fetched = datetime(2026, 9, 29, 14, 54, tzinfo=SGT)
    with _client(first_eta) as client:
        first = fetch_arrivals(
            "08057",
            "36",
            client=client,
            account_key="test-account-key",
            now=fetched,
            user_lat=USER[0],
            user_lon=USER[1],
            accuracy=18,
            cache=cache,
        )
    with _client(second_eta) as client:
        second = fetch_arrivals(
            "08057",
            "36",
            client=client,
            account_key="test-account-key",
            now=fetched,
            user_lat=USER[0],
            user_lon=USER[1],
            accuracy=18,
            cache=cache,
        )
    assert first["leave_by"] == "2026-09-29T14:57:15+08:00"
    assert second["leave_by"] == "2026-09-29T15:09:15+08:00"
    assert "probability" in first["buses"][0]


def test_journey_endpoint_stays_on_the_local_cache(tmp_path, monkeypatch):
    write_cache(
        tmp_path,
        [
            _stop("B", *USER, "Boarding"),
            _stop("D", *PLACE, "Dest"),
        ],
        [_route("36", 1, "B", 1.0), _route("36", 4, "D", 3.5)],
        [_service("36", "10-10")],
    )
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)

    def explode(*_args, **_kwargs):
        raise AssertionError("journey must not open a live client")

    monkeypatch.setattr(httpx, "Client", explode)
    with TestClient(app) as client:
        response = client.get(
            "/api/journey",
            params={
                "dest_lat": PLACE[0],
                "dest_lon": PLACE[1],
                "user_lat": USER[0],
                "user_lon": USER[1],
                "destination_stop_code": "D",
                "boarding_stop_code": "B",
                "service_no": "36",
                "arrive_by": "2000-01-01T00:00:00+08:00",
                "eta": "2099-01-01T12:00:00+08:00",
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["ride_minutes"] is not None
    assert body["comparison_label"] == "Arrive-by check: Risk of delay"
    assert body["comparison_note"] == "Rough check: may miss arrive-by time."
    assert body["leave_by"] is not None
    assert "AccountKey" not in response.text
    assert "probability" not in body


@pytest.mark.parametrize(
    "params",
    [
        {"destination_stop_code": "D"},
        {
            "dest_lat": 1,
            "dest_lon": 103,
            "user_lat": 1,
            "user_lon": 103,
            "destination_stop_code": " ",
        },
        {
            "dest_lat": 1,
            "dest_lon": 103,
            "user_lat": 1,
            "user_lon": 103,
            "destination_stop_code": "D",
            "arrive_by": "tomorrow",
        },
        {
            "dest_lat": 1,
            "dest_lon": 103,
            "user_lat": 1,
            "user_lon": 103,
            "destination_stop_code": "D",
            "arrival_status": "guess",
        },
    ],
)
def test_journey_rejects_invalid_input(tmp_path, monkeypatch, params):
    write_cache(
        tmp_path,
        [_stop("D", *PLACE, "Dest")],
        [_route("36", 1, "D", 0)],
        [],
    )
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)

    def explode(*_args, **_kwargs):
        raise AssertionError("journey must not open a live client")

    monkeypatch.setattr(httpx, "Client", explode)
    with TestClient(app) as client:
        response = client.get("/api/journey", params=params)
    assert response.status_code == 422
