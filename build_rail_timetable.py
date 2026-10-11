"""Build cache/rail_timetable.json from the LTA train GTFS (GTFS Schedule (Train), DataMall guide 2.31).

Command, from the repository root:

    .venv\\Scripts\\python build_rail_timetable.py [GTFS] [--out PATH] [--today YYYY-MM-DD] [--allow-expired]

- GTFS is a folder or a .zip that holds agency, calendar, calendar_dates, feed_info, routes, stops, stop_times
  and trips (.txt). Default: tmp/gtfs_train. This command never calls DataMall and needs no key. Download the zip
  yourself (one GTFSScheduleTrain call) and unzip it into a folder of your choice.
- --out is the table (default cache/rail_timetable.json). It is written to a temporary file next to it, read back
  and validated, and only then moved into place. The old table is kept as <out>.bak. A table that fails validation
  never replaces the old one and the command exits with 1.
- --min-stations and --required-lines change the validation floor (for a small test feed only).
- --today sets the build date (default: today in Singapore). --allow-expired builds from a feed whose end date has
  passed (the command refuses by default).

What goes in the table (schema 1):
- lines: per line code (NS, EW, ...) the GTFS long name, mode (SUBWAY for MRT, TRAM for LRT, as OneMap names it),
  and the official fill and text colours of routes.txt.
- stations: per station code (the GTFS stop_code, one per line at an interchange) the name, coordinates, the
  interchange group (parent_station) and, per direction, the headsign it is keyed by (with `platforms`, the platform
  codes of platform_code in stops.txt that trains of that direction leave from; empty when any is blank or a list). A terminus that only ends
  trips of a headsign has no direction of that headsign (nobody boards there) but is still listed. A direction holds one entry
  per day type WD (Monday to Friday), SAT or SUN (Sunday and public holidays): first and last train as "HHMM"
  (hours past 24 are kept: "2414" is 00:14 the next day) and headway_s, the median gap between trains in seconds
  for each departure hour ("5" to "28"; gaps over an hour are breaks in service and are left out).
- patterns: per line and headsign, the station codes in travel order (used to name the direction of a ride).
- built, feed: the Singapore build date and the dates of the feed.

Rules for the numbers:
- Day types come from calendar.txt: Monday to Friday is WD, Saturday is SAT, Sunday is SUN (GTFS calls it PH).
  One-day services (start date equals end date) are ignored: they replace the usual timetable on three named days.
  If a line has more than one usable service for a day type, the one that starts last and covers the build date wins.
- A short working is a trip whose headsign has under 10 percent of the trips of its line and direction (for
  example NS "Toa Payoh", TE "Woodlands South"). Short workings count for nothing: not first, not last, not headway.
- A train cannot be boarded at the last stop of its trip, so that stop is not a departure.
- First train is the earliest departure (rounded down to the minute), last train the latest (rounded up).
"""

import argparse
import csv
import io
import json
import os
import shutil
import statistics
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SCHEMA = 1
SGT = timezone(timedelta(hours=8))
DEFAULT_GTFS = Path("tmp") / "gtfs_train"
DEFAULT_OUT = Path("cache") / "rail_timetable.json"
SHORT_WORKING_SHARE = 0.10
DAY_TYPES = ("WD", "SAT", "SUN")
MODE_BY_ROUTE_TYPE = {"0": "TRAM", "1": "SUBWAY"}
REQUIRED_LINES = ("NS", "EW", "NE", "CC", "DT", "TE", "BP", "SK", "PG")
MIN_STATIONS = 150
MAX_HEADWAY_S = 3600  # a longer gap is a break in service, not a headway
FILES = ("calendar", "feed_info", "routes", "stops", "stop_times", "trips")


class BuildError(Exception):
    """The feed or the table is not usable. The message lists the problems and never contains a key."""


# ---- reading the feed -------------------------------------------------------------------------------------


