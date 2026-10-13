"""The estimator wired into the real page: lifecycle, requests and permission. Real app, real page, headless Edge."""

import concurrent.futures

import pytest

from page_runner import require_edge, run_scenario, running_app


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("app")) as base:
        yield base


def test_start_runs_nothing_before_the_tap_and_asks_for_motion_inside_it(app):
    report = run_scenario("start", app, {"permission": "granted"})["result"]
    for step in ("afterLoad", "onOverview"):
        assert report[step]["wanted"] is False and report[step]["listeners"] == 0 and report[step]["watching"] == 0, step
    assert report["permissionCallsOnLoad"] == 0 and report["permissionCallsOnOverview"] == 0
    assert report["permission"]["calls"] == 1 and report["permission"]["duringClick"] == [True]
    after = report["afterTap"]
    assert after["wanted"] and after["running"] and after["listeners"] == 1 and after["watching"] == 1
    assert after["screen"] == "live" and after["monitoring"]
    assert not any("walk_speed" in url for url in report["requestsBeforeStart"])


STOP_CASES = ["yes", "yes-transfer", "no", "end", "leave", "back", "hidden", "onway", "newjourney", "demo", "ended-by-unanswered"]


@pytest.fixture(scope="module")
def stop_reports(app):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {name: pool.submit(run_scenario, "stops", app, {"which": name}) for name in STOP_CASES}
        return {name: future.result()["result"] for name, future in futures.items()}


@pytest.mark.parametrize("name", [n for n in STOP_CASES if n not in ("hidden", "newjourney")])
def test_the_estimator_stops_when(stop_reports, name):
    report = stop_reports[name]
    started = report["started"]
    assert started["wanted"] and started["listeners"] == 1 and started["watching"] == 1, "it never started"
    after = report["after"]
    assert after["wanted"] is False and after["running"] is False, after
    assert after["listeners"] == 0 and after["watching"] == 0, after


def test_a_hidden_page_stops_it_and_a_visible_page_resumes_it(stop_reports):
    report = stop_reports["hidden"]
    assert report["whileHidden"]["listeners"] == 0 and report["whileHidden"]["watching"] == 0
    assert report["afterShown"]["listeners"] == 1 and report["afterShown"]["watching"] == 1


def test_the_new_journey_overview_pauses_it_and_the_live_page_resumes_it(stop_reports):
    report = stop_reports["newjourney"]
    assert report["whileOverview"]["listeners"] == 0 and report["whileOverview"]["watching"] == 0
    assert report["backOnLive"]["listeners"] == 1 and report["backOnLive"]["watching"] == 1


def test_the_catch_answers_and_the_end_card_are_the_page_states_that_were_reached(stop_reports):
    assert stop_reports["yes"]["beforeAnswer"]["listeners"] == 1
    assert stop_reports["no"]["beforeAnswer"]["listeners"] == 1
    assert stop_reports["end"]["endCardShown"] is True


def test_demo_mode_never_starts_it_and_never_asks_for_motion(app):
    report = run_scenario("demo_start", app)["result"]
    assert report["state"]["wanted"] is False and report["state"]["listeners"] == 0 and report["state"]["watching"] == 0
    assert report["permission"] == 0 and report["query"] == ""


JOBS = {
    "near": ("stops", {"which": "near"}),
    "denied": ("permission", {"permission": "denied"}),
    "missing": ("permission", {"permission": "missing"}),
    "none": ("permission", {"permission": "none"}),
    "granted": ("permission", {"permission": "granted", "events": True}),
    "gps_only": ("permission", {"permission": "denied", "gpsOnly": True}),
    "requests": ("requests", {}),
}


@pytest.fixture(scope="module")
def reports(app):
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        futures = {name: pool.submit(run_scenario, scenario, app, extra) for name, (scenario, extra) in JOBS.items()}
        return {name: future.result()["result"] for name, future in futures.items()}


def test_near_the_stop_two_polls_latch_it_off_and_the_speed_stays_frozen(reports):
    r = reports["near"]
    assert "walk_speed=" in r["firstPollUrl"] and "walk_speed_source=gps" in r["firstPollUrl"]
    assert r["firstPollSpeed"]["source"] == "gps" and 1.2 <= r["firstPollSpeed"]["used"] <= 1.4
    assert r["usedWatchFix"] is True  # a newer watch fix reached the page's position
    assert r["nearFlag1"] is True
    assert r["afterFirstNear"]["running"] is True and r["afterFirstNear"]["latched"] is False
    assert r["afterSecondNear"]["running"] is False and r["afterSecondNear"]["latched"] is True
    assert r["afterSecondNear"]["listeners"] == 0 and r["afterSecondNear"]["watching"] == 0
    assert r["deliveredAfterStop"] == 0, "sensor events were still being handled after the stop"
    frozen = [url.split("walk_speed=")[1].split("&")[0] for url in r["frozenUrls"]]
    assert all("walk_speed=" in url for url in r["frozenUrls"]), "the frozen speed was not sent"
    assert len(set(frozen)) == 1, frozen
    assert r["frozenSpeed"]["source"] == "gps" and abs(r["frozenSpeed"]["used"] - float(frozen[0])) < 0.01
    assert r["restarted"]["wanted"] is True and r["restarted"]["latched"] is False


