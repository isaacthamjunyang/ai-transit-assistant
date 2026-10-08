"""The Custom arrive-by control: a time input and a Today / Tomorrow toggle, in Singapore time.

The browser part drives the real page in headless Edge with a fake clock and a Los Angeles time zone
(tests/js/scenarios/arrivecustom.mjs). The source checks pin the markup, the copy and the style guide.
"""

import re
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

import lta_static
from lta_static import write_cache
from main import app
from page_runner import require_edge, run_scenario, running_app
from test_journey import PLACE, USER, _route, _stop

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
PAST = "That time has already passed today. Choose Tomorrow or a later time."
FAR = "That time is more than 24 hours away. Choose an earlier time."
NB = " "


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("arrivecustom"), eta_minutes=[10.3]) as base:
        return run_scenario("arrivecustom", base, {"zone": "America/Los_Angeles"})["result"]


# ---- the controls

def test_no_date_control_or_datetime_local_input_anywhere():
    assert "datetime-local" not in INDEX and 'type="date"' not in INDEX and "showPicker" not in INDEX
    assert "datetime-local" not in CSS


def test_the_browser_has_one_time_input_and_no_date_input_on_home_and_on_confirm(report):
    controls = report["controls"]
    assert controls["dateInputs"] == 0 and controls["timeInputs"] == 1 and controls["timeType"] == "time"
    confirm = report["confirm"]
    assert confirm["inSlot"] is True and confirm["timeInputs"] == 1 and confirm["dateInputs"] == 0  # one shared component


def test_the_toggle_has_only_today_and_tomorrow_and_is_a_labelled_radiogroup(report):
    controls = report["controls"]
    assert controls["options"] == ["Today", "Tomorrow"]
    assert controls["group"] == "radiogroup|Arrive by day"
    assert controls["labels"] == ["Arrive today", "Arrive tomorrow"]
    assert controls["state"]["day"] == "today" and controls["state"]["today"] == "true" and controls["state"]["tomorrow"] == "false"


def test_each_option_and_the_time_input_are_at_least_44_px_high(report):
    assert all(height >= 44 for height in report["controls"]["heights"]), report["controls"]["heights"]


def test_the_selected_day_has_a_thicker_border_and_bold_text_and_no_tick(report):
    selected = CSS.split(".arrive-day__option.is-selected {", 1)[1].split("}", 1)[0]
    assert "font-weight: 700" in selected and "border-color: var(--color-selected-outline)" in selected
    assert "box-shadow: 0 0 0 2px var(--color-selected-outline)" in selected  # on top of the 1 px border
    for tick in ("2713", "2714", "\u2713", "\u2714", "\u2705"):
        assert tick not in CSS and tick not in INDEX and tick not in COPY, tick
    assert "::before" not in CSS.split(".arrive-day {", 1)[1].split(".arrive-chip {", 1)[0]
    sample = GUIDE.split('class="arrive-day"', 1)[1].split("</div>", 1)[0]
    assert "\u2713" not in sample and "✓" not in sample and "✔" not in sample
    assert report["afterArrow"] == {"day": "tomorrow", "focus": "arrive-day-tomorrow"}


def test_aria_checked_follows_the_selection_and_the_weight_and_ring_change(report):
    toggle = report["toggle"]
    assert toggle["today"] == {"checked": "true", "weight": "700", "ring": True, "content": "none"}
    assert toggle["tomorrow"] == {"checked": "false", "weight": "400", "ring": False, "content": "none"}
    assert toggle["afterTomorrow"]["tomorrow"]["checked"] == "true" and toggle["afterTomorrow"]["tomorrow"]["weight"] == "700"
    assert toggle["afterTomorrow"]["today"]["checked"] == "false" and toggle["afterTomorrow"]["today"]["weight"] == "400"


def test_toggling_the_day_changes_no_width_height_or_position(report):
    toggle = report["toggle"]
    assert toggle["boxesToday"] == toggle["boxesTomorrow"], toggle  # the same boxes whichever is selected
    assert toggle["boxesToday"][0][2] == toggle["boxesToday"][1][2]  # the two options are equally wide
    assert toggle["panelWidthToday"] == toggle["panelWidthTomorrow"]


def test_the_control_uses_only_tokens_and_the_existing_chip():
    block = CSS.split(".arrive-custom {", 1)[1].split(".arrive-chip {", 1)[0]
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", block)
    assert 'class="arrive-chip arrive-day__option' in INDEX and 'style="' not in INDEX.split('id="arrive-by-custom"', 1)[1][:1500]


