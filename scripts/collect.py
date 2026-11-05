"""
Collects the public data that changes often, once a day, into docs/ for GitHub Pages. The Cosmic Vista 3D app reads only these static files
and never calls these services itself. Standard library only.

    python scripts/collect.py

A source that fails keeps its last good data and is noted in docs/status.json. CelesTrak always goes through celestrak_guard.
"""
import json
import os
import sys
import urllib.request
from datetime import timezone

from celestrak_guard import Guard, Refused, USER_AGENT, now_utc

SCHEMA = 1
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = os.path.join(ROOT, "docs")
GUARD_STATE = os.path.join(ROOT, "state", "celestrak-guard.json")

AURORA_URL = "https://services.swpc.noaa.gov/json/ovation_aurora_latest.json"
USNO = "https://aa.usno.navy.mil/api/"

# The forecast grid is one point per degree, about 65,000 points. Every fifth degree, above a low chance, is plenty for a daily summary.
AURORA_STEP_DEGREES = 5
AURORA_MIN_PERCENT = 10


def stamp(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_json(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def read_existing(name):
    try:
        with open(os.path.join(DOCS, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(name, data):
    os.makedirs(DOCS, exist_ok=True)
    temporary = os.path.join(DOCS, name + ".tmp")
    with open(temporary, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")
    os.replace(temporary, os.path.join(DOCS, name))


def iss_document(body, fetched_utc):
    """CelesTrak's three lines as JSON, with when they were fetched."""
    lines = [line.strip() for line in body.strip().splitlines()]
    first = next(line for line in lines if line.startswith("1 "))
    second = next(line for line in lines if line.startswith("2 "))
    name = next((line for line in lines if not line.startswith(("1 ", "2 "))), "ISS")
    return {"schema": SCHEMA, "source": "CelesTrak GP data", "fetched_utc": fetched_utc, "name": name, "line1": first, "line2": second}


def summarize_aurora(raw):
    """Keeps the forecast's times, each hemisphere's highest chance and a coarse grid of [longitude, latitude, percent]."""
    north = south = 0
    cells = []
    for longitude, latitude, percent in raw.get("coordinates", []):
        if latitude >= 0:
            north = max(north, percent)
        else:
            south = max(south, percent)
        if percent >= AURORA_MIN_PERCENT and longitude % AURORA_STEP_DEGREES == 0 and latitude % AURORA_STEP_DEGREES == 0:
            cells.append([longitude, latitude, percent])
    return {
        "observation_time": raw.get("Observation Time"),
        "forecast_time": raw.get("Forecast Time"),
        "north_max_percent": north,
        "south_max_percent": south,
        "cells": cells,
    }


def collect_usno(years, get=get_json):
    result = {"moon_phases": [], "solar_eclipses": [], "seasons": []}
    for year in years:
        result["moon_phases"] += get(USNO + "moon/phases/year?year=%d" % year).get("phasedata", [])
        result["solar_eclipses"] += get(USNO + "eclipses/solar/year?year=%d" % year).get("eclipses_in_year", [])
        result["seasons"] += get(USNO + "seasons?year=%d" % year).get("data", [])
    return result


def collect(guard, get=get_json, clock=now_utc):
    """Runs every source. One source failing never stops the others. Returns the status written to docs/status.json."""
    now = clock()
    status = {"schema": SCHEMA, "generated_utc": stamp(now), "sources": {}}

    try:
        body, fetched, cached = guard.fetch()
        write_json("iss_tle.json", iss_document(body, fetched))
        status["sources"]["celestrak"] = {"result": "cached" if cached else "ok", "fetched_utc": fetched}
    except Refused as refusal:
        status["sources"]["celestrak"] = {"result": "skipped", "why": str(refusal)}

    sky = read_existing("sky_events.json") or {}

    try:
        sky["aurora"] = summarize_aurora(get(AURORA_URL, 120))
        status["sources"]["noaa_aurora"] = {"result": "ok"}
    except (OSError, ValueError, KeyError, TypeError) as error:
        status["sources"]["noaa_aurora"] = {"result": "failed", "why": type(error).__name__}

    try:
        sky.update(collect_usno([now.year, now.year + 1], get))
        status["sources"]["usno"] = {"result": "ok"}
    except (OSError, ValueError, KeyError, TypeError) as error:
        status["sources"]["usno"] = {"result": "failed", "why": type(error).__name__}

    sky["schema"] = SCHEMA
    sky["generated_utc"] = stamp(now)
    write_json("sky_events.json", sky)

    # NASA DONKI needs an API key, and this public repository holds no keys. It stays skipped until a decision changes that.
    status["sources"]["nasa_donki"] = {"result": "skipped", "why": "Needs an API key. Not collected."}

    write_json("status.json", status)
    return status


def main():
    print(json.dumps(collect(Guard(GUARD_STATE)), indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