@pytest.mark.parametrize("permission", ["denied", "missing", "none"])
def test_no_motion_sensor_keeps_the_journey_working(reports, permission):
    r = reports[permission]
    assert r["monitoring"] is True and r["pollWorked"] is True
    assert r["status"]["motion"] == "off", r["status"]
    assert r["query"] == ""  # nothing measured, nothing sent: the server default
    assert r["calls"] == (1 if permission == "denied" else 0)


def test_granted_with_events_turns_the_sensor_on(reports):
    r = reports["granted"]
    assert r["status"]["motion"] == "on" and r["monitoring"] is True and r["pollWorked"] is True


def test_with_no_motion_sensor_steady_gps_walking_still_gives_a_speed(reports):
    r = reports["gps_only"]
    assert "walk_speed=1.2" in r["gpsOnlyUrl"] and "walk_speed_source=gps" in r["gpsOnlyUrl"]
    assert r["gpsOnlySnapshot"]["mode"] == "gps"


def test_a_remembered_pace_goes_with_the_planning_request_and_the_page_shows_the_servers_value(reports):
    r = reports["requests"]
    assert "walk_speed=0.9" in r["planUrl"] and "walk_speed_source=remembered" in r["planUrl"]
    assert r["serverSpeed"] == {"used": 0.9, "source": "remembered"}
    assert r["mirror"] == 6  # 300 m at 0.9 m/s is 5.6 minutes, shown as 6
    assert "walk_speed=0.9" in r["arrivalsUrl"] and r["after"]["last"] == 0.9


PRIVACY = "Motion data stays on your phone. Only the walking speed worked out from it is sent. Your location is sent as before."
SENSOR_OFF = "Motion sensor is off, so your steps are not used."
CAPTIONS = {
    "gps": ("if you leave now and keep walking at your current pace", "Walking pace: 4.7 km/h · from GPS"),
    "cadence": ("if you leave now and keep walking at your current pace", "Walking pace: 4.3 km/h · from your steps"),
    "remembered": ("if you leave now and walk at your usual pace", "Walking pace: 3.2 km/h · your usual pace"),
    "default": ("if you leave now and walk at a normal pace", "Walking pace: 4.5 km/h · normal pace"),
}


@pytest.fixture(scope="module")
def ui(app):
    jobs = {
        "captions": ("captions", {}),
        "notes_granted": ("notes", {"permission": "granted"}),
        "notes_missing": ("notes", {"permission": "missing"}),
        "notes_denied": ("notes", {"permission": "denied"}),
        "notes_demo": ("notes", {"permission": "granted", "demo": True}),
    }
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {name: pool.submit(run_scenario, scenario, app, extra) for name, (scenario, extra) in jobs.items()}
        return {name: future.result()["result"] for name, future in futures.items()}


@pytest.mark.parametrize("source", list(CAPTIONS))
def test_the_card_shows_the_caption_and_pace_line_for_the_servers_source(ui, source):
    card = ui["captions"]["sources"][source]
    assert (card["caption"], card["line"]) == CAPTIONS[source]
    assert card["live"] == "off" and card["visible"] is True


def test_the_real_poll_with_no_value_is_the_normal_pace(ui):
    real = ui["captions"]["real"]
    assert real["server"] == {"used": 1.25, "source": "default"}
    assert real["card"]["line"] == "Walking pace: 4.5 km/h · normal pace"
    assert real["card"]["caption"] == "if you leave now and walk at a normal pace"


def test_an_unknown_source_falls_back_to_the_normal_pace(ui):
    bogus = ui["captions"]["bogus"]
    assert bogus["caption"] == CAPTIONS["default"][0] and bogus["line"] == "Walking pace: 4.5 km/h · normal pace"


def test_the_overview_shows_the_privacy_line_or_the_sensor_off_line(ui):
    assert ui["notes_granted"]["onOverview"] == {"overview": PRIVACY, "newJourney": PRIVACY}
    assert ui["notes_missing"]["onOverview"]["overview"] == SENSOR_OFF
    assert ui["notes_denied"]["afterDenied"]["newJourney"] == SENSOR_OFF
    assert ui["notes_demo"]["inDemo"] == {"overview": "", "newJourney": ""}


def test_yes_on_a_transfer_route_shows_the_overview_and_stops_everything(stop_reports):
    report = stop_reports["yes-transfer"]
    assert report["afterYes"] == {"screen": "onway", "monitoring": False, "poll": True, "display": True,
                                  "pace": False, "proposal": ""}
    text = report["onWayText"]
    assert "On board" in text and "Bus 18" in text and "Bus 14" in text
    assert "Schedule: about every 12 min." in text
    assert "first bus only" not in text
    assert "alert you" not in text


