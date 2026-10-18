"""Skip on the destination stops page: a green button beside Back keeps the searched place as the destination with no stop chosen;
Confirm and Your journey then show the place and no Destination stop row, the planner ends at the place, and Edit destination goes back
to the stops page. Tapping a stop behaves as before. Layout at 320, 360 and 1280 px, light and dark. No live API."""

import re
from pathlib import Path

import pytest

import onemap_stub as stub
from page_runner import DEST, require_edge, run_scenario, running_app, north
from test_train_pages import _table

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
LABEL = "Skip: Let us plan your route"
COMBOS = [(320, False, "skip"), (320, True, "skip"), (360, False, "skip"), (360, True, "skip"), (1280, False, "skip"), (1280, True, "skip"),
          (360, False, "stop"), (1280, True, "stop")]


def _rgb(text):
    text = text.strip()
    if text.startswith("#"):
        text = text.lstrip("#")
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    return [round(float(v)) for v in re.findall(r"[\d.]+", text)[:3]]


def _lum(rgb):
    c = [v / 255 for v in rgb]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    high, low = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.fixture(scope="module", params=COMBOS, ids=[f"{w}-{'dark' if d else 'light'}-{p}" for w, d, p in COMBOS])
def run(request, tmp_path_factory):
    width, dark, path = request.param
    require_edge()
    builders = {"TRANSIT": stub.bus_only, "BUS": stub.bus_only}
    with running_app(tmp_path_factory.mktemp(f"sk{width}{dark}{path}"), onemap=stub.by_mode(builders), rail_table=_table()) as base:
        return path, run_scenario("skipstop", base, {"width": width, "height": 800, "dark": dark, "path": path, "dest": DEST,
                                                    "destPos": north(2000)}, timeout=300)["result"]


# ---- the button -----------------------------------------------------------------------------------------------------------------


def test_the_button_is_beside_back_in_the_same_row_with_the_label(run):
    path, result = run
    stops = result["stops"]
    skip, back, bar = stops["skip"], stops["back"], stops["bar"]
    assert stops["top"] == "stops" and skip["shown"] is True and skip["text"] == LABEL
    assert skip["rect"]["left"] >= back["right"] - 0.5  # to the right of Back
    assert skip["rect"]["top"] < back["bottom"] and skip["rect"]["bottom"] > back["top"]  # in the same row
    assert skip["rect"]["left"] >= bar["left"] and skip["rect"]["right"] <= bar["right"] + 0.5  # inside the row


def test_it_is_44px_or_more_wraps_to_at_most_two_lines_and_never_overflows(run):
    path, result = run
    stops = result["stops"]
    height = stops["skip"]["rect"]["height"]
    assert height >= 44 and height <= 44 + 2 * 20, height  # two lines at most
    assert stops["scrollWidth"] <= stops["innerWidth"]
    assert stops["bar"]["right"] <= stops["innerWidth"] + 0.5 and stops["skip"]["rect"]["right"] <= stops["innerWidth"]


def test_it_is_the_filled_green_with_a_white_label_and_contrast(run):
    path, result = run
    skip = result["stops"]["skip"]
    assert skip["borderWidth"] == "0px" and int(skip["weight"]) >= 700 and skip["tokenFill"]
    assert _rgb(skip["bg"]) != [0, 0, 0] and skip["bg"] not in ("rgba(0, 0, 0, 0)", "transparent")  # fully filled
    assert _contrast(skip["color"], skip["bg"]) >= 4.5  # the white label on the green


def test_it_shows_on_the_stops_page_only(run):
    path, result = run
    assert result["confirm"]["skip"]["shown"] is False and result["journey"]["skip"]["shown"] is False


# ---- the two paths --------------------------------------------------------------------------------------------------------------


def test_after_skip_confirm_and_the_journey_show_the_place_and_no_stop_row(run):
    path, result = run
    if path != "skip":
        pytest.skip("the skip path")
    assert result["confirm"]["top"] == "confirm" and result["confirm"]["confirm"]["place"] == "Pebble Bay Plaza"
    assert result["confirm"]["confirm"]["stopSection"] is False and result["confirm"]["confirm"]["rule"] is False  # no Destination stop row
    journey = result["journey"]
    assert journey["top"] == "journey" and journey["overview"]["state"] == "ready" and journey["skipped"] is True
    assert journey["overview"]["hasStopRow"] is False
    assert journey["overview"]["destinationRow"].startswith("DestinationPebble Bay Plaza")
    walk = [row for row in journey["overview"]["rows"] if row.startswith("Walk") and "Pebble Bay Plaza" in row]
    assert walk and not walk[0].endswith("Edit")  # the final walk has no Edit destination stop link: there is no stop to edit
    assert journey["walkRows"] and journey["walkRows"] == journey["walkTexts"]  # the Walking figure is the sum of the rows shown
    assert journey["walkingCell"].replace(chr(0xA0), " ") == f"{sum(journey['walkRows'])} min"


