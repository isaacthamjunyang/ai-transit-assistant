"""Train service alerts (LTA guide 2.11): the line-code mapping, the parse, the 60 s shared cache, silent failure, no
coordinates, Demo Mode, and the banner on the real page. Every LTA answer here is scripted: no live call is made."""

import re
from pathlib import Path

import httpx
import pytest

import demo
import onemap_stub as stub
import train_alerts
from page_runner import require_edge, run_scenario, running_app
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")

NEL_MESSAGE = ("1657hrs : NEL - Additional travelling time of 20 minutes between Boon Keng and Dhoby Ghaut stations "
               "towards HarbourFront station due to a signal fault.")


def payload(status=2, segments=(("NEL", "HarbourFront", "NE9,NE8,NE7,NE6"),), messages=(NEL_MESSAGE,)):
    """The shape of the guide's Annex C answer."""
    return {
        "odata.metadata": "http://datamall2.mytransport.sg/ltaodataservice/$metadata#TrainServicesAlerts",
        "value": {
            "Status": status,
            "AffectedSegments": [
                {"Line": line, "Direction": direction, "Stations": stations, "FreePublicBus": "", "FreeMRTShuttle": "",
                 "MRTShuttleDirection": ""} for line, direction, stations in segments],
            "Message": [{"Content": text, "CreatedDate": "2017-12-11 16:57:25"} for text in messages],
        },
    }


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setattr(demo, "demo_enabled", lambda env_path=None: False)
    train_alerts.clear_cache()
    yield
    train_alerts.clear_cache()


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


# ---- the code mapping and the parse -----------------------------------------------------------------------------

def test_the_line_codes_map_to_the_app_codes_exactly():
    assert train_alerts.LINE_CODES == {
        "EWL": "EW", "NSL": "NS", "NEL": "NE", "CCL": "CC", "DTL": "DT", "TEL": "TE", "BPL": "BP", "STL": "SK", "PTL": "PG"}


@pytest.mark.parametrize("lta, short", list(train_alerts.LINE_CODES.items()))
def test_every_guide_line_code_becomes_the_app_code(lta, short):
    result = train_alerts.parse_alerts(payload(segments=((lta, "Both", "X1"),), messages=(f"{lta} - delay",)))
    assert result == [{"line": short, "status": "disrupted", "message": f"{lta} - delay"}]


def test_status_2_is_disrupted_and_status_1_with_a_segment_is_a_minor_delay():
    assert train_alerts.parse_alerts(payload(status=2))[0]["status"] == "disrupted"
    assert train_alerts.parse_alerts(payload(status=1))[0]["status"] == "minor"


def test_normal_service_and_malformed_answers_give_no_alerts():
    assert train_alerts.parse_alerts(payload(status=1, segments=(), messages=())) == []
    for bad in (None, [], "x", {}, {"value": None}, {"value": {"AffectedSegments": "no"}}, {"value": {"AffectedSegments": [1]}}):
        assert train_alerts.parse_alerts(bad) == []


def test_a_line_the_guide_does_not_list_is_dropped_and_the_message_follows_its_own_line():
    body = payload(segments=(("NSL", "Both", "NS1"), ("XYZ", "Both", "X1"), ("EWL", "Both", "EW1")),
                   messages=("1700hrs : EWL - No train service.", "1701hrs : NSL - Slow."))
    result = {alert["line"]: alert["message"] for alert in train_alerts.parse_alerts(body)}
    assert result == {"NS": "1701hrs : NSL - Slow.", "EW": "1700hrs : EWL - No train service."}


def test_the_message_is_text_only_and_capped():
    long_text = "NEL " + "x" * 2000 + "\x00\x07"
    (alert,) = train_alerts.parse_alerts(payload(messages=(long_text,)))
    assert len(alert["message"]) <= train_alerts.MAX_MESSAGE_CHARS and "\x00" not in alert["message"]


