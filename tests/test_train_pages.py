"""The live pages for a train first leg (plan_edits_9 4.6, 4.8): Pages W, A and B, the missed train, Yes, and the rules
that a train never makes a bus call, a reroute or a notification. Bus-first words are checked unchanged.

The browser tests drive the real page in headless Edge against the real app, a stubbed OneMap and a rail table
(tests/onemap_stub.py). The LTA stub answers 500 for the train runs, so a BusArrival call would show as a failure."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import north, require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
NB = chr(0xA0)
ESC = chr(92) + "u00a0"
MSP = "Marina South Pier"


# ---- words: copy.js and the page say the same ---------------------------------------------------------------------


def _pairs(block: str) -> dict:
    return dict(re.findall(r'^\s*(\w+): "((?:[^"\\]|\\.)*)",?$', block, flags=re.M))


COPY_PAGE = _pairs(COPY.split("trainPage: {", 1)[1].split("\n  },", 1)[0])
PAGE_PAGE = _pairs(INDEX.split("var TRAIN_PAGE = {", 1)[1].split("\n    };", 1)[0])


def test_the_page_words_are_copy_js_character_for_character():
    assert COPY_PAGE == PAGE_PAGE and len(COPY_PAGE) >= 20


def test_the_spec_words_are_exact():
    expected = {
        "walkTitle": "Walk to your station", "walkArrived": "Arrived at the station", "departsLabel": "Train departs",
        "seeTimes": "See train times", "question": "Did you catch the train?", "scheduled": "Scheduled",
        "every": "Every about {n} min", "notLive": "Train times are scheduled, not live.", "nextTrains": "Next trains",
    }
    for key, value in expected.items():
        assert COPY_PAGE[key] == value, key


def test_the_words_that_the_server_also_sends_match_copy_train():
    train = COPY.split("train: {", 1)[1].split("\n  },", 1)[0]
    server = dict(re.findall(r'^\s*(\w+): "((?:[^"\\]|\\.)*)",?$', train, flags=re.M))
    assert PAGE_PAGE["about"] == server["trainAbout"] and PAGE_PAGE["left"] == server["trainLeft"]
    assert PAGE_PAGE["notLive"] == server["trainNotLive"]


def test_a_number_never_splits_from_min_in_the_new_words():
    for key in ("tileAway", "tileDeparting"):
        assert "}" + ESC + "min" in PAGE_PAGE[key] or key == "tileDeparting" and "{w}" + ESC + "min" in PAGE_PAGE[key], key
    assert "{e}" + ESC + "min" in PAGE_PAGE["tileAway"] and "{w}" + ESC + "min" in PAGE_PAGE["tileAway"]


def test_the_temporary_note_is_gone_everywhere():
    for text in ("overview-train-note", "JO_TRAIN_LIVE_SOON", "syncStartAvailability"):
        assert text not in INDEX, text
    assert "trainLiveSoon" not in COPY and "trainLiveSoon" not in GUIDE
    assert "Live guidance for a train start is not ready yet" not in PLAN


def test_the_bus_words_are_still_in_the_markup():
    for text in ('Walk to your stop</h2>', 'id="next-buses-label">Next 3 buses', 'Did you catch the bus?</p>',
                 "<span>See bus arrival times</span>", 'Estimated destination arrival</p>', 'Bus arrives</span>'):
        assert text in INDEX, text


def test_the_new_code_uses_no_colour_and_no_inline_style():
    region = INDEX.split("// ---- A train as the first leg (plan_edits_9 4.6", 1)[1].split("function legIsRail(leg)", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", region) and ".style." not in region
    css = CSS.split("/* A train as the first leg: the missed-train card", 1)[1].split(".overview-state__actions {", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", css) and "style=" not in css


def test_a_train_never_reaches_the_bus_or_reroute_code():
    for guard in ("function maybeFiveMinuteReminder(body) {\n      if (isTrain() ||",
                  "function syncLeaveNow(body) {\n      if (isTrain()) {",
                  "!!selectedService && !isTrain();",
                  "isUnlikely(hero) && !displayFrozen && !isTrain()",
                  "if (!isTrain() && activeRoutePlan && activeRoutePlan.route_type === \"one_transfer\" && activeRoutePlan.leg_index)"):
        assert guard in INDEX, guard
    assert "trainQuery()" in INDEX.split("function walkRescoreTick(", 1)[1].split("function applyRescore", 1)[0]
    assert "trainQuery()" in INDEX.split("function requestArrivals(", 1)[1].split("function applySuccess", 1)[0]
    assert "trainJourneyQuery()" in INDEX.split("function loadJourney()", 1)[1].split("function renderJourney", 1)[0]


def test_the_plan_describes_the_train_pages_and_the_map():
    for text in ("**A train as the first leg.**", "Walk to your station", "Did you catch the train?", "See train times",
                 "Train times are scheduled, not live.", "`--map-line-<code>`", "plain rows"):
        assert text in PLAN, text


def test_the_style_guide_shows_the_train_pages_in_both_themes():
    section = GUIDE.split('id="legs-heading"', 1)[1].split("</section>", 1)[0]
    assert "trainPagesSample" in GUIDE and "trainPagesSample" in GUIDE.split("function legsSample()", 1)[1]
    assert "legs-sample-light" in section and "legs-sample-dark" in section
    assert "train-rows" in GUIDE.split("function trainPagesSample()", 1)[1]


# ---- the page in a browser ----------------------------------------------------------------------------------------


def _table() -> dict:
    day = lambda first, final: {"first": first, "last": final, "headway_s": {str(h): 240 for h in range(24)}}  # noqa: E731
    lat, lon = north(80)
    hours = lambda: {"WD": day("0000", "2759"), "SAT": day("0000", "2759"), "SUN": day("0000", "2759")}  # noqa: E731
    return {
        "schema": 1,
        "stations": {"NS17": {"name": "Bishan", "latitude": lat, "longitude": lon, "directions": {
            MSP: {"line": "NS", "direction_id": 1, "trips": 100, **hours()}}}},
        "lines": {"NS": {"name": "North-South Line", "mode": "SUBWAY", "color": "D62821", "text_color": "FFFFFF"},
                  "EW": {"name": "East-West Line", "mode": "SUBWAY", "color": "189E4A", "text_color": "000000"}},
        "patterns": {"NS": {MSP: ["NS17", "NS22", "NS26"]}, "EW": {"Tuas Link": ["EW14", "EW15"]}},
    }


def _run(tmp_path_factory, name, builder, lta_status=200, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode({"TRANSIT": builder}), rail_table=_table(),
                     lta_status=lta_status) as base:
        return run_scenario("trainpages", base, {"name": name, **config}, timeout=300)["result"]


@pytest.fixture(scope="module")
def missed_light(tmp_path_factory):
    return _run(tmp_path_factory, "missedlight", stub.train_first, lta_status=500, width=390, height=844, answer="no")


@pytest.fixture(scope="module")
def yes_dark(tmp_path_factory):
    return _run(tmp_path_factory, "yesdark", stub.train_transfer, lta_status=500, width=360, height=800, dark=True,
                answer="yes")


@pytest.fixture(scope="module")
def wide_dark(tmp_path_factory):
    return _run(tmp_path_factory, "widedark", stub.train_first, lta_status=500, width=1280, height=900, dark=True)


@pytest.fixture(scope="module")
def bus_first(tmp_path_factory):
    return _run(tmp_path_factory, "busfirst", stub.bus_only, width=390, height=844, bus=True)


def _clock(text: str) -> str:
    return re.sub(r"\d{1,2}:\d{2}" + NB + "[AP]M", "TIME", text)


def test_start_journey_is_on_for_a_train_first_route(missed_light):
    assert missed_light["startDisabled"] is False and missed_light["overviewRows"] >= 5


def test_the_page_asks_for_a_train_and_makes_no_bus_reroute_or_options_request(missed_light, yes_dark):
    for run in (missed_light, yes_dark):
        urls = run["requests"]
        assert urls and all(("leg_kind=rail" in u) for u in urls if re.match(r"/api/(arrivals|rescore|journey)\?", u))
        for kind in ("arrivals", "rescore", "journey"):
            assert any(u.startswith(f"/api/{kind}?") for u in urls), kind
        for u in urls:
            if u.startswith(("/api/arrivals?", "/api/rescore?")):
                assert "stop_code=NS17" in u and "service_no=NS" in u and "train_departure=" in u
                assert "headsign=Marina%20South%20Pier" in u
            assert "route_type=" not in u and "leg2_" not in u
        journey = next(u for u in urls if u.startswith("/api/journey?"))
        assert "eta=" in journey and "leg1_ride_minutes=" in journey and "boarding_stop_code=NS17" in journey
        assert not any(u.startswith("/api/reroute") for u in run["allRequests"])


def test_page_a_for_a_train(missed_light):
    a = missed_light["pageA"]
    assert a["isTrain"] is True and a["service"] == "NS" and a["top"] == "live"
    assert a["title"] == "Chance to catch the North-South Line train"
    assert a["pill"] == "schedule only" and a["notLive"] == "Train times are scheduled, not live."
    assert a["hero"]["monitored"] is False and a["hero"]["quality"] == "schedule" and a["hero"]["atStop"] is False
    assert a["hero"]["point"] <= 60 and a["hero"]["high"] <= 60  # the schedule cap
    assert a["ring"] == f"{a['hero']['point']}%"
    assert re.match(r"Departs in \d+ min · ", a["sub"].replace(NB, " "))
    assert a["tileLeaveLabel"] == "Leave by" and a["tileDepartsLabel"] == "Train departs" and a["tileRange"] is False
    assert re.fullmatch(r"\d{1,2}:\d{2}" + NB + "[AP]M", a["tileDeparts"])
    assert a["arrivesLabel"].startswith("Train departs")
    assert a["bar"] == "See train times" and a["catchBar"] is False
    assert a["miss"].startswith("If you miss it, the next train is at about ") and a["missLabelShown"] is False
    assert "The North-South Line train is scheduled in " in a["ai"] and "Live train times are not available." in a["ai"]
    assert "Leave by" in a["ai"] and "catch the train departing at" in a["ai"] and "bus" not in a["ai"].lower()
    assert not a["unlikelyBanner"] and not a["catchWarning"] and not a["pageC"]
    assert a["scrollWidth"] <= a["innerWidth"]
    body = a["body"]
    assert body["leg_kind"] == "rail" and body["headsign"] == MSP and len(body["next"]) == 3
    assert body["leaveNow"]["eligible"] is False and body["notifications"] == {"leave_now": False, "five_minutes": False}
    assert body["reroute"] == {"enabled": False, "switched": False}


def test_page_w_for_a_train_and_arrived_reads_station(missed_light):
    w, arrived = missed_light["pageW"], missed_light["pageWArrived"]
    assert w["pageW"] is True and w["title"] == "Walk to your station"
    assert w["distance"].endswith(NB + "m to the station") and w["heading"] == "Chance to catch the North-South Line train"
    assert w["arrives"].startswith("Train departs") and w["barText"] == "See train times"
    assert w["marker"] and w["marker"]["label"].startswith("Bishan MRT Station") and "NS17" in w["marker"]["label"]
    assert w["state"] != "Arrived at the stop"
    assert arrived["state"] == "Arrived at the station"


def test_page_b_for_a_train(missed_light):
    b = missed_light["pageB"]
    assert b["pageB"] is True and b["card"] is True
    assert b["badge"]["text"] == "NS" and "line-badge--ns" in b["badge"]["cls"] and b["title"].endswith("North-South Line")
    assert b["to"] == "Toward Marina South Pier" and re.fullmatch(r"Departs \d{1,2}:\d{2}" + NB + "[AP]M", b["then"])
    assert b["pill"] == "schedule only" and b["label"] == "Next trains"
    assert len(b["next"]) == 3 and all(re.match(r"about \d{1,2}:\d{2}" + NB + "[AP]M", row) for row in b["next"])
    assert b["cells"]["live"] == "Scheduled" and b["cells"]["monitored"] == "Every about 4 min"
    assert b["question"] == "Did you catch the train?" and b["seeBar"] is False and b["yes"] and b["no"]
    assert b["scrollWidth"] <= b["innerWidth"]


def test_a_train_never_makes_a_leave_now_or_five_minute_notification(missed_light, yes_dark):
    for run in (missed_light, yes_dark):
        assert run["notes"] == {"notes": [], "banner": False} and run["notesAfter"] == []


def test_the_missed_train_shows_the_left_text_the_next_three_rows_and_plan_a_new_journey(missed_light):
    m = missed_light["missed"]
    assert m["top"] == "live" and m["missedShown"] is True
    assert re.fullmatch(r"The North-South Line train has left\. The next one is at about \d{1,2}:\d{2}" + NB + r"[AP]M\.", m["left"])
    assert m["left"] == missed_light["leftText"]
    assert m["heading"] == "Next trains" and len(m["rows"]) == 3
    assert all(re.fullmatch(r"about \d{1,2}:\d{2}" + NB + "[AP]M", row) for row in m["rows"])
    assert m["rows"][0] in m["left"]
    assert m["buttons"] == ["Plan a new journey"] and m["switchButtons"] == 0 and m["planNew"] is True
    assert m["pageCShown"] is False and m["requests"] == 0  # no options search, nothing to switch to
    assert not m["catchBar"] and not m["seeBar"] and not m["arrivalCard"] and not m["tiles"] and m["monitoring"] is False
    assert m["scrollWidth"] <= m["innerWidth"]
    assert missed_light["afterPlanNew"] == {"top": "home", "monitoring": False, "shown": False}


def test_yes_shows_the_on_your_way_overview_with_the_remaining_legs_and_schedule_lines(yes_dark):
    way = yes_dark["onWay"]
    assert way["top"] == "onway" and way["shown"] is True and way["monitoring"] is False
    rows = way["rows"]
    kinds = [re.search(r"journey-step--(\w+)", row["cls"]).group(1) for row in rows]
    assert kinds == ["rail", "walk", "rail", "walk", "destination"], kinds
    first = rows[0]
    assert first["badge"] == "NS" and "On board" in first["text"] and "To Marina South Pier" in first["text"]
    assert "to Raffles Place MRT Station (EW14)" in rows[1]["text"] and "Change" not in rows[1]["text"]  # a walk row
    assert rows[2]["badge"] == "EW" and re.search(r"Scheduled · \d{1,2}:\d{2}", rows[2]["text"].replace(NB, " "))
    assert "Edit" not in rows[3]["text"] and way["scrollWidth"] <= way["innerWidth"]


def test_a_train_page_has_no_page_overflow_at_360_and_1280_in_dark(yes_dark, wide_dark):
    assert yes_dark["pageA"]["scrollWidth"] <= 360 and wide_dark["pageA"]["scrollWidth"] <= 1280
    assert wide_dark["pageB"]["scrollWidth"] <= 1280 and wide_dark["pageW"]["scrollWidth"] <= 1280
    for run in (yes_dark, wide_dark):
        assert run["pageA"]["title"] == "Chance to catch the North-South Line train"
        assert run["pageB"]["badge"]["bg"] == "rgb(214, 40, 33)" and run["pageB"]["badge"]["color"] == "rgb(255, 255, 255)"


def test_a_bus_first_journey_keeps_every_bus_word_and_request(bus_first):
    a, b, w = bus_first["pageA"], bus_first["pageB"], bus_first["pageW"]
    assert a["isTrain"] is False and a["title"] == "Chance to catch Bus 18"
    assert a["pill"] in ("live", "schedule only") and a["notLive"] is None
    assert a["tileDepartsLabel"] == "Estimated destination arrival" and a["tileLeaveLabel"] == "Leave by"
    assert a["arrivesLabel"].startswith("Bus arrives") and a["bar"] == "See bus arrival times"
    assert w["title"] == "Walk to your stop" and w["distance"].endswith(NB + "m to the stop")
    assert "Bus 18" in b["title"] and b["badge"] is None and b["label"] in (None, "Next 3 buses")
    assert b["question"] == "Did you catch the bus?" and b["to"].startswith("To ")
    assert b["cells"]["live"] in ("Live bus location available", "Live bus location unavailable")
    assert all("leg_kind" not in u and "train_departure" not in u for u in bus_first["allRequests"])
    assert any(u.startswith("/api/arrivals?stop_code=") for u in bus_first["allRequests"])
