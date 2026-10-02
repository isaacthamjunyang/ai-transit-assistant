"""Which option the reroute page recommends. Pure Python, ordered rules, no blended score.

Inputs per option: point and range probability, estimated arrival A, walk distance d to its
stop (0 at the current stop), service and stop. Overall input: the arrive-by target T, if set.
The walk is already inside each probability, so the three factors are the target, the catch
probability and the walking distance. The first matching rule wins and an option whose
range_high is below MIN_REAL_CHANCE_RANGE_HIGH is never recommended.
"""

from datetime import datetime

from config import MIN_REAL_CHANCE_RANGE_HIGH, PROB_TIE_POINTS, RUSH_MARGIN_MINUTES

FASTEST_RUSHING = "FASTEST_RUSHING"
HIGHEST_CHANCE_ON_TIME = "HIGHEST_CHANCE_ON_TIME"
HIGHEST_CHANCE = "HIGHEST_CHANCE"
SHORTER_WALK = "SHORTER_WALK"
NONE_BY_TARGET = "NONE_BY_TARGET"
REASON_CODES = (FASTEST_RUSHING, HIGHEST_CHANCE_ON_TIME, HIGHEST_CHANCE, SHORTER_WALK, NONE_BY_TARGET)

# Written here, never by the model. {s} is the service number and the only digits in any sentence.
REASON_TEXT = {
    FASTEST_RUSHING: "Your arrive-by time is close, so Bus {s} is recommended: it should get you to your destination first.",
    HIGHEST_CHANCE_ON_TIME: (
        "Bus {s} is recommended: it has the highest chance of catching, "
        "and it should still get you there by your arrive-by time."
    ),
    HIGHEST_CHANCE: "Bus {s} is recommended: it has the highest chance of catching.",
    SHORTER_WALK: "Bus {s} has a similar chance to the other options, and the walk to its stop is shorter.",
    NONE_BY_TARGET: (
        "No option should reach your destination by your arrive-by time. "
        "Bus {s} should get you there earliest."
    ),
}


def reason_text(code: str, service: str) -> str:
    return REASON_TEXT[code].replace("{s}", service)


def _when(value) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def natural_key(service) -> tuple:
    text = str(service)
    return (0, int(text), text) if text.isdigit() else (1, 0, text)


def _distance(option: dict) -> float:
    """The walk to the option's stop: 0 at the current stop (walk_m), else the straight-line distance."""
    value = option.get("walk_m", option.get("distance_m"))
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def arrival_key(option: dict, field: str = "estimated_arrival") -> tuple:
    """Earlier first; an option with no usable estimate sorts last."""
    when = _when(option.get(field))
    return (when is None, when.timestamp() if when is not None else 0.0)


def _is_eligible(option: dict) -> bool:
    high = option.get("range_high")
    return isinstance(high, int) and not isinstance(high, bool) and high >= MIN_REAL_CHANCE_RANGE_HIGH


def _highest_point(options: list[dict]) -> dict:
    """The highest point probability, ties to the earlier arrival, then the service number."""
    return min(
        options,
        key=lambda o: (-o["point"], arrival_key(o), natural_key(o.get("service_no", ""))),
    )


def _best_by_chance(options: list[dict]) -> tuple[dict, str]:
    """Highest point probability; a tie within PROB_TIE_POINTS goes to the shorter walk, then the earlier A."""
    top = _highest_point(options)
    cohort = [o for o in options if top["point"] - o["point"] <= PROB_TIE_POINTS]
    chosen = min(
        cohort,
        key=lambda o: (_distance(o), arrival_key(o), -o["point"], natural_key(o.get("service_no", ""))),
    )
    by_walk = chosen is not top and _distance(chosen) < _distance(top)
    return chosen, SHORTER_WALK if by_walk else None


def _earliest(options: list[dict]) -> dict:
    """Earliest estimated arrival; ties to the higher probability, then the shorter walk."""
    return min(
        options,
        key=lambda o: (arrival_key(o), -o["point"], _distance(o), natural_key(o.get("service_no", ""))),
    )


def recommend_option(options: list[dict], target: datetime | str | None = None) -> dict | None:
    """The recommended option and why: {"id", "reason"}, or None when nothing is eligible.

    Rules, first match wins:
      0. Eligible options have range_high at or above MIN_REAL_CHANCE_RANGE_HIGH. None: no recommendation.
      1. Target set. ontime = eligible options with A at or before T.
         No ontime option: the eligible option with the earliest A (NONE_BY_TARGET).
         Otherwise best = the highest point probability among ontime options. Rushing means
         T minus A of best is less than RUSH_MARGIN_MINUTES: the earliest ontime option wins
         (FASTEST_RUSHING, or HIGHEST_CHANCE_ON_TIME when it is best itself). Not rushing: best
         (HIGHEST_CHANCE_ON_TIME, or SHORTER_WALK when the walk tie-break decided it).
      2. No target: the highest point probability (HIGHEST_CHANCE, or SHORTER_WALK).
    """
    eligible = [o for o in options if _is_eligible(o)]
    if not eligible:
        return None
    deadline = _when(target)
    if deadline is None:
        chosen, walk = _best_by_chance(eligible)
        return {"id": chosen["id"], "reason": walk or HIGHEST_CHANCE}
    ontime = []
    for option in eligible:
        arrival = _when(option.get("estimated_arrival"))
        if arrival is not None and arrival <= deadline:
            ontime.append(option)
    if not ontime:
        return {"id": _earliest(eligible)["id"], "reason": NONE_BY_TARGET}
    best, walk = _best_by_chance(ontime)
    spare = (deadline - _when(best["estimated_arrival"])).total_seconds() / 60
    if spare < RUSH_MARGIN_MINUTES:
        quickest = _earliest(ontime)
        reason = HIGHEST_CHANCE_ON_TIME if quickest is best else FASTEST_RUSHING
        return {"id": quickest["id"], "reason": reason}
    return {"id": best["id"], "reason": walk or HIGHEST_CHANCE_ON_TIME}


def pills(options: list[dict]) -> dict[str, str | None]:
    """The ids that carry each pill. No blended score.

    highest_chance: the highest point probability among all options (ties to the earlier arrival).
    fastest: the earliest estimated arrival among options whose range_high is at least
    MIN_REAL_CHANCE_RANGE_HIGH and that have an estimate (ties to the higher probability).
    """
    holders: dict[str, str | None] = {"highest_chance": None, "fastest": None}
    if not options:
        return holders
    holders["highest_chance"] = _highest_point(options)["id"]
    pool = [o for o in options if _is_eligible(o) and _when(o.get("estimated_arrival")) is not None]
    if pool:
        holders["fastest"] = min(
            pool,
            key=lambda o: (arrival_key(o), -o["point"], natural_key(o.get("service_no", ""))),
        )["id"]
    return holders