def test_an_alert_carries_a_line_a_status_and_a_message_and_nothing_positional():
    (alert,) = train_alerts.parse_alerts(payload())
    assert set(alert) == {"line", "status", "message"}


# ---- the 60 s shared cache, silent failure, Demo Mode, no coordinates ----------------------------------------------

def test_the_request_has_no_parameters_and_only_the_account_key_header():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=payload())

    alerts = train_alerts.current_alerts(client=_client(handler), account_key="k", now=1000.0)
    assert [alert["line"] for alert in alerts] == ["NE"]
    (request,) = seen
    assert str(request.url) == train_alerts.ALERTS_URL and request.url.query == b""
    assert request.method == "GET" and request.content == b""
    assert not re.search(r"(lat|lon|latitude|longitude|coord\w*|position)", str(request.url) + str(dict(request.headers)), re.I)


def test_one_lta_call_serves_every_user_for_60_seconds():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json=payload())

    client = _client(handler)
    for moment in (1000.0, 1000.5, 1030.0, 1059.9):
        assert train_alerts.current_alerts(client=client, account_key="k", now=moment)[0]["line"] == "NE"
    assert len(calls) == 1
    train_alerts.current_alerts(client=client, account_key="k", now=1060.1)
    assert len(calls) == 2


@pytest.mark.parametrize("answer", ["status500", "badjson", "timeout", "neterror", "wrongshape"])
def test_any_failure_returns_no_alerts_silently(answer):
    def handler(request):
        if answer == "status500":
            return httpx.Response(500, json={})
        if answer == "badjson":
            return httpx.Response(200, content=b"<html>")
        if answer == "timeout":
            raise httpx.ReadTimeout("slow", request=request)
        if answer == "neterror":
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(200, json=["not", "an", "answer"])

    assert train_alerts.current_alerts(client=_client(handler), account_key="k", now=1.0) == []


def test_a_missing_key_makes_no_request_and_returns_nothing():
    def handler(request):
        raise AssertionError("no request may be made without a key")

    assert train_alerts.current_alerts(client=_client(handler), account_key="  ", now=1.0) == []


def test_demo_mode_makes_no_request_and_returns_nothing(monkeypatch):
    monkeypatch.setattr(demo, "demo_enabled", lambda env_path=None: True)

    def handler(request):
        raise AssertionError("Demo Mode never reaches LTA for alerts")

    assert train_alerts.current_alerts(client=_client(handler), account_key="k", now=1.0) == []


# ---- the endpoint and the real page ------------------------------------------------------------------------------

def test_the_endpoint_answers_a_list_and_asks_lta_once(tmp_path):
    log = []
    with running_app(tmp_path, train_alerts_payload=payload(), alerts_log=log) as base:
        first = httpx.get(base + "/api/train-alerts", timeout=10).json()
        second = httpx.get(base + "/api/train-alerts", timeout=10).json()
    assert first == second and [alert["line"] for alert in first["alerts"]] == ["NE"]
    assert len(log) == 1 and log[0]["params"] == {} and log[0]["has_key"] is True


def test_the_endpoint_failure_is_an_empty_list(tmp_path):
    with running_app(tmp_path, alerts_status=503) as base:
        assert httpx.get(base + "/api/train-alerts", timeout=10).json() == {"alerts": []}


def test_the_alert_strings_are_in_copy_js_and_the_page_character_for_character():
    for key, text in (("text", "{line}: {message}"), ("noMessageMinor", "Minor delays. Check for updates."),
                      ("noMessageDisrupted", "Train service is disrupted. Check for updates."),
                      ("more", "Show more"), ("less", "Show less")):
        assert f'{key}: "{text}"' in COPY
    for name, text in (("TRAIN_ALERT_TEXT", "{line}: {message}"), ("TRAIN_ALERT_MORE", "Show more"),
                       ("TRAIN_ALERT_LESS", "Show less"),
                       ("TRAIN_ALERT_NO_MESSAGE_MINOR", "Minor delays. Check for updates."),
                       ("TRAIN_ALERT_NO_MESSAGE_DISRUPTED", "Train service is disrupted. Check for updates.")):
        assert f'var {name} = "{text}";' in INDEX


