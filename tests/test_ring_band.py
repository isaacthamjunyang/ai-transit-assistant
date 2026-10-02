"""The ring colour band is decided in Python from the point, with named thresholds defined once in config."""

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import config
from catch_heuristic import ring_band, score_buses

ROOT = Path(__file__).resolve().parents[1]
SGT = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 1, 18, 0, tzinfo=SGT)


@pytest.mark.parametrize("point, band", [(39, "low"), (40, "mid"), (49, "mid"), (50, "ok"), (5, "low"), (92, "ok")])
def test_band_edges(point, band):
    assert ring_band(point) == band


@pytest.mark.parametrize("value", [None, True, "50", 50.0])
def test_no_point_means_no_band(value):
    assert ring_band(value) is None


def test_thresholds_live_once_in_config():
    assert config.RING_BAND_OK_FROM == 50 and config.RING_BAND_MID_FROM == 40
    source = (ROOT / "catch_heuristic.py").read_text(encoding="utf-8")
    body = source.split("def ring_band(", 1)[1].split("def ", 1)[0]
    assert not re.search(r"\b(40|50)\b", body)  # the numbers are not repeated beside the function
    assert "RING_BAND_OK_FROM" in body and "RING_BAND_MID_FROM" in body
    from destination_stops import BUS_SPEED_KM_H

    assert BUS_SPEED_KM_H == config.BUS_SPEED_KM_H == 18  # one definition, still importable from both


def _bus(minutes: float) -> list[dict]:
    return [{"position": "NextBus", "arrival_time": (NOW + timedelta(minutes=minutes)).isoformat(), "monitored": True,
             "origin_code": None, "destination_code": None}]


def _score(buses, located=True):
    return score_buses(
        buses, user_lat=1.3 + 100 / 111_195 if located else None, user_lon=103.8 if located else None, accuracy_m=10 if located else None,
        stop_lat=1.3, stop_lon=103.8, services=[], routes=[], service_no="36", stop_code="1", now=NOW,
    )[0]


def test_the_band_follows_the_final_point_in_the_probability_object():
    prob = _score(_bus(10))["probability"]
    assert prob["point"] == 92 and prob["band"] == "ok"
    mid = _score(_bus(2.9))["probability"]
    assert mid["band"] == ring_band(mid["point"])
    low = _score(_bus(2.0))["probability"]
    assert low["band"] == ring_band(low["point"]) == "low"
    # The point, range and quality keys are unchanged by the new field.
    assert {"point", "range_low", "range_high", "slack_seconds", "data_quality", "reliability_label", "is_missed", "pace"} <= set(prob)


def test_no_probability_means_no_band():
    assert _score(_bus(10), located=False)["probability"] is None  # no probability, so nothing to colour
    missed = _score(_bus(-5))
    assert missed["probability"] is None


def test_the_page_maps_the_band_without_numbers():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    mapping = html.split("var RING_BAND_CLASS", 1)[1].split("function setRing", 1)[0]
    assert not re.search(r"\b(40|50)\b", mapping)
    assert "ringBand(" not in html  # the old comparison is gone
    plan = (ROOT / "PROJECT_PLAN.md").read_bytes().decode("utf-8")
    assert "ring colour band comes from Python" in plan
