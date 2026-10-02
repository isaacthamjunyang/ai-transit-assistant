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

UNANSWERED_END_MINUTES = 10
MAX_MONITOR_MINUTES = 60

TRANSFER_NEAR_METERS = 300
TRANSFER_WATCH_MAX_MINUTES = 90
TRANSFER_BUS_SPEED_MPS = BUS_SPEED_KM_H / 3.6
LEG2_REACH_RANGE_FRACTION = 0.25

PAGE_CONSTANTS = {
    "MIN_REAL_CHANCE_RANGE_HIGH": MIN_REAL_CHANCE_RANGE_HIGH,
    "UNANSWERED_END_MINUTES": UNANSWERED_END_MINUTES,
    "MAX_MONITOR_MINUTES": MAX_MONITOR_MINUTES,
    "TRANSFER_NEAR_METERS": TRANSFER_NEAR_METERS,
    "TRANSFER_WATCH_MAX_MINUTES": TRANSFER_WATCH_MAX_MINUTES,
}
