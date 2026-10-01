"""Pace guidance is a display hint. It does not change the catch numbers."""

import re
from pathlib import Path

from explain import UNSAFE_PHRASES
from pace import PaceSession, pace_guidance

ROOT = Path(__file__).resolve().parents[1]

PACE_LINES = (
    "Walk slower",
    "You have time. A relaxed pace should still work.",
    "Walk slightly slower",
    "You can ease your pace a little.",
    "Keep a steady pace",
    "A normal walking pace works.",
    "Walk slightly faster",
    "A slightly brisker walk improves your chances.",
    "Walk faster",
    "A brisk walk improves your chances. Stay on footpaths and use crossings.",
    "Unlikely at a normal pace",
    "Walking faster is unlikely to be enough. Check the reroute options or the next bus.",
)


def _pace(**overrides):
    values = {
        "point": 70,
        "range_low": 60,
        "range_high": 85,
        "data_quality": "live",
        "location_uncertain": False,
        "distance_to_stop_m": 100,
        "previous_category": None,
    }
    values.update(overrides)
    return pace_guidance(**values)


def test_category_boundaries():
    assert _pace(point=49, range_low=40, range_high=60) == "faster"
    assert _pace(point=50, range_low=40, range_high=60) == "slightly_faster"
    assert _pace(point=64, range_low=40, range_high=80) == "slightly_faster"
    assert _pace(point=65, range_low=50, range_high=80) == "steady"
    assert _pace(point=79, range_low=60, range_high=90) == "steady"
    assert _pace(point=80, range_low=60, range_high=90) == "slightly_slower"
    assert _pace(point=70, range_low=60, range_high=39) == "unlikely"
    assert _pace(point=70, range_low=60, range_high=40) == "steady"
    assert _pace(point=70, range_low=74, range_high=90) == "steady"
    assert _pace(point=70, range_low=75, range_high=90) == "slower"


def test_hidden_conditions():
    assert _pace(data_quality="stale") is None
    assert _pace(data_quality="unavailable") is None
    assert _pace(location_uncertain=True) is None
    assert _pace(distance_to_stop_m=29) is None
    assert _pace(distance_to_stop_m=30) == "steady"


def test_schedule_never_suggests_slower():
    assert _pace(point=90, range_low=85, range_high=90, data_quality="schedule") == "steady"
    assert _pace(point=80, range_low=70, range_high=90, data_quality="schedule") == "steady"
    assert _pace(point=49, range_low=40, range_high=55, data_quality="schedule") == "faster"


def test_slower_waits_for_two_consecutive_polls_and_faster_does_not():
    session = PaceSession()
    steady = dict(point=70, range_low=60, range_high=85, data_quality="live", location_uncertain=False, distance_to_stop_m=100)
    slower = dict(point=70, range_low=75, range_high=90, data_quality="live", location_uncertain=False, distance_to_stop_m=100)
    faster = dict(point=49, range_low=40, range_high=60, data_quality="live", location_uncertain=False, distance_to_stop_m=100)
    slightly = dict(point=55, range_low=45, range_high=70, data_quality="live", location_uncertain=False, distance_to_stop_m=100)
    unlikely = dict(point=30, range_low=10, range_high=39, data_quality="live", location_uncertain=False, distance_to_stop_m=100)

    assert session.poll(**steady) == "steady"
    assert session.poll(**slower) == "steady"
    assert session.poll(**slower) == "slower"
    assert session.poll(**faster) == "faster"
    assert session.poll(**slightly) == "slightly_faster"
    assert session.poll(**unlikely) == "unlikely"


def test_slightly_slower_also_waits_for_two_polls():
    session = PaceSession()
    steady = dict(point=70, range_low=60, range_high=85, data_quality="live", location_uncertain=False, distance_to_stop_m=100)
    ease = dict(point=80, range_low=60, range_high=90, data_quality="live", location_uncertain=False, distance_to_stop_m=100)
    assert session.poll(**steady) == "steady"
    assert session.poll(**ease) == "steady"
    assert session.poll(**ease) == "slightly_slower"


def test_state_resets_at_journey_start_reroute_and_leg_change():
    slower = dict(point=70, range_low=75, range_high=90, data_quality="live", location_uncertain=False, distance_to_stop_m=100)
    for _label in ("journey start", "reroute", "leg change"):
        session = PaceSession()
        session.poll(point=70, range_low=60, range_high=85, data_quality="live", location_uncertain=False, distance_to_stop_m=100)
        session.poll(**slower)
        assert session.display == "steady"
        session.reset()
        assert session.display is None
        assert session.pending is None
        assert session.poll(**slower) == "slower"


def test_pace_copy_avoids_unsafe_language_and_is_in_the_plan():
    copy_js = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    plan = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
    section = plan.split("### Pace guidance", 1)[1].split("\n## ", 1)[0]
    blob = "\n".join(PACE_LINES)
    for line in PACE_LINES:
        assert line in copy_js
        assert line in page
        assert line in section
    for phrase in UNSAFE_PHRASES:
        pattern = r"\b" + re.escape(phrase) + r"\b" if " " not in phrase else re.escape(phrase)
        assert re.search(pattern, blob, flags=re.IGNORECASE) is None
        assert re.search(pattern, section, flags=re.IGNORECASE) is None
