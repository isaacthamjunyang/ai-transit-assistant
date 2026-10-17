"""The 12 full-text rows of the AI card (tmp/plan_edits_7.md section A), word for word, in Python and in the page mirror.

Example: now 3:55 PM, bus in 14 minutes (arrives 4:09 PM), leave by 4:04 PM, 203 m, 4.5 km/h. "~" stands for the
no-break space the strings carry between a number and its unit and before AM or PM.
"""

from datetime import datetime, timedelta, timezone

import pytest

from explain import build_numbers, card_text
from test_explanation_consistency import _case, _mirror_cases, _python_lead, needs_node

SGT = timezone(timedelta(hours=8))
NOON_ISH = datetime(2026, 10, 8, 15, 55, 0, tzinfo=SGT)  # 3:55 PM
LATE = datetime(2026, 10, 8, 23, 50, 0, tzinfo=SGT)  # 11:50 PM


def nb(text: str) -> str:
    return text.replace("~", " ")


# (label, case kwargs, expected text)
ROWS = [
    ("1 by, remembered", dict(e=14, w=5, leave_in=540, source="remembered", distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave by 4:04~PM to reach your stop in 5 minutes and catch the bus arriving at 4:09~PM."),
    ("2 by, measured", dict(e=14, w=5, leave_in=540, source="gps", speed=4.8 / 3.6, distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at about 4.8~km/h. "
     "Leave by 4:04~PM to reach your stop in 5 minutes and catch the bus arriving at 4:09~PM."),
    ("3 by, default", dict(e=14, w=5, leave_in=540, source="default", distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at an average speed of 4.5~km/h. "
     "Leave by 4:04~PM to reach your stop in 5 minutes and catch the bus arriving at 4:09~PM."),
    ("4 by, across midnight", dict(e=14, w=5, leave_in=540, source="remembered", distance=203.0, now=LATE),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave by 11:59~PM to reach your stop in 5 minutes and catch the bus arriving at 12:04~AM (tomorrow)."),
    ("5 by, X = 2", dict(e=14, w=2, leave_in=720, source="remembered", distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave by 4:07~PM to reach your stop in 2 minutes and catch the bus arriving at 4:09~PM."),
    ("6 now, e = 6", dict(e=6, w=6, leave_in=30, source="remembered", distance=203.0),
     "The bus is 6 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave now to reach your stop in 6 minutes and catch the bus arriving at 4:01~PM."),
    ("7 now, e = 1", dict(e=1, w=1, leave_in=0, source="remembered", distance=203.0),
     "The bus is 1 minute away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave now to reach your stop in 1 minute and catch the bus arriving at 3:56~PM."),
    ("8 now, arriving now", dict(e=0, leave_in=0, source="gps", speed=4.8 / 3.6, distance=20.0),
     "The bus is arriving now, and you are 20~m from the stop and walking at about 4.8~km/h. "
     "Leave now to try to catch the bus arriving at 3:55~PM."),
    ("9 by + uncertain", dict(e=14, w=5, leave_in=540, source="remembered", distance=203.0, unc=True),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave by 4:04~PM to reach your stop in 5 minutes and catch the bus arriving at 4:09~PM. "
     "Location uncertain: leave a little earlier to be safe."),
    ("10 now + uncertain", dict(e=6, w=6, leave_in=30, source="remembered", distance=203.0, unc=True),
     "The bus is 6 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave now to reach your stop in 6 minutes and catch the bus arriving at 4:01~PM. "
     "Location uncertain: the walk time may be off."),
    ("11 unlikely", dict(e=14, leave_in=540, band="low", distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop, but catching this bus is unlikely."),
    ("12 unlikely, arriving now, 800 m", dict(e=0, leave_in=540, band="low", distance=800.0),
     "The bus is arriving now, and you are 800~m from the stop, but catching this bus is unlikely."),
]


def _cases():
    out = []
    for _label, kwargs, _text in ROWS:
        kwargs = dict(kwargs)
        kwargs.setdefault("now", NOON_ISH)
        kwargs.setdefault("speed", 1.25)
        out.append(_case(**kwargs))
    return out


def _python_text(c) -> str:
    now = datetime.fromisoformat(c["now"])
    numbers = build_numbers(
        bus_minutes=c["e"], walk_minutes=c["w"], chosen_action=c["action"], distance_m=c["distance"],
        walk_speed_used=c["speed"], walk_speed_source=c["source"],
        leave_by=(now + timedelta(seconds=c["leave_in"])).isoformat(),
        arrival_time=(now + timedelta(seconds=c["arr_off"])).isoformat(), now=now, at_stop=c.get("at_stop", False))
    return card_text(numbers, band=c["band"], uncertain=c["unc"])


@pytest.mark.parametrize("index", range(len(ROWS)), ids=[r[0] for r in ROWS])
def test_python_writes_the_row_word_for_word(index):
    assert _python_text(_cases()[index]) == nb(ROWS[index][2])


@needs_node
def test_the_page_mirror_writes_every_row_word_for_word():
    got = _mirror_cases(_cases())
    assert got == [nb(row[2]) for row in ROWS]


# ---- one value: the walk minutes in the sentence are the pack's walk_minutes, whatever the two clock times are

BOUNDARY = [
    ("leave 4:04:59, arrival 4:09:00", dict(e=14, w=5, leave_in=599, arr_off=840)),
    ("leave 4:04:00, arrival 4:09:59", dict(e=14, w=5, leave_in=540, arr_off=899)),
    ("gap 2 but walk 7", dict(e=14, w=7, leave_in=720, arr_off=840)),
]


def _boundary_cases():
    return [_case(now=NOON_ISH, speed=1.25, source="remembered", distance=203.0, **kwargs) for _l, kwargs in BOUNDARY]


@pytest.mark.parametrize("index", range(len(BOUNDARY)), ids=[b[0] for b in BOUNDARY])
def test_python_states_the_walk_minutes_not_the_gap(index):
    case = _boundary_cases()[index]
    assert f"to reach your stop in {case['w']} minutes and catch the bus" in _python_text(case)


@needs_node
def test_the_page_mirror_states_the_same_walk_minutes():
    cases = _boundary_cases()
    assert _mirror_cases(cases) == [_python_text(c) for c in cases]


def _sentence_minutes(text: str):
    import re

    found = re.search(r" in (\d+) minutes? and catch the (?:bus|train)", text)
    return int(found.group(1)) if found else None


def _tile_grid():
    cases = []
    for e in (2, 6, 14):
        for w in (1, 2, 5, 12):
            for leave_in in (30, 540, 900):
                for unc in (False, True):
                    for train in (None, "North-South Line"):
                        cases.append(_case(e=e, w=w, now=NOON_ISH, speed=1.25, source="gps", distance=203.0,
                                           leave_in=leave_in, unc=unc, train=train))
    return cases


@needs_node
def test_the_tile_minutes_equal_the_minutes_in_the_sentence_for_every_grid_case():
    cases = _tile_grid()
    texts = _mirror_cases(cases)
    assert len(texts) == len(cases)
    seen = {"1 minute": 0, "uncertain": 0, "train": 0}
    for case, text in zip(cases, texts):
        assert _sentence_minutes(text) == case["w"], (case, text)
        seen["1 minute"] += case["w"] == 1
        seen["uncertain"] += case["unc"]
        seen["train"] += bool(case["train"])
    assert all(seen.values()) and ("in 1 minute and catch" in " ".join(texts))


def test_the_leave_sentences_never_use_the_leave_to_arrival_gap():
    for case in _tile_grid():
        now = datetime.fromisoformat(case["now"])
        numbers = build_numbers(
            bus_minutes=case["e"], walk_minutes=case["w"], chosen_action="wait", distance_m=203.0, walk_speed_used=1.25,
            walk_speed_source="gps", leave_by=(now + timedelta(seconds=case["leave_in"])).isoformat(),
            arrival_time=(now + timedelta(seconds=case["arr_off"])).isoformat(), now=now, train_line=case["train"])
        text = card_text(numbers, band="ok", uncertain=case["unc"])
        assert "so you have" not in text and _sentence_minutes(text) == case["w"], text


# ---- at the stop (tmp/plan_edits_8.md section 6): the whole card, nothing after it

AT_STOP_ROWS = [
    ("A1 e = 4", 4, "You're here. 4 minutes to wait."),
    ("A2 e = 2", 2, "You're here. 2 minutes to wait."),
    ("A3 e = 1", 1, "You're here. 1 minute to wait."),
    ("A4 arriving now", 0, "You're here. The bus is arriving."),
    ("A5 e = 14", 14, "You're here. 14 minutes to wait."),
]


def _at_stop_cases():
    return [_case(e=e, now=NOON_ISH, speed=1.25, source="gps", distance=12.0, leave_in=-100, at_stop=True)
            for _label, e, _text in AT_STOP_ROWS]


@pytest.mark.parametrize("index", range(len(AT_STOP_ROWS)), ids=[r[0] for r in AT_STOP_ROWS])
def test_python_writes_the_at_stop_rows_word_for_word(index):
    assert _python_text(_at_stop_cases()[index]) == AT_STOP_ROWS[index][2]


@needs_node
def test_the_page_mirror_writes_the_at_stop_rows_word_for_word():
    assert _mirror_cases(_at_stop_cases()) == [row[2] for row in AT_STOP_ROWS]


@needs_node
def test_python_and_the_page_mirror_agree_for_every_bus_minute_at_the_stop():
    cases = [_case(e=e, now=NOON_ISH, speed=1.25, source=source, distance=15.0, leave_in=leave_in, unc=unc, at_stop=True)
             for e in range(0, 31) for source in ("gps", "default") for leave_in in (-50, 30, 900) for unc in (False, True)]
    assert _mirror_cases(cases) == [_python_text(c) for c in cases]


def test_at_the_stop_nothing_about_speed_distance_or_leaving_follows():
    for case in _at_stop_cases():
        text = _python_text(case)
        assert text.count(".") == 2 and "km/h" not in text and "Leave" not in text and "uncertain" not in text
        assert "from the stop" not in text and "unlikely" not in text


def test_the_low_band_and_the_uncertain_flag_do_not_change_the_at_stop_card():
    plain = _python_text(_case(e=4, now=NOON_ISH, source="gps", distance=12.0, at_stop=True))
    assert _python_text(_case(e=4, now=NOON_ISH, source="gps", distance=12.0, at_stop=True, band="low", unc=True)) == plain


TRAIN_AT_STATION_ROWS = [
    (4, "You're here. 4 minutes to wait."),
    (1, "You're here. 1 minute to wait."),
    (0, "You're here. The train is arriving."),
]


def _train_at_station_cases():
    return [_case(e=e, now=NOON_ISH, speed=1.25, source="gps", distance=12.0, leave_in=-100, at_stop=True,
                  train="North-South Line") for e, _text in TRAIN_AT_STATION_ROWS]


def test_python_tells_a_train_rider_at_the_station_the_train_is_arriving():
    texts = [_python_lead(c) for c in _train_at_station_cases()]
    assert texts == [row[1] for row in TRAIN_AT_STATION_ROWS]
    assert not any("bus" in t.lower() or "stop" in t.lower() for t in texts)


@needs_node
def test_the_page_mirror_tells_a_train_rider_the_same():
    assert _mirror_cases(_train_at_station_cases()) == [row[1] for row in TRAIN_AT_STATION_ROWS]
