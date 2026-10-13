"""The ride-app card under an empty plan answer (no service, no feasible route, walk only), for each priority.

Static checks read the page, copy.js, the style guide and the plan; browser checks drive the real page against the real app
and a stubbed OneMap (nothing here calls a live API). No operator documents a prefilled link we could confirm, so the links
are plain operator sites and carry no trip data."""

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest

import onemap_stub as stub
from page_runner import require_edge, run_scenario, running_app
from test_train_pages import _table

ROOT = Path(__file__).resolve().parent.parent
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")

ALL = ["fastest", "fewest_transfers", "least_walking", "bus_only", "mrt_only"]
HEADING = "No transit right now. Open a ride app:"
NOTE = "These links open each app's own site. Your trip is not sent."
PREFILL_LINE = "Opens the app with your trip. We don't see your location."
# exactly as sourced (see the link report): each is the operator's own site, with no query string or trip data
LINKS = [
    ("Grab", "https://www.grab.com/sg/download/"),
    ("Gojek", "https://gojek.com/sg/about"),
    ("CDG Zig", "https://www.cdgtaxi.com.sg/"),
    ("TADA", "https://tada.global"),
    ("Ryde", "https://rydesharing.com/"),
]


# ---- static: words, links, privacy, no prices -------------------------------------------------------------------


def _ride_block() -> str:
    return COPY.split("rideApps: {", 1)[1].split("\n  },", 1)[0]


def test_copy_js_has_the_words_and_the_links_exactly_as_sourced():
    block = _ride_block()
    assert f'heading: "{HEADING}"' in block and f'note: "{NOTE}"' in block
    assert 'distance: "About {km} km in a straight line"' in block
    pairs = re.findall(r'\{ name: "([^"]+)", url: "([^"]+)" \}', block)
    assert pairs == LINKS


def test_the_page_mirrors_copy_js_character_for_character():
    markup = INDEX.split('<div id="ride-apps"', 1)[1].split("</div>", 1)[0]
    assert HEADING in markup and NOTE in markup
    anchors = re.findall(r'<a class="secondary ride-apps__link" href="([^"]+)" target="_blank" rel="noopener noreferrer">([^<]+)</a>', markup)
    assert [(name, url) for url, name in anchors] == LINKS
    assert markup.count("<a ") == 5
    assert 'var JO_RIDE_DISTANCE = "About {km} km in a straight line";' in INDEX


APPROVED_HOSTS = {"www.grab.com", "gojek.com", "www.cdgtaxi.com.sg", "tada.global", "rydesharing.com"}


def test_every_link_is_a_plain_site_with_no_trip_data_on_an_approved_domain():
    assert [name for name, _url in LINKS] == ["Grab", "Gojek", "CDG Zig", "TADA", "Ryde"]
    for _name, url in LINKS:
        parts = urlsplit(url)
        assert parts.scheme == "https" and not parts.query and not parts.fragment, url
        assert parts.netloc in APPROVED_HOSTS, url  # an unconfirmed domain is a failure
    assert {urlsplit(url).netloc for _n, url in LINKS} == APPROVED_HOSTS


def test_the_prefill_sentence_is_not_used_because_no_link_prefills():
    assert PREFILL_LINE not in COPY and PREFILL_LINE not in INDEX and PREFILL_LINE not in GUIDE
    assert PREFILL_LINE in PLAN  # reserved in the plan for a link that really prefills


def test_the_card_function_makes_no_request_and_builds_no_link():
    body = INDEX.split("function showRideApps(body) {", 1)[1].split("\n    }\n", 1)[0]
    for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "href", "setAttribute", "location", "Image(", "src"):
        assert banned not in body, banned
    # the card's distance is worked out from points already on the phone
    assert "haversineMetres(userLat, userLon, selectedDestination.latitude, selectedDestination.longitude)" in body


def test_the_page_never_puts_the_users_points_into_a_ride_app_link():
    # the only places a ride-app link is written are the static markup and the style guide's sample, both from copy.js
    assert INDEX.count("ride-apps__link") == 5
    assert re.search(r"ride-apps[^\n]*(userLat|userLon|latitude|longitude)", INDEX.split("function showRideApps", 1)[0]) is None


def test_no_price_words_in_copy_js_the_card_the_function_or_the_style_guide():
    pieces = {
        "copy.js": COPY,
        "markup": INDEX.split('<div id="ride-apps"', 1)[1].split("</div>", 1)[0],
        "function": INDEX.split("function showRideApps(body) {", 1)[1].split("\n    }\n", 1)[0],
        "guide": GUIDE.split("function sgRideApps(", 1)[1].split("function sgArriveBox", 1)[0],
    }
    for name, text in pieces.items():
        assert re.search(r"\b(price|prices|priced|fare|fares|cost|costs|surge|cheap|cheaper)\b", text, re.I) is None, name
    for name, text in {"copy.js": COPY, "page": INDEX, "guide": GUIDE}.items():
        assert re.search(r"S?\$\s?\d", text) is None, name