# ---- 11:50 PM in Singapore, phone in Los Angeles

def test_at_11_50_pm_tomorrow_12_10_am_works_and_reads_tomorrow(report):
    case = report["cases"]["midnight"]
    assert report["browserZone"] == "America/Los_Angeles"
    assert case["value"] == "2026-10-09T00:10" and case["day"] == "tomorrow" and case["errorHidden"] is True
    assert case["confirmDisabled"] is False and case["picked"] is True
    assert report["cases"]["midnightClock"] == f"12:10{NB}AM (tomorrow)"
    assert case["chosen"] == f"Arrive by: 12:10{NB}AM (tomorrow)"  # the overview line keeps its "(tomorrow)"
    assert "(tomorrow)" in case["display"]  # the header line keeps its "(tomorrow)"


def test_today_with_a_passed_time_shows_the_message_and_keeps_confirm_disabled(report):
    case = report["cases"]["midnightToday"]  # Today 12:10 AM at 11:50 PM
    assert case["day"] == "today" and case["value"] == "" and case["picked"] is False
    assert case["errorHidden"] is False and case["error"] == PAST
    assert case["confirmDisabled"] is True and case["findRoute"] == "true"
    past = report["cases"]["pastToday"]  # 5:00 PM at 6:00 PM
    assert past["error"] == PAST and past["errorHidden"] is False and past["confirmDisabled"] is True
    assert past["day"] == "today"  # not switched silently
    assert past["value"] == ""


def test_a_late_time_today_is_fine(report):
    case = report["cases"]["midnightTodayLate"]
    assert case["value"] == "2026-10-08T23:55" and case["errorHidden"] is True and case["confirmDisabled"] is False


def test_choosing_tomorrow_fixes_a_passed_time(report):
    case = report["cases"]["pastThenTomorrow"]
    assert case["value"] == "2026-10-09T17:00" and case["errorHidden"] is True and case["confirmDisabled"] is False


def test_more_than_24_hours_ahead_shows_its_own_message_and_disables_confirm(report):
    for name in ("midnightTooFar", "tooFarTomorrow"):
        case = report["cases"][name]
        assert case["error"] == FAR and case["errorHidden"] is False and case["confirmDisabled"] is True, name
        assert case["value"] == "" and case["picked"] is False


def test_an_empty_time_keeps_confirm_disabled_without_a_message(report):
    case = report["cases"]["empty"]
    assert case["value"] == "" and case["confirmDisabled"] is True and case["errorHidden"] is True
    assert case["customVisible"] is True


# ---- presets

def test_a_preset_after_midnight_selects_tomorrow_and_custom_shows_it(report):
    p30, p60 = report["cases"]["preset30"], report["cases"]["preset60"]
    assert p30["value"] == "2026-10-09T00:20" and p30["day"] == "tomorrow" and p30["time"] == "00:20"
    assert p60["value"] == "2026-10-09T00:50" and p60["day"] == "tomorrow" and p60["time"] == "00:50"
    shown = report["cases"]["preset30InCustom"]  # opening Custom afterwards
    assert shown["customVisible"] is True and shown["time"] == "00:20" and shown["tomorrow"] == "true"
    assert shown["value"] == "2026-10-09T00:20" and shown["confirmDisabled"] is False


def test_a_preset_in_the_afternoon_selects_today(report):
    case = report["cases"]["preset30Afternoon"]
    assert case["value"] == "2026-10-08T15:30" and case["day"] == "today" and case["time"] == "15:30"
    assert case["today"] == "true" and case["tomorrow"] == "false"


# ---- Singapore date, not the phone's

def test_the_singapore_date_is_used_when_the_phone_is_in_another_zone(report):
    # 7:30 AM on Oct 9 in Singapore is 4:30 PM on Oct 8 in Los Angeles
    assert report["localDate"] == "2026-10-08" and report["singaporeDay"] == "2026-10-09"
    assert report["cases"]["singaporeToday"]["value"] == "2026-10-09T08:00"
    tomorrow = report["cases"]["singaporeTomorrow"]  # Oct 10 08:00 is 24.5 h after Oct 9 07:30: over the limit
    assert tomorrow["value"] == "" and tomorrow["error"] == FAR and tomorrow["day"] == "tomorrow"


