"""What the planner says when it finds nothing, by priority and by cause (plan: Priority select, section 4.9).

Causes: a walk-only OneMap answer (`no_service`), a 404 or an empty plan (`no_feasible_route`), and every itinerary dropped
for hours (`no_service`). Each is tried at an open hour and at a closed hour, for each of the five priorities. The
OneMap fixtures are the planner's own; nothing here calls OneMap."""

import re
from datetime import datetime
from pathlib import Path

import pytest

import pt_plan
import service_hours
import test_pt_plan as base
from test_pt_plan import SGT, Server, ok, plan, rail_table

ROOT = Path(__file__).resolve().parents[1]
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")

OPEN = datetime(2026, 10, 12, 8, 30, tzinfo=SGT)    # Monday morning
CLOSED = datetime(2026, 10, 13, 1, 0, tzinfo=SGT)   # Tuesday 01:00: after the last bus and the last train
ANY = ("fastest", "fewest_transfers", "least_walking")
ALL = ANY + ("bus_only", "mrt_only")
_ORIGINAL_LTA = base.lta


def _hours(cache, first, last):
    for row in cache.routes:
        for day in ("WD", "SAT", "SUN"):
            row[f"{day}_FirstBus"], row[f"{day}_LastBus"] = first, last
    return cache


@pytest.fixture(autouse=True)
def bus_hours(monkeypatch):
    """Every bus runs 05:00 to 24:00, so Tuesday 01:00 is closed and Monday 08:30 is open."""
    monkeypatch.setattr(base, "lta", lambda: _hours(_ORIGINAL_LTA(), "0500", "2400"))


def _table(**extra):
    hours = {"WD": ("0500", "2430"), "SAT": ("0500", "2430"), "SUN": ("0500", "2430")}
    return rail_table(NS22={"Marina South Pier": hours}, **extra)


def _walk_only(priority, now):
    return plan(Server(default=ok("night")), fixture="night", priority=priority, now=now, rail=_table())


def _no_route(priority, now):
    return plan(Server(default=(404, {"error": "none"})), fixture="night", priority=priority, now=now, rail=_table())


def _expect(priority, status, closed):
    if priority == "mrt_only":
        return pt_plan.NO_MRT_CLOSED_MESSAGE if closed else pt_plan.NO_MRT_ONLY_MESSAGE
    if priority == "bus_only":
        return pt_plan.NO_BUS_CLOSED_MESSAGE if closed else pt_plan.NO_BUS_ONLY_MESSAGE
    return pt_plan.NO_SERVICE_MESSAGE if status == "no_service" else pt_plan.NO_ROUTE_MESSAGE


@pytest.mark.parametrize("priority", ALL)
@pytest.mark.parametrize("now,closed", [(OPEN, False), (CLOSED, True)], ids=["open", "closed"])
def test_a_walk_only_answer_is_no_service_with_the_priority_sentence(priority, now, closed):
    result = _walk_only(priority, now)
    assert result["route_status"] == "no_service" and result["option"] is None
    assert result["message"] == _expect(priority, "no_service", closed), result["message"]
    assert result["stopped"] is (closed and priority in ("bus_only", "mrt_only"))


@pytest.mark.parametrize("priority", ALL)
@pytest.mark.parametrize("now,closed", [(OPEN, False), (CLOSED, True)], ids=["open", "closed"])
def test_a_404_is_no_feasible_route_with_the_priority_sentence(priority, now, closed):
    result = _no_route(priority, now)
    assert result["route_status"] == "no_feasible_route" and result["option"] is None
    assert result["message"] == _expect(priority, "no_feasible_route", closed), result["message"]
    assert result["stopped"] is (closed and priority in ("bus_only", "mrt_only"))


def test_the_three_general_priorities_never_name_a_single_mode():
    for priority in ANY:
        for now in (OPEN, CLOSED):
            message = _walk_only(priority, now)["message"]
            assert message == "No services to this destination right now."
            assert "buses are running" not in message and "stopped" not in message


def test_the_old_bus_only_sentence_is_gone_from_the_onemap_planner():
    assert pt_plan.NO_SERVICE_MESSAGE != "No service to this destination right now."
    for priority in ALL:
        for result in (_walk_only(priority, OPEN), _walk_only(priority, CLOSED), _no_route(priority, OPEN)):
            assert result["message"] != "No service to this destination right now."


def _late(keep):
    return base._late_itinerary(keep)


def test_every_itinerary_dropped_for_hours_says_the_chips_closed_words_only_when_the_whole_mode_is_closed():
    now = datetime(2026, 10, 13, 0, 15, tzinfo=SGT)
    closed_table = rail_table(NS22={"Marina South Pier": {"WD": ("0530", "2315"), "SAT": ("0530", "2315"), "SUN": ("0530", "2315")}})
    result = plan(Server({"RAIL": [_late([0])]}), fixture="late", priority="mrt_only", now=now, rail=closed_table)
    assert result["route_status"] == "no_service" and result["dropped"]["hours"] == 1
    assert result["message"] == pt_plan.NO_MRT_CLOSED_MESSAGE and result["stopped"] is True
    # another station is still running: this trip's train has gone, but MRT and LRT have not stopped for now
    still = rail_table(NS22={"Marina South Pier": {"WD": ("0530", "2315"), "SAT": ("0530", "2315"), "SUN": ("0530", "2315")}},
                       EW27={"Pasir Ris": {"WD": ("0500", "2900"), "SAT": ("0500", "2900"), "SUN": ("0500", "2900")}})
    result = plan(Server({"RAIL": [_late([0])]}), fixture="late", priority="mrt_only", now=now, rail=still)
    assert result["route_status"] == "no_service" and result["message"] == pt_plan.NO_MRT_ONLY_MESSAGE
    assert result["stopped"] is False
    # the same drop for a general priority reads the general sentence
    general = plan(Server(default=_late([0])), fixture="late", priority="fastest", now=now, rail=closed_table)
    assert general["route_status"] == "no_service" and general["message"] == pt_plan.NO_SERVICE_MESSAGE
    assert general["stopped"] is False


