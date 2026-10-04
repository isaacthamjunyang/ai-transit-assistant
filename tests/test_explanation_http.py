"""The explanation over the HTTP poll path: the pack's keys, and a hostile model clause.

Sentences one and two are written by Python in the poll response. Whatever a model (or a tampered request) offers
as sentence three, they stay exactly as Python wrote them, and a bad clause falls back to the fixed one.
"""

import json
import math
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

import arrivals
import demo
import explain
import lta_static
import observations
from explain import ACTION_ADVICE, ACTIONS, PAGE_PACK_FIELDS, REASON_CODES, reset_explanation_gate
from lta_static import StopAndRouteCache
from main import app
from nearby import EARTH_RADIUS_M

SGT = timezone(timedelta(hours=8))
LAT, LON = 1.3, 103.8
ORIGIN, DEST = "01011", "99999"


def _north(metres):
    return LAT + math.degrees(metres / EARTH_RADIUS_M), LON


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    env = tmp_path / "demo.env"
    env.write_text("", encoding="utf-8")
    monkeypatch.setattr(lta_static, "ENV_PATH", env)
    monkeypatch.setattr(observations, "DEFAULT_DB_PATH", tmp_path / "observations.db")
    monkeypatch.delenv("DEMO_MODE", raising=False)
    demo.reset_to_live()
    reset_explanation_gate()
    yield
    demo.reset_to_live()
    reset_explanation_gate()


@pytest.fixture
def client(monkeypatch):
    dest_lat, dest_lon = _north(2000)
    stops = [
        {"BusStopCode": ORIGIN, "Description": "Origin", "RoadName": "Orchard Rd", "Latitude": LAT, "Longitude": LON},
        {"BusStopCode": DEST, "Description": "Destination", "RoadName": "Orchard Rd", "Latitude": dest_lat, "Longitude": dest_lon},
    ]
    routes = [
        {"ServiceNo": "18", "Direction": 1, "BusStopCode": ORIGIN, "StopSequence": 1, "Distance": 0},
        {"ServiceNo": "18", "Direction": 1, "BusStopCode": DEST, "StopSequence": 5, "Distance": 3},
    ]
    services = [{"ServiceNo": "18", "Direction": 1, "OriginCode": ORIGIN, "DestinationCode": DEST,
                 "AM_Offpeak_Freq": "10-10", "AM_Peak_Freq": "10-10", "PM_Peak_Freq": "10-10", "PM_Offpeak_Freq": "10-10"}]
    cache = StopAndRouteCache(stops, routes, services)
    monkeypatch.setattr("main.load_static_data", lambda: cache)
    monkeypatch.setattr(arrivals, "read_account_key", lambda: "test-account-key")
    eta = (datetime.now(SGT) + timedelta(minutes=10, seconds=17)).replace(microsecond=0).isoformat()

    def fake_get(self, url, *args, **kwargs):
        bus = {"EstimatedArrival": eta, "Monitored": 1, "Latitude": "", "Longitude": "", "OriginCode": "", "DestinationCode": ""}
        return httpx.Response(200, json={"Services": [{"ServiceNo": "18", "NextBus": bus}]})

    monkeypatch.setattr(httpx.Client, "get", fake_get)
    with TestClient(app) as test_client:
        yield test_client


USER = _north(300)  # 300 m from the stop: a 4 minute walk, so a bus at 10 minutes leaves time to spare


