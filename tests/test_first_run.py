"""The first-run explainer: five skippable steps over Home, shown once per phone (a versioned flag in this phone's
localStorage only), reopened from the menu as "How it works". No server is told, and Demo Mode never shows it.
Browser tests run the real page in headless Edge. No live service is called."""

import re
import shutil
import subprocess
import json
from pathlib import Path

import pytest

from page_runner import require_edge, run_scenario, running_app

ROOT = Path(__file__).resolve().parents[1]
INDEX = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
COPY = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
FIRST_RUN_JS = (ROOT / "static" / "first-run.js").read_text(encoding="utf-8")
GUIDE = (ROOT / "static" / "styleguide.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "components.css").read_text(encoding="utf-8")
THEME = (ROOT / "static" / "theme.css").read_text(encoding="utf-8")
PLAN = (ROOT / "PROJECT_PLAN.md").read_text(encoding="utf-8")

STEPS = ["Pick where you're going.", "We show when to leave and your chance of catching it.",
         "Walk, and we keep the chance updated.", "Missed it? We find other options.",
         "Get alerts during your journey."]


# ---- static ---------------------------------------------------------------------------------------------------

def test_the_words_are_in_copy_js_and_the_page_character_for_character():
    block = COPY.split("firstRun: {", 1)[1].split("},", 1)[0]
    for key, text in (("title", "How it works"), ("menu", "How it works"), ("stepOf", "Step {n} of {total}"),
                      ("step1", STEPS[0]), ("step2", STEPS[1]), ("step3", STEPS[2]), ("step4", STEPS[3]), ("step5", STEPS[4]), ("skip", "Skip"), ("next", "Next"),
                      ("done", "Done")):
        assert f'{key}: "{text}"' in block, key
    for name, text in (("FIRST_RUN_STEP_OF", "Step {n} of {total}"), ("FIRST_RUN_SKIP", "Skip"),
                       ("FIRST_RUN_NEXT", "Next"), ("FIRST_RUN_DONE", "Done")):
        assert f'var {name} = "{text}";' in INDEX
    for text in STEPS:
        assert f'"{text}"' in INDEX
    assert '<span>How it works</span></button>' in INDEX and 'aria-label="How it works"' in INDEX


def test_the_flag_is_one_versioned_key_in_its_own_file_and_the_page_never_touches_storage():
    assert 'var KEY = "bus-catch-first-run-v2";' in FIRST_RUN_JS and "VERSION = 2" in FIRST_RUN_JS
    assert "try {" in FIRST_RUN_JS and "fetch(" not in FIRST_RUN_JS and "XMLHttpRequest" not in FIRST_RUN_JS
    assert "localStorage" not in INDEX and "sessionStorage" not in INDEX  # index.html must not use storage
    assert "window.FirstRun.markDone()" in INDEX and 'src="first-run.js"' in INDEX
    controller = INDEX.split("function openFirstRun() {", 1)[1].split("function showDemoChrome", 1)[0]
    assert "fetch(" not in controller and "XMLHttpRequest" not in controller and "sendBeacon" not in controller


def test_the_card_is_a_fixed_overlay_with_tokens_only_and_44_px_controls():
    css = CSS.split("/* First-run explainer:", 1)[1]
    assert "position: fixed;" in css and "background: var(--scrim);" in css and "min-height: var(--tap-min);" in css
    assert not re.search(r"#[0-9A-Fa-f]{3,8}\b|rgb\(|hsl\(", css) and "style=" not in css
    assert THEME.count("--scrim:") == 4  # light, dark, and the two attribute overrides
    assert "role=\"dialog\" aria-modal=\"true\"" in INDEX
    assert ".style." not in INDEX.split("function openFirstRun() {", 1)[1].split("function showDemoChrome", 1)[0]


def test_the_plan_and_the_style_guide_describe_the_explainer():
    assert "**First-run explainer.**" in PLAN and "bus-catch-first-run-v2" in PLAN and "How it works" in PLAN
    assert "function sgFirstRun(" in GUIDE and "first-run__card" in GUIDE


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_flag_module_validates_and_survives_blocked_storage():
    program = r"""
var out = {};
function fake(items, broken) {
  var data = Object.assign({}, items);
  return { getItem: function (k) { if (broken === "get") { throw new Error("x"); } return k in data ? data[k] : null; },
           setItem: function (k, v) { if (broken === "set") { throw new Error("full"); } data[k] = String(v); },
           removeItem: function (k) { delete data[k]; }, _data: data };
}
function fresh(storage) {
  var win = { localStorage: storage };
  if (storage === "throws") { Object.defineProperty(win, "localStorage", { get: function () { throw new Error("blocked"); } }); }
  var holder = {};
  new Function("window", FIRST_RUN_SRC)(win);
  return win.FirstRun;
}
var FIRST_RUN_SRC = %SRC%;
var KEY = "bus-catch-first-run-v2";
var a = fresh(fake({})); out.empty = a.isDone(); a.markDone(); out.afterMark = a.isDone();
out.stored = JSON.parse(fake({})._data[KEY] || "null");
var s1 = fake({}); var b = fresh(s1); b.markDone(); out.written = s1._data[KEY];
out.rereads = fresh(s1).isDone();
out.badValues = ["", "true", "{}", "{\"v\":1,\"done\":true}", "{\"v\":3,\"done\":true}", "{\"v\":2,\"done\":false}", "[1]", "null", "x".repeat(200), "{\"v\":2,\"done\":\"yes\"}"]
  .map(function (raw) { var s = {}; s[KEY] = raw; return fresh(fake(s)).isDone(); });
var c = fresh("throws"); out.blockedEmpty = c.isDone(); out.blockedMark = c.markDone(); out.blockedAfter = c.isDone(); out.blockedAvail = c.storageAvailable();
var d = fresh(fake({}, "set")); d.markDone(); out.setFails = d.isDone(); out.setFailsAvail = d.storageAvailable();
var e = fresh(fake({}, "get")); out.getFails = e.isDone();
console.log(JSON.stringify(out));
""".replace("%SRC%", json.dumps(FIRST_RUN_JS))
    done = subprocess.run(["node", "-e", program], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert done.returncode == 0, done.stderr[-800:]
    out = json.loads(done.stdout)
    assert out["empty"] is False and out["afterMark"] is True
    assert json.loads(out["written"]) == {"v": 2, "done": True} and out["rereads"] is True
    # anything but the exact object counts as not seen, and so does the old v1 flag (so the two new steps show once)
    assert out["badValues"] == [False] * 10
    assert out["blockedEmpty"] is False and out["blockedMark"] is False and out["blockedAfter"] is True
    assert out["blockedAvail"] is False  # unavailable storage still works for the session, from memory
    assert out["setFails"] is True and out["setFailsAvail"] is False and out["getFails"] is False


# ---- the real page --------------------------------------------------------------------------------------------

VIEWPORTS = [("l360", 360, 800, False), ("d1280", 1280, 900, True)]


def _run(tmp_path_factory, name, width, height, dark, mode):
    require_edge()
    with running_app(tmp_path_factory.mktemp(name)) as base:
        return run_scenario("firstrun", base, {"name": name, "width": width, "height": height, "dark": dark, "mode": mode},
                            timeout=300)["result"]


@pytest.fixture(scope="module", params=VIEWPORTS, ids=["360-light", "1280-dark"])
def normal(request, tmp_path_factory):
    name, width, height, dark = request.param
    return _run(tmp_path_factory, "fr" + name, width, height, dark, "normal")


@pytest.fixture(scope="module")
def blocked(tmp_path_factory):
    return _run(tmp_path_factory, "frblocked", 360, 800, False, "blocked")


def test_it_opens_on_the_first_visit_with_step_one_an_icon_and_44_px_controls(normal):
    opened = normal["opened"]
    assert opened["shown"] is True and opened["bodyClass"] is True and opened["flag"] is None
    assert opened["step"] == "Step 1 of 5" and opened["text"] == STEPS[0] and opened["icon"] is True
    assert opened["active"] == "first-run-next" and opened["inside"] is True  # focus moves into the card
    labels = {b["id"]: b for b in opened["buttons"]}
    assert labels["first-run-skip"]["text"] == "Skip" and labels["first-run-next"]["text"] == "Next"
    assert all(b["h"] >= 44 for b in opened["buttons"] if not b["hidden"])
    assert opened["card"]["r"] <= opened["innerWidth"] and opened["scrollWidth"] <= opened["innerWidth"]


def test_the_five_steps_run_in_order_and_only_the_last_has_done_and_no_skip(normal):
    for n in (2, 3, 4, 5):
        assert normal[f"step{n}"]["step"] == f"Step {n} of 5" and normal[f"step{n}"]["text"] == STEPS[n - 1]
    for n in (2, 3, 4):
        buttons = {b["id"]: b for b in normal[f"step{n}"]["buttons"]}
        assert buttons["first-run-next"]["text"] == "Next" and buttons["first-run-skip"]["hidden"] is False
    last = {b["id"]: b for b in normal["step5"]["buttons"]}
    assert last["first-run-next"]["text"] == "Done" and last["first-run-skip"]["hidden"] is True


def test_done_sets_the_flag_and_closes_and_it_does_not_come_back_after_a_reload(normal):
    after = normal["afterDone"]
    assert after["shown"] is False and after["bodyClass"] is False
    assert json.loads(after["flag"]) == {"v": 2, "done": True} and after["api"]["done"] is True
    assert normal["reloaded"]["shown"] is False


def test_the_keyboard_keeps_focus_inside_and_escape_closes(normal):
    assert set(normal["tabs"]) <= {"first-run-skip", "first-run-next"} and len(set(normal["tabs"])) == 2
    assert normal["shiftTab"] in ("first-run-skip", "first-run-next")
    assert normal["reopened"]["shown"] is True and normal["reopened"]["step"] == "Step 1 of 5"
    assert normal["afterEscape"]["shown"] is False
    assert json.loads(normal["afterEscape"]["flag"]) == {"v": 2, "done": True}


def test_the_menu_row_reopens_it_and_closes_the_menu(normal):
    assert normal["menuOpen"]["menuHidden"] is False and normal["reopened"]["menuHidden"] is True
    assert normal["reopened"]["shown"] is True


def test_skip_sets_the_flag(normal):
    assert normal["afterSkip"]["shown"] is False
    assert normal["fresh"]["shown"] is True and normal["fresh"]["flag"] is None  # a reset phone shows it again
    assert normal["skipFlag"]["shown"] is False and json.loads(normal["skipFlag"]["flag"]) == {"v": 2, "done": True}


def test_demo_mode_never_shows_it(normal):
    assert normal["demo"]["shown"] is False


def test_no_network_request_is_made_by_the_card_and_nothing_shifts(normal):
    assert normal["step3"]["requests"] == normal["opened"]["requests"]  # Next makes no request
    assert normal["afterDone"]["requests"] == normal["opened"]["requests"]  # Done makes none
    assert normal["reopened"]["requests"] == normal["menuOpen"]["requests"]  # the menu's own data request came first
    for key in ("afterDone", "reopened"):  # the overlay is fixed: the page's own boxes do not move
        assert normal[key]["header"] == normal["opened"]["header"], key
        assert normal[key]["main"] == normal["opened"]["main"], key


def test_with_storage_blocked_it_still_works_for_the_session(blocked):
    assert blocked["opened"]["shown"] is True and blocked["opened"]["api"]["storage"] is False
    assert blocked["step5"]["buttons"][1]["text"] == "Done"
    assert blocked["afterDone"]["shown"] is False and blocked["afterDone"]["api"]["done"] is True  # kept in memory
    assert blocked["reopened"]["shown"] is True and blocked["afterEscape"]["shown"] is False
    assert blocked["afterSkip"]["shown"] is False
