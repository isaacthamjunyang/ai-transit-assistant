"""Named constants shared with the page. main.py writes them into the served page."""

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
