"""Foreground transfer wait. A later GPS fix has to confirm the stay."""

TRANSFER_RADIUS_M = 50
TRANSFER_WAIT_S = 30


def fresh_transfer_wait() -> dict:
    return {"armed_at": None, "last_confirmed_at": None}


def note_transfer_fix(state: dict, distance_m: float | None, at: float | None, valid: bool) -> str:
    """Return ignore, waiting, cancel, or activate.

    An invalid fix does not start or extend a stay, and it does not activate.
    A gap of WAIT seconds or more between valid inside fixes starts a new wait.
    """
    if (
        not valid
        or isinstance(distance_m, bool)
        or not isinstance(distance_m, (int, float))
        or isinstance(at, bool)
        or not isinstance(at, (int, float))
    ):
        return "ignore"
    if distance_m > TRANSFER_RADIUS_M:
        state["armed_at"] = None
        state["last_confirmed_at"] = None
        return "cancel"
    if state["armed_at"] is None or state["last_confirmed_at"] is None:
        state["armed_at"] = at
        state["last_confirmed_at"] = at
        return "waiting"
    if at - state["last_confirmed_at"] >= TRANSFER_WAIT_S:
        state["armed_at"] = at
        state["last_confirmed_at"] = at
        return "waiting"
    state["last_confirmed_at"] = at
    if at - state["armed_at"] >= TRANSFER_WAIT_S:
        return "activate"
    return "waiting"