def test_the_style_guide_shows_the_card_with_and_without_the_distance():
    assert "function sgRideApps(withDistance)" in GUIDE
    assert "sgRideApps(true)" in GUIDE and "sgRideApps(false)" in GUIDE
    assert "copy.rideApps" in GUIDE


def test_the_plan_carries_the_card():
    for text in (HEADING, NOTE, "About {km} km in a straight line", "Grab, Gojek, CDG Zig, TADA and Ryde",
                 "`rel=\"noopener noreferrer\"`"):
        assert text in PLAN, text


def test_the_styles_use_tokens_and_a_44_px_link():
    css = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
    block = css.split(".ride-apps {", 1)[1].split(".ride-apps__link:focus-visible", 1)[0]
    assert "min-height: var(--tap-min);" in block
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block) is None


# ---- browser: the real page ---------------------------------------------------------------------------------


def _walk_only():
    return stub.answer(stub.itinerary(stub.walk(0, 6, 400)))


def _run(tmp_path_factory, name, builders, **config):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name), onemap=stub.by_mode(builders), rail_table=_table()) as base:
        return run_scenario("rideapps", base, {"name": name, "priorities": ALL, **config}, timeout=300)["result"]


@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)], ids=["360-light", "1280-dark"])
def walk_only(request, tmp_path_factory):
    name, width, height, dark = request.param
    builders = {"TRANSIT": _walk_only, "BUS": _walk_only, "RAIL": _walk_only}
    return _run(tmp_path_factory, "ride" + name, builders, width=width, height=height, dark=dark, tap=name == "l360")


@pytest.fixture(scope="module")
def no_route(tmp_path_factory):
    return _run(tmp_path_factory, "rideroute", {"TRANSIT": None, "BUS": None, "RAIL": None}, width=390, height=844)


@pytest.fixture(scope="module")
def has_route(tmp_path_factory):
    builders = {"TRANSIT": stub.bus_only, "BUS": stub.bus_only, "RAIL": stub.bus_only}
    return _run(tmp_path_factory, "ridefound", builders, width=390, height=844, priorities=["fastest", "bus_only"])


def _check_card(state, width):
    assert state["shown"] is True and state["heading"] == HEADING and state["note"] == NOTE, state
    assert [(a["text"], a["href"]) for a in state["links"]] == LINKS
    for link in state["links"]:
        assert link["target"] == "_blank" and link["rel"] == "noopener noreferrer"
        assert link["height"] >= 44, link
        assert 0 <= link["left"] and link["right"] <= width, link
    assert state["scrollWidth"] <= state["innerWidth"] and state["inlineStyles"] == 0
    # nothing moved after the answer settled
    assert abs(state["settledTop"] - state["box"]["top"]) < 0.5 and abs(state["settledHeight"] - state["box"]["height"]) < 0.5


@pytest.mark.parametrize("priority", ALL)
def test_the_card_shows_for_a_walk_only_answer_with_a_straight_line_distance(walk_only, priority):
    state = walk_only["byPriority"][priority]
    assert state["priority"] == priority and state["noService"] is True and state["ready"] is False
    _check_card(state, state["innerWidth"])
    # the stub places the user 300 m north of the origin and the place 2000 m north: about 1.7 km apart
    assert state["distance"] == "About 1.7 km in a straight line", state["distance"]


@pytest.mark.parametrize("priority", ALL)
def test_the_card_shows_for_a_404_for_every_priority(no_route, priority):
    state = no_route["byPriority"][priority]
    assert state["priority"] == priority and state["noRoute"] is True and state["ready"] is False
    _check_card(state, state["innerWidth"])
    assert state["distance"] == "About 1.7 km in a straight line"


@pytest.mark.parametrize("priority", ["fastest", "bus_only"])
def test_the_card_is_hidden_when_a_route_exists(has_route, priority):
    state = has_route["byPriority"][priority]
    assert state["ready"] is True and state["shown"] is False and state["distance"] is None, state


def test_tapping_the_links_sends_nothing_and_leaves_the_page_where_it_is(walk_only):
    if "tapped" not in walk_only:
        pytest.skip("the tap run is made in the 360 px fixture")
    assert walk_only["tapped"] == 5
    assert walk_only["after"]["sent"] == [] and walk_only["after"]["requests"] == []
    assert walk_only["after"]["href"] == walk_only["before"]["href"]
    # no link carries a coordinate of the user or the place
    coords = [str(value) for value in walk_only["coords"].values()]
    for href in walk_only["hrefs"]:
        assert not any(text[:6] in href for text in coords), href
        assert urlsplit(href).query == "", href
    assert [(urlsplit(h).netloc) for h in walk_only["hrefs"]] == [urlsplit(u).netloc for _n, u in LINKS]