def test_the_page_never_builds_the_value_from_the_phones_date():
    block = INDEX.split("function singaporeDay(offsetDays)", 1)[1].split("function arriveCustomResult", 1)[0]
    assert "singapore24(new Date())" in block and "getDate" not in block and "toISOString" not in block
    result = INDEX.split("function arriveCustomResult()", 1)[1].split("function renderArriveDay", 1)[0]
    assert '+ "T" + time' in result and ':00+08:00' in result and "getDate" not in result


# ---- copy and style guide

def test_the_messages_and_labels_are_in_copy_js_and_the_page():
    for text in (PAST, FAR):
        assert text in COPY and text in INDEX, text
    for text in ('dayToday: "Today"', 'dayTomorrow: "Tomorrow"', 'timeLabel: "Time"'):
        assert text in COPY, text


def test_the_style_guide_shows_the_custom_control_with_both_messages():
    assert 'type="time"' in GUIDE and "datetime-local" not in GUIDE
    assert 'data-copy="arriveBy.dayToday"' in GUIDE and 'data-copy="arriveBy.dayTomorrow"' in GUIDE
    assert 'data-copy="arriveBy.past"' in GUIDE and 'data-copy="arriveBy.tooFar"' in GUIDE


# ---- the server today: static messages that never echo the input

