"""Other bus options (the "better" entry) searches exactly as No, I missed it does (the OneMap planner's bus-first routes are asked for
too), apart from the missed bus: the current bus and the same service's later buses are not excluded. The server used to ask the planner
only after a miss, so an entry whose options came from the planner showed "No other buses or routes are available right now." No live API."""

from fastapi.testclient import TestClient  # noqa: F401  (the client comes from the shared fixture)

import main
from test_page_c_entry import _poll_client


def _options(client, params, entry, **extra):
    wanted = {k: params[k] for k in ("stop_code", "service_no", "lat", "lon", "destination_stop_code", "dest_lat", "dest_lon")}
    wanted["accuracy"] = 12
    return client.get("/api/reroute-options", params={**wanted, "entry": entry, **extra}).json()


def test_both_entries_ask_the_planner_for_bus_first_routes(tmp_path, monkeypatch):
    client, params, _ = _poll_client(monkeypatch, tmp_path, high=30, point=20)
    asked = []
    monkeypatch.setattr(main, "_reroute_planner_starts", lambda *args, **kwargs: asked.append(1) or [])
    with client:
        _options(client, params, "recommended", missed_eta=1)
        after_miss = len(asked)
        _options(client, params, "better")
    assert after_miss == 1 and len(asked) == 2, asked  # the planner is asked once for each entry


def test_the_other_entry_keeps_the_current_bus_and_the_same_services_later_buses(tmp_path, monkeypatch):
    client, params, _ = _poll_client(monkeypatch, tmp_path, high=30, point=20)
    with client:
        better = _options(client, params, "better")
        missed = _options(client, params, "recommended", missed_eta=1)
    ids = lambda body: {row["service_no"] for row in body["options"]["cards"] + body["options"]["rows"]}  # noqa: E731
    assert ids(better) == ids(missed) and ids(better)  # the same results, with the current service still listed
    assert better["options"]["entry"] == "better" and missed["options"]["entry"] == "recommended"


# ---- in the page: both entries with options ---------------------------------------------------------------------------------------

import pytest  # noqa: E402

from page_runner import require_edge, run_scenario, running_app  # noqa: E402


@pytest.fixture(scope="module", params=["other", "missed"])
def entry_run(request, tmp_path_factory):
    require_edge()
    with running_app(tmp_path_factory.mktemp("oe" + request.param), eta_minutes=[10.3, 16.3, 24.3]) as base:
        return request.param, run_scenario("otherentries", base, {"entry": request.param}, timeout=300)["result"]


def test_each_entry_shows_its_banner_and_the_full_results_with_options(entry_run):
    entry, result = entry_run
    assert result["entry"] == entry and result["failed"] is False and result["mode"] == "winner"
    assert result["cards"] >= 1 and result["cards"] + result["rows"] >= 2, result  # the recommended cards and the alternatives
    assert result["none"] == ""
    assert "No other buses or routes are available right now." not in (result["notice"] or "")
    expected = "Here are your other options." if entry == "other" else "Bus 18 has left. Here are your other options."
    assert result["notice"] == expected


def test_the_request_names_the_entry_and_only_no_i_missed_it_sends_the_missed_arrival(entry_run):
    entry, result = entry_run
    (url,) = result["requests"]
    assert ("entry=better" in url) is (entry == "other") and ("entry=recommended" in url) is (entry == "missed")
    assert ("missed_eta=" in url) is (entry == "missed")
