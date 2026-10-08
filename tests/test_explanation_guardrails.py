"""Every deterministic string of the AI card is safe: no guarantee, no unsafe advice, no stray digit.

Deterministic means written by Python or by the page, not by the model: the sentence-one variants, every
leave-sentence string (and the uncertain-location sentences), and every fixed clause (the dormant model path). A phrase from the guarantee or
unsafe-language lists, "will make it", "guaranteed", "definitely", or a digit that does not come through a template
placeholder, makes this test fail.
"""

import re
from pathlib import Path

import explain
from explain import (
    ACTION_ADVICE,
    GUARANTEE_PHRASES,
    S1_ARRIVING_NOW,
    S1_BUS_MINUTES,
    S1_SPEED,
    S1_UNLIKELY,
    S1_YOU,
    S2_LEAVE_BY,
    S2_LEAVE_NOW,
    S2_LEAVE_NOW_ARRIVING,
    S2_UNCERTAIN_BY,
    S2_UNCERTAIN_NOW,
    UNSAFE_PHRASES,
    clause_text,
    contains_guarantee,
    contains_unsafe,
)

ROOT = Path(__file__).resolve().parents[1]
EXTRA_BANNED = ("will make it", "guaranteed", "definitely", "certain to", "for sure", "no chance of missing")
PLACEHOLDERS = ("{distance}", "{kmh}", "{time}", "{x}", "{arrival}")


def _templates() -> dict[str, str]:
    strings = {
        "sentence one, arriving now": S1_ARRIVING_NOW,
        "sentence one, minutes": S1_BUS_MINUTES,
        "sentence one, one minute": "The bus is 1 minute away",
        "sentence one, you are": S1_YOU,
        "sentence one, unlikely": S1_UNLIKELY,
        "leave sentence, by": S2_LEAVE_BY,
        "leave sentence, now": S2_LEAVE_NOW,
        "leave sentence, now, bus arriving now": S2_LEAVE_NOW_ARRIVING,
        "leave sentence, uncertain after leave by": S2_UNCERTAIN_BY,
        "leave sentence, uncertain after leave now": S2_UNCERTAIN_NOW,
    }
    for kind, text in S1_SPEED.items():
        strings[f"sentence one, speed, {kind}"] = text
    for action, advice in ACTION_ADVICE.items():
        strings[f"dormant clause, {action}"] = clause_text(advice)
    return strings


def _page_and_copy_strings() -> dict[str, str]:
    copy = (ROOT / "static" / "copy.js").read_text(encoding="utf-8")
    block = copy.split("explanation: {", 1)[1].split("scenarios:", 1)[0]
    return {f"copy.js {i}": s for i, s in enumerate(re.findall(r'"((?:[^"\\]|\\.)*)"', block))}


def _check(name: str, text: str) -> None:
    lowered = text.lower().replace("’", "'")
    assert not contains_guarantee(text), (name, text)
    assert not contains_unsafe(text), (name, text)
    for phrase in GUARANTEE_PHRASES + EXTRA_BANNED:
        assert phrase not in lowered, (name, phrase)
    for phrase in UNSAFE_PHRASES:
        assert not re.search(r"\b" + re.escape(phrase) + r"\b", lowered), (name, phrase)
    # no digit except through a template placeholder ({e} stands for the bus minutes; the one-minute string is fixed)
    stripped = text
    for placeholder in PLACEHOLDERS + ("{e}",):
        stripped = stripped.replace(placeholder, "")
    if name != "sentence one, one minute":
        assert not re.search(r"\d", stripped), (name, text)
    for banned in ("probability", "chance", "%", "second"):
        assert banned not in lowered or name.startswith("copy.js"), (name, banned)


def test_every_deterministic_string_is_safe():
    templates = _templates()
    assert len(templates) == 10 + len(S1_SPEED) + len(ACTION_ADVICE)
    for name, text in templates.items():
        _check(name, text)


def test_the_page_and_copy_strings_of_the_card_are_safe_too():
    strings = _page_and_copy_strings()
    assert len(strings) > 15
    for name, text in strings.items():
        lowered = text.lower()
        assert not contains_guarantee(text) and not contains_unsafe(text), (name, text)
        for phrase in EXTRA_BANNED:
            assert phrase not in lowered, (name, phrase)
    page = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    region = page.split("var EXPL_ARRIVING_NOW", 1)[1].split("function renderExplanation(view)", 1)[0]
    for text in re.findall(r'"((?:[^"\\]|\\.)*)"', region):
        assert not contains_guarantee(text) and not contains_unsafe(text), text
        for phrase in EXTRA_BANNED:
            assert phrase not in text.lower(), (text, phrase)
        plain = text.replace(chr(92) + "u00a0", " ")  # the escape for a no-break space holds a zero
        assert not re.search(r"\d", plain.replace("{e}", "").replace("{n}", "").replace("{w}", "").replace("1 min", "")), text


def test_a_rendered_card_is_safe_for_every_variant():
    from datetime import datetime, timedelta, timezone

    from explain import build_numbers, card_text

    now = datetime(2026, 10, 5, 9, 0, tzinfo=timezone(timedelta(hours=8)))
    for e in (0, 1, 10):
        for action in explain.ACTIONS:
            for band in ("ok", "low", None):
                for unc in (False, True):
                    for source in ("gps", "cadence", "remembered", "default"):
                        for leave_in in (600, 0):
                            numbers = build_numbers(
                                bus_minutes=e, walk_minutes=3, chosen_action=action, distance_m=420.0, walk_speed_used=1.3,
                                walk_speed_source=source, leave_by=(now + timedelta(seconds=leave_in)).isoformat(),
                                arrival_time=(now + timedelta(minutes=e)).isoformat(), now=now)
                            text = card_text(numbers, band=band, uncertain=unc)
                            assert not contains_guarantee(text) and not contains_unsafe(text), text
                            lowered = text.lower()
                            for phrase in EXTRA_BANNED:
                                assert phrase not in lowered, (text, phrase)
