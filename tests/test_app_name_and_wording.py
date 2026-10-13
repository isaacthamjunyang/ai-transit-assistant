"""The app name, the removed subtitle, and the removed lines (best available, the rough arrive-by check, "about" on the train
tiles). Static checks over the page, copy.js, the style guide, the plan and the rule files: nothing here calls an API."""

import re
from pathlib import Path

import journey
import pt_plan

ROOT = Path(__file__).resolve().parents[1]
NAME = "Beat the Bus and MRT"


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


INDEX, COPY, GUIDE, PLAN = (_read("static/index.html"), _read("static/copy.js"), _read("static/styleguide.html"), _read("PROJECT_PLAN.md"))
README, MAIN = _read("README.md"), _read("main.py")
NAMED_FILES = ("static/index.html", "static/copy.js", "static/styleguide.html", "PROJECT_PLAN.md", "README.md", "main.py",
               ".cursorrules", ".cursor/rules/mockup-fidelity.mdc", ".cursor/rules/ui-theme.mdc")


def test_the_app_is_named_beat_the_bus_and_mrt_in_the_page_title_header_and_home_link():
    assert f"<title>{NAME}</title>" in INDEX
    assert f'<span class="app-header__title">{NAME}</span>' in INDEX
    assert f'aria-label="{NAME}, go to home"' in INDEX
    assert f'homeLabel: "{NAME}, go to home"' in COPY and f'app: "{NAME}"' in COPY  # the home link and the Leave now banner
    assert f'<span class="leave-now-banner__app">{NAME}</span>' in INDEX
    assert f'FastAPI(title="{NAME}"' in MAIN
    assert f'<h1 class="app-header__title">{NAME}</h1>' in GUIDE
    assert NAME in README and NAME in PLAN


def test_the_old_name_is_gone_from_every_file_that_names_the_app():
    for path in NAMED_FILES:
        text = _read(path)
        assert not re.search(r"bus catch assistant", text, re.IGNORECASE), path


def test_the_internal_keys_that_hold_users_saved_settings_keep_their_old_spelling_on_purpose():
    # a rename here would make every phone forget its theme, step length and pace
    assert "bus-catch-theme" in _read("static/theme-boot.js")
    assert "bus-catch-step-length" in _read("static/walk-speed.js") and "bus-catch-pace" in _read("static/walk-speed.js")
    assert "busCatch:" in INDEX  # the history state key, never shown


def test_the_subtitle_is_gone_everywhere_and_the_home_tagline_is_unchanged():
    for path in NAMED_FILES:
        assert "AI-powered bus guidance" not in _read(path), path
    assert "app-header__subtitle" not in INDEX + GUIDE + _read("static/components.css")
    assert 'subtitle: "' not in COPY.split("home: {", 1)[1].split("},", 1)[0]
    support = "Get real-time bus information, catch probability and personalised leave-by time."
    assert support in INDEX and f'heroSupport: "{support}"' in COPY  # not asked to change


def test_the_best_available_line_is_gone_from_the_server_the_page_the_copy_and_the_guide():
    assert not hasattr(pt_plan, "BEST_AVAILABLE_MESSAGE")
    for name, text in (("index", INDEX), ("copy", COPY), ("guide", GUIDE)):
        assert "best available for this trip" not in text and "bestAvailable" not in text, name
    assert "best_available" not in _read("pt_plan.py") and "best_available" not in PLAN
    assert "This is the best available" not in PLAN
    # the empty-choice messages stay
    for text in ("No bus-only route found. Try another priority.", "No MRT or LRT route found. Try another priority."):
        assert text in COPY and text in INDEX


def test_the_rough_check_sentence_is_gone_but_the_risk_badge_stays():
    for name, text in (("index", INDEX), ("copy", COPY), ("guide", GUIDE), ("plan", PLAN), ("journey", _read("journey.py"))):
        assert "Rough check" not in text and "may miss arrive-by time" not in text, name
    assert "riskMessage" not in COPY and "arriveBy.riskMessage" not in GUIDE and not hasattr(journey, "LATE_MESSAGE")
    assert journey.LATE_LABEL == "Arrive-by check: Risk of delay" and 'risk: "Arrive-by check: Risk of delay"' in COPY
    assert "Earliest arrival is about {earliest}, after your {target} target." in COPY  # the planning warning is untouched


def test_the_train_tiles_under_next_trains_show_the_plain_time_and_other_about_strings_stay():
    tiles = INDEX.split("times.forEach(function (iso, index) {", 1)[1].split("var name = document.createElement", 1)[0]
    assert "formatClock(iso, true)" in tiles and "trainAbout" not in tiles
    # still "about", on purpose: the missed-train rows and the sentences
    assert "row.textContent = trainAbout(iso);" in INDEX
    for text in ('about: "about {time}"', 'left: "The {line} train has left. The next one is at about {time}."',
                 'every: "Every about {n} min"', 'ringLabel: "about {p} percent chance of catching the {line} train{eta}{at}"'):
        assert text in COPY, text
