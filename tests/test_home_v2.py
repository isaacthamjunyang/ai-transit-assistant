"""Home follows the approved design tmp/design/home-v2.html: four states, the animated hero and its still frame."""

import re
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")

HERO = INDEX.split('<div class="hero home-only">', 1)[1].split("</svg>", 1)[0] + "</svg>"


def _lum(rgb):
    def f(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2])


def _rgb(text):
    text = text.strip()
    if text.startswith("#"):
        text = text.lstrip("#")
        if len(text) == 3:
            text = "".join(ch * 2 for ch in text)
        return [int(text[i:i + 2], 16) for i in (0, 2, 4)]
    return [int(float(n)) for n in re.findall(r"[\d.]+", text)[:3]]


def _contrast(a, b):
    la, lb = sorted((_lum(_rgb(a)), _lum(_rgb(b))), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ---- static: the page, the copy file, the style guide, the plan -----------------------------------------------------


def test_the_hero_is_decorative_inline_svg_with_no_controls_no_styles_and_no_colours():
    assert 'aria-hidden="true"' in HERO and 'focusable="false"' in HERO
    assert not re.search(r"<(a|button|input|select|textarea)\b|tabindex|onclick|style=", HERO)
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", HERO) is None  # the colours come from the theme tokens
    assert "<image" not in HERO and "href=" not in HERO  # no remote or bundled picture


def test_the_hero_has_the_bus_the_train_the_tree_and_a_building_and_no_text():
    for part in ("hero-move--bus", "hero-move--train", "hero-tree", "hero-skyline", "hero-mbs", "hero-wheel"):
        assert part in HERO, part
    hero = INDEX.split('<div class="hero home-only">', 1)[1].split("</svg>", 1)[1].split("</div>", 1)[0]
    assert hero.strip() == ""  # nothing but the illustration inside the hero
    for text in ("Know when to leave.", "Catch your bus or train."):  # not used anywhere else either
        for name, body in (("index", INDEX), ("copy", COPY), ("guide", GUIDE), ("plan", PLAN), ("css", CSS)):
            assert text not in body, (name, text)
    for name, body in (("index", INDEX), ("copy", COPY), ("guide", GUIDE), ("css", CSS)):
        assert "heroLeave" not in body and "heroCatch" not in body and "hero__copy" not in body, name
        assert "hero__line" not in body and "hero-ink" not in body, name


def test_the_grey_support_line_is_gone_everywhere():
    line = "Live arrivals, catch chance and a personal leave-by time."
    for name, text in (("index", INDEX), ("copy", COPY), ("guide", GUIDE), ("plan", PLAN), ("css", CSS)):
        assert line not in text and "heroSupport" not in text and "hero-support" not in text, name
    for path in (ROOT / "tests").glob("*.py"):
        if path.name not in ("test_home_v2.py", "test_app_name_and_wording.py"):  # these two assert it is gone
            assert line not in path.read_text(encoding="utf-8"), path.name


def test_the_motion_is_slow_decorative_css_and_reduced_motion_makes_it_none():
    assert "animation-duration: 14s;" in CSS.split(".hero-move--bus {", 1)[1].split("}", 1)[0]
    train = CSS.split(".hero-move--train {", 1)[1].split("}", 1)[0]
    assert "animation-duration: 20s;" in train and "animation-delay: -7s;" in train
    assert "animation: hero-sway 3s ease-in-out infinite alternate;" in CSS
    assert "animation: hero-drift 18s ease-in-out infinite alternate;" in CSS
    assert "animation: home-shine 8s linear infinite;" in CSS
    reduced = CSS.split("@media (prefers-reduced-motion: reduce) {\n  .hero-move,", 1)[1].split("\n}\n", 1)[0]
    assert ".hero-tree" in reduced and ".hero-cloud" in reduced and "animation: none;" in reduced
    assert "setInterval" not in HERO and "requestAnimationFrame" not in HERO and "<animate" not in HERO  # pure CSS
    for keyframes in ("hero-drive-bus", "hero-drive-train", "hero-sway", "hero-drift", "home-shine"):
        assert f"@keyframes {keyframes}" in CSS, keyframes


def test_nothing_in_the_hero_flashes():
    # no keyframe step changes opacity or colour, so nothing can flash; the fastest loop is the 3 s sway
    for name in ("hero-drive-bus", "hero-drive-train", "hero-sway", "hero-drift"):
        block = CSS.split(f"@keyframes {name} " + "{", 1)[1].split("\n}\n", 1)[0]
        assert "opacity" not in block and "color" not in block and "visibility" not in block, name


def test_the_tokens_exist_in_theme_css_for_every_theme_and_the_page_uses_no_hex():
    for token in ("--hero-sky-1", "--hero-bus", "--hero-train", "--hero-tower-blue", "--hero-mbs"):
        assert THEME.count(f"{token}:") == 1, token  # the same in both themes: set once
    for token in ("--heading-g1", "--heading-g2", "--heading-g3", "--heading-g4"):
        assert THEME.count(f"{token}:") == 4, token  # base light, dark media, light and dark explicit
    home = CSS.split("/* ---- Home (approved design", 1)[1]
    hero = CSS.split(".hero {", 1)[1].split(".search-row {", 1)[0]
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", home + hero) is None


def test_the_heading_gradient_stops_have_4_5_to_1_on_the_card_in_both_themes():
    light = THEME.split(":root {", 1)[1].split("}", 1)[0]
    dark = THEME.split("@media (prefers-color-scheme: dark) {", 1)[1].split("\n  }\n", 1)[0]
    for block, card in ((light, "#FFFFFF"), (dark, "#16223A")):
        for n in range(1, 5):
            value = re.search(rf"--heading-g{n}: (#[0-9A-Fa-f]{{6}});", block).group(1)
            assert _contrast(value, card) >= 4.5, (n, value)


def _mix(a, b, t):
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(_rgb(a), _rgb(b)))