def test_after_skip_the_planner_is_asked_for_the_place_with_no_stop_code_and_no_end_point(run):
    path, result = run
    if path != "skip":
        pytest.skip("the skip path")
    (url,) = result["plan"]
    assert "destination_stop_code" not in url and "end_lat" not in url and "end_lon" not in url
    assert "dest_lat=" in url and "dest_lon=" in url
    assert result["journey"]["destStopCode"]  # the planned route's own last bus stop serves the stop-based calls, unseen


def test_tapping_a_stop_still_makes_it_the_destination(run):
    path, result = run
    if path != "stop":
        pytest.skip("the stop path")
    assert result["confirm"]["confirm"]["stopSection"] is True and result["confirm"]["confirm"]["stopName"] == "Destination"
    assert result["journey"]["skipped"] is False and result["journey"]["confirmedStop"] == DEST
    (url,) = result["plan"]
    assert f"destination_stop_code={DEST}" in url and "end_lat=" in url and "end_lon=" in url


def test_back_and_edit_destination_are_consistent_after_either_path(run):
    path, result = run
    stack = ["home", "results", "stops", "confirm", "journey"]
    assert result["journey"]["stack"] == stack
    assert result["backOnce"] == {"top": "confirm", "stack": stack[:4]}  # Back from the journey goes to Confirm
    assert result["backTwice"] == {"top": "stops", "stack": stack[:3]}  # and from Confirm to the stops page
    assert result["again"]["stack"] == stack  # forward again by the same path
    # Edit destination: the stops page after Skip (to choose again), the search results after a stop (as before)
    assert result["edit"]["top"] == ("stops" if path == "skip" else "results")


# ---- the sources ----------------------------------------------------------------------------------------------------------------


def test_the_label_is_in_copy_js_and_the_markup_and_the_style_guide_and_the_plan():
    assert f'skip: "{LABEL}",' in COPY
    assert f'<button type="button" class="primary skip-stop pulse-button" id="skip-stop" hidden><span>{LABEL}</span></button>' in INDEX
    assert 'id="confirm-stop-section"' in INDEX and 'id="confirm-stop-rule"' in INDEX
    assert "skip-stop" in GUIDE and "destinationStops.skip" in GUIDE
    assert "`Skip: Let us plan your route`" in PLAN and "no `Destination stop` row" in PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()


def test_the_css_uses_tokens_only():
    block = CSS.split(".back-bar:has(.skip-stop:not([hidden])) {", 1)[1].split(".back-bar .skip-stop:focus-visible", 1)[0]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block)
    assert "min-height: var(--tap-min);" in block and "background: var(--action-yes);" in block and "border: 0;" in block
    assert "color: var(--action-ink);" in block and "overflow-wrap: anywhere;" in block


# ---- the server with no destination stop code -----------------------------------------------------------------------------------

from test_pt_plan import JOURNEY, Server, api, end_of  # noqa: E402,F401  (api is a fixture)


def _without_code(place, **extra):
    params = {key: value for key, value in JOURNEY.items() if key != "destination_stop_code"}
    return {**params, "dest_lat": place[0], "dest_lon": place[1], "priority": "fastest", **extra}


def test_the_planner_answers_with_no_stop_code_and_routes_to_the_place(api):
    place = end_of("direct_bus")
    response = api.get("/api/journey-plan", params=_without_code(place))
    assert response.status_code == 200 and response.json()["status"] == "ok"
    assert api.holder["server"].gets[-1].url.params["end"] == f"{place[0]:.5f},{place[1]:.5f}"  # the place is the end
    assert response.json()["itinerary"]["legs"]  # a route comes back


def test_a_blank_stop_code_is_still_refused_and_the_bus_planner_fallback_finds_no_route_without_a_stop(api):
    place = end_of("direct_bus")
    blank = api.get("/api/journey-plan", params={**_without_code(place), "destination_stop_code": " "})
    assert blank.status_code == 422 and "destination_stop_code" in blank.json()["detail"]
    api.holder["server"] = Server(default=(500, {}))  # OneMap down: the static bus planner needs a stop
    body = api.get("/api/journey-plan", params=_without_code(place)).json()
    assert body["planner"] == "static" and body["route_status"] == "no_feasible_route" and body.get("journey") is None


def test_the_poll_works_with_no_destination_stop_code_and_just_leaves_the_reroute_and_estimate_out(tmp_path, monkeypatch):
    from test_page_c_entry import _poll_client
    client, params, _ = _poll_client(monkeypatch, tmp_path, high=30, point=20)
    without = {key: value for key, value in params.items() if key != "destination_stop_code"}
    with client:
        body = client.get("/api/arrivals", params=without)
    assert body.status_code == 200 and body.json()["status"] == "ok"
    assert not body.json().get("reroute", {}).get("switched")  # no destination stop, so nothing to switch to
