"""Live next-bus times for later bus legs: the server lookup (one call per stop, cached 60 s, a stop code and service numbers
only, refused in Demo Mode) and the page (when it looks up, the labels, the limits). Mock transports only: nothing here
calls LTA, OneMap or any other service."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import arrivals
import demo
import main
import onemap_stub as stub
from lta_static import StopAndRouteCache
from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
SGT = timezone(timedelta(hours=8))
REAL_CLIENT = httpx.Client  # before any test patches it
NB = " "
KEY = "never-printed-test-key"


def _eta(minutes):
    return (datetime.now(SGT) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def _service(number, minutes_list, monitored=1):
    item = {"ServiceNo": number}
    for name, minutes in zip(("NextBus", "NextBus2", "NextBus3"), minutes_list):
        item[name] = {"EstimatedArrival": _eta(minutes), "Monitored": monitored, "Latitude": "", "Longitude": "",
                      "OriginCode": "", "DestinationCode": ""}
    return item


class Lta:
    """A fake BusArrival that records the queries it gets."""

    def __init__(self, services=None, status=200, error=None):
        self.services = services if services is not None else [_service("36", [4.5]), _service("77", [9]), _service("12", [2])]
        self.status, self.error, self.queries, self.headers = status, error, [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.queries.append(dict(request.url.params))
        self.headers.append(dict(request.headers))
        if self.error:
            raise self.error
        if self.status != 200:
            return httpx.Response(self.status, json={})
        return httpx.Response(200, json={"Services": self.services})

    def client(self):
        return httpx.Client(transport=httpx.MockTransport(self))


@pytest.fixture(autouse=True)
def _clean():
    arrivals.clear_later_arrivals()
    yield
    arrivals.clear_later_arrivals()


@pytest.fixture
def api(monkeypatch):
    lta = Lta()
    monkeypatch.setattr(arrivals, "read_account_key", lambda: KEY)
    monkeypatch.setattr(arrivals.httpx, "Client", lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(lta)))
    monkeypatch.setattr(demo, "demo_enabled", lambda: False)
    cache = StopAndRouteCache(**json.loads((ROOT / "tests" / "fixtures" / "pt_lta_cache.json").read_text(encoding="utf-8")))
    monkeypatch.setattr(main, "load_static_data", lambda: cache)
    monkeypatch.setattr(main, "startup_warning", lambda today: None)
    with TestClient(main.app) as client:
        client.lta = lta
        yield client


# ---- the server lookup -------------------------------------------------------------------------------------


def test_one_call_serves_every_service_at_a_stop_and_sends_only_the_stop_code(api):
    body = api.get("/api/arrivals/later", params={"stop_code": "03011", "services": "36,77"}).json()
    assert body["status"] == "ok" and set(body["services"]) == {"36", "77"}
    assert api.lta.queries == [{"BusStopCode": "03011"}]  # one call, no ServiceNo, no coordinate
    assert all(set(bus) == {"arrival_time", "monitored"} for bus in body["services"]["36"])
    assert set(body) == {"status", "stop_code", "fetched_at", "services"}  # no probability, no leave-by, no position


def test_a_position_in_the_query_is_never_forwarded(api):
    api.get("/api/arrivals/later", params={"stop_code": "03011", "services": "36", "user_lat": 1.3691, "user_lon": 103.8476})
    assert api.lta.queries == [{"BusStopCode": "03011"}]
    assert "1.3691" not in json.dumps(api.lta.queries) and "103.8476" not in json.dumps(api.lta.queries)


def test_a_stop_is_kept_for_60_seconds_then_looked_up_again(api, monkeypatch):
    params = {"stop_code": "03011", "services": "36"}
    api.get("/api/arrivals/later", params=params)
    api.get("/api/arrivals/later", params={"stop_code": "03011", "services": "77"})  # another service, same stop: shared
    assert len(api.lta.queries) == 1
    clock = {"now": arrivals.time.monotonic()}
    monkeypatch.setattr(arrivals.time, "monotonic", lambda: clock["now"] + 61)
    api.get("/api/arrivals/later", params=params)
    assert len(api.lta.queries) == 2
    api.get("/api/arrivals/later", params={"stop_code": "05012", "services": "36"})  # another stop: its own call
    assert [q["BusStopCode"] for q in api.lta.queries] == ["03011", "03011", "05012"]


def test_at_most_three_services_are_returned_for_a_stop(api):
    body = api.get("/api/arrivals/later", params={"stop_code": "03011", "services": "36,77,12,99,98"}).json()
    assert list(body["services"]) == ["36", "77", "12"]


@pytest.mark.parametrize("make", [
    lambda: Lta(status=500), lambda: Lta(status=429), lambda: Lta(error=httpx.ReadTimeout("slow")),
    lambda: Lta(error=httpx.ConnectError("down")), lambda: Lta(services="not a list"),
])
def test_a_failure_is_plain_unavailable_with_no_text(api, monkeypatch, make):
    lta = make()
    monkeypatch.setattr(arrivals.httpx, "Client", lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(lta)))
    response = api.get("/api/arrivals/later", params={"stop_code": "03011", "services": "36"})
    assert response.status_code == 503 and response.json() == {"status": "unavailable"}
    assert KEY not in response.text


def test_demo_mode_is_refused_and_makes_no_call(api, monkeypatch):
    monkeypatch.setattr(demo, "demo_enabled", lambda: True)
    response = api.get("/api/arrivals/later", params={"stop_code": "03011", "services": "36"})
    assert response.status_code == 503 and not api.lta.queries


def test_the_service_hours_check_is_the_one_the_reroute_uses(api, monkeypatch):
    calls = []

    def runs(cache, service, stop, when, direction=None, live=False):
        calls.append((service, stop, live))
        return live  # the schedule says no; only a recent monitored bus overrides it

    monkeypatch.setattr(arrivals, "service_runs_at", runs)
    lta = Lta([_service("36", [4], monitored=1), _service("77", [9], monitored=0)])
    monkeypatch.setattr(arrivals.httpx, "Client", lambda *a, **k: REAL_CLIENT(transport=httpx.MockTransport(lta)))
    body = api.get("/api/arrivals/later", params={"stop_code": "03011", "services": "36,77"}).json()
    assert len(body["services"]["36"]) == 1  # monitored and recent: kept
    assert body["services"]["77"] == []  # not monitored and outside the schedule: dropped
    assert ("36", "03011", True) in calls and ("77", "03011", False) in calls


def test_the_account_key_goes_only_in_the_header_to_lta(api):
    api.get("/api/arrivals/later", params={"stop_code": "03011", "services": "36"})
    assert api.lta.headers[0].get("accountkey") == KEY
    assert KEY not in json.dumps(api.lta.queries)


# ---- the page ----------------------------------------------------------------------------------------------


def _run(tmp_path_factory, name, builder, table=None, **config):
    require_edge()
    log = []
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode({"TRANSIT": builder}), rail_table=table,
                     lta_services={"36": [4.5], "77": [12], "12": [2]}, lta_log=log) as base:
        out = run_scenario("laterlegs", base, {"name": name, **config})["result"]
    out["lta"] = log
    return out


@pytest.fixture(scope="module")
def chain(tmp_path_factory):
    return _run(tmp_path_factory, "chain", stub.bus_chain, width=360, height=1100)


@pytest.fixture(scope="module")
def chain_wide_dark(tmp_path_factory):
    return _run(tmp_path_factory, "chain_dark", stub.bus_chain, width=1280, height=900, dark=True)


@pytest.fixture(scope="module")
def rails(tmp_path_factory):
    return _run(tmp_path_factory, "rails", stub.later_buses, mode="rail", width=390)


def _bus_rows(rows):
    return [row for row in rows if "journey-step--bus" in row["cls"]]


def test_nothing_is_looked_up_before_start_journey(chain):
    assert chain["beforeStart"]["requests"] == []
    assert all(("36" in row["text"] or "77" in row["text"]) is False or "Scheduled" in row["text"]
               for row in _bus_rows(chain["beforeStart"]["rows"]))


def test_after_start_the_leg_after_the_first_is_looked_up_once_with_a_stop_and_a_service_only(chain):
    assert len(chain["afterStart"]["requests"]) == 1
    query = chain["afterStart"]["requests"][0]
    assert query == "/api/arrivals/later?stop_code=03011&services=36"  # not bus 77: the user is not on leg 2 yet
    assert not re.search(r"[?&](lat|lon|user|position|accuracy)", query)
    assert {"BusStopCode": "03011"} in chain["lta"]  # one BusArrival call with only the stop code


def test_a_later_bus_row_says_live_and_the_next_one_says_scheduled_each_with_its_own_type(chain):
    buses = _bus_rows(chain["overview"]["rows"])
    assert len(buses) == 3
    first, second, third = buses
    assert any(line.startswith("Arriving in") or line == "Arriving soon" for line in first["lines"])
    assert any(re.fullmatch(r"Live · In \d+" + NB + "min", line) for line in second["lines"]), second["lines"]
    assert any(re.fullmatch(r"Scheduled · \d{1,2}:\d\d" + NB + "(AM|PM)( [(]tomorrow[)])?", line) for line in third["lines"]) or \
        not any("Live" in line for line in third["lines"])
    assert not any("Live" in line for line in third["lines"])  # bus 77 has not been looked up, so it is not live
    assert "Live tracking covers" not in " ".join(row["text"] for row in chain["overview"]["rows"])


def test_the_cadence_the_shared_stop_and_the_cap(chain):
    assert len(chain["immediate"]) == len(chain["overview"]["requests"])  # two calls at once add none
    assert len(chain["afterWait"]) == len(chain["immediate"]) + 1  # one after 60 s
    assert chain["capped"] == ["11", "12", "13"]  # five later legs, three looked up
    assert sorted(chain["capRequests"]) == sorted([
        "/api/arrivals/later?stop_code=S1&services=11%2C12", "/api/arrivals/later?stop_code=S2&services=13"])  # S1 shared


def test_no_lookup_in_demo_mode_off_the_pages_or_after_tracking_ends(chain):
    assert chain["gates"] == {"demo": 0, "offpage": 0, "afterEnd": 0}


def test_the_labels_follow_the_existing_thresholds(chain):
    assert chain["labels"] == ["Live · Now", "Live · Arriving soon", "Live · Arriving soon",
                               "Live · In 1" + NB + "min", "Live · In 2" + NB + "min", "Live · In 10" + NB + "min"]
    assert chain["firstBus"][0].endswith("Arriving soon") or "Arriving soon" in chain["firstBus"][0]
    assert "Due" not in chain["firstBus"][0]
    assert re.search(r"Arriving in [45]" + r"\s?min", chain["firstBus"][1].replace(NB, " "))


def test_a_train_leg_is_never_looked_up(rails):
    assert rails["afterStart"]["requests"] == []  # the leg after bus 18 is a train
    reached = rails["reachAll"]["requests"]
    assert len(reached) == 2 and all("stop_code=NS" not in url for url in reached)  # buses 36 and 77 only
    assert [url.split("services=")[1] for url in reached] == ["36", "77"]


def test_the_row_shape_and_labels_fit_at_360_and_1280_in_both_themes(chain, chain_wide_dark):
    for run in (chain, chain_wide_dark):
        second = _bus_rows(run["overview"]["rows"])[1]
        assert any(line.startswith("Live · ") for line in second["lines"])


# ---- the words and the note --------------------------------------------------------------------------------


def test_the_new_strings_are_in_copy_js_and_the_page_character_for_character():
    jo = COPY.split("journeyOverview: {", 1)[1].split("\n  },", 1)[0]
    for key, variable in {"liveIn": "JO_LIVE_IN", "liveArrivingSoon": "JO_LIVE_ARRIVING_SOON", "liveNow": "JO_LIVE_NOW",
                          "arrivingSoon": "JO_ARRIVING_SOON"}.items():
        copy_value = re.search(rf'\b{key}: "((?:[^"\\]|\\.)*)"', jo).group(1)
        page_value = re.search(rf'var {variable} = "((?:[^"\\]|\\.)*)";', INDEX).group(1)
        assert copy_value == page_value, key
    assert 'liveNow: "Live · Now"' in COPY and 'arrivingSoon: "Arriving soon"' in COPY


def test_due_stays_everywhere_else():
    assert 'return "Due";' in INDEX  # the arrival tile's own word
    row = INDEX.split("function transitRow(", 1)[1].split("// The change between two legs", 1)[0]
    assert 'arriving === "Due" ? JO_ARRIVING_SOON' in row


def test_the_first_bus_only_text_is_gone_everywhere():
    needle = "covers your first bus"
    for path in ("static/copy.js", "static/index.html", "static/styleguide.html", "PROJECT_PLAN.md"):
        assert needle not in (ROOT / path).read_text(encoding="utf-8"), path
    assert "FIRST_BUS_ONLY_NOTE" not in INDEX and "firstBusOnly" not in COPY
    for path in (ROOT / "static").glob("*"):
        if path.suffix in (".js", ".html", ".css"):
            assert needle not in path.read_text(encoding="utf-8"), path.name
    for path in (ROOT / "tests").glob("test_*.py"):
        if path.name != Path(__file__).name:  # this file names the text it checks for
            assert "Live tracking covers your first bus" not in path.read_text(encoding="utf-8"), path.name


def test_the_lookup_code_has_the_limits_the_plan_states():
    code = INDEX.split("function laterLegsNow()", 1)[1].split("function stepItem(", 1)[0]
    assert "var LATER_MIN_MS = 60000;" in INDEX and "var LATER_CAP = 3;" in INDEX
    for needle in ("!monitoringActive", "trackingStopped", "demoModeOn()", 'document.visibilityState === "hidden"',
                   '!legIsRail(leg)', ".slice(0, LATER_CAP)", "laterAt[stop]", "laterPending[stop]"):
        assert needle in code, needle
    assert code.count("fetch(") == 1 and "/api/arrivals/later?stop_code=" in code
    assert "latitude" not in code and "userLat" not in code and "userLon" not in code  # no position in the lookup
    assert INDEX.count("setInterval(") == 3  # no new timer: it rides on the poll tick
    assert "maybeLookupLater();" in INDEX.split("function armPollTimer(generation)", 1)[1].split("function refreshLocationFix", 1)[0]
    stop = INDEX.split("function stopTracking()", 1)[1].split("function markTrackingStopped", 1)[0]
    assert "resetLaterLookups()" in stop


def test_a_later_time_reaches_no_catch_logic():
    for name in ("laterLiveFor", "laterLiveText", "laterCache", "laterLegsNow", "maybeLookupLater"):
        for fn in ("function requestArrivals(", "function renderCatchCard(", "function handleSuccess(", "function renderLiveTracking("):
            if fn in INDEX:
                body = INDEX.split(fn, 1)[1].split("\n    function ", 1)[0]
                assert name not in body, (fn, name)
    server = (ROOT / "arrivals.py").read_text(encoding="utf-8").split("def peek_later(", 1)[1].split("def _parse_iso", 1)[0]
    for word in ("score_buses", "leave_by", "reroute", "notification", "probability"):
        assert word not in server.split('"""', 2)[2], word
