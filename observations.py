"""SQLite observations for a scored poll, including the reroute audit fields.

This is the observations table named in the plan. It does not call LTA,
OneMap, or OpenAI.

The user's position is not stored. The columns user_lat, user_lon and gps_accuracy stay in the table
(so there is no migration) but are always written as NULL, whatever the caller passes. The log keeps
the poll time, the stop, the bus position, the ETA, the probabilities, the data quality and the walk
distance.
"""

import sqlite3
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent / "observations.db"

_CREATE = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    stop_code TEXT,
    service TEXT,
    direction INTEGER,
    eta TEXT,
    monitored INTEGER,
    bus_lat REAL,
    bus_lon REAL,
    user_lat REAL,
    user_lon REAL,
    gps_accuracy REAL,
    walk_metres REAL,
    slack_seconds INTEGER,
    p INTEGER,
    p_low INTEGER,
    p_high INTEGER,
    data_quality TEXT,
    reroute_fired INTEGER NOT NULL,
    reroute_reason TEXT
)
"""

_INSERT = """
INSERT INTO observations (
    timestamp, stop_code, service, direction, eta, monitored,
    bus_lat, bus_lon, user_lat, user_lon, gps_accuracy, walk_metres,
    slack_seconds, p, p_low, p_high, data_quality,
    reroute_fired, reroute_reason
) VALUES (
    :timestamp, :stop_code, :service, :direction, :eta, :monitored,
    :bus_lat, :bus_lon, :user_lat, :user_lon, :gps_accuracy, :walk_metres,
    :slack_seconds, :p, :p_low, :p_high, :data_quality,
    :reroute_fired, :reroute_reason
)
"""


def record_observation(row: dict, db_path: Path | None = None) -> None:
    """Insert one scored-poll row. Missing keys are stored as NULL. The user's position and the GPS
    accuracy are never stored: those three columns are NULL on every row."""
    path = DEFAULT_DB_PATH if db_path is None else db_path
    stored = {
        "timestamp": row.get("timestamp"),
        "stop_code": row.get("stop_code"),
        "service": row.get("service"),
        "direction": row.get("direction"),
        "eta": row.get("eta"),
        "monitored": row.get("monitored"),
        "bus_lat": row.get("bus_lat"),
        "bus_lon": row.get("bus_lon"),
        "user_lat": None,
        "user_lon": None,
        "gps_accuracy": None,
        "walk_metres": row.get("walk_metres"),
        "slack_seconds": row.get("slack_seconds"),
        "p": row.get("p"),
        "p_low": row.get("p_low"),
        "p_high": row.get("p_high"),
        "data_quality": row.get("data_quality"),
        "reroute_fired": 1 if row.get("reroute_fired") else 0,
        "reroute_reason": row.get("reroute_reason") or "",
    }
    with sqlite3.connect(path) as connection:
        connection.execute(_CREATE)
        connection.execute(_INSERT, stored)