def test_the_server_never_echoes_a_bad_arrive_by(tmp_path, monkeypatch):
    write_cache(tmp_path, [_stop("D", *PLACE, "Dest")], [_route("36", 1, "D", 0)], [])
    monkeypatch.setattr(lta_static, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(httpx, "Client", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no live client")))
    secret = "SECRET-not-a-time-9731"
    with TestClient(app) as client:
        response = client.get("/api/journey", params={
            "dest_lat": PLACE[0], "dest_lon": PLACE[1], "user_lat": USER[0], "user_lon": USER[1],
            "destination_stop_code": "D", "boarding_stop_code": "B", "service_no": "36", "arrive_by": secret,
        })
    assert response.status_code == 422 and secret not in response.text and "9731" not in response.text


# ---- the prefill: Singapore now + 5 minutes, rounded up to the whole minute, valid at once

def test_custom_opens_prefilled_with_singapore_now_plus_5_rounded_up(report):
    mid = report["prefill"]["mid"]  # 6:00:10 PM + 5 min = 6:05:10 PM, rounded up to 6:06 PM
    assert mid["time"] == "18:06" and mid["day"] == "today" and mid["value"] == "2026-10-08T18:06"
    assert report["prefill"]["lateInMinute"]["time"] == "18:06"  # 6:05:45 PM rounds up to 6:06 PM


def test_the_prefill_uses_singapore_time_when_the_phone_is_in_los_angeles(report):
    shown = report["prefill"]["singapore"]  # 7:30:10 AM on Oct 9 in Singapore, 4:30 PM on Oct 8 in Los Angeles
    assert report["browserZone"] == "America/Los_Angeles"
    assert shown["time"] == "07:36" and shown["value"] == "2026-10-09T07:36" and shown["day"] == "today"


def test_crossing_midnight_the_prefill_selects_tomorrow(report):
    shown = report["prefill"]["midnight"]  # 11:58:10 PM + 5 min = 12:03:10 AM, rounded up to 12:04 AM
    assert shown["time"] == "00:04" and shown["day"] == "tomorrow" and shown["value"] == "2026-10-09T00:04"
    assert shown["tomorrow"] == "true" and shown["today"] == "false"


def test_the_prefilled_value_is_valid_and_the_buttons_are_enabled_on_open(report):
    for name in ("mid", "lateInMinute", "singapore", "midnight"):
        shown = report["prefill"][name]
        assert shown["errorHidden"] is True and shown["confirmDisabled"] is False, name
        assert shown["picked"] is True and shown["customVisible"] is True, name
        assert shown["display"].startswith("Custom") and ":" in shown["display"], name  # the header line shows the time again


def test_the_old_arrive_by_line_is_gone_and_the_hint_is_gone_everywhere():
    assert 'id="arrive-by-resolved"' not in INDEX and "arrive-by-resolved" not in INDEX
    assert 'resolved: "Arrive by {time}"' not in COPY
    for source in (INDEX, COPY, GUIDE, CSS, (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")):
        assert "Adjust the time to continue" not in source and "adjustHint" not in source and "arrive-by-hint" not in source
    assert "arriveUntouched" not in INDEX


def test_the_browser_page_has_no_old_line_and_no_hint(report):
    assert report["prefill"]["mid"]["resolvedGone"] is True


# ---- nothing under the time field except the passed-time message

def test_nothing_is_shown_under_the_time_field_and_there_is_no_from_now_text(report):
    shown = report["nothingUnder"]
    assert shown["underField"] == [] and shown["fromNowAnywhere"] is False
    assert shown["describedBy"] == "arrive-by-error"  # only the message, no stale reference
    assert report["prefill"]["mid"]["fromNowAnywhere"] is False


def test_no_from_now_wording_remains_in_the_page_copy_style_guide_css_or_plan():
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    for source in (INDEX, COPY, GUIDE, CSS, plan):
        for gone in ("from now", "fromNow", "unitMin", "unitHr", "arrive-when", "arrive-by-when", "renderArriveWhen",
                     "arriveSpanText", "arriveMinutesFromNow", "ARRIVE_FROM_NOW", "arriveWhenTick"):
            assert gone not in source, gone


def test_the_time_input_has_no_wrapper_or_in_field_span_and_describes_itself_with_the_message_only():
    assert re.search(r'<div class="arrive-custom">\s*<label[^>]*>[^<]*</label>\s*<input id="arrive-by-time" class="arrive-time" type="time"[^>]*aria-describedby="arrive-by-error">\s*<div id="arrive-day"', INDEX)
    block = CSS.split(".arrive-time {", 1)[1].split("}", 1)[0]
    assert "min-height: var(--tap-min)" in block and "width:" not in block and "padding" not in block


def test_the_passed_time_message_still_works_and_the_minute_recheck_is_kept_for_it(report):
    past = report["whenPast"]  # Today 5:30 PM at 6:00 PM
    assert past["error"] == PAST and past["errorHidden"] is False and past["confirmDisabled"] is True
    tomorrow = report["whenTomorrow"]  # Tomorrow 5:30 PM, 23 h 30 min ahead: valid
    assert tomorrow["errorHidden"] is True and tomorrow["confirmDisabled"] is False
    assert report["whenBefore"]["errorHidden"] is True and report["whenTick"]["errorHidden"] is True
    passed = report["whenPassed"]  # the clock passed 6:30 PM while the page sat open
    assert passed["error"] == PAST and passed["errorHidden"] is False and passed["confirmDisabled"] is True
    block = INDEX.split("function arriveRecheckTick()", 1)[1].split("function showArriveProblem", 1)[0]
    assert "60000 - (Date.now() % 60000)" in block and "onArriveCustomEdit()" in block


def test_a_presets_time_and_a_time_the_user_chose_are_not_overwritten(report):
    prefill = report["prefill"]
    assert prefill["preset"]["time"] != "" and prefill["presetKept"]["time"] == prefill["preset"]["time"]
    assert prefill["presetKept"]["value"] == prefill["preset"]["value"] and prefill["presetKept"]["day"] == "today"
    assert prefill["userKept"]["time"] == "16:45" and prefill["userKept"]["value"] == "2026-10-08T16:45"


def test_no_target_clears_the_time_and_the_next_custom_prefills_again(report):
    prefill = report["prefill"]
    assert prefill["none"]["time"] == "" and prefill["none"]["value"] == ""
    assert prefill["afterNone"]["time"] == "15:06" and prefill["afterNone"]["value"] == "2026-10-08T15:06"
    assert prefill["afterClear"]["time"] == "15:06"  # an emptied time is prefilled when Custom is opened


def test_when_the_clock_passes_the_chosen_time_the_message_and_disabled_confirm_apply(report):
    passed = report["prefill"]["clockPassed"]  # the user typed 3:05 PM, the clock is now 3:07 PM
    assert passed["error"] == PAST and passed["errorHidden"] is False
    assert passed["confirmDisabled"] is True and passed["value"] == "" and passed["day"] == "today"


def test_the_prefill_code_only_fills_an_empty_time_and_rounds_up():
    block = INDEX.split("function prefillArriveTime()", 1)[1].split('document.getElementById("arrive-custom")', 1)[0]
    assert "if (arriveTimeInput.value) {" in block and "return;" in block.split("Math.ceil", 1)[0]
    assert "Math.ceil((Date.now() + ARRIVE_PREFILL_MIN * 60000) / 60000) * 60000" in block
    assert "ARRIVE_PREFILL_MIN = 5" in INDEX


def test_the_plan_says_nothing_is_shown_under_the_time_field():
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    assert "Nothing is shown under the time field except" in plan and "5 minutes ahead, rounded up to the whole minute" in plan