def test_the_alerts_never_reach_ranking_probability_or_reroute():
    for name in ("recommend.py", "reroute.py", "catch_heuristic.py", "journey.py", "explain.py", "pt_plan.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "train_alerts" not in text and "TrainServiceAlerts" not in text, name
    sync = INDEX.split("function syncTrainAlerts() {", 1)[1].split("\n    }\n", 1)[0]
    assert "fetch(\"/api/train-alerts\"" in sync and "userLat" not in sync and "latitude" not in sync


def test_the_plan_and_the_style_guide_describe_the_alert_banner():
    assert "TrainServiceAlerts" in PLAN and "`EWL`" in PLAN and "60 seconds" in PLAN
    assert "sgTrainAlert(" in GUIDE and "train-alert__text" in GUIDE
    assert ".train-alert__text {" in CSS and "-webkit-line-clamp: 2;" in CSS


VIEWPORTS = [("l360", 360, 800, False), ("d1280", 1280, 900, True)]
LONG = "No train service between Bishan and Woodlands. " + "Please plan for extra time and use the free bus service. " * 3
NS_TRAIN_FIRST = stub.train_first


def _run(tmp_path_factory, name, width, height, dark, **kwargs):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode({"TRANSIT": stub.train_first}),
                     rail_table=_table(), lta_status=500, **kwargs) as base:
        return run_scenario("trainalerts", base, {"name": name, "width": width, "height": height, "dark": dark},
                            timeout=300)["result"]


@pytest.fixture(scope="module", params=VIEWPORTS, ids=["360-light", "1280-dark"])
def affected(request, tmp_path_factory):
    name, width, height, dark = request.param
    body = payload(status=2, segments=(("NSL", "Both", "NS17"),), messages=("1700hrs : NSL - " + LONG,))
    log = []
    out = _run(tmp_path_factory, "alert" + name, width, height, dark, train_alerts_payload=body, alerts_log=log)
    out["log"] = log
    return out


def test_a_route_on_the_affected_line_shows_the_banner_on_the_overview_and_both_live_pages(affected):
    for key in ("overview", "pageA", "pageB"):
        view = affected[key]
        assert view["shown"] is True and len(view["boxes"]) == 1, key
        box = view["boxes"][0]
        assert box["text"].startswith("North-South Line: 5:00 PM: No train service"), box["text"]
        assert box["line"] == "NS" and box["status"] == "disrupted" and box["icon"] is True  # icon and text
        assert box["lines"] <= 2, {k: box[k] for k in ("cls", "boxCls", "display", "clamp")}  # cut at two lines
        assert box["right"] <= view["innerWidth"] and view["scrollWidth"] <= view["innerWidth"]


def test_a_long_message_gets_an_expand_control_that_opens_and_closes(affected):
    box = affected["pageA"]["boxes"][0]
    assert box["toggleShown"] is True and box["toggleText"] == "Show more" and box["expanded"] == "false"
    assert box["toggleHeight"] >= 44
    opened = affected["pageAExpanded"]["boxes"][0]
    assert opened["expanded"] == "true" and opened["toggleText"] == "Show less" and opened["lines"] > 2


def test_the_page_asks_for_the_alerts_without_sending_anything_about_the_user(affected):
    assert 1 <= len(affected["log"]) <= 2  # the server's 60 s cache: one LTA call for the whole run
    assert all(entry["params"] == {} for entry in affected["log"])


@pytest.fixture(scope="module")
def other_line(tmp_path_factory):
    body = payload(status=2, segments=(("EWL", "Both", "EW14"),), messages=("1700hrs : EWL - No train service.",))
    return _run(tmp_path_factory, "otherline", 360, 800, False, train_alerts_payload=body)