def _rows(source: Path, name: str):
    """Rows of <name>.txt from a folder or a zip, as dicts."""
    if source.is_dir():
        path = source / f"{name}.txt"
        if not path.is_file():
            raise BuildError(f"{name}.txt is missing from {source}")
        with open(path, newline="", encoding="utf-8-sig") as handle:
            yield from csv.DictReader(handle)
        return
    with zipfile.ZipFile(source) as archive:
        try:
            member = archive.open(f"{name}.txt")
        except KeyError as exc:
            raise BuildError(f"{name}.txt is missing from {source}") from exc
        with member, io.TextIOWrapper(member, encoding="utf-8-sig", newline="") as handle:
            yield from csv.DictReader(handle)


def _seconds(text: str) -> int:
    hours, minutes, seconds = text.strip().split(":")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds)


def _hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}{minutes % 60:02d}"


def _day_type_of(row: dict) -> str | None:
    flags = [row[key] == "1" for key in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")]
    if all(flags[:5]) and not flags[5] and not flags[6]:
        return "WD"
    if flags[5] and not any(flags[:5]) and not flags[6]:
        return "SAT"
    if flags[6] and not any(flags[:5]) and not flags[5]:
        return "SUN"
    return None


# ---- building ---------------------------------------------------------------------------------------------


def build_table(source: Path, today: date, allow_expired: bool = False) -> dict:
    feed = next(iter(_rows(source, "feed_info")), {})
    feed_end = feed.get("feed_end_date", "")
    if feed_end and not allow_expired and today.strftime("%Y%m%d") > feed_end:
        raise BuildError(f"the feed ended on {feed_end}; use --allow-expired to build anyway")
    services = _usable_services(source, today)
    routes = {row["route_id"]: row for row in _rows(source, "routes")}
    lines = _lines(routes.values())
    trips = _trips(source, routes, services, today)
    stations_info = _station_info(source)
    last_sequence = _last_sequences(source, trips)
    groups = defaultdict(int)  # (line, direction_id, headsign) -> trips
    totals = defaultdict(int)  # (line, direction_id) -> trips
    for trip in trips.values():
        groups[(trip["line"], trip["direction_id"], trip["headsign"])] += 1
        totals[(trip["line"], trip["direction_id"])] += 1
    main = {key for key, count in groups.items() if count >= SHORT_WORKING_SHARE * totals[key[:2]]}
    departures = defaultdict(lambda: defaultdict(list))  # (code, headsign) -> day type -> seconds
    meta: dict[tuple[str, str], dict] = {}
    orders: dict[tuple[str, str], list[tuple[int, str]]] = {}
    code_of = {stop_id: info["code"] for stop_id, info in stations_info["platforms"].items()}
    platform_of = {stop_id: info["platform"] for stop_id, info in stations_info["platforms"].items()}
    boarded_from: dict[tuple[str, str], set[str]] = defaultdict(set)  # (code, headsign) -> platform codes ("" unknown)
    trip_stops: dict[str, list[tuple[int, str, int, str]]] = defaultdict(list)
    for row in _rows(source, "stop_times"):
        trip = trips.get(row["trip_id"])
        if trip is None or (trip["line"], trip["direction_id"], trip["headsign"]) not in main:
            continue
        code = code_of.get(row["stop_id"])
        if code is None:
            continue
        sequence = int(row["stop_sequence"])
        trip_stops[row["trip_id"]].append((sequence, code, _seconds(row["departure_time"]), platform_of[row["stop_id"]]))
    for trip_id, stops in trip_stops.items():
        trip = trips[trip_id]
        stops.sort()
        key_line = (trip["line"], trip["headsign"])
        codes = [code for _seq, code, _t, _p in stops]
        if len(codes) > len(orders.get(key_line, [])):
            orders[key_line] = list(codes)
        final = last_sequence[trip_id]
        for sequence, code, seconds, platform in stops:
            if sequence == final:
                continue  # the train ends here: nobody boards it
            key = (code, trip["headsign"])
            boarded_from[key].add(platform)
            departures[key][trip["day_type"]].append(seconds)
            meta.setdefault(key, {"line": trip["line"], "direction_id": trip["direction_id"], "trips": 0})["trips"] += 1
    stations: dict[str, dict] = {}
    for (code, headsign), by_day in sorted(departures.items()):
        info = stations_info["stations"].get(code, {})
        station = stations.setdefault(code, {
            "name": info.get("name", ""), "latitude": info.get("latitude"), "longitude": info.get("longitude"),
            "interchange": info.get("interchange"), "directions": {},
        })
        entry = {**meta[(code, headsign)], "platforms": _platforms(boarded_from[(code, headsign)])}
        for day_type in DAY_TYPES:
            times = sorted(by_day.get(day_type, []))
            if times:
                entry[day_type] = _day_entry(times)
        station["directions"][headsign] = entry
    patterns: dict[str, dict] = {}
    for (line, headsign), codes in sorted(orders.items()):
        patterns.setdefault(line, {})[headsign] = _dedupe(codes)
    for codes in (code for by_headsign in patterns.values() for code in by_headsign.values()):
        for code in codes:  # a terminus has no departure of its own headsign but is still a place a ride can end
            info = stations_info["stations"].get(code, {})
            stations.setdefault(code, {
                "name": info.get("name", ""), "latitude": info.get("latitude"), "longitude": info.get("longitude"),
                "interchange": info.get("interchange"), "directions": {},
            })
    used_lines = {entry["line"] for station in stations.values() for entry in station["directions"].values()}
    table = {
        "schema": SCHEMA,
        "source": "LTA DataMall GTFS Schedule (Train)",
        "built": today.isoformat(),
        "feed": {
            "start_date": feed.get("feed_start_date", ""), "end_date": feed_end,
            "version": feed.get("feed_version", ""), "publisher": feed.get("feed_publisher_name", ""),
            "services": sorted(services["used"]),
        },
        "lines": {code: lines[code] for code in sorted(lines) if code in used_lines},
        "stations": stations,
        "patterns": patterns,
    }
    return table


def _platforms(seen: set[str]) -> list[str]:
    """The platform codes trains of one direction leave a station from. If any departure has no usable code (blank,
    or a list such as "A / D / E"), the answer is unknown and the list is empty: a platform is never guessed."""
    if not seen or any(not code or "/" in code for code in seen):
        return []
    return sorted(seen)


def _day_entry(times: list[int]) -> dict:
    first = times[0] // 60
    last = -(-times[-1] // 60)  # round up to the minute
    gaps: dict[int, list[int]] = defaultdict(list)
    for earlier, later in zip(times, times[1:]):
        if 0 < later - earlier <= MAX_HEADWAY_S:
            gaps[earlier // 3600].append(later - earlier)
    return {
        "first": _hhmm(first),
        "last": _hhmm(last),
        "headway_s": {str(hour): int(round(statistics.median(values))) for hour, values in sorted(gaps.items())},
    }


def _dedupe(codes: list[str]) -> list[str]:
    """Keep the order; a loop line may list a code twice, which is kept (it is the same station later)."""
    return list(codes)


def _usable_services(source: Path, today: date) -> dict:
    """service_id -> day type for the usual timetables (not the one-day services)."""
    stamp = today.strftime("%Y%m%d")
    mapping: dict[str, dict] = {}
    for row in _rows(source, "calendar"):
        if row["start_date"] == row["end_date"]:
            continue  # a one-day service
        day_type = _day_type_of(row)
        if day_type is None:
            continue
        mapping[row["service_id"]] = {
            "day_type": day_type, "start": row["start_date"], "end": row["end_date"],
            "covers": row["start_date"] <= stamp <= row["end_date"],
        }
    return {"by_id": mapping, "used": set()}


def _lines(route_rows) -> dict:
    lines = {}
    for row in route_rows:
        code = row["route_short_name"]
        if code in lines:
            continue
        lines[code] = {
            "name": row["route_long_name"],
            "mode": MODE_BY_ROUTE_TYPE.get(row["route_type"], "SUBWAY"),
            "color": row["route_color"].upper(),
            "text_color": row["route_text_color"].upper(),
        }
    return lines


def _trips(source: Path, routes: dict, services: dict, today: date) -> dict:
    """trip_id -> {line, direction_id, headsign, day_type}, one service per line and day type."""
    by_id = services["by_id"]
    raw = []
    for row in _rows(source, "trips"):
        info = by_id.get(row["service_id"])
        route = routes.get(row["route_id"])
        if info is None or route is None:
            continue
        raw.append((row, info, route["route_short_name"]))
    best: dict[tuple[str, str], str] = {}
    for row, info, line in raw:
        key = (line, info["day_type"])
        current = best.get(key)
        rank = (info["covers"], info["start"])
        if current is None or rank > (by_id[current]["covers"], by_id[current]["start"]):
            best[key] = row["service_id"]
    trips = {}
    for row, info, line in raw:
        if best[(line, info["day_type"])] != row["service_id"]:
            continue
        services["used"].add(row["service_id"])
        trips[row["trip_id"]] = {
            "line": line, "direction_id": int(row["direction_id"] or 0),
            "headsign": row["trip_headsign"].strip(), "day_type": info["day_type"],
        }
    return trips


def _last_sequences(source: Path, trips: dict) -> dict:
    last: dict[str, int] = {}
    for row in _rows(source, "stop_times"):
        trip_id = row["trip_id"]
        if trip_id in trips:
            sequence = int(row["stop_sequence"])
            if sequence > last.get(trip_id, -1):
                last[trip_id] = sequence
    return last


def _station_info(source: Path) -> dict:
    """Platforms (location_type 0) with their station code, and one name and point per code."""
    platforms: dict[str, dict] = {}
    stations: dict[str, dict] = {}
    for row in _rows(source, "stops"):
        code = row["stop_code"].strip()
        kind = row.get("location_type", "0") or "0"
        if not code or kind == "2":
            continue
        point = {"latitude": _float(row["stop_lat"]), "longitude": _float(row["stop_lon"])}
        if kind == "0":
            platforms[row["stop_id"]] = {"code": code, "platform": (row.get("platform_code") or "").strip()}
            parent = row.get("parent_station", "").strip()
            entry = stations.setdefault(code, {"name": row["stop_name"].strip(), **point, "interchange": None})
            if parent and parent != code and entry["interchange"] is None:
                entry["interchange"] = parent
        elif kind == "1":
            stations[code] = {**stations.get(code, {"interchange": None}), "name": row["stop_name"].strip(), **point}
    return {"platforms": platforms, "stations": stations}


def _float(text: str) -> float | None:
    try:
        return round(float(text), 6)
    except (TypeError, ValueError):
        return None


# ---- validating and writing -------------------------------------------------------------------------------


def validate_table(table: dict, today: date, required_lines=REQUIRED_LINES, min_stations: int = MIN_STATIONS,
                   allow_expired: bool = False) -> list[str]:
    """The problems that make a table unusable; an empty list means it can replace the old one."""
    problems: list[str] = []
    if not isinstance(table, dict) or table.get("schema") != SCHEMA:
        return ["the table is not schema 1"]
    for key in ("built", "feed", "lines", "stations", "patterns"):
        if key not in table:
            problems.append(f"missing key {key}")
    if problems:
        return problems
    try:
        date.fromisoformat(table["built"])
    except (TypeError, ValueError):
        problems.append("built is not a date")
    end = table["feed"].get("end_date", "")
    if end and not allow_expired and today.strftime("%Y%m%d") > end:
        problems.append(f"the feed ended on {end}")
    for code in required_lines:
        if code not in table["lines"]:
            problems.append(f"line {code} is missing")
    for code, line in table["lines"].items():
        if not (len(line.get("color", "")) == 6 and len(line.get("text_color", "")) == 6):
            problems.append(f"line {code} has no official colours")
    if len(table["stations"]) < min_stations:
        problems.append(f"only {len(table['stations'])} stations (need {min_stations})")
    in_a_pattern = {code for by_headsign in table["patterns"].values() for codes in by_headsign.values() for code in codes}
    for code, station in table["stations"].items():
        if not station.get("directions") and code not in in_a_pattern:
            problems.append(f"station {code} has no direction")
        for headsign, entry in station.get("directions", {}).items():
            if entry.get("line") not in table["lines"]:
                problems.append(f"{code} {headsign}: unknown line")
            listed = entry.get("platforms", [])
            if not isinstance(listed, list) or not all(isinstance(item, str) and item for item in listed):
                problems.append(f"{code} {headsign}: platforms {listed!r}")
            days = [day for day in DAY_TYPES if day in entry]
            if not days:
                problems.append(f"{code} {headsign}: no day type")
            for day in days:
                problems.extend(_validate_day(f"{code} {headsign} {day}", entry[day]))
    for line, by_headsign in table["patterns"].items():
        for headsign, codes in by_headsign.items():
            missing = [code for code in codes if code not in table["stations"]]
            if missing:
                problems.append(f"pattern {line} {headsign}: unknown stations {missing[:3]}")
    return problems


def _validate_day(label: str, entry: dict) -> list[str]:
    problems = []
    first, last = entry.get("first", ""), entry.get("last", "")
    for name, value in (("first", first), ("last", last)):
        if not (isinstance(value, str) and len(value) == 4 and value.isdigit()
                and int(value[:2]) <= 29 and int(value[2:]) <= 59):
            problems.append(f"{label}: {name} {value!r} is not HHMM")
    if not problems and last < first:
        problems.append(f"{label}: last {last} is before first {first}")
    for hour, seconds in entry.get("headway_s", {}).items():
        if not (hour.isdigit() and isinstance(seconds, int) and 0 < seconds <= MAX_HEADWAY_S):
            problems.append(f"{label}: headway {hour}={seconds!r}")
    return problems


def write_table(table: dict, out: Path, today: date, allow_expired: bool = False, **limits) -> None:
    """Temp file, read back, validate, back up the old table, replace. A bad table never replaces the old one."""
    out.parent.mkdir(parents=True, exist_ok=True)
    temporary = out.with_name(out.name + ".tmp")
    try:
        temporary.write_text(json.dumps(table, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        reread = json.loads(temporary.read_text(encoding="utf-8"))
        problems = validate_table(reread, today, allow_expired=allow_expired, **limits)
        if problems:
            raise BuildError("the new table is not usable: " + "; ".join(problems[:8]))
        if out.exists():
            shutil.copyfile(out, out.with_name(out.name + ".bak"))
        os.replace(temporary, out)
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build cache/rail_timetable.json from the LTA train GTFS.")
    parser.add_argument("gtfs", nargs="?", default=str(DEFAULT_GTFS), help="folder or zip of the GTFS")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--today", help="build date YYYY-MM-DD (default: today in Singapore)")
    parser.add_argument("--allow-expired", action="store_true")
    parser.add_argument("--min-stations", type=int, default=MIN_STATIONS, help="validation floor (tests use less)")
    parser.add_argument("--required-lines", default=",".join(REQUIRED_LINES), help="comma list of line codes")
    args = parser.parse_args(argv)
    today = date.fromisoformat(args.today) if args.today else datetime.now(SGT).date()
    source, out = Path(args.gtfs), Path(args.out)
    if not source.exists():
        print(f"GTFS not found at {source}. Download it first (this command makes no network call).")
        return 1
    try:
        table = build_table(source, today, allow_expired=args.allow_expired)
        write_table(table, out, today, allow_expired=args.allow_expired, min_stations=args.min_stations,
                    required_lines=tuple(code for code in args.required_lines.split(",") if code))
    except BuildError as exc:
        print(f"Not written: {exc}")
        return 1
    stations = table["stations"]
    rows = sum(len(station["directions"]) for station in stations.values())
    print(f"Wrote {out}: {len(stations)} stations, {rows} directions, {out.stat().st_size // 1024} KB, "
          f"built {table['built']}, feed {table['feed']['start_date']} to {table['feed']['end_date']}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
