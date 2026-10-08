"""Second-stop tracking is gone: no transfer watch, prompt, notification, Leg 2 page or Leg 2 input."""

from pathlib import Path

import explain

ROOT = Path(__file__).resolve().parents[1]
REMOVED = (
    "transferWatch", "stopTransferWatch", "startTransferWatch", "onTransferFix", "onTransferError",
    "fireTransferAlert", "showTransferPrompt", "hideTransferPrompt", "acknowledgeTransferAlert",
    "transferStopInfo", "transferNearCount", "transferNoGps", "transferAlertShown", "syncOnWayNote",
    "openLeg2", "onLeg2", "transfer-top", "transfer-next", "transfer-alert", "on-way-note", "is-leg2",
    "TRANSFER_NEAR_METERS", "TRANSFER_WATCH_MAX_MINUTES", "TRANSFER_BUS_SPEED_MPS", "TRANSFER_NOTE",
    "TRANSFER_PROMPT_TEXT", "TRANSFER_NOTIFICATION", "TRANSFER_NO_GPS", "COUNTED_FIX_MAX_AGE_S",
    "LEG2_REACH_RANGE_FRACTION", "LEG2_CAPTION", "LEG2_REACH_LABEL", "LEG2_SCHEDULE_NOTE", "CATCH_HEADING_LEG2",
    "reach_stop", "_reach_window", "reach_minutes", "reach_speed_m_s", "reach_range_fraction", "reach_distance_m",
    "transferAlert", "transferNote", "leg2Default", "leg2Note", "leg2Headway", "chanceToCatchLeg2",
    "tile-leave-meta",
    "You are reaching the second bus stop", "Get ready to change bus", "Turn on location to get a transfer alert",
    "We'll alert you when you're near", "Reach the stop", "based on how far you are from the stop",
    "Live tracking starts when you reach the transfer stop",
)


def _sources() -> dict[str, str]:
    files = {}
    for path in sorted((ROOT / "static").iterdir()):
        if path.suffix in (".html", ".js", ".css"):
            files[f"static/{path.name}"] = path.read_text(encoding="utf-8")
    for path in sorted(ROOT.glob("*.py")):
        files[path.name] = path.read_text(encoding="utf-8")
    return files


def test_no_removed_identifier_or_string_remains_in_static_or_python():
    for name, text in _sources().items():
        for needle in REMOVED:
            assert needle not in text, (name, needle)


def test_the_service_worker_stays_for_the_leave_now_notification_but_does_not_message_the_page():
    code = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    assert "notificationclick" in code and "postMessage" not in code
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert 'register("/sw.js")' in html and "showLocalNotification(notice.title" in html


def test_the_explanation_has_no_leg_2_variant():
    import inspect

    assert "leg2" not in inspect.signature(explain.sentence_two).parameters
    assert not hasattr(explain, "parse_context")  # the page sends the model no context at all
    assert "reach_distance_m" not in inspect.signature(explain.build_poll_explanation).parameters