def test_the_debug_bar_sits_on_top_of_the_page_stays_one_line_and_survives_navigation(app):
    report = run_scenario("debugbar", app)["result"]
    for step in ("beforeStart", "onOverview", "onLive", "afterHome"):
        bar = report[step]
        assert bar["onTop"] and bar["top"] <= 1 and bar["height"] <= 40 and bar["width"] <= bar["vw"], (step, bar)
        assert bar["search"] == "?pace=debug", (step, bar)
        assert bar["text"].startswith("mode "), (step, bar)
    assert report["beforeStart"]["text"].endswith("journey not started · srv age -")
    assert report["open"]["hidden"] is False and report["open"]["onTop"] and report["open"]["buttons"] == 3
    assert report["open"]["bottom"] <= report["open"]["vh"]
    assert report["boxes"] == 1


@pytest.fixture(scope="module")
def fresh_fix_reports(app):
    names = ["old", "hang", "fail", "recent"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futures = {n: pool.submit(run_scenario, "freshfix", app, {"which": n}) for n in names}
        return {n: f.result()["result"] for n, f in futures.items()}


def test_the_first_poll_after_a_long_planner_session_carries_a_fresh_timestamp(fresh_fix_reports):
    report = fresh_fix_reports["old"]
    assert report["newCalls"] == [{"maximumAge": 0, "timeout": 4000}], report["newCalls"]
    assert report["hasLocation"] and report["sentTimestamp"] is not None
    assert report["pageNow"] - report["sentTimestamp"] < 5000, (report["pageNow"], report["sentTimestamp"])
    assert report["elapsedMs"] < 3500


@pytest.mark.parametrize("which", ["hang", "fail"])
def test_a_failed_or_timed_out_fix_still_lets_the_first_poll_go_ahead(fresh_fix_reports, which):
    report = fresh_fix_reports[which]
    assert report["newCalls"] == [{"maximumAge": 0, "timeout": 4000}]
    assert report["url"], "the poll never went out"
    assert report["pageNow"] - report["sentTimestamp"] > 100000  # the old fix is still what was sent
    if which == "hang":
        assert 3500 <= report["elapsedMs"] < 9000, report["elapsedMs"]  # after the 4 s timer, not before
    else:
        assert report["elapsedMs"] < 3500  # the error answers at once


def test_a_recent_fix_does_not_wait_or_ask_for_another(fresh_fix_reports):
    report = fresh_fix_reports["recent"]
    assert report["newCalls"] == [] and report["elapsedMs"] < 3500
    assert report["pollMs"] == 20000


def test_with_the_model_path_off_the_page_makes_no_explain_call(app):
    report = run_scenario("nomodel", app)["result"]
    assert report["modelEnabled"] is False and report["pageFlag"] is False
    assert report["calls"] == [], report["calls"]
    assert report["text"].startswith("The bus is ")  # the card still shows Python's text


def test_a_late_model_reply_for_an_older_poll_is_ignored_and_the_text_follows_the_tile(app, monkeypatch):
    monkeypatch.setenv("AI_EXPLANATION_ENABLED", "true")  # the server reads it per request: the pack then says model_enabled
    report = run_scenario("explainsnap", app)["result"]
    assert report["firstPack"]["keys"] == ["chosen_action", "reason_code"]
    assert report["s1"] != report["s2"], "two polls must have two snapshot keys"
    assert report["firstRequest"]["snapshot"] == report["s1"]
    assert set(report["firstRequest"]["fact_sheet"]) == {"reason_code", "chosen_action"}
    assert report["pendingAfterPoll"] is True
    late = report["afterLate"]
    assert late["advice"] is None and "alert before leaving" not in late["text"], late
    assert late["text"].startswith("The bus is") and "It is advisable" not in late["text"]
    assert late["secondBody"]["snapshot"] == report["s2"]  # the newer poll asks for its own clause
    match = report["afterMatch"]
    assert match["advice"].startswith("wait for your leave-by alert and keep") and match["advice"] not in match["text"]
    assert match["text"] == late["text"]  # a model clause never changes the card text
    assert report["tile"]["text"].startswith("The bus is 7 minutes away, and you are ")
    assert report["tile"]["sub"] == "Arriving in 7 min"
    assert report["cleared"] == ""


def test_the_location_card_states_the_reason_the_server_gave_and_no_card_when_there_is_none(app):
    report = run_scenario("locationcard", app)["result"]
    cards = report["cards"]
    # The phone thinks its fix is fresh and accurate (the old fall-through printed "GPS accuracy is 22 m" here).
    assert report["phone"]["accuracy"] < 100 and report["phone"]["ageMs"] < 60000
    assert cards["age"]["hidden"] is False and "hasn't updated for 95 s" in cards["age"]["body"]
    assert "GPS accuracy" not in cards["age"]["body"]
    assert cards["accuracy"]["hidden"] is False and "Your GPS accuracy is 140 m" in cards["accuracy"]["body"]
    assert cards["both"]["hidden"] is False and "Your GPS accuracy is 140 m" in cards["both"]["body"]
    assert cards["neither-uncertain"]["hidden"] is True and cards["neither-live"]["hidden"] is True
    assert cards["age"]["title"] == "Location uncertain"
