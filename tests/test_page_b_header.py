"""Page B for a bus: the header is the logo tile, the bus number badge, "To {destination stop}" and the pill, with no
"Arriving in" line; the grey rows are gone; the stale-data message shows only when the data is old and the refresh
button stays. 360 px and 1280 px, light and dark. No live API is called."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")


def test_the_header_markup_is_one_row_and_has_no_arrival_line():
    card = INDEX.split('id="live-tracking"', 1)[1].split('id="next-buses-label"', 1)[0]
    row = card.split('class="journey-step__line bus-card__line"', 1)[1].split("</p>", 1)[0]
    assert row.index('id="live-bus-title"') < row.index('id="live-bus-to"') < row.index('id="live-bus-pill"')
    for gone in ("Arriving", "live-bus-arriving", "bus-card__title", "live-then", "status-grid"):
        assert gone not in card, gone


@pytest.fixture(scope="module", params=[("l360", 360, 800, False), ("d1280", 1280, 900, True)], ids=["360-light", "1280-dark"])
def run(request, tmp_path_factory):
    name, width, height, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp("pb" + name), eta_minutes=[10.3]) as base:
        return run_scenario("pagebstale", base, {"name": name, "width": width, "height": height, "dark": dark},
                            timeout=300)["result"]


def test_the_bus_header_has_the_tile_the_badge_to_destination_and_the_pill(run):
    fresh = run["fresh"]
    assert fresh["top"] == "arrivals" and fresh["pageB"] is True
    assert fresh["badgeBus"] is True and re.fullmatch(r"Bus \d+", fresh["badgeText"]), fresh["badgeText"]
    assert fresh["to"].startswith("To ") and not re.search(r"\(\d{5}\)", fresh["to"])
    assert fresh["pill"] in ("live", "schedule only")
    assert "Arriving in" not in fresh["header"] and "Arriving now" not in fresh["header"]
    assert fresh["badge"]["left"] >= fresh["tile"]["right"] - 0.5  # beside the logo tile
    assert fresh["toBox"]["left"] >= fresh["badge"]["right"] - 0.5 or fresh["toBox"]["top"] >= fresh["badge"]["bottom"] - 1
    assert fresh["scrollWidth"] <= fresh["innerWidth"]


def test_no_grey_rows_but_the_next_buses_the_map_and_the_refresh_button_stay(run):
    fresh = run["fresh"]
    assert fresh["greyRows"] is False
    for gone in ("Then Bus", "Live bus location", "GPS accuracy", "Last update", "Monitored (live GPS)"):
        assert gone not in fresh["body"], gone
    assert fresh["nextTiles"] >= 1 and fresh["map"] is True and fresh["refresh"] is True


def test_the_stale_message_shows_only_when_the_data_is_old(run):
    assert run["fresh"]["staleShown"] is False
    stale = run["stale"]
    assert stale["staleShown"] is True and stale["staleTitle"] == "LTA data is stale"
    assert stale["staleUpdated"] is None or stale["staleUpdated"].startswith("Last update")
    assert stale["refresh"] is True  # the refresh button stays
    assert run["fresh2"]["staleShown"] is False