def test_the_heading_stays_4_5_to_1_at_every_point_of_the_gradient_in_both_themes():
    light = THEME.split(":root {", 1)[1].split("}", 1)[0]
    dark = THEME.split("@media (prefers-color-scheme: dark) {", 1)[1].split("\n  }\n", 1)[0]
    for block, card in ((light, "#FFFFFF"), (dark, "#16223A")):
        stops = [re.search(rf"--heading-g{n}: (#[0-9A-Fa-f]{{6}});", block).group(1) for n in (1, 2, 3, 4)]
        stops.append(stops[0])  # the gradient loops back to its first colour
        worst = 99
        for i in range(4):
            for step in range(0, 101):  # the browser blends in sRGB, one straight line per pair of stops
                worst = min(worst, _contrast(_mix(stops[i], stops[i + 1], step / 100), card))
        assert worst >= 4.5, (card, worst)


def test_the_heading_has_a_solid_fallback_and_is_still_with_reduced_motion():
    heading = CSS.split(".card .home-heading {", 1)[1].split("}", 1)[0]
    assert "background-clip: text;" in heading and "color: var(--color-ink);" in heading
    assert "animation: home-shine 8s linear infinite;" in heading
    fallback = CSS.split("@supports not ((-webkit-background-clip: text) or (background-clip: text)) {", 1)[1]
    assert "background: none;" in fallback.split("}", 1)[0] and "currentColor" in fallback.split("}", 1)[0]
    assert "@media (forced-colors: active)" in CSS
    reduced = CSS.split("@media (prefers-reduced-motion: reduce) {\n  .card .home-heading {", 1)[1].split("}", 1)[0]
    assert "animation: none;" in reduced
    block = CSS.split("@keyframes home-shine {", 1)[1].split("\n}\n", 1)[0]
    for forbidden in ("font-size", "padding", "margin", "line-height", "width", "height"):  # colour only: no shift
        assert forbidden not in block


def test_the_style_guide_shows_the_animated_hero_the_new_chips_and_the_find_route_bar():
    assert "hero-move--bus" in GUIDE and "hero-move--train" in GUIDE and "animated" in GUIDE
    assert 'class=\\"home-heading\\"' in GUIDE and "home-footer" in GUIDE and "info-row--location" in GUIDE
    assert "arrive-band" in GUIDE and "icon-tile--start" in GUIDE and "saved-panel__actions--form" in GUIDE
    assert "saved-panel__actions--delete" in GUIDE and "fr.savedPlaces" not in GUIDE


def test_the_plan_names_the_approved_design_and_the_motion():
    para = PLAN.split("**Home (the approved design supersedes the mockup for Home).**", 1)[1].split("\n", 1)[0]
    for text in ("tmp/design/home-v2.html", "14 s", "20 s", "reduced motion", "aria-hidden", "--hero-sky-*", "--heading-g1",
                 "`Just-In-Time`", "yellowish-orange menu button", "carries no text"):
        assert text in para, text
    assert b"\r\n" in (ROOT / "PROJECT_PLAN.md").read_bytes()  # the line endings are kept


