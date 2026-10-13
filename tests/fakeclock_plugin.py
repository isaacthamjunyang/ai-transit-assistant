"""Opt-in pytest plugin that makes the app's own clock read a fixed Singapore time, to prove no test depends on the
machine time. Off unless used: `python -m pytest -p fakeclock_plugin` with FAKE_NOW_SGT="2026-10-13 00:48" in the
environment (and tests on PYTHONPATH). It replaces `datetime` in every project module (app and tests alike, like a system clock change) with a subclass whose
now() reads the machine clock shifted by a fixed offset, so the app sees that time at the start and time still passes
(a frozen clock would break the age and cooldown checks). App code is not changed and a normal run never loads this file."""

import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
SGT = timezone(timedelta(hours=8))
RAW = os.environ.get("FAKE_NOW_SGT", "")
FAKE = datetime.strptime(RAW, "%Y-%m-%d %H:%M").replace(tzinfo=SGT) if RAW else None
OFFSET = (FAKE - datetime.now(SGT)) if FAKE is not None else timedelta(0)


_Real = datetime


class _Meta(type(datetime)):
    def __instancecheck__(cls, instance):  # an ordinary datetime still counts as one
        return isinstance(instance, _Real)

    def __subclasscheck__(cls, subclass):
        return issubclass(subclass, _Real)


class _Fixed(datetime, metaclass=_Meta):
    @classmethod
    def now(cls, tz=None):
        moment = _Real.now(SGT) + OFFSET
        return moment.replace(tzinfo=None) if tz is None else moment.astimezone(tz)


def _shiftable(module) -> bool:
    """Any module of this project, app or test, that holds the real datetime class by name (not this plugin)."""
    path = getattr(module, "__file__", None)
    if not path or module is sys.modules.get(__name__):
        return False
    file = Path(path).resolve()
    return file.suffix == ".py" and (file.parent == ROOT or file.parent == TESTS)


@pytest.fixture(autouse=True)
def _fake_clock(monkeypatch):
    if FAKE is None:
        yield
        return
    for module in list(sys.modules.values()):
        if _shiftable(module) and getattr(module, "datetime", None) is _Real:
            monkeypatch.setattr(module, "datetime", _Fixed)
    real_time = time.time
    seconds = OFFSET.total_seconds()
    monkeypatch.setattr(time, "time", lambda: real_time() + seconds)  # epoch seconds move with the clock too
    yield
