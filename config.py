"""Named constants shared with the page. main.py writes them into the served page."""

from datetime import date

BUS_SPEED_KM_H = 18  # the existing ride-speed constant, defined here once

# The colour band of the probability ring is decided in Python from the point.
RING_BAND_OK_FROM = 50
RING_BAND_MID_FROM = 40

# Page C recommendation rules (recommend.py). The 40 is the existing gate: the Step 10 leave-now
# gate and the Step 11 reroute trigger (reroute.RANGE_HIGH_BELOW takes its value from here).
RUSH_MARGIN_MINUTES = 10
PROB_TIE_POINTS = 5
MIN_REAL_CHANCE_RANGE_HIGH = 40

# leave_by = bus ETA - walk time - this margin. 135 is the 45 s boarding buffer plus the 90 s sigmoid midpoint.
LEAVE_MARGIN_SECONDS = 135   # chosen by me: at leave_by the app's own catch chance is about 50 percent.

# At the stop: under 30 m from the boarding stop (the pace.is_near_stop rule), a fix of AT_STOP_MAX_ACCURACY_M or better
# no older than 60 s, and live data. The user is there, so there is no walk and no 45 s buffer: P is this number, the
# range is the same number and the action is wait. It is above the 92 percent cap of the formula on purpose.
AT_STOP_PROBABILITY = 97
AT_STOP_MAX_ACCURACY_M = 30

# Train headway used when the rail timetable has no figure: 300 s in the weekday peak hours, 420 s otherwise.
# Peak hours are the departure hours 07:00 to 08:59 and 17:00 to 19:59, Monday to Friday (LTA: 2 to 3 min peak, 5 to 7 off-peak).
RAIL_HEADWAY_PEAK_S = 300
RAIL_HEADWAY_OFFPEAK_S = 420
RAIL_PEAK_HOURS = (7, 8, 17, 18, 19)

UNANSWERED_END_MINUTES = 10
MAX_MONITOR_MINUTES = 60

# The walking speed. The default is the old assumed speed. A measured speed from the page replaces it
# for the walking terms only, after walk_speed.resolve_walk_speed clamps it to [MIN, MAX].
WALK_SPEED_DEFAULT_MPS = 1.25
WALK_SPEED_MIN_MPS = 0.5
WALK_SPEED_MAX_MPS = 1.4  # the top of a normal walk: the speed is never above this; running is not
# reliably recognised from the motion sensor alone and at worst gives this capped value
RANGE_SLOW_RATIO = 1.1 / 1.25  # the old slow end divided by the default
RANGE_FAST_RATIO = 1.4 / 1.25  # the old fast end divided by the default
# GPS-error conversion: metres of accuracy to seconds, and metres of fix age to seconds. This is a
# model of the error, not the user's pace, so it stays fixed whatever speed_used is.
ERROR_MODEL_SPEED_MPS = 1.25
# Pace guidance: below this gap between the fast end and the point there is no room to "walk faster".
PACE_MIN_HEADROOM_MPS = 0.05

PAGE_CONSTANTS = {
    "MIN_REAL_CHANCE_RANGE_HIGH": MIN_REAL_CHANCE_RANGE_HIGH,
    "UNANSWERED_END_MINUTES": UNANSWERED_END_MINUTES,
    "MAX_MONITOR_MINUTES": MAX_MONITOR_MINUTES,
}

# Singapore public holidays, which use the Sunday bus hours (service_hours.py).
# Source: Ministry of Manpower (mom.gov.sg). A date not listed here is read as the
# weekday, Saturday or Sunday it falls on. Update this list every year.
PUBLIC_HOLIDAYS: frozenset[date] = frozenset({
    # 2026 (remaining)
    date(2026, 11, 8),    # Deepavali (Sun)
    date(2026, 11, 9),    # Mon in lieu of Sun 8 Nov 
    date(2026, 12, 25),   # Christmas Day (Fri)
    # 2027
    date(2027, 1, 1),     # New Year's Day (Fri)
    date(2027, 2, 6),     # Chinese New Year (Sat)
    date(2027, 2, 7),     # Chinese New Year (Sun)
    date(2027, 2, 8),     # Mon in lieu of Sun 7 Feb 
    date(2027, 3, 10),    # Hari Raya Puasa (Wed)
    date(2027, 3, 26),    # Good Friday (Fri)
    date(2027, 5, 1),     # Labour Day (Sat)
    date(2027, 5, 17),    # Hari Raya Haji (Mon)
    date(2027, 5, 20),    # Vesak Day (Thu)
    date(2027, 8, 9),     # National Day (Mon)
    date(2027, 10, 28),   # Deepavali (Thu)
    date(2027, 12, 25),   # Christmas Day (Sat)
})

# The newest year the list covers; shown in the menu so you know when to update it.
PUBLIC_HOLIDAYS_YEAR: int = max(d.year for d in PUBLIC_HOLIDAYS)