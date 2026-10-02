"""Reroute options: every evaluated candidate, badges without a blended score, on-demand search."""

import math
from datetime import datetime, timedelta, timezone

from lta_static import StopAndRouteCache
from nearby import EARTH_RADIUS_M
from reroute import plan_options, plan_reroute, rank_options

SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 9, 29, 14, 0, tzinfo=SGT)
LAT = 1.3
LON = 103.8
ORIGIN = "01011"
ALT = "01012"
DEST = "99999"


def _north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


def _row(service, point, low, high, arrival="2026-09-29T14:10:00+08:00", estimated="2026-09-29T14:30:00+08:00"):
    return {
        "id": f"{service}|X|{arrival}",
        "service_no": service,
        "stop_code": "X",
        "point": point,
        "range_low": low,
        "range_high": high,
        "arrival_time": arrival,
        "estimated_arrival": estimated,
        "distance_m": 0,
        "walk_m": 0,
    }


def _ids(ranked):
    return [row["service_no"] for row in ranked["rows"]]


def _all(ranked):
    """Every option: the recommended one (the card) and the list rows."""
    return ([ranked["recommended"]] if ranked["recommended"] else []) + ranked["rows"]


def _by_service(ranked):
    return {row["service_no"]: row for row in _all(ranked)}


def _rank(options, target=None, entry="recommended"):
    from recommend import recommend_option

    return rank_options(options, recommend_option(options, target), target, entry)


def test_one_option_with_both_pills_is_the_recommendation():
    options = [_row("7", 70, 60, 80), _row("16", 41, 33, 50, estimated="2026-09-29T14:40:00+08:00")]
    ranked = _rank(options)
    top = ranked["recommended"]
    assert top["service_no"] == "7" and top["badges"] == ["highest_chance", "fastest"]
    assert ranked["recommended_id"] == top["id"] and ranked["mode"] == "winner"
    assert [row["service_no"] for row in ranked["rows"]] == ["16"]  # the recommended option is not in the list


def test_different_holders_carry_one_pill_each_and_the_recommended_option_leaves_the_list():
    options = [
        _row("7", 70, 60, 80, estimated="2026-09-29T14:50:00+08:00"),
        _row("16", 55, 45, 65, estimated="2026-09-29T14:30:00+08:00"),
        _row("36", 41, 33, 50, estimated="2026-09-29T14:45:00+08:00"),
    ]
    ranked = _rank(options)
    by_service = _by_service(ranked)
    assert by_service["7"]["badges"] == ["highest_chance"]
    assert by_service["16"]["badges"] == ["fastest"]
    assert by_service["36"]["badges"] == []
    assert ranked["recommended"]["service_no"] == "7"
    assert _ids(ranked) == ["16", "36"]  # point probability, highest first


def test_no_recommendation_gives_no_card_but_the_full_list():
    options = [_row("7", 30, 20, 35), _row("16", 25, 15, 30)]
    ranked = _rank(options)
    assert ranked["mode"] == "none" and ranked["recommended"] is None and ranked["recommended_id"] is None
    assert len(ranked["rows"]) == 2
    assert all(row["unlikely"] for row in ranked["rows"])


def test_the_quick_pill_excludes_range_high_below_forty():
    options = [
        _row("7", 30, 20, 39, estimated="2026-09-29T14:20:00+08:00"),
        _row("16", 50, 40, 60, estimated="2026-09-29T14:40:00+08:00"),
    ]
    by_service = _by_service(_rank(options))
    assert "fastest" not in by_service["7"]["badges"]
    assert "fastest" in by_service["16"]["badges"]
    assert by_service["7"]["unlikely"] is True and by_service["16"]["unlikely"] is False
    only_unlikely = _rank([_row("7", 30, 20, 39)])
    assert all("fastest" not in row["badges"] for row in _all(only_unlikely))


def test_the_list_orders_by_point_then_estimated_arrival_then_service():
    options = [
        _row("16", 60, 50, 70, estimated="2026-09-29T14:30:00+08:00"),
        _row("7", 60, 50, 70, estimated="2026-09-29T14:30:00+08:00"),
        _row("36", 60, 50, 70, estimated="2026-09-29T14:25:00+08:00"),
        _row("99", 80, 70, 90),
        _row("12", 20, 10, 25),
    ]
    ranked = _rank(options)
    assert ranked["recommended"]["service_no"] == "99"
    assert _ids(ranked) == ["36", "7", "16", "12"]