# ---- the real page --------------------------------------------------------------------------------------------------

CASES = [(360, False), (360, True), (1280, False), (1280, True), (320, False), (320, True)]


@pytest.fixture(scope="module", params=CASES, ids=[f"{w}-{'dark' if d else 'light'}" for w, d in CASES])
def report(request, tmp_path_factory):
    require_edge()
    width, dark = request.param
    with running_app(tmp_path_factory.mktemp("homev2")) as base:
        return run_scenario("homev2", base, {"width": width, "dark": dark}, timeout=300)["result"]


def test_nothing_scrolls_sideways_in_any_state(report):
    for name, state in report["states"].items():
        geometry = state["geometry"]
        assert geometry["scrollWidth"] <= geometry["innerWidth"], name


def test_no_layout_shift_between_the_states(report):
    states = report["states"]
    keys = ("hero", "heading", "search", "row")
    for name in ("saved", "edit", "add"):
        for key in keys:
            assert states[name]["geometry"][key] == states["empty"]["geometry"][key], (name, key)
    assert states["saved"]["geometry"] == states["edit"]["geometry"]  # saved and edit mode: nothing moves at all
    assert states["empty"]["geometry"]["heroHeight"] == states["add"]["geometry"]["heroHeight"]


def test_every_control_is_at_least_44px_in_every_state(report):
    for name, state in report["states"].items():
        controls = state["controls"]
        for chip in controls["chips"]:
            assert chip["h"] >= 44 and chip["w"] >= 44, (name, chip)
        for key in ("#find-route", "#arrive-by-field", "#destination"):
            assert controls[key]["h"] >= 44, (name, key)
        for item in controls["panel"]:
            assert item["h"] >= 44, (name, item)
    assert report["states"]["empty"]["controls"]["#arrive-by-field"]["h"] >= 56
    assert report["states"]["empty"]["controls"]["#destination"]["h"] >= 44


def test_the_edit_and_done_chip_keeps_one_size(report):
    saved = [c for c in report["states"]["saved"]["controls"]["chips"] if c["text"] == "Edit"][0]
    editing = [c for c in report["states"]["edit"]["controls"]["chips"] if c["text"] == "Done"][0]
    assert saved["w"] == editing["w"] and saved["h"] == editing["h"]


def test_the_hero_is_animated_with_the_documented_durations(report):
    motion = report["motion"]
    assert motion["bus"] == {"name": "hero-drive-bus", "duration": "14s", "count": "infinite"}
    assert motion["train"] == {"name": "hero-drive-train", "duration": "20s", "count": "infinite"}
    assert motion["tree"]["name"] == "hero-sway" and motion["tree"]["duration"] == "3s"
    assert motion["cloud"]["name"] == "hero-drift" and motion["cloud"]["duration"] == "18s"
    assert motion["heading"]["name"] == "home-shine" and motion["heading"]["duration"] == "8s"


def test_the_hero_svg_is_aria_hidden_with_nothing_to_tap(report):
    for key in ("motion", "reduced"):
        motion = report[key]
        assert motion["ariaHidden"] == "true" and motion["focusable"] == "false"
        assert motion["interactive"] == 0 and motion["styleAttrs"] == 0


def test_with_reduced_motion_every_animation_is_none_and_the_bus_and_train_are_in_view(report):
    reduced = report["reduced"]
    for key in ("bus", "train", "tree", "cloud", "heading"):
        assert reduced[key]["name"] == "none", key
    assert reduced["busInside"] is True and reduced["trainInside"] is True  # a still frame showing both
    assert report["reducedFind"] == "none"


def test_the_hero_keeps_its_height_so_nothing_moves_while_it_plays(report):
    heights = {state["geometry"]["heroHeight"] for state in report["states"].values()}
    assert len(heights) == 1


def test_find_my_route_has_its_own_bar_and_is_dimmed_until_ready(report):
    find = report["find"]
    assert find["disabled"] == "true" and float(find["opacity"]) == 0.45
    assert find["footerHeight"] >= 52 + 32


