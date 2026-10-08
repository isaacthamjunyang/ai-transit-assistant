"""The 12 full-text rows of the AI card (tmp/plan_edits_7.md section A), word for word, in Python and in the page mirror.

Example: now 3:55 PM, bus in 14 minutes (arrives 4:09 PM), leave by 4:04 PM, 203 m, 4.5 km/h. "~" stands for the
no-break space the strings carry between a number and its unit and before AM or PM.
"""

from datetime import datetime, timedelta, timezone

import pytest

from explain import build_numbers, card_text
from test_explanation_consistency import _case, _mirror_cases, needs_node

SGT = timezone(timedelta(hours=8))
NOON_ISH = datetime(2026, 10, 8, 15, 55, 0, tzinfo=SGT)  # 3:55 PM
LATE = datetime(2026, 10, 8, 23, 50, 0, tzinfo=SGT)  # 11:50 PM


def nb(text: str) -> str:
    return text.replace("~", " ")


# (label, case kwargs, expected text)
ROWS = [
    ("1 by, remembered", dict(e=14, leave_in=540, source="remembered", distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave by 4:04~PM so you have 5 minutes to reach your stop and catch the bus arriving at 4:09~PM."),
    ("2 by, measured", dict(e=14, leave_in=540, source="gps", speed=4.8 / 3.6, distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at about 4.8~km/h. "
     "Leave by 4:04~PM so you have 5 minutes to reach your stop and catch the bus arriving at 4:09~PM."),
    ("3 by, default", dict(e=14, leave_in=540, source="default", distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at an average speed of 4.5~km/h. "
     "Leave by 4:04~PM so you have 5 minutes to reach your stop and catch the bus arriving at 4:09~PM."),
    ("4 by, across midnight", dict(e=14, leave_in=540, source="remembered", distance=203.0, now=LATE),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave by 11:59~PM so you have 5 minutes to reach your stop and catch the bus arriving at 12:04~AM (tomorrow)."),
    ("5 by, X = 2", dict(e=14, leave_in=720, source="remembered", distance=203.0),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave by 4:07~PM so you have 2 minutes to reach your stop and catch the bus arriving at 4:09~PM."),
    ("6 now, e = 6", dict(e=6, leave_in=30, source="remembered", distance=203.0),
     "The bus is 6 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave now so you have 6 minutes to reach your stop and catch the bus arriving at 4:01~PM."),
    ("7 now, e = 1", dict(e=1, leave_in=0, source="remembered", distance=203.0),
     "The bus is 1 minute away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave now so you have 1 minute to reach your stop and catch the bus arriving at 3:56~PM."),
    ("8 now, arriving now", dict(e=0, leave_in=0, source="gps", speed=4.8 / 3.6, distance=20.0),
     "The bus is arriving now, and you are 20~m from the stop and walking at about 4.8~km/h. "
     "Leave now to try to catch the bus arriving at 3:55~PM."),
    ("9 by + uncertain", dict(e=14, leave_in=540, source="remembered", distance=203.0, unc=True),
     "The bus is 14 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave by 4:04~PM so you have 5 minutes to reach your stop and catch the bus arriving at 4:09~PM. "
     "Your location is uncertain, so leave a little earlier than that to be safe."),
    ("10 now + uncertain", dict(e=6, leave_in=30, source="remembered", distance=203.0, unc=True),
     "The bus is 6 minutes away, and you are 203~m from the stop and walking at your usual speed of 4.5~km/h. "
     "Leave now so you have 6 minutes to reach your stop and catch the bus arriving at 4:01~PM. "
     "Your location is uncertain, so the walking time may be off."),
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
        arrival_time=(now + timedelta(seconds=c["arr_off"])).isoformat(), now=now)
    return card_text(numbers, band=c["band"], uncertain=c["unc"])


@pytest.mark.parametrize("index", range(len(ROWS)), ids=[r[0] for r in ROWS])
def test_python_writes_the_row_word_for_word(index):
    assert _python_text(_cases()[index]) == nb(ROWS[index][2])


@needs_node
def test_the_page_mirror_writes_every_row_word_for_word():
    got = _mirror_cases(_cases())
    assert got == [nb(row[2]) for row in ROWS]


# ---- the boundary rule: X is the difference of the two clock minutes as displayed

BOUNDARY = [
    ("leave 4:04:59, arrival 4:09:00", dict(e=14, leave_in=599, arr_off=840)),
    ("leave 4:04:00, arrival 4:09:59", dict(e=14, leave_in=540, arr_off=899)),
]


def _boundary_cases():
    return [_case(now=NOON_ISH, speed=1.25, source="remembered", distance=203.0, **kwargs) for _l, kwargs in BOUNDARY]


@pytest.mark.parametrize("index", range(len(BOUNDARY)), ids=[b[0] for b in BOUNDARY])
def test_python_reads_5_minutes_when_the_displayed_clocks_are_5_apart(index):
    text = _python_text(_boundary_cases()[index])
    assert "so you have 5 minutes to reach your stop" in text and "Leave by 4:04 PM" in text


@needs_node
def test_the_page_mirror_reads_5_minutes_at_the_same_boundaries():
    cases = _boundary_cases()
    got = _mirror_cases(cases)
    assert got == [_python_text(c) for c in cases]
    assert all("so you have 5 minutes to reach your stop" in text for text in got)


def test_less_than_a_minute_apart_reads_one_minute():
    c = _case(e=14, now=NOON_ISH, speed=1.25, source="remembered", distance=203.0, leave_in=540, arr_off=540 + 30)
    # leave by 4:04:00 and a bus at 4:04:30 cannot be a leave-by case in the app, but the text still reads "1 minute"
    assert "so you have 1 minute to reach your stop" in _python_text(dict(c, e=9))