def test_every_row_keeps_its_point_and_range():
    single = [_row("7", 64, 51, 78)]
    row = _rank(single)["recommended"]
    assert (row["point"], row["range_low"], row["range_high"]) == (64, 51, 78)


def test_a_row_after_the_target_is_labelled():
    deadline = datetime(2026, 9, 29, 14, 40, tzinfo=SGT)
    options = [_row("7", 60, 50, 70, estimated="2026-09-29T14:30:00+08:00"), _row("16", 50, 40, 60, estimated="2026-09-29T14:50:00+08:00")]
    by_service = _by_service(_rank(options, deadline))
    assert by_service["7"]["after_target"] is False and by_service["16"]["after_target"] is True
    assert all(row["after_target"] is False for row in _all(_rank(options)))


def _cache():
    dest_lat, dest_lon = _north(2000)
    alt_lat, alt_lon = _north(150)
    stops = [
        {"BusStopCode": ORIGIN, "Description": "Origin", "RoadName": "Rd", "Latitude": LAT, "Longitude": LON},
        {"BusStopCode": ALT, "Description": "Alt", "RoadName": "Rd", "Latitude": alt_lat, "Longitude": alt_lon},
        {"BusStopCode": DEST, "Description": "Destination", "RoadName": "Rd", "Latitude": dest_lat, "Longitude": dest_lon},
    ]
    routes = []
    for service, code in (("18", ORIGIN), ("7", ALT), ("16", ALT)):
        routes.append({"ServiceNo": service, "Direction": 1, "BusStopCode": code, "StopSequence": 1, "Distance": 0})
        routes.append({"ServiceNo": service, "Direction": 1, "BusStopCode": DEST, "StopSequence": 5, "Distance": 2.0})
    return StopAndRouteCache(stops, routes, [])


def _bus(position, point, low, high, minutes, *, primary=False):
    eta = (NOW + timedelta(minutes=minutes)).isoformat()
    return {
        "position": position,
        "arrival_time": eta,
        "is_missed": False,
        "is_primary": primary,
        "monitored": True,
        "latitude": LAT,
        "longitude": LON,
        "probability": {"point": point, "range_low": low, "range_high": high, "slack_seconds": 10, "data_quality": "live"},
    }


def _current(buses):
    return {"status": "ok", "stop_code": ORIGIN, "service_no": "18", "buses": buses}


def _kwargs(loader, **extra):
    dest_lat, dest_lon = _north(2000)
    return dict(
        cache=_cache(), user_lat=LAT, user_lon=LON, destination_stop_code=DEST,
        place_lat=dest_lat, place_lon=dest_lon, arrive_by=None, now=NOW, loader=loader, **extra,
    )


def test_on_demand_search_ignores_the_trigger_and_keeps_low_chance_rows():
    calls = []

    def loader(code, service):
        calls.append((code, service))
        return {"status": "ok", "stop_code": code, "service_no": service,
                "buses": [_bus("NextBus", 20, 10, 25, 9)]}

    current = _current([_bus("NextBus", 90, 80, 92, 5, primary=True), _bus("NextBus2", 70, 60, 80, 12)])
    result = plan_options(current=current, **_kwargs(loader))
    services = sorted(row["service_no"] for row in _all(result))
    assert services == ["16", "18", "18", "7"]
    low = [row for row in _all(result) if row["service_no"] in ("7", "16")]
    assert all(row["unlikely"] for row in low)
    assert sorted(calls) == [(ALT, "16"), (ALT, "7")]  # one lookup per alternate (stop, service); nothing else
    same = [row for row in _all(result) if row["next_of_same_service"]]
    assert len(same) == 2


def test_on_demand_search_drops_the_missed_bus():
    def loader(code, service):
        return {"status": "ok", "buses": []}

    primary = _bus("NextBus", 90, 80, 92, 5, primary=True)
    missed_epoch = datetime.fromisoformat(primary["arrival_time"]).timestamp()
    current = _current([primary, _bus("NextBus2", 70, 60, 80, 12)])
    result = plan_options(current=current, missed_eta_epoch=missed_epoch, **_kwargs(loader))
    only = _all(result)
    assert [row["service_no"] for row in only] == ["18"]
    assert only[0]["next_of_same_service"] is True
    assert only[0]["reroute"]["service_no"] == "18"
    assert result["rows"] == []  # the recommended option is the card, not a list row