def test_colours_pass_in_this_theme(report):
    t = report["tokens"]
    for stop in t["g"]:
        assert _contrast(stop, t["card"]) >= 4.5, stop
    assert _contrast(t["locationMeta"], t["pageCard"]) >= 4.5
    assert _contrast(t["arriveTitle"], t["arriveBg"]) >= 4.5
    assert _contrast(t["selectColor"], t["selectBg"]) >= 4.5
    assert _contrast(t["requiredColor"], t["arriveBg"]) >= 4.5
    assert _contrast(t["selectBorder"], t["selectBg"]) >= 3.0 and t["selectBorderWidth"] == "2px"
    assert _contrast(t["searchBorder"], t["searchBg"]) >= 3.0 and t["searchBorderWidth"] == "2px"
    assert _contrast(t["requiredBorder"], t["arriveBg"]) >= 3.0


# ---- the header, the removed strings, the delete question -------------------------------------------------------------

README = (ROOT / "README.md").read_text(encoding="utf-8")


def test_the_app_name_has_hyphens_everywhere_and_the_old_spelling_is_gone():
    for path in (".cursor/rules/mockup-fidelity.mdc", ".cursor/rules/ui-theme.mdc", ".cursorrules", "main.py",
                 "PROJECT_PLAN.md", "README.md", "static/copy.js", "static/index.html", "static/styleguide.html"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "Just in Time" not in text and "Just-In-Time" in text, path
    assert "<title>Just-In-Time</title>" in INDEX
    assert 'aria-label="Just-In-Time, go to home"' in INDEX and 'homeLabel: "Just-In-Time, go to home"' in COPY


def test_the_two_grey_lines_and_the_how_it_works_saved_line_are_gone_everywhere():
    for text in ("Pick a place from the results, then name it.", "Saved on this phone only."):
        for name, body in (("index", INDEX), ("copy", COPY), ("guide", GUIDE), ("plan", PLAN), ("readme", README)):
            assert text not in body, (name, text)
    for body in (INDEX, COPY, GUIDE):
        assert "pickHint" not in body and "saved-places-note" not in body and "is-concealed" not in body
    assert "is-concealed" not in CSS
    for name, body in (("index", INDEX), ("copy", COPY), ("guide", GUIDE), ("plan", PLAN)):  # the card is bare now
        assert "Saved places stay on this phone." not in body, name
    assert "first-run-saved" not in INDEX


def test_the_menu_button_is_the_yellowish_orange_fill_from_existing_tokens():
    rule = CSS.split(".app-header .icon-button {", 1)[1].split("}", 1)[0]
    assert "background: var(--fill-warning);" in rule and "color: var(--line-cc-ink);" in rule
    assert "border: 2px solid var(--status-uncertain);" in rule
    assert "--fill-warning: #F2A900;" in THEME  # the design's #F2A900
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", rule) is None
    assert 'class="icon-button" id="menu-open"' in INDEX and '<span class="visually-hidden">Menu</span>' in INDEX


def test_the_brand_is_a_primary_pill_with_white_text():
    brand = CSS.split(".app-header__brand {", 1)[1].split("}", 1)[0]
    assert "background: var(--color-primary);" in brand and "color: var(--color-primary-ink);" in brand
    assert "min-height: var(--tap-min);" in brand


def test_the_header_in_this_theme_is_named_coloured_and_44px(report):
    t, header = report["tokens"], report["header"]
    assert header["title"] == "Just-In-Time" and header["brand"] == "Just-In-Time"
    assert header["brandLabel"] == "Just-In-Time, go to home"
    assert header["menu"]["w"] >= 44 and header["menu"]["h"] >= 44 and header["brandBox"]["h"] >= 44
    assert header["menuName"] == "Menu"  # the accessible name
    assert _contrast(t["brandColor"], t["brandBg"]) >= 4.5
    assert _contrast(t["menuIcon"], t["menuBg"]) >= 4.5  # the icon on the button (3:1 is required)
    assert _contrast(t["menuBorder"], t["headerBg"]) >= 3.0 and t["menuBorderWidth"] == "2px"
    assert _rgb(t["menuBg"]) == [242, 169, 0]


def test_the_delete_question_uses_the_add_panels_button_colour_and_format(report):
    question, add = report["deleteQuestion"], report["addPanel"]
    assert question["order"] == ["Delete", "Cancel"]
    assert question["focus"] == "Cancel"  # the default focus
    delete, cancel = question["buttons"]
    save, add_cancel = add["buttons"]
    assert save["text"] == "Save" and add_cancel["text"] == "Cancel"
    for key in ("color", "background", "border", "borderWidth", "borderStyle", "radius", "fontSize", "fontWeight",
                "paddingLeft", "h"):
        assert delete[key] == add_cancel[key], ("Delete is the add panel's Cancel", key)
        assert cancel[key] == save[key], ("Cancel is the add panel's Save", key)
    assert delete["h"] >= 44 and cancel["h"] >= 44
    assert delete["border"] != cancel["border"]  # red against green: the words still tell them apart
    assert add["pick"] == -1  # the grey hint is gone


def test_the_delete_buttons_have_the_contrast_of_the_add_panel_buttons(report):
    delete, cancel = report["deleteQuestion"]["buttons"]
    card = report["tokens"]["card"]
    for button in (delete, cancel):
        assert _contrast(button["color"], card) >= 4.5 and _contrast(button["border"], card) >= 3.0


# ---- the heading is one line at every width and text size ------------------------------------------------------------

HEADING_CASES = [(w, d) for w in (320, 360, 390, 1280) for d in (False, True)]


@pytest.fixture(scope="module", params=HEADING_CASES, ids=[f"{w}-{'dark' if d else 'light'}" for w, d in HEADING_CASES])
def heading(request, tmp_path_factory):
    require_edge()
    width, dark = request.param
    with running_app(tmp_path_factory.mktemp("homeheading")) as base:
        return {"width": width, **run_scenario("homeheading", base, {"width": width, "dark": dark}, timeout=300)["result"]}


def test_the_heading_css_is_nowrap_and_sized_from_the_forms_width():
    heading_css = CSS.split(".card .home-heading {", 1)[1].split("}", 1)[0]
    assert "white-space: nowrap;" in heading_css
    assert "font-size: min(1.5rem, 6.2cqw);" in heading_css  # follows the form's width, capped, never wraps
    assert "container-type: inline-size;" in CSS.split("#destination-form {\n  gap: var(--space-4);", 1)[1].split("}", 1)[0]
    assert "background-clip: text;" in heading_css  # the gradient style is kept


def test_the_heading_is_one_line_at_every_width_and_text_size(heading):
    for pct, size in heading["sizes"].items():
        assert size["lines"] == 1, (heading["width"], pct, size["lines"])
        assert size["height"] <= size["lineHeight"] + size["padding"] + 1, (heading["width"], pct, size)  # one line tall
        assert size["whiteSpace"] == "nowrap"


def test_the_heading_text_never_overflows_or_clips_and_the_page_never_scrolls_sideways(heading):
    for pct, size in heading["sizes"].items():
        assert size["scrollWidth"] <= size["clientWidth"], (heading["width"], pct, size)
        assert size["textWidth"] <= size["formWidth"], (heading["width"], pct, size)
        assert size["pageScroll"] <= size["innerWidth"], (heading["width"], pct, size)


def test_the_heading_spans_about_80_percent_of_its_container_and_keeps_the_gradient(heading):
    if heading["width"] <= 390:
        for pct, size in heading["sizes"].items():
            assert 0.72 <= size["share"] <= 0.88, (heading["width"], pct, size["share"])
    assert heading["sizes"]["100"]["gradient"] is True and heading["sizes"]["100"]["clip"] == "text"
    assert heading["sizes"]["100"]["textAlign"] == "center"
    assert heading["sizes"]["100"]["fontSize"] >= 17  # readable, even at 320 px


def test_the_heading_is_centred_in_its_container_at_every_width_and_text_size(heading):
    assert "text-align: center;" in CSS.split(".card .home-heading {", 1)[1].split("}", 1)[0]
    for pct, size in heading["sizes"].items():
        assert abs(size["textMid"] - size["formMid"]) <= 2, (heading["width"], pct, size["textMid"], size["formMid"])
        assert abs(size["boxMid"] - size["formMid"]) <= 2, (heading["width"], pct)  # and its box fills the container


# ---- the Your location card is the Arrive by card ------------------------------------------------------------------------


def _rule(selector):
    return CSS.split(selector + " {", 1)[1].split("}", 1)[0]


def test_the_location_card_has_the_arrive_by_cards_fill_token_radius_and_padding():
    card, band = _rule(".info-row--location"), _rule(".arrive-band")
    for declaration in ("background: var(--color-secondary);", "border-radius: var(--radius-card);", "padding: var(--space-3);"):
        assert declaration in card and declaration in band, declaration
    assert "border" not in card.replace("border-radius", "") and "border" not in band.replace("border-radius", "")
    assert "surface-raised" not in card and "--surface-raised" not in THEME and "--surface-raised" not in CSS
    assert re.search(r"#[0-9a-fA-F]{3,8}\b|rgb\(|hsl\(", card) is None
    plan = PLAN.split("**Home (the approved design supersedes the mockup for Home).**", 1)[1].split("\n", 1)[0]
    assert "same card as `Arrive by`" in plan and "no border" in plan


def test_text_and_icon_pass_on_the_shared_fill_in_both_themes():
    light = THEME.split(":root {", 1)[1].split("}", 1)[0]
    dark = THEME.split("@media (prefers-color-scheme: dark) {", 1)[1].split("\n  }\n", 1)[0]
    for block in (light, dark):
        fill = re.search(r"--color-secondary: (#[0-9A-Fa-f]{6});", block).group(1)
        ink = re.search(r"--color-ink: (#[0-9A-Fa-f]{6});", block).group(1)
        live = re.search(r"--status-live: (#[0-9A-Fa-f]{6});", block).group(1)
        pin = re.search(r"--marker-start: (#[0-9A-Fa-f]{6});", block).group(1)
        assert _contrast(ink, fill) >= 4.5, (fill, ink)
        assert _contrast(pin, fill) >= 3.0, (fill, pin)  # the pin icon
        assert _contrast(live, fill) >= 3.0, (fill, live)  # the green dot


def test_in_this_theme_the_location_card_matches_the_arrive_by_card_exactly(report):
    t = report["tokens"]
    assert _rgb(t["locationFill"]) == _rgb(t["arriveBg"]) and t["locationFill"] != "rgba(0, 0, 0, 0)"
    assert _rgb(t["locationFill"]) == _rgb(t["secondary"])  # the shared token
    assert t["locationBorderWidth"] == t["arriveBorderWidth"] == "0px"
    assert t["locationBorderStyle"] == t["arriveBorderStyle"]
    assert t["locationRadius"] == t["arriveRadius"] == "12px"
    assert t["locationPadding"] == t["arrivePadding"] == ["16px"] * 4
    assert _contrast(t["locationMeta"], t["locationFill"]) >= 4.5 and _contrast(t["locationTitle"], t["locationFill"]) >= 4.5
    assert t["dotShown"] != "none" and _contrast(t["dot"], t["locationFill"]) >= 3.0  # the green dot is kept
    assert _contrast(t["pinColor"], t["locationFill"]) >= 3.0  # the pin icon on the card


def test_the_location_card_is_the_same_in_every_state(report):
    boxes = {name: state["geometry"]["locationBox"] for name, state in report["states"].items()}
    assert len({(b["h"], b["titleTop"], b["titleLeft"]) for b in boxes.values()}) == 1, boxes


# ---- one gap under the search bar and under the saved places, the same in every state ---------------------------------------


def test_the_gap_under_the_search_bar_equals_the_gap_under_the_saved_places_in_all_four_states(report):
    states = report["states"]
    assert set(states) == {"empty", "saved", "edit", "add"}
    searches = {name: state["geometry"]["searchGap"] for name, state in states.items()}
    locations = {name: state["geometry"]["savedGap"] for name, state in states.items()}
    for name in states:
        assert abs(searches[name] - locations[name]) <= 1, (name, searches[name], locations[name])  # the two gaps are equal
        assert abs(locations[name] - 36) <= 1, (name, locations[name])  # --space-6
    assert max(searches.values()) - min(searches.values()) <= 1, searches  # and the same in every state: no shift
    assert max(locations.values()) - min(locations.values()) <= 1, locations


def test_one_shared_spacing_token_makes_both_gaps():
    assert "--space-6: 36px;" in THEME and THEME.count("--space-6:") == 1
    for selector in (".quick-picks", ".info-row--location"):
        assert "margin-top: calc(var(--space-6) - var(--space-4));" in _rule(selector), selector
    assert ".saved-places:not(:has(> :not([hidden]))) {\n  display: none;" in CSS.replace("\r\n", "\n")
    plan = PLAN.split("**Home (the approved design supersedes the mockup for Home).**", 1)[1].split("\n", 1)[0]
    assert "36 px (`--space-6`)" in plan


def test_the_search_bar_has_no_placeholder_but_keeps_its_label():
    field = INDEX.split('id="destination"', 1)[1].split(">", 1)[0]
    assert "placeholder" not in field  # the example text is gone from the search bar
    assert "e.g. Marina Bay Sands, NUS, Orchard Road" not in INDEX + COPY + GUIDE + PLAN
    assert "placeholder:" not in COPY.split("home: {", 1)[1].split("savedPlaces", 1)[0]
    assert '<label class="visually-hidden" for="destination">Where do you want to go?</label>' in INDEX  # the accessible name