def _poll(client, extra=None):
    dest_lat, dest_lon = _north(2000)
    params = {"stop_code": ORIGIN, "service_no": "18", "lat": USER[0], "lon": USER[1], "accuracy": 10,
              "location_timestamp": time.time(), "destination_stop_code": DEST, "dest_lat": dest_lat,
              "dest_lon": dest_lon, "explanation_rendered": 1}
    params.update(extra or {})
    response = client.get("/api/arrivals", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _lead(pack):
    assert pack["text"].endswith(pack["clause"])
    return pack["text"][: -len(pack["clause"])].rstrip()


FIXED = "It is advisable to " + ACTION_ADVICE["wait"] + "."


def test_the_pack_over_http_has_the_keys_the_page_reads_and_the_right_types(client):
    pack = _poll(client)["explanation"]
    assert set(pack) == {"snapshot", "fact_sheet", "text", "clause", "action", "reason_code", "arrival_time",
                         "walk_minutes", "band", "uncertain", "call", "pending"}
    assert set(PAGE_PACK_FIELDS) <= set(pack)
    assert isinstance(pack["snapshot"], str) and pack["snapshot"].startswith("18|01011|")
    assert isinstance(pack["text"], str) and isinstance(pack["clause"], str) and pack["text"].endswith(pack["clause"])
    assert pack["action"] in ACTIONS and pack["reason_code"] in REASON_CODES
    assert pack["fact_sheet"] == {"reason_code": pack["reason_code"], "chosen_action": pack["action"]}
    assert type(pack["walk_minutes"]) is int and pack["band"] in ("ok", "mid", "low", None)
    assert pack["uncertain"] is False and isinstance(pack["call"], bool) and isinstance(pack["pending"], bool)
    assert datetime.fromisoformat(pack["arrival_time"]).tzinfo is not None
    assert pack["text"].startswith("The bus is 10 minutes away.")


HOSTILE = [
    ("digits", "wait", "wait for the bus in 7 minutes"),
    ("a heading", "wait", "Headline: wait for your alert"),
    ("a newline and a sentence", "wait", "wait for your alert\nThe bus is 99 minutes away."),
    ("a sentence about the bus", "wait", "The bus is 99 minutes away."),
    ("more than 15 words", "wait",
     "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen"),
    ("a clause for another action", "wait", "leave now and walk to the bus stop"),
    ("a cached clause of another action", "switch_route", "switch to another bus"),
]


@pytest.mark.parametrize("label, action, advice", HOSTILE, ids=[h[0] for h in HOSTILE])
def test_a_hostile_clause_in_the_poll_leaves_sentences_one_and_two_alone_and_uses_the_fixed_clause(
        client, label, action, advice):
    baseline = _poll(client)["explanation"]
    assert baseline["clause"] == FIXED and baseline["action"] == "wait"
    pack = _poll(client, {"explained_action": action, "explained_advice": advice})["explanation"]
    assert _lead(pack) == _lead(baseline), label  # sentences one and two exactly as Python wrote them
    assert pack["clause"] == FIXED and pack["text"].endswith(FIXED)
    assert pack["call"] is True  # the page asks the model again
    assert "99 minutes" not in pack["text"] and "\n" not in pack["text"] and "Headline" not in pack["text"]


@pytest.mark.parametrize("label, action, advice", HOSTILE[:6], ids=[h[0] for h in HOSTILE[:6]])
def test_a_hostile_model_reply_over_http_falls_back_and_the_next_poll_keeps_sentences_one_and_two(
        client, monkeypatch, label, action, advice):
    monkeypatch.setattr(explain, "read_openai_api_key", lambda: "sk-test-not-real")
    monkeypatch.setattr(explain, "_openai_complete",
                        lambda fact, key, request: {"status": 200, "body": json.dumps({"advice": advice})})
    baseline = _poll(client)["explanation"]
    reply = client.post("/api/explain", json={"fact_sheet": baseline["fact_sheet"], "snapshot": baseline["snapshot"]})
    assert reply.status_code == 200
    body = reply.json()
    assert body["source"] == "fallback" and body["clause"] == FIXED and body["snapshot"] == baseline["snapshot"]
    assert "text" not in body and "99 minutes" not in json.dumps(body)
    after = _poll(client, {"explained_action": body["action"], "explained_advice": body["advice"]})["explanation"]
    assert _lead(after) == _lead(baseline) and after["clause"] == FIXED and after["call"] is False


def test_a_good_model_clause_replaces_only_sentence_three(client, monkeypatch):
    good = "wait for your alert before leaving"
    monkeypatch.setattr(explain, "read_openai_api_key", lambda: "sk-test-not-real")
    monkeypatch.setattr(explain, "_openai_complete",
                        lambda fact, key, request: {"status": 200, "body": json.dumps({"advice": good})})
    baseline = _poll(client)["explanation"]
    body = client.post("/api/explain", json={"fact_sheet": baseline["fact_sheet"], "snapshot": baseline["snapshot"]}).json()
    assert body["source"] == "model" and body["clause"] == f"It is advisable to {good}."
    after = _poll(client, {"explained_action": body["action"], "explained_advice": body["advice"]})["explanation"]
    assert _lead(after) == _lead(baseline) and after["clause"] == body["clause"] and after["call"] is False
