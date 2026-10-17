"""The Arrive by chips in two single-line rows (In 30 min, In 1 hour, In 1 hr 30 min / No target, Custom), the new 90-minute preset in
Singapore time, and the Custom time field: no visible label, the selected-chip outline, and a real clock button. Home and the Confirm
destination screen, 320, 360 and 1280 px, light and dark, with the browser in another time zone. No live API."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8").replace("\r\n", "\n")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")
NB = chr(0xA0)
COMBOS = [(w, d) for w in (320, 360, 1280) for d in (False, True)]
ROW_1 = ["arrive-30", "arrive-60", "arrive-90"]
ROW_2 = ["arrive-none", "arrive-custom"]


def _rgb(text):
    text = text.strip()
    if text.startswith("#"):
        text = text.lstrip("#")
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    return [int(value) for value in re.findall(r"\d+", text)[:3]]


def _lum(rgb):
    c = [v / 255 for v in rgb]
    c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def _contrast(a, b):
    high, low = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.fixture(scope="module", params=COMBOS, ids=[f"{w}-{'dark' if d else 'light'}" for w, d in COMBOS])
def run(request, tmp_path_factory):
    width, dark = request.param
    require_edge()
    with running_app(tmp_path_factory.mktemp(f"al{width}{dark}")) as base:
        return run_scenario("arrivelayout", base, {"width": width, "height": 800, "dark": dark, "zone": "America/Los_Angeles"}, timeout=300)["result"]


# ---- the rows ---------------------------------------------------------------------------------------------------------------


def test_the_rows_have_the_right_chips_in_the_right_order_on_home_and_on_confirm(run):
    assert run["browserZone"] == "America/Los_Angeles"
    for page in ("home", "confirm"):
        layout = run[page]
        assert [[chip["id"] for chip in row["chips"]] for row in layout["rows"]] == [ROW_1, ROW_2], page
        assert [[chip["text"] for chip in row["chips"]] for row in layout["rows"]] == [["In 30 min", "In 1 hour", "In 1 hr 30 min"], ["No target", "Custom"]], page
        assert layout["focusable"][:5] == ROW_1 + ROW_2, page  # the tab order follows the rows
        assert layout["group"] == "radiogroup|Arrive by", page
        assert all(chip["role"] == "radio" for row in layout["rows"] for chip in row["chips"]), page
    assert run["home"]["inConfirm"] is False and run["confirm"]["inConfirm"] is True and run["confirm"]["screen"] == "confirm"


def test_every_row_is_one_line_with_no_wrap_no_overflow_and_44px_chips(run):
    for page in ("home", "confirm"):
        layout = run[page]
        for row in layout["rows"]:
            tops = {round(chip["top"]) for chip in row["chips"]}
            assert len(tops) == 1, (page, tops)  # all the chips of a row sit on one line
            assert all(chip["lines"] == 1 for chip in row["chips"]), (page, [c["lines"] for c in row["chips"]])  # the text never wraps
            assert all(chip["height"] >= 44 and chip["height"] <= 46 for chip in row["chips"]), page
            assert row["scrollW"] <= row["clientW"] + 0.5, (page, row["scrollW"], row["clientW"])  # nothing runs out of the row
            assert all(chip["scrollW"] <= chip["clientW"] + 0.5 for chip in row["chips"]), page  # nor out of its chip
            assert all(chip["right"] <= row["rect"]["right"] + 0.5 and chip["left"] >= row["rect"]["left"] - 0.5 for chip in row["chips"]), page
        assert layout["rows"][1]["rect"]["top"] >= layout["rows"][0]["rect"]["bottom"], page  # row 2 is under row 1
        assert layout["scrollWidth"] <= layout["innerWidth"] and layout["panelScrollW"] <= layout["panelClientW"] + 0.5, page
        assert all(float(chip["fontSize"][:-2]) >= 11 for row in layout["rows"] for chip in row["chips"]), page  # still readable


def test_the_chips_are_a_little_smaller_on_a_narrow_phone_and_full_size_on_a_wide_one(run):
    size = float(run["home"]["rows"][0]["chips"][0]["fontSize"][:-2])
    if run["home"]["innerWidth"] >= 1000:
        assert size == 16
    elif run["home"]["innerWidth"] <= 340:
        assert size < 16
    assert size >= 12  # on Home the chips stay near the normal size even at 320 px


# ---- the new preset ---------------------------------------------------------------------------------------------------------


def test_in_1_hr_30_min_is_ninety_minutes_on_in_singapore_time_whatever_the_phone_zone(run):
    noon = run["cases"]["noon"]  # 12:00 PM in Singapore, 8:00 PM the day before in Los Angeles
    assert noon["value"] == "2026-01-15T13:30" and noon["choice"] == "arrive-90" and noon["picked"] is True
    assert noon["display"] == "In 1 hr 30 min · 1:30 PM"  # the page text folds the no-break space
    assert noon["chosen"] == "Arrive by: 1:30 PM"
    assert noon["panelHidden"] is True and noon["customVisible"] is False  # the panel closes
    midnight = run["cases"]["midnight"]  # 11:07 PM in Singapore on the 15th: 12:40 AM on the 16th (rounded up to 5 minutes)
    assert midnight["value"] == "2026-01-16T00:40"  # the Singapore date, not the phone's (the 15th)
    assert midnight["display"] == "In 1 hr 30 min · 12:40 AM (Tomorrow)" and midnight["chosen"] == "Arrive by: 12:40 AM (tomorrow)"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", midnight["value"])  # the format the server takes


def test_the_other_presets_and_no_target_still_work_and_the_checked_state_follows(run):
    cases = run["cases"]
    assert cases["half"]["value"] == "2026-01-15T23:40" and cases["half"]["display"] == "In 30 min · 11:40 PM"
    assert cases["hour"]["value"] == "2026-01-16T00:10" and cases["hour"]["display"] == "In 1 hour · 12:10 AM (Tomorrow)"
    for key, chosen in (("noon", "arrive-90"), ("midnight", "arrive-90"), ("hour", "arrive-60"), ("half", "arrive-30"), ("none", "arrive-none")):
        checked = [entry.split(":")[0] for entry in cases[key]["checked"] if entry.endswith(":true")]
        assert checked == [chosen], (key, cases[key]["checked"])  # exactly one chip is checked
    assert cases["none"]["value"] == "" and cases["none"]["display"] == "No target"


def test_choosing_it_clears_a_custom_day_choice(run):
    cases = run["cases"]
    assert cases["customTomorrow"]["tomorrow"] == "true" and cases["customTomorrow"]["day"] == "tomorrow"
    assert cases["afterPreset"]["choice"] == "arrive-90" and cases["afterPreset"]["customVisible"] is False
    again = cases["customAgain"]  # Custom opens with Today and Tomorrow unselected
    assert again["today"] == "false" and again["tomorrow"] == "false" and again["day"] == "" and again["customVisible"] is True


# ---- the Custom panel's time field -------------------------------------------------------------------------------------------


def test_the_time_field_has_no_visible_label_and_keeps_an_accessible_name(run):
    field = run["field"]
    assert field["labelPresent"] is False and field["labelTexts"] == [] and field["bodyHasTime"] is False
    assert field["inputLabel"] == "Arrive by time"


def test_the_time_field_is_outlined_like_the_selected_custom_chip(run):
    field = run["field"]
    assert field["inputShadow"] == field["chipShadow"] and field["inputRadius"] == field["chipRadius"] == "999px"
    blue = _rgb(field["tokens"]["outline"])
    assert field["inputShadow"].replace(" ", "") == f"rgb({blue[0]},{blue[1]},{blue[2]})0px0px0px2px"  # the selected-outline token, 2 px
    assert field["inputBorderWidth"] == field["chipBorderWidth"] == "1px"
    assert _contrast(field["tokens"]["outline"], field["tokens"]["card"]) >= 3.0  # 3:1 against the card
    assert run["fieldAfterFocus"]["inputShadow"] == field["inputShadow"] and (run["fieldAfterFocus"]["input"]["width"], run["fieldAfterFocus"]["input"]["height"]) == (field["input"]["width"], field["input"]["height"])  # no change on focus (the page may scroll to it)
    assert field["scrollWidth"] <= field["innerWidth"]


def test_the_clock_is_a_real_44px_button_with_a_visible_colour(run):
    field = run["field"]
    assert field["buttonType"] == "BUTTON|button" and field["buttonLabel"] == "Choose time"
    assert field["button"]["width"] >= 44 and field["button"]["height"] >= 44
    assert field["button"]["right"] <= field["field"]["right"] + 0.5 and field["button"]["top"] >= field["field"]["top"] - 0.5
    assert field["button"]["left"] >= field["input"]["left"] and field["button"]["bottom"] <= field["field"]["bottom"] + 0.5  # inside the field
    assert _rgb(field["buttonColor"]) == _rgb(field["tokens"]["link"])  # an existing token
    assert _contrast(field["buttonColor"], field["inputBg"]) >= 3.0  # 3:1 on the field


def test_the_button_and_the_field_open_the_picker_and_fall_back_to_the_focus(run):
    picker = run["picker"]
    assert picker["buttonCalls"] == 1 and picker["fieldCalls"] == 1  # showPicker from the button and from a tap on the field
    assert picker["refusedFocus"] is True  # showPicker refused: the input is focused
    assert picker["missingFocus"] is True and picker["fieldMissingFocus"] is True  # no showPicker (iPhone Safari): the input is focused


def test_opening_custom_moves_nothing_in_the_rows(run):
    for before, after in zip(run["home"]["rows"], run["homeCustom"]["rows"]):
        assert [(c["left"], c["top"], c["width"]) for c in before["chips"]] == [(c["left"], c["top"], c["width"]) for c in after["chips"]]


# ---- the sources ----------------------------------------------------------------------------------------------------------


def test_the_label_and_its_css_and_string_are_gone_and_the_strings_are_in_copy_js():
    assert "timeLabel" not in COPY and "arrive-custom__label" not in INDEX + CSS + GUIDE
    assert 'in90: "In 1 hr 30 min"' in COPY and 'timeAria: "Arrive by time"' in COPY and 'chooseTime: "Choose time"' in COPY
    assert '"arrive-90": "In 1 hr 30 min"' in INDEX and 'id="arrive-90"' in INDEX
    assert 'aria-label="Choose time"' in INDEX and 'aria-label="Arrive by time"' in INDEX
    assert 'document.getElementById("arrive-90").addEventListener("click"' in INDEX and "resolveChipDate(90)" in INDEX
    assert 'typeof arriveTimeInput.showPicker === "function"' in INDEX and "arriveTimeInput.focus();" in INDEX


def test_the_css_uses_tokens_only_and_hides_the_native_icon():
    assert ".arrive-time::-webkit-calendar-picker-indicator {\n  display: none;\n}" in CSS
    block = CSS.split("/* Two rows that never wrap inside", 1)[1].split(".arrive-custom {", 1)[0]
    field = CSS.split(".arrive-time-field .arrive-time {", 1)[1].split("}", 1)[0]
    button = CSS.split(".arrive-time-picker {", 1)[1].split("}", 1)[0]
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", block + field + button)
    assert "box-shadow: 0 0 0 2px var(--color-selected-outline);" in field and "border-radius: var(--radius-pill);" in field
    assert "color: var(--color-link);" in button and "width: var(--tap-min);" in button and "height: var(--tap-min);" in button
    assert "flex-wrap: nowrap;" in block and "white-space: nowrap;" in block


def test_the_style_guide_and_the_plan_describe_it():
    assert GUIDE.count("arrive-chips__row") >= 6 and "arriveBy.in90" in GUIDE and "arrive-time-picker" in GUIDE and "arrive-custom__label" not in GUIDE
    assert "In 1 hr 30 min" in GUIDE
    assert "two rows of chips, each on one line that never wraps" in PLAN and "`In 1 hr 30 min`" in PLAN
    assert "no visible `Time` label" in PLAN and "`Choose time`" in PLAN and "`showPicker()`" in PLAN
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes() and b"\n" not in (ROOT / "PROJECT_PLAN.md").read_bytes().replace(b"\r\n", b"")
