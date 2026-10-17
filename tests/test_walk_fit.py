"""Page W's map fit in the real page: both markers in view at every distance, the zoom, the Range chip, the stop chip,
the user-moved flag, a real pan, open-back-open, and Page B's map (no hidden-container problem).

Cause of the "whole island" bug: Page B's fit (fitLiveView) ran on the one-second display tick while Page W was showing and
replaced Page W's view (a different maxZoom and padding, and the live bus, which can be kilometres away).
"""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

INDEX = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def fit(tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("fit"), eta_minutes=[10.3]) as base:
        return run_scenario("walkfit", base, {"dark": True})["result"]


def _chip_metres(text):
    number, unit = re.search(r"Range: ([\d.]+) (m|km)", text).groups()
    return float(number) * (1000 if unit == "km" else 1)


@pytest.mark.parametrize("metres", ["8", "12", "20", "24", "25", "59", "300", "1200", "5000"])
def test_both_markers_are_inside_the_map_at_every_distance(fit, metres):
    v = fit["distances"][metres]
    assert v["top"] == "walk" and v["youInside"] is True and v["stopInside"] is True, v
    assert v["size"][0] > 200 and v["size"][1] > 200  # the map has its real size
    assert v["lineVisible"] is True and v["labelOverlapsYou"] is False, v  # the dashed line, and the chip clear of You
    assert v["moved"] is False  # the programmatic fit did not set the user-moved flag


@pytest.mark.parametrize("metres", ["12", "20", "24", "25", "59", "300"])
def test_markers_under_300_m_are_at_least_40_px_apart_and_the_range_chip_is_small(fit, metres):
    v = fit["distances"][metres]
    assert v["apart"] >= 40, v
    assert _chip_metres(v["chip"]) <= 1000
    assert v["labelOverlapsYou"] is False, v  # the stop chip is never over the You marker


@pytest.mark.parametrize("metres, zoom", [("8", 19), ("12", 19), ("20", 19), ("24", 18), ("25", 18), ("59", 18)])
def test_zoom_19_is_used_only_when_the_markers_would_be_closer_than_40_px_at_zoom_18(fit, metres, zoom):
    assert fit["distances"][metres]["zoom"] == zoom, fit["distances"][metres]


def test_at_8_m_the_markers_may_overlap_but_both_are_visible_and_the_chip_is_clear(fit):
    v = fit["distances"]["8"]
    assert v["youInside"] and v["stopInside"] and v["labelOverlapsYou"] is False and 20 <= v["apart"] < 40, v


def test_the_map_and_tile_layer_allow_zoom_19():
    assert 'L.map("map", { scrollWheelZoom: true, maxZoom: 19 })' in INDEX
    assert "maxZoom: 19," in INDEX.split("L.tileLayer(", 1)[1].split(")", 1)[0]
    assert "WALK_FIT_CLOSE_ZOOM = 19" in INDEX and "WALK_FIT_MIN_APART_PX = 40" in INDEX


def test_the_zoom_for_59_m_is_17_or_18_with_a_50_m_chip_and_a_visible_accuracy_circle(fit):
    v = fit["distances"]["59"]
    assert v["zoom"] in (17, 18) and _chip_metres(v["chip"]) <= 100
    assert v["accuracyVisible"] is True and v["accuracyWidth"] >= 20
    assert fit["afterTicks"]["zoom"] == v["zoom"] and fit["afterTicks"]["center"] == v["center"]  # the ticks did not move it


def test_a_live_bus_kilometres_away_does_not_pull_page_w_out_to_the_whole_island(fit):
    v = fit["withFarBus"]
    assert v["zoom"] == 18 and _chip_metres(v["chip"]) <= 100 and v["apart"] >= 40, v  # the original evidence: "Range 3 km"
    assert v["youInside"] and v["stopInside"] and v["center"] == fit["afterTicks"]["center"]


def test_the_zoom_never_goes_below_15_under_300_m_and_fitbounds_serves_the_far_cases(fit):
    for metres in ("20", "59", "300"):
        assert fit["distances"][metres]["zoom"] >= 15
    # the approved Page W map is 300 px tall, so 1.2 km is fitted at zoom 14 or 15 (15 in the old, taller map)
    assert fit["distances"]["1200"]["zoom"] in (14, 15) and fit["distances"]["5000"]["zoom"] <= 14
    assert "map.fitBounds(bounds" in INDEX and "WALK_FIT_MAX_ZOOM = 18" in INDEX and "WALK_FIT_NEAR_MIN_ZOOM = 15" in INDEX


def test_the_stop_chip_goes_on_the_side_away_from_you(fit):
    for metres in ("59", "300", "1200", "5000"):
        assert fit["distances"][metres]["side"] == ["is-right"]  # You is straight north: horizontal first, right is clear
    for metres in ("8", "12", "20", "24", "25"):
        assert len(fit["distances"][metres]["side"]) == 1
    assert "walkLayoutStopLabel" in INDEX


def test_a_programmatic_fit_and_leaflets_animated_zooms_do_not_set_the_user_moved_flag(fit):
    for key in ("afterProgrammaticFit", "afterAnimatedZooms"):
        assert fit[key]["moved"] is False and fit[key]["liveMoved"] is False, key
    assert fit["afterAnimatedZooms"]["zoom"] == fit["afterProgrammaticFit"]["zoom"]
    listener = INDEX.split("Only real input counts as the user moving the map", 1)[1].split("});", 1)[0]
    assert "liveProgrammatic" in listener and "walkUserMoved = true" in listener


def test_a_real_pan_stops_later_refits_and_recentre_refits(fit):
    before, panned, far, recentred = fit["afterAnimatedZooms"], fit["afterPan"], fit["afterFarFix"], fit["afterRecentre"]
    assert panned["moved"] is True and panned["center"] != before["center"]  # a real drag moved the map and set the flag
    assert far["center"] == panned["center"] and far["zoom"] == panned["zoom"]  # a far fix did not refit it
    assert far["apart"] > 600  # (the markers drifted apart on screen: no refit happened)
    assert recentred["moved"] is False and recentred["center"] != far["center"] and recentred["apart"] < 400  # Recentre refits


def test_open_back_open_keeps_the_fit_correct(fit):
    first, second = fit["firstOpen"], fit["secondOpen"]
    assert first["zoom"] == second["zoom"] == 18 and first["center"] == second["center"]
    assert second["youInside"] and second["stopInside"] and second["moved"] is False


def test_a_fix_that_arrives_after_opening_is_fitted(fit):
    assert fit["noFix"]["you"] is None and fit["noFix"]["zoom"] == 17  # no fix: the map shows the stop
    assert fit["late"]["zoom"] == 18 and fit["late"]["youInside"] and fit["late"]["stopInside"]


def test_page_b_s_map_has_a_size_and_both_markers_in_view_at_every_distance(fit):
    for metres, v in fit["pageB"].items():
        assert v["top"] == "arrivals" and v["inSlot"] is True and v["tilePane"] is True, v
        assert v["size"][0] > 200 and v["size"][1] > 150 and v["clientWidth"] > 200, v  # no hidden-container problem
        assert v["youInside"] is True and v["stopInside"] is True, (metres, v)
    after = fit["pageBAfterW"]
    assert after["inSlot"] is True and after["size"][0] > 200 and after["youInside"] and after["stopInside"]


def test_page_b_s_fit_does_not_run_while_page_w_shows():
    guard = INDEX.split("function fitLiveView(busPoint, stopPoint) {", 1)[1].split("if (liveFull", 1)[0]
    assert 'document.body.classList.contains("is-page-w")' in guard and "return;" in guard