def test_automatic_decision_carries_every_candidate_even_with_no_winner():
    calls = []

    def loader(code, service):
        calls.append((code, service))
        return {"status": "ok", "stop_code": code, "service_no": service, "buses": [_bus("NextBus", 20, 10, 25, 9)]}

    dest_lat, dest_lon = _north(2000)
    current = _current([_bus("NextBus", 20, 10, 30, 6, primary=True), _bus("NextBus2", 22, 12, 32, 13)])
    decision = plan_reroute(
        cache=_cache(), current=current, user_lat=LAT, user_lon=LON, accuracy_m=10, location_timestamp=None,
        destination_stop_code=DEST, place_lat=dest_lat, place_lon=dest_lon, arrive_by=None, last_reroute_at=None,
        now=NOW, loader=loader,
    )
    assert decision["switched"] is False and decision["no_better_option"]
    options = decision["options"]
    assert options["mode"] == "none" and options["recommended"] is None
    assert len(options["rows"]) == 3  # NextBus2 at this stop plus Bus 7 and Bus 16 at the alternate stop
    assert len(calls) == 2


def test_automatic_decision_with_a_winner_lists_everything_and_a_card():
    def loader(code, service):
        point = 80 if service == "7" else 20
        return {"status": "ok", "stop_code": code, "service_no": service,
                "buses": [_bus("NextBus", point, point - 10, point + 10, 9)]}

    dest_lat, dest_lon = _north(2000)
    current = _current([_bus("NextBus", 20, 10, 30, 6, primary=True)])
    decision = plan_reroute(
        cache=_cache(), current=current, user_lat=LAT, user_lon=LON, accuracy_m=10, location_timestamp=None,
        destination_stop_code=DEST, place_lat=dest_lat, place_lon=dest_lon, arrive_by=None, last_reroute_at=None,
        now=NOW, loader=loader,
    )
    assert decision["switched"] is True
    options = decision["options"]
    assert options["mode"] == "winner"
    assert options["entry"] == "better"
    assert options["recommended"]["service_no"] == "7" and options["recommended"]["recommended"] is True
    assert [row["service_no"] for row in options["rows"]] == ["16"]
    everything = _all(options)
    assert {row["service_no"] for row in everything} == {"7", "16"}
    assert all("reroute" in row and row["reroute"]["stop"]["stop_code"] for row in everything)
    assert all(row["band"] in ("ok", "mid", "low") for row in everything)


def test_page_wiring_for_cards_rows_overview_and_the_stale_bus_guard():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")
    assert 'id="new-journey"' in html and "Your new journey" in html
    assert "Switching because your current bus is unlikely to be caught." in html
    for gone in ("From", "Boarding stop", "Bus service", "Destination stop"):
        assert gone in html.split("function renderNewJourney()", 1)[1].split("function leaveNewJourneyScreen", 1)[0]
    render = html.split("function renderNewJourney()", 1)[1].split("function leaveNewJourneyScreen", 1)[0]
    assert "Edit" not in render  # no Edit links
    assert 'id="new-journey-start"' in html and "Start journey" in html.split('id="new-journey-start"', 1)[1][:200]
    guard = html.split("function startNewJourney()", 1)[1].split('.addEventListener("click", startNewJourney)', 1)[0]
    assert "OPTIONS_CACHE_MAX_AGE_MS" in guard and "/api/arrivals/peek" in guard
    assert "showBusAlreadyLeft()" in guard
    assert "That bus has already left. Choose another option." in html
    # Back from the new-journey screen keeps the current journey: no leave dialog and no endMonitoring.
    back = html.split("function requestBack()", 1)[1].split("var pendingLeaveAction", 1)[0]
    assert "!returnsWithoutConfirm()" in back
    helper = html.split("function returnsWithoutConfirm()", 1)[1].split("function requestBack()", 1)[0]
    assert '"newjourney"' in helper and '"arrivals"' in helper
    leave = html.split("function leaveNewJourneyScreen(toPageA)", 1)[1].split("function chosenBusStillListed", 1)[0]
    assert "endMonitoring" not in leave
    # One merged card per recommendation, with its own Switch button; no separate Fastest option card.
    assert "Fastest option" not in html and "Better option found" in html and "Recommended option" in html
    assert "Other buses at your stop" in html and "Other options at your stop" not in html and "buildSwitchButton(row)" in html
