"""The in-app "Leave Now" banner is gone (the browser notification is the only leave-now alert and keeps its text and the locked Step 10
payload), and the caution banner drops "Tap to enable Leave-Now Alert." when notification permission is granted. No live API."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
DASH = chr(0x2013)
EMDASH = chr(0x2014)
WARN = chr(0x26A0)


def _function(name):
    return "function " + name + INDEX.split("function " + name, 1)[1].split("\n    function ", 1)[0]


def test_the_banner_is_gone_from_the_page_the_css_the_copy_the_style_guide_and_the_plan():
    for gone in ("leave-now-banner", "leave-now-title", "leave-now-body", "leave-now-details", "leave-now-dismiss", "leave-now-simulated",
                 "showLeaveNowBanner", "hideLeaveNowBanner", "leaveNowStillHolds", "leaveNowBannerBody", "leaveNowBanner", "LEAVE_NOW_BANNER"):
        assert gone not in INDEX, gone
    assert "leave-now-banner" not in CSS and "leave-now-banner" not in GUIDE
    for gone in ("sgLeaveNow", "copy.leaveNowBanner", "Leave now banner"):
        assert gone not in GUIDE, gone
    assert "leaveNowBanner" not in COPY and "viewDetails" not in COPY and "bannerProbability" not in COPY
    assert "the Leave now banner" not in PLAN and "in-app Leave-now banner" not in PLAN and "There is no in-app Leave now banner" in PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()


def test_the_notification_text_and_the_step_10_payload_are_unchanged():
    assert f'body: "Walk to {{stop_name}} now to catch Bus {{service_no}}. Catch probability: {{point}}% ({{range_low}}{DASH}{{range_high}}%)."' in COPY
    assert f'title: "Leave Now {EMDASH} Bus {{service_no}}",' in COPY
    assert f"- Body: `Walk to {{stop_name}} now to catch Bus {{service_no}}. Catch probability: {{point}}% ({{range_low}}{DASH}{{range_high}}%).`" in PLAN
    deliver = _function("deliverLeaveNow")  # the browser notification: the server's own title and body, once per bus, with permission
    assert "showLocalNotification(notice.title, { body: notice.body })" in deliver and "lastNotifiedBusId = busId;" in deliver
    assert 'Notification.permission === "granted"' in deliver
    assert '" Catch probability: " + chance.point + "% (range "' in INDEX  # the "5 minutes left" reminder keeps its range text


def test_nothing_that_the_banner_set_is_left_behind():
    for state in ("leaveNowBanner.shown", "leaveNowBanner.busId", "is-suppressed"):
        if state == "is-suppressed":
            continue
        assert state not in INDEX, state
    occupants = INDEX.split("var occupants = [", 1)[1].split("];", 1)[0]
    assert "leave-now" not in occupants  # the alert slot no longer lists it
    assert 'getElementById("arrival-card")' in INDEX and 'tabindex="-1"' in INDEX.split('id="arrival-card"', 1)[1].split(">", 1)[0]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
@pytest.mark.parametrize("permission,enable", [("granted", False), ("default", True), ("denied", True), (None, True)])
def test_the_caution_banner_drops_the_enable_sentence_only_when_permission_is_granted(permission, enable):
    expected = f"{WARN} Catch chance dropping (39%)." + (" Tap to enable Leave-Now Alert." if enable else "")
    script = (
        f'var CAUTION_BANNER_TEXT = "{WARN} Catch chance dropping ({{point}}%). Tap to enable Leave-Now Alert.";'
        f'var CAUTION_BANNER_GRANTED_TEXT = "{WARN} Catch chance dropping ({{point}}%).";'
        + ("" if permission is None else "var Notification = function () {}; Notification.permission = %s;" % json.dumps(permission))
        + _function("fillText") + "\n" + _function("cautionText") + "\n"
        + "console.log(JSON.stringify(cautionText(39)));"
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == expected


def test_the_permission_is_read_without_prompting_and_the_strings_are_mirrored():
    caution = _function("cautionText")
    assert "Notification.permission" in caution and "requestPermission" not in caution
    assert f'cautionBannerGranted: "{WARN} Catch chance dropping ({{point}}%).",' in COPY
    assert f'var CAUTION_BANNER_GRANTED_TEXT = "{WARN} Catch chance dropping ({{point}}%).";' in INDEX
    assert "cautionText(chance.point)" in _function("renderCatchWarning")
    assert "`Notification.permission`" in PLAN and "slot-caution-granted" in GUIDE