def test_an_alert_on_another_line_shows_nothing(other_line):
    for key in ("overview", "pageA", "pageB"):
        assert other_line[key]["shown"] is False and other_line[key]["boxes"] == [], key


@pytest.fixture(scope="module")
def failing(tmp_path_factory):
    return _run(tmp_path_factory, "failing", 360, 800, False, alerts_status=500)


def test_a_failed_alert_lookup_shows_nothing(failing):
    for key in ("overview", "pageA", "pageB"):
        assert failing[key]["shown"] is False and failing[key]["boxes"] == [], key
    assert failing["pageA"]["scrollWidth"] <= failing["pageA"]["innerWidth"]


# ---- the cleaned message and the two fallbacks (the page's own function, run in node) ------------------------

def _clean(messages):
    import json
    import shutil
    import subprocess
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    marker = "function cleanTrainAlertMessage(text) {"
    body = INDEX.split(marker, 1)[1].split("\n    }\n", 1)[0]
    program = marker + body + "\n}\nconsole.log(JSON.stringify(" + json.dumps(messages) + ".map(cleanTrainAlertMessage)));"
    done = subprocess.run(["node", "-e", program], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr[-500:]
    return json.loads(done.stdout)


def test_a_leading_line_code_and_dash_is_dropped_wherever_it_starts_the_message():
    codes = ["EWL", "NSL", "NEL", "CCL", "DTL", "TEL", "BPL", "STL", "PTL", "EW", "NS", "NE", "CC", "DT", "TE", "BP", "SK", "PG"]
    assert _clean([f"{code} - Additional travelling time of 10 minutes." for code in codes]) ==         ["Additional travelling time of 10 minutes."] * len(codes)
    assert _clean(["NEL – Slow.", "NEL-Slow."]) == ["Slow.", "Slow."]


def test_a_time_stamp_is_kept_as_the_12_hour_clock_and_the_code_after_it_is_dropped():
    assert _clean(["1700hrs : NSL - No train service between Bishan and Marina South Pier."]) ==         ["5:00 PM: No train service between Bishan and Marina South Pier."]
    assert _clean(["0005hrs : EWL - Slow.", "1200hrs : CCL - Slow.", "0930hrs: NEL - Slow."]) ==         ["12:05 AM: Slow.", "12:00 PM: Slow.", "9:30 AM: Slow."]


def test_a_time_stamp_with_no_code_after_it_is_kept_reformatted():
    assert _clean(["1657hrs : Trains are slow."]) == ["4:57 PM: Trains are slow."]


def test_a_message_with_neither_is_unchanged_and_an_unparseable_stamp_is_left_alone():
    assert _clean(["Trains are slow near Bishan.", "Stations NEL are busy."]) ==         ["Trains are slow near Bishan.", "Stations NEL are busy."]
    assert _clean(["2575hrs : NSL - Slow.", "2460hrs : Slow."]) == ["2575hrs : NSL - Slow.", "2460hrs : Slow."]


def test_nothing_left_after_cleaning_is_empty_so_the_status_fallback_shows():
    assert _clean(["NSL - ", "1700hrs : NSL - "]) == ["", ""]
    build = INDEX.split("function buildTrainAlert(", 1)[1].split("var box = ", 1)[0]
    assert "TRAIN_ALERT_NO_MESSAGE_DISRUPTED : TRAIN_ALERT_NO_MESSAGE_MINOR" in build
    assert 'alert.status === "disrupted"' in build


def test_the_banner_never_doubles_the_line_name():
    # the cleaned text never starts with a code, so "{line}: {message}" names the line once
    cleaned = _clean(["NEL - Additional travelling time of 10 minutes.", "1700hrs : NSL - No train service."])
    assert all(not text.startswith(("NEL", "NSL")) for text in cleaned)
