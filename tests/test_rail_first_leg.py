"""A train as the first leg: score_scheduled_rail, rail_arrivals, the endpoints that carry leg_kind=rail, the
train card text and its page mirror. Fixtures only: nothing here calls LTA, OneMap or any network."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import catch_heuristic as ch
import config
import explain
import journey
import main
import rail_arrivals as ra
import service_hours as sh
from lta_static import StopAndRouteCache
from route_plan import reroute_enabled

SGT = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 12, 8, 20, tzinfo=SGT)  # a Monday, in the morning peak
STATION = (1.35092, 103.8485)
NEAR = (1.35092 + 0.0018, 103.8485)  # about 200 m north of the station
MSP = "Marina South Pier"
DEPARTURE = "2026-10-12T08:31:11+08:00"
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def table(headway=None, last="2415"):
    day = lambda first, final: {"first": first, "last": final, "headway_s": dict(headway or {})}  # noqa: E731
    return {
        "schema": 1,
        "stations": {"NS17": {"name": "Bishan", "latitude": STATION[0], "longitude": STATION[1], "directions": {
            MSP: {"line": "NS", "direction_id": 1, "trips": 100,
                  "WD": day("0548", last), "SAT": day("0543", "2335"), "SUN": day("0608", "2335")}}}},
        "lines": {"NS": {"name": "North-South Line", "mode": "SUBWAY", "color": "D62821", "text_color": "FFFFFF"}},
        "patterns": {"NS": {MSP: ["NS16", "NS17", "NS18"]}},
    }


def iso(minutes_from_now: float) -> str:
    return (NOW + timedelta(minutes=minutes_from_now)).isoformat()


def train(minutes: float) -> dict:
    return {"arrival_time": iso(minutes)}


def score(trains, *, user=NEAR, accuracy=10.0, headway=240, location_timestamp=None, speed=1.25, now=NOW, calls=None):
    def headway_for(when):
        if calls is not None:
            calls.append(when)
        return headway

    return ch.score_scheduled_rail(
        trains, user_lat=None if user is None else user[0], user_lon=None if user is None else user[1],
        accuracy_m=accuracy, stop_lat=STATION[0], stop_lon=STATION[1], headway_for=headway_for, now=now,
        location_timestamp=location_timestamp, walk_speed_m_s=speed)


# ---- score_scheduled_rail -----------------------------------------------------------------------------------


def test_a_train_is_schedule_quality_never_live_and_never_at_stop():
    scored = score([train(10)])
    chance = scored[0]["probability"]
    assert scored[0]["monitored"] is False and scored[0]["is_primary"] is True and scored[0]["is_missed"] is False
    assert chance["data_quality"] == "schedule" and chance["at_stop"] is False
    assert chance["band"] in ("ok", "mid", "low") and "pace" in chance and chance["location_reason"] is None


def test_point_low_and_high_are_capped_at_60_whatever_the_slack():
    for minutes in (3, 5, 8, 12, 30, 90):
        for headway in (60, 240, 900):
            for user in (STATION, NEAR, (1.37, 103.85)):
                chance = score([train(minutes)], user=user, headway=headway)[0]["probability"]
                assert max(chance["point"], chance["range_low"], chance["range_high"]) <= round(ch.SCHEDULE_CEILING * 100)
    ample = score([train(40)])[0]["probability"]
    assert (ample["point"], ample["range_low"], ample["range_high"]) == (60, 60, 60)


def test_the_range_is_half_the_headway_each_side_of_the_slack_functions():
    seconds, distance = 100.0, ch.straight_line_m(NEAR[0], NEAR[1], *STATION)
    point_speed, slow_speed, fast_speed = ch.range_speeds(1.25)
    for headway in (120, 300, 600):
        chance = score([{"arrival_time": (NOW + timedelta(seconds=seconds)).isoformat()}], headway=headway)[0]["probability"]
        slack = ch.point_slack(seconds, distance, point_speed)
        low = ch.low_slack(seconds, distance, 10.0, slow_speed) - headway / 2
        high = ch.high_slack(seconds, distance, fast_speed) + headway / 2
        assert chance["point"] == ch.to_percent(min(ch.catch_probability(slack), ch.SCHEDULE_CEILING))
        assert chance["range_low"] == ch.to_percent(min(ch.catch_probability(low), ch.SCHEDULE_CEILING))
        assert chance["range_high"] == ch.to_percent(min(ch.catch_probability(high), ch.SCHEDULE_CEILING))
        assert chance["slack_seconds"] == int(round(slack))


def test_a_longer_headway_widens_the_range_on_both_sides():
    arrival = {"arrival_time": (NOW + timedelta(seconds=150)).isoformat()}
    short = score([arrival], headway=60)[0]["probability"]
    long = score([arrival], headway=900)[0]["probability"]
    assert long["range_low"] <= short["range_low"] and long["range_high"] >= short["range_high"]
    assert (long["range_high"] - long["range_low"]) > (short["range_high"] - short["range_low"])
    assert long["point"] == short["point"]  # the point uses the timetable's own time


def test_the_headway_is_asked_for_each_trains_own_departure_and_kept():
    asked = []
    scored = score([train(5), train(7)], headway=300, calls=asked)
    assert asked == [NOW + timedelta(minutes=5), NOW + timedelta(minutes=7)]
    assert [t["headway_s"] for t in scored] == [300, 300]


def test_walk_time_uses_the_walking_speed_given():
    arrival = {"arrival_time": (NOW + timedelta(seconds=260)).isoformat()}
    slow = score([arrival], speed=0.8)[0]["probability"]["point"]
    fast = score([arrival], speed=1.4)[0]["probability"]["point"]
    assert slow < fast


def test_the_at_stop_rule_that_makes_a_live_bus_97_never_applies_to_a_train():
    on_the_stop = score([train(4)], user=STATION)[0]["probability"]
    assert on_the_stop["at_stop"] is False and on_the_stop["point"] <= 60
    bus = ch.score_buses([{"arrival_time": iso(4), "monitored": True}], user_lat=STATION[0], user_lon=STATION[1],
                         accuracy_m=10.0, stop_lat=STATION[0], stop_lon=STATION[1], services=[], routes=[],
                         service_no="36", stop_code="1", now=NOW, location_timestamp=None)
    assert bus[0]["probability"]["at_stop"] is True and bus[0]["probability"]["point"] == config.AT_STOP_PROBABILITY


def test_a_missed_train_has_no_probability_and_the_next_one_becomes_primary():
    scored = score([train(-2), train(6), train(12)])
    assert scored[0]["is_missed"] is True and scored[0]["probability"] is None and scored[0]["is_primary"] is False
    assert scored[1]["is_primary"] is True and scored[1]["probability"] is not None and scored[2]["is_primary"] is False
    grace = score([{"arrival_time": (NOW - timedelta(seconds=20)).isoformat()}])
    assert grace[0]["is_missed"] is False and grace[0]["probability"] is not None  # inside the 30 s grace


def test_no_fix_means_no_probability_but_the_train_is_still_listed_as_primary():
    scored = score([train(6)], user=None)
    assert scored[0]["probability"] is None and scored[0]["is_primary"] is True and scored[0]["headway_s"] == 240


def test_a_poor_or_old_fix_is_location_uncertain_as_for_a_schedule_only_bus():
    poor = score([train(8)], accuracy=150.0)[0]["probability"]
    assert poor["data_quality"] == "location uncertain" and poor["location_reason"] == "accuracy"
    old = score([train(8)], location_timestamp=NOW.timestamp() - 120)[0]["probability"]
    assert old["data_quality"] == "location uncertain" and old["location_reason"] == "age"


def test_the_bus_scorer_is_untouched():
    live = ch.score_buses([{"arrival_time": iso(10), "monitored": True}], user_lat=NEAR[0], user_lon=NEAR[1],
                          accuracy_m=10.0, stop_lat=STATION[0], stop_lon=STATION[1], services=[], routes=[],
                          service_no="36", stop_code="1", now=NOW)[0]["probability"]
    assert live["data_quality"] == "live" and live["at_stop"] is False and live["point"] > 60  # the 92 cap, not 60
    asleep = ch.score_buses([{"arrival_time": iso(10), "monitored": False}], user_lat=NEAR[0], user_lon=NEAR[1],
                            accuracy_m=10.0, stop_lat=STATION[0], stop_lon=STATION[1], services=[], routes=[],
                            service_no="36", stop_code="1", now=NOW)[0]["probability"]
    assert asleep["data_quality"] == "schedule" and asleep["point"] <= 60


# ---- the timetable side: next departures, headway fallbacks -------------------------------------------------------


def test_headway_fallback_is_300_s_at_the_weekday_peak_and_420_s_otherwise():
    empty = table()
    assert sh.rail_headway_seconds(empty, "NS17", MSP, NOW.replace(hour=7, minute=30)) == config.RAIL_HEADWAY_PEAK_S == 300
    assert sh.rail_headway_seconds(empty, "NS17", MSP, NOW.replace(hour=11, minute=0)) == config.RAIL_HEADWAY_OFFPEAK_S == 420
    assert sh.rail_headway_seconds(table({"8": 120}), "NS17", MSP, NOW) == 120  # the table's own figure wins


def test_next_departures_are_projected_by_the_headway_from_the_planned_train():
    anchor = datetime.fromisoformat(DEPARTURE)
    coming = ra.next_departures(table({"8": 120}), "NS17", MSP, anchor, NOW)
    assert coming == [anchor, anchor + timedelta(seconds=120), anchor + timedelta(seconds=240)]


def test_after_a_missed_train_the_next_three_start_after_now():
    anchor = NOW - timedelta(minutes=3)
    coming = ra.next_departures(table({"8": 120}), "NS17", MSP, anchor, NOW)
    assert len(coming) == 3 and all(d >= NOW - timedelta(seconds=30) for d in coming) and coming[0] > anchor
    assert [b - a for a, b in zip(coming, coming[1:])] == [timedelta(seconds=120)] * 2


def test_next_departures_stop_at_the_last_train():
    late = datetime(2026, 10, 12, 23, 55, tzinfo=SGT)
    closing = table({"23": 300, "24": 300}, last="2358")  # the last train leaves at 23:58, plus 5 min of grace
    coming = ra.next_departures(closing, "NS17", MSP, late, late)
    assert coming == [late, late + timedelta(minutes=5)] and coming[-1] <= datetime(2026, 10, 13, 0, 3, tzinfo=SGT)
    assert ra.next_departures(closing, "NS17", MSP, datetime(2026, 10, 13, 0, 30, tzinfo=SGT), datetime(2026, 10, 13, 0, 30, tzinfo=SGT)) == []


# ---- rail_payload -------------------------------------------------------------------------------------------------


def payload(**kw):
    args = dict(station_code="NS17", line_code="NS", headsign=MSP, departure_iso=DEPARTURE, user_lat=NEAR[0],
                user_lon=NEAR[1], accuracy=10.0, location_timestamp=None, now=NOW, walk_speed_m_s=1.25)
    args.update(kw)
    return ra.rail_payload(table({"8": 120}), **args)


def test_the_payload_has_the_poll_shape_and_says_it_is_scheduled():
    body = payload()
    assert body["status"] == "ok" and body["stop_code"] == "NS17" and body["service_no"] == "NS"
    assert (body["leg_kind"], body["scheduled"], body["live"]) == ("rail", True, False)
    assert body["line_name"] == "North-South Line" and body["headsign"] == MSP and body["headway_s"] == 120
    first = body["buses"][0]
    assert first["arrival_time"] == DEPARTURE and first["is_primary"] and first["monitored"] is False
    chance = first["probability"]
    assert chance["data_quality"] == "schedule" and chance["at_stop"] is False and chance["point"] <= 60
    assert body["not_live_text"] == "Train times are scheduled, not live."
    assert len(body["next_departures"]) == 3 and body["next_departures"][0] == DEPARTURE


def test_leave_by_is_the_departure_minus_the_walk_minus_135_seconds():
    body = payload()
    distance = ch.straight_line_m(NEAR[0], NEAR[1], *STATION)
    expected = journey.leave_by_time(datetime.fromisoformat(DEPARTURE), distance, 1.25)
    assert datetime.fromisoformat(body["leave_by"]) == expected.replace(microsecond=0) or abs(
        (datetime.fromisoformat(body["leave_by"]) - expected).total_seconds()) < 1
    assert (datetime.fromisoformat(DEPARTURE) - datetime.fromisoformat(body["leave_by"])).total_seconds() == pytest.approx(
        distance / 1.25 + config.LEAVE_MARGIN_SECONDS, abs=1)
    slow = datetime.fromisoformat(payload(walk_speed_m_s=0.8)["leave_by"])
    assert slow < datetime.fromisoformat(body["leave_by"])  # the same walking speed the bus path uses


def test_the_leave_now_notice_is_never_eligible_for_a_train():
    body = payload()
    assert body["leave_now"]["eligible"] is False and body["leave_now"]["title"] is None and body["leave_now"]["body"] is None
    assert body["leave_now"]["reason"] == "train_wording_pending" and body["leave_now"]["range_high"] >= 40
    assert body["notification_time"] is None
    assert body["notifications"] == {"leave_now": False, "five_minutes": False}
    close = payload(departure_iso=iso(4.5))  # the "5 minutes left" moment
    assert close["notifications"]["five_minutes"] is False and close["leave_now"]["eligible"] is False


def test_reroute_is_off_in_the_payload_and_in_reroute_enabled():
    assert payload()["reroute"] == {"enabled": False, "switched": False}
    assert reroute_enabled("direct", 1, "rail") is False and reroute_enabled("one_transfer", 1, "rail") is False
    for kind in (None, "bus"):
        assert reroute_enabled("direct", 1, kind) is True and reroute_enabled("one_transfer", 2, kind) is True
    assert reroute_enabled(None, None) is True


def test_a_missed_train_lists_the_next_three_departures_and_says_the_train_has_left():
    body = payload(departure_iso=iso(-3))
    assert body["buses"][0]["is_missed"] is True and body["buses"][0]["probability"] is None
    assert body["if_you_miss_text"] is None
    assert len(body["next_departures"]) == 3 and datetime.fromisoformat(body["next_departures"][0]) > NOW - timedelta(seconds=30)
    assert body["left_text"] == ("The North-South Line train has left. The next one is at about "
                                 + explain.format_clock(datetime.fromisoformat(body["next_departures"][0]), NOW) + ".")
    primary = next(t for t in body["buses"] if t["is_primary"])
    assert primary["arrival_time"] == body["next_departures"][0] and primary["probability"] is not None


def test_a_train_that_is_coming_says_what_to_do_if_you_miss_it():
    body = payload()
    assert body["left_text"] is None
    assert body["if_you_miss_text"] == "If you miss it, the next train is at about " + explain.format_clock(
        datetime.fromisoformat(body["next_departures"][1]), NOW) + "."


def test_a_bad_departure_is_a_value_error_and_a_missing_table_still_works():
    for bad in ("", "soon", "2026-13-45T99:00"):
        with pytest.raises(ValueError):
            payload(departure_iso=bad)
    body = ra.rail_payload(None, station_code="NS17", line_code="NS", headsign=None, departure_iso=DEPARTURE,
                           user_lat=NEAR[0], user_lon=NEAR[1], accuracy=10.0, location_timestamp=None, now=NOW)
    assert body["line_name"] == "NS" and body["buses"][0]["probability"] is None  # no station point, so no fix to use
    assert body["headway_s"] == 300 and body["leave_by"] is None and body["near_stop"] is False


def test_near_stop_is_the_30_m_rule_but_the_train_is_still_not_at_stop():
    body = payload(user_lat=STATION[0] + 0.0001, user_lon=STATION[1])  # about 11 m
    assert body["near_stop"] is True
    assert body["buses"][0]["probability"]["at_stop"] is False and body["buses"][0]["probability"]["point"] <= 60


def test_the_journey_for_a_train_first_leg_uses_the_shared_leave_by_function():
    cache = StopAndRouteCache([{"BusStopCode": "DEST", "Description": "Dest", "Latitude": 1.30, "Longitude": 103.83,
                                "RoadName": "x"}], [], [])
    built = ra.rail_journey(
        table({"8": 120}), cache, station_code="NS17", line_code="NS", headsign=MSP, departure_iso=DEPARTURE,
        user_lat=NEAR[0], user_lon=NEAR[1], dest_lat=1.3005, dest_lon=103.83, destination_stop_code="DEST",
        arrive_by=None, ride_minutes=12.0, arrival_status="ok", now=NOW)
    distance = ch.straight_line_m(NEAR[0], NEAR[1], *STATION)
    expected = journey.leave_by_time(datetime.fromisoformat(DEPARTURE), distance, 1.25)
    assert abs((datetime.fromisoformat(built["leave_by"]) - expected).total_seconds()) < 1
    assert built["leg_kind"] == "rail" and built["connecting_services"] == ["NS"] and built["ride_minutes"] > 12
    assert built["ride_label"].startswith("Ride time: ~") and built["arrival_point"]
    unknown = ra.rail_journey(
        table(), cache, station_code="NS17", line_code="NS", headsign=MSP, departure_iso=None, user_lat=NEAR[0],
        user_lon=NEAR[1], dest_lat=1.3005, dest_lon=103.83, destination_stop_code="DEST", arrive_by=None,
        ride_minutes=None, arrival_status="ok", now=NOW)
    assert unknown["ride_minutes"] is None and unknown["leave_by"] is None
    stale = ra.rail_journey(
        table(), cache, station_code="NS17", line_code="NS", headsign=MSP, departure_iso=DEPARTURE, user_lat=NEAR[0],
        user_lon=NEAR[1], dest_lat=1.3005, dest_lon=103.83, destination_stop_code="DEST", arrive_by=None,
        ride_minutes=12, arrival_status="stale", now=NOW)
    assert stale["leave_by"] is None  # the same rule as the bus path: a stale ETA has no clock


# ---- the card text -----------------------------------------------------------------------------------------------


def numbers(e=4, leave_in=600, action="wait", line="North-South Line", walk=3):
    leave_by = (NOW + timedelta(seconds=leave_in)).isoformat()
    return explain.build_numbers(
        bus_minutes=e, walk_minutes=walk, chosen_action=action, distance_m=300.0, walk_speed_used=1.25,
        walk_speed_source="gps", leave_by=leave_by, arrival_time=(NOW + timedelta(minutes=e)).isoformat(), now=NOW,
        train_line=line)


NB = " "
LINE = "North-South Line"


@pytest.mark.parametrize("e, leave_in, expected", [
    (4, 120, f"The {LINE} train is scheduled in 4{NB}min. Live train times are not available. "
             f"Leave by 8:22{NB}AM so you have 2 minutes to reach your station and catch the train departing at 8:24{NB}AM."),
    (1, 61, f"The {LINE} train is scheduled in 1{NB}min. Live train times are not available. "
            f"Leave by 8:21{NB}AM so you have 1 minute to reach your station and catch the train departing at 8:21{NB}AM."),
    (0, 0, f"The {LINE} train is scheduled to leave now. Live train times are not available. "
           f"Leave now to try to catch the train departing at 8:20{NB}AM."),
])
def test_the_train_card_is_the_train_sentence_then_the_train_leave_sentence(e, leave_in, expected):
    text = explain.card_text(numbers(e=e, leave_in=leave_in), band="ok", uncertain=False)
    assert text == expected


def test_the_train_card_with_leave_now_and_with_an_uncertain_location():
    now_text = explain.card_text(numbers(e=4, leave_in=30, action="leave_now"), band="ok", uncertain=True)
    assert now_text == (f"The {LINE} train is scheduled in 4{NB}min. Live train times are not available. "
                        f"Leave now so you have 4 minutes to reach your station and catch the train departing at 8:24{NB}AM. "
                        "Your location is uncertain, so the walking time may be off.")
    by_text = explain.card_text(numbers(e=4, leave_in=120), band="ok", uncertain=True)
    assert by_text.endswith("Your location is uncertain, so leave a little earlier than that to be safe.")
    arriving = explain.card_text(numbers(e=0, leave_in=0, action="leave_now"), band="mid", uncertain=False)
    assert arriving == (f"The {LINE} train is scheduled to leave now. Live train times are not available. "
                        f"Leave now to try to catch the train departing at 8:20{NB}AM.")
    arriving_uncertain = explain.card_text(numbers(e=0, leave_in=0, action="leave_now"), band="mid", uncertain=True)
    assert arriving_uncertain.endswith(f"departing at 8:20{NB}AM. Your location is uncertain, so the walking time may be off.")


def test_an_unlikely_train_names_the_distance_to_the_station_and_is_one_sentence():
    for action, band in (("do_not_rely", "ok"), ("wait", "low"), ("switch_route", "mid")):
        text = explain.card_text(numbers(action=action), band=band, uncertain=True)  # the uncertain add-on is not used
        assert text == (f"The {LINE} train is scheduled in 4{NB}min, and you are 300{NB}m from the station, "
                        "but catching this train is unlikely.")
    leaving = explain.card_text(numbers(e=0, action="do_not_rely"), band="ok", uncertain=False)
    assert leaving == (f"The {LINE} train is scheduled to leave now, and you are 300{NB}m from the station, "
                       "but catching this train is unlikely.")
    far = explain.card_text(numbers(e=7, action="wait"), band="low", uncertain=False)
    assert "7" + NB + "min" in far


def test_no_train_card_says_bus_or_stop_and_no_bus_card_says_train():
    train_cards, bus_cards = set(), set()
    for e in (0, 1, 2, 10, 59):
        for leave_in in (-600, 0, 30, 60, 61, 120, 600, 36000):
            for action in explain.ACTIONS:
                for band in ("ok", "mid", "low", None):
                    for uncertain in (False, True):
                        n = numbers(e=e, leave_in=leave_in, action=action)
                        train_cards.add(explain.card_text(n, band=band, uncertain=uncertain))
                        b = numbers(e=e, leave_in=leave_in, action=action, line=None)
                        bus_cards.add(explain.card_text(b, band=band, uncertain=uncertain))
    assert len(train_cards) > 30 and len(bus_cards) > 30
    for text in train_cards:
        assert not re.search(r"\b(bus|buses|stop|stops)\b", text, re.IGNORECASE), text
        assert "train" in text
    for text in bus_cards:
        assert not re.search(r"train", text, re.IGNORECASE), text
    for text in (explain.TRAIN_MISS, explain.TRAIN_LEFT, explain.TRAIN_NEXT, explain.TRAIN_ABOUT, explain.TRAIN_NOT_LIVE):
        assert not re.search(r"\b(bus|stop)\b", text, re.IGNORECASE), text


def test_projected_departures_are_listed_with_about():
    assert explain.TRAIN_ABOUT == "about {time}" and explain.TRAIN_NEXT == "Next trains: {list}."
    assert explain.TRAIN_MISS == "If you miss it, the next train is at about {time}."
    assert explain.TRAIN_LEFT == "The {line} train has left. The next one is at about {time}."
    body = payload()
    first = [datetime.fromisoformat(d) for d in body["next_departures"]]
    expected = "Next trains: " + ", ".join("about " + explain.format_clock(d, NOW) for d in first) + "."
    assert body["next_departures_text"] == expected and expected.count("about") == 3
    assert body["if_you_miss_text"] == "If you miss it, the next train is at about " + explain.format_clock(first[1], NOW) + "."
    closed = payload(departure_iso=iso(-3))
    assert closed["left_text"].endswith("The next one is at about " + explain.format_clock(
        datetime.fromisoformat(closed["next_departures"][0]), NOW) + ".")
    assert ra.next_departures_text([], NOW) is None


def test_the_bus_card_is_word_for_word_what_it_was():
    bus = explain.build_numbers(
        bus_minutes=10, walk_minutes=4, chosen_action="wait", distance_m=300.0, walk_speed_used=1.25,
        walk_speed_source="gps", leave_by=(NOW + timedelta(seconds=600)).isoformat(),
        arrival_time=(NOW + timedelta(seconds=1200)).isoformat(), now=NOW)
    assert bus["train_line"] is None
    assert explain.card_text(bus, band="ok", uncertain=False) == (
        "The bus is 10 minutes away, and you are 300 m from the stop and walking at about 4.5 km/h. "
        "Leave by 8:30 AM so you have 10 minutes to reach your stop and catch the bus arriving at 8:40 AM.")
    empty = explain.build_numbers(
        bus_minutes=4, walk_minutes=4, chosen_action="wait", distance_m=300.0, walk_speed_used=1.25,
        walk_speed_source="gps", leave_by=iso(10), arrival_time=iso(4), now=NOW, train_line="  ")
    assert empty["train_line"] is None  # a blank line name is not a train


def test_the_train_strings_match_copy_js_and_the_page_mirror():
    escape = chr(92) + "u00a0"  # how copy.js and the page spell the no-break space in source
    in_both = {  # copy.js key: (Python constant, the page's variable)
        "explTrain": (explain.S_TRAIN, "EXPL_TRAIN"),
        "explTrainNow": (explain.S_TRAIN_NOW, "EXPL_TRAIN_NOW"),
        "explTrainUnlikely": (explain.S_TRAIN_UNLIKELY, "EXPL_TRAIN_UNLIKELY"),
        "explTrainNowUnlikely": (explain.S_TRAIN_NOW_UNLIKELY, "EXPL_TRAIN_NOW_UNLIKELY"),
        "leaveByTrain": (explain.S2_TRAIN_LEAVE_BY, "EXPL_TRAIN_LEAVE_BY"),
        "leaveNowTrain": (explain.S2_TRAIN_LEAVE_NOW, "EXPL_TRAIN_LEAVE_NOW"),
        "leaveNowDepartingTrain": (explain.S2_TRAIN_LEAVE_NOW_DEPARTING, "EXPL_TRAIN_LEAVE_NOW_DEPARTING"),
    }
    copy_only = {"trainNotLive": explain.TRAIN_NOT_LIVE, "trainAbout": explain.TRAIN_ABOUT,
                 "trainNext": explain.TRAIN_NEXT, "trainMiss": explain.TRAIN_MISS, "trainLeft": explain.TRAIN_LEFT}
    block = COPY.split("train: {", 1)[1].split(chr(10) + "  },", 1)[0]
    for key, (value, variable) in in_both.items():
        source = value.replace(chr(0xA0), escape)
        assert f'{key}: "{source}"' in block, key
        assert f'var {variable} = "{source}";' in INDEX, variable
    for key, value in copy_only.items():
        assert f'{key}: "{value}"' in block, key
    assert "{e}" + escape + "min" in block and "{e} min" not in block  # the number never splits from "min"
    assert "pack.train_line" in INDEX and "train_line" in explain.PAGE_PACK_FIELDS and "train_line" in explain.PACK_KEYS
    assert COPY.count("train: {") == 1



def test_the_pack_for_a_train_carries_the_line_and_never_asks_the_model():
    body = payload()
    pack = explain.build_poll_explanation(
        body, now=NOW, cache=None, user_lat=NEAR[0], user_lon=NEAR[1], stop_code="NS17", explained_action=None,
        explained_advice=None, in_flight=False, reroute_fired=False, station_point=STATION, train_line=body["line_name"])
    assert pack["train_line"] == "North-South Line" and pack["at_stop"] is False
    assert pack["text"].startswith("The North-South Line train is scheduled in ")
    assert pack["call"] is False and pack["pending"] is False
    assert set(pack) == set(explain.PACK_KEYS)
    bus = {"service_no": "36", "leave_by": iso(10), "buses": [{
        "arrival_time": iso(4), "is_primary": True, "is_missed": False, "monitored": True,
        "probability": {"point": 70, "range_low": 50, "range_high": 80, "data_quality": "live", "band": "ok"}}]}

    class Cache:
        def stop_by_code(self, code):
            return {"Latitude": STATION[0], "Longitude": STATION[1]}

    plain = explain.build_poll_explanation(bus, now=NOW, cache=Cache(), user_lat=NEAR[0], user_lon=NEAR[1],
                                           stop_code="1", explained_action=None, explained_advice=None,
                                           in_flight=False, reroute_fired=False)
    assert plain["train_line"] is None and plain["text"].startswith("The bus is 4 minutes away")


# ---- the endpoints ------------------------------------------------------------------------------------------------


@pytest.fixture
def api(monkeypatch):
    class FixedClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW if tz is None else NOW.astimezone(tz)

    def forbidden(*args, **kwargs):
        raise AssertionError("a train first leg must not reach LTA, OneMap or any network")

    cache = StopAndRouteCache([{"BusStopCode": "99999", "Description": "Dest", "Latitude": 1.30, "Longitude": 103.83,
                                "RoadName": "x"}], [], [])
    monkeypatch.setattr(main, "datetime", FixedClock)
    monkeypatch.setattr(main, "load_static_data", lambda: cache)
    monkeypatch.setattr(main, "startup_warning", lambda today: None)
    monkeypatch.setattr(main, "load_rail_table", lambda: table({"8": 120}))
    with TestClient(main.app) as client:
        monkeypatch.setattr(httpx, "Client", forbidden)  # after the test client exists: any new client is a failure
        monkeypatch.setattr(main, "fetch_arrivals", forbidden)
        monkeypatch.setattr(main, "fetch_stop_arrivals", forbidden)
        monkeypatch.setattr(main, "plan_reroute", forbidden)
        monkeypatch.setattr(main, "rescore_latest", forbidden)
        yield client


RAIL = {"stop_code": "NS17", "service_no": "NS", "leg_kind": "rail", "train_departure": DEPARTURE, "headsign": MSP,
        "lat": NEAR[0], "lon": NEAR[1], "accuracy": 10}


def test_arrivals_for_a_train_makes_no_lta_call_and_is_schedule_quality(api):
    response = api.get("/api/arrivals", params=RAIL)
    assert response.status_code == 200
    body = response.json()
    chance = body["buses"][0]["probability"]
    assert body["leg_kind"] == "rail" and body["scheduled"] is True and body["live"] is False
    assert chance["data_quality"] == "schedule" and chance["at_stop"] is False and chance["point"] <= 60
    assert chance["range_high"] <= 60 and body["near_stop"] is False
    assert body["walk_speed_used"] == 1.25 and body["leave_now_threshold_s"] == 60
    assert body["chosen_action"] in ("wait", "leave_now", "do_not_rely")
    assert body["arrival_estimate"] is None and body["if_you_miss"] is None
    assert body["leave_now"]["eligible"] is False and body["notifications"]["five_minutes"] is False


def test_arrivals_for_a_train_never_runs_the_reroute_search_even_with_a_destination(api):
    params = {**RAIL, "destination_stop_code": "99999", "dest_lat": 1.30, "dest_lon": 103.83,
              "route_type": "direct", "leg_index": 1}
    body = api.get("/api/arrivals", params=params).json()
    assert body["reroute"] == {"enabled": False, "switched": False}  # plan_reroute is a forbidden call in this fixture


def test_arrivals_for_a_train_carries_the_explanation_when_asked(api):
    body = api.get("/api/arrivals", params={**RAIL, "explanation_rendered": 0}).json()
    pack = body["explanation"]
    assert pack["train_line"] == "North-South Line" and pack["at_stop"] is False
    assert pack["text"].startswith("The North-South Line train is scheduled in 11" + chr(160) + "min. Live train times")
    assert pack["call"] is False and body["chosen_action"] == pack["action"]


def test_a_missed_train_through_arrivals_lists_the_next_three(api):
    late = (NOW - timedelta(minutes=4)).isoformat()
    body = api.get("/api/arrivals", params={**RAIL, "train_departure": late}).json()
    assert body["buses"][0]["is_missed"] is True and len(body["next_departures"]) == 3
    assert body["left_text"].startswith("The North-South Line train has left. The next one is at about ")


@pytest.mark.parametrize("bad", ["", "tomorrow", "2026-99-99T00:00"])
def test_a_bad_departure_is_refused_with_a_fixed_sentence_and_without_echo(api, bad):
    response = api.get("/api/arrivals", params={**RAIL, "train_departure": bad or " "})
    assert response.status_code == 422 and response.json() == {"detail": "train_departure must be an ISO timestamp for a train."}
    if len(bad) > 3:
        assert bad not in response.text
    assert api.get("/api/arrivals", params={k: v for k, v in RAIL.items() if k != "train_departure"}).status_code == 422


def test_an_unknown_leg_kind_is_refused_by_every_endpoint(api):
    for path, extra in (("/api/arrivals", {}), ("/api/rescore", {}), ("/api/journey", {})):
        params = {**RAIL, "leg_kind": "ferry"}
        if path == "/api/journey":
            params = {"dest_lat": 1.3, "dest_lon": 103.8, "user_lat": 1.3, "user_lon": 103.8, "destination_stop_code": "x",
                      "leg_kind": "ferry"}
        response = api.get(path, params=params)
        assert response.status_code == 422 and response.json() == {"detail": "leg_kind must be bus or rail."}, path


def test_rescore_for_a_train_needs_no_remembered_arrivals_and_never_says_at_stop(api):
    response = api.get("/api/rescore", params=RAIL)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["rescored"] is True and body["leg_kind"] == "rail"
    chance = body["buses"][0]["probability"]
    assert chance["data_quality"] == "schedule" and chance["at_stop"] is False and chance["point"] <= 60
    assert set(body["buses"][0]) == set(main.RESCORE_BUS_FIELDS)
    assert body["leave_by"] and body["near_stop"] is False and body["chosen_action"] in ("wait", "leave_now", "do_not_rely")
    on_the_stop = api.get("/api/rescore", params={**RAIL, "lat": STATION[0], "lon": STATION[1]}).json()
    assert on_the_stop["near_stop"] is True and on_the_stop["buses"][0]["probability"]["at_stop"] is False
    assert on_the_stop["buses"][0]["probability"]["data_quality"] == "schedule"


def test_rescore_for_a_train_after_a_miss_lists_the_next_departures(api):
    body = api.get("/api/rescore", params={**RAIL, "train_departure": (NOW - timedelta(minutes=5)).isoformat()}).json()
    assert body["buses"][0]["is_missed"] is True and len(body["next_departures"]) == 3 and body["left_text"]


def test_rescore_for_a_train_carries_the_explanation_and_the_bus_path_still_says_use_poll(api):
    body = api.get("/api/rescore", params={**RAIL, "explanation_rendered": 0}).json()
    assert body["explanation"]["train_line"] == "North-South Line"
    with pytest.raises(AssertionError):  # the bus path reaches rescore_latest, which this fixture forbids
        api.get("/api/rescore", params={"stop_code": "1", "service_no": "36", "lat": 1.3, "lon": 103.8, "accuracy": 10})


def test_reroute_options_for_a_train_is_off_and_lists_the_next_departures(api):
    params = {"stop_code": "NS17", "service_no": "NS", "lat": NEAR[0], "lon": NEAR[1], "accuracy": 10,
              "destination_stop_code": "99999", "dest_lat": 1.30, "dest_lon": 103.83, "leg_kind": "rail",
              "train_departure": DEPARTURE, "headsign": MSP}
    body = api.get("/api/reroute-options", params=params).json()
    assert body["reroute_enabled"] is False and body["options"] == [] and len(body["next_departures"]) == 3
    assert api.get("/api/reroute-options", params={**params, "train_departure": "later"}).status_code == 422


def test_journey_for_a_train_uses_the_shared_leave_by(api):
    params = {"dest_lat": 1.3005, "dest_lon": 103.83, "user_lat": NEAR[0], "user_lon": NEAR[1],
              "destination_stop_code": "99999", "boarding_stop_code": "NS17", "service_no": "NS",
              "leg_kind": "rail", "eta": DEPARTURE, "leg1_ride_minutes": 12, "headsign": MSP}
    body = api.get("/api/journey", params=params).json()
    distance = ch.straight_line_m(NEAR[0], NEAR[1], *STATION)
    expected = journey.leave_by_time(datetime.fromisoformat(DEPARTURE), distance, 1.25)
    assert body["leg_kind"] == "rail" and abs((datetime.fromisoformat(body["leave_by"]) - expected).total_seconds()) < 1
    assert body["connecting_services"] == ["NS"] and body["walk_speed_used"] == 1.25
    assert api.get("/api/journey", params={k: v for k, v in params.items() if k != "service_no"}).status_code == 422


def test_a_bus_first_leg_is_unchanged_by_the_new_parameters(api):
    # with no leg_kind the endpoint reaches the bus code, which here is the forbidden fetch_arrivals
    with pytest.raises(AssertionError):
        api.get("/api/arrivals", params={"stop_code": "1", "service_no": "36"})
    with pytest.raises(AssertionError):
        api.get("/api/arrivals", params={"stop_code": "1", "service_no": "36", "leg_kind": "bus"})


def test_the_plan_describes_the_train_first_leg():
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    for text in ("score_scheduled_rail", "leg_kind=rail", "train_line", "next_departures", "`5 minutes left` reminder",
                 "reroute_enabled(..., leg_kind)", "copy.train"):
        assert text in plan, text