def test_bus_only_with_every_bus_dropped_for_hours_says_stopped_when_no_bus_runs():
    now = datetime(2026, 10, 13, 0, 15, tzinfo=SGT)
    result = plan(Server({"BUS": [_late([1])]}), fixture="late", priority="bus_only", now=now, rail=_table())
    assert result["route_status"] == "no_service" and result["dropped"]["hours"] == 1
    assert result["message"] == pt_plan.NO_BUS_CLOSED_MESSAGE and result["stopped"] is True


def test_a_pool_of_the_wrong_mode_is_the_chips_no_route_sentence_not_stopped():
    wrong = plan(Server({"RAIL": [ok("direct_bus")]}), fixture="direct_bus", priority="mrt_only", now=OPEN, rail=_table())
    assert wrong["route_status"] == "no_feasible_route" and wrong["message"] == pt_plan.NO_MRT_ONLY_MESSAGE
    assert wrong["stopped"] is False


# ---- the timetable questions ------------------------------------------------------------------------------


def test_bus_closed_at_is_true_only_when_hours_are_readable_and_none_runs():
    cache = _hours(_ORIGINAL_LTA(), "0500", "2400")
    assert service_hours.bus_closed_at(cache, OPEN) is False
    assert service_hours.bus_closed_at(cache, CLOSED) is True
    unknown = _ORIGINAL_LTA()
    for row in unknown.routes:
        for day in ("WD", "SAT", "SUN"):
            row[f"{day}_FirstBus"] = row[f"{day}_LastBus"] = "-"
    assert service_hours.bus_closed_at(unknown, CLOSED) is False  # no readable hours is not "closed"
    assert service_hours.bus_closed_at(None, CLOSED) is False


def test_rail_closed_at_is_true_only_when_hours_are_readable_and_no_train_leaves():
    table = _table()
    assert service_hours.rail_closed_at(table, OPEN) is False
    assert service_hours.rail_closed_at(table, CLOSED) is True
    assert service_hours.rail_closed_at(None, CLOSED) is False and service_hours.rail_closed_at({}, CLOSED) is False
    one_open = _table(EW27={"Pasir Ris": {"WD": ("0500", "2900")}})
    assert service_hours.rail_closed_at(one_open, datetime(2026, 10, 13, 1, 0, tzinfo=SGT)) is False


def test_the_closed_check_does_not_touch_the_missing_hours_counters():
    service_hours.reset_missing_hours_count()
    service_hours.reset_missing_rail_hours_count()
    _walk_only("bus_only", CLOSED)
    _walk_only("mrt_only", CLOSED)
    assert service_hours.missing_hours_count() == 0 and service_hours.missing_rail_hours_count() == 0


# ---- python and the page say the same ---------------------------------------------------------------------


PAIRS = {  # pt_plan constant: (copy.js journeyOverview key, the page constant)
    "NO_SERVICE_MESSAGE": ("noServiceAny", "JO_NO_SERVICE_ANY"),
    "NO_BUS_CLOSED_MESSAGE": ("noBusClosed", "JO_NO_BUS_CLOSED"),
    "NO_MRT_CLOSED_MESSAGE": ("noMrtClosed", "JO_NO_MRT_CLOSED"),
    "NO_BUS_ONLY_MESSAGE": ("noBusOnly", "JO_NO_BUS_ONLY"),
    "NO_MRT_ONLY_MESSAGE": ("noMrtOnly", "JO_NO_MRT_ONLY"),
    "NO_ROUTE_MESSAGE": ("noRouteFound", "JO_NO_ROUTE_FOUND"),
}


def test_python_copy_js_and_the_page_say_the_same_words():
    jo = COPY.split("journeyOverview: {", 1)[1].split("\n  },", 1)[0]
    for constant, (key, variable) in PAIRS.items():
        python = getattr(pt_plan, constant)
        copy_value = re.search(rf'\b{key}: "((?:[^"\\]|\\.)*)"', jo).group(1)
        page_value = re.search(rf'var {variable} = "((?:[^"\\]|\\.)*)";', INDEX).group(1)
        assert python == copy_value == page_value, (constant, python, copy_value, page_value)


def test_the_static_planner_keeps_its_bus_only_sentence_in_copy_js_and_the_page():
    jo = COPY.split("journeyOverview: {", 1)[1].split("\n  },", 1)[0]
    assert 'noService: "No service to this destination right now."' in jo
    assert 'var JO_NO_SERVICE_STATIC = "No service to this destination right now.";' in INDEX
    text = INDEX.split("function noServiceText(body) {", 1)[1].split("function syncOverviewArrive", 1)[0]
    assert 'body.planner !== "onemap"' in text and "JO_NO_SERVICE_STATIC" in text and "JO_NO_SERVICE_ANY" in text


def test_the_plan_and_the_style_guide_carry_the_words():
    for text in (pt_plan.NO_SERVICE_MESSAGE, pt_plan.NO_BUS_CLOSED_MESSAGE, pt_plan.NO_MRT_CLOSED_MESSAGE,
                 "`stopped`", "bus_closed_at", "rail_closed_at"):
        assert text in PLAN, text
    for key in ("noServiceAny", "noBusClosed", "noMrtClosed"):
        assert f"jo.{key}" in GUIDE, key
