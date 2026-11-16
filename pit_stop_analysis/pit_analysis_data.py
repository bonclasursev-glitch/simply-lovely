"""Download race laps with FastF1 and build the small parquet files the app reads.

Run once (takes a while the first time), then re-run after each race weekend;
races already downloaded are skipped.

    python build_data.py                 # 2019 -> current season
    python build_data.py --start 2023    # fewer seasons, faster
    python build_data.py --event "Bahrain Grand Prix"   # one event across the years
    python build_data.py --wait         # sleep through FastF1's 500 calls/h limit instead of stopping
"""
from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path

import fastf1
import pandas as pd
from fastf1.exceptions import RateLimitExceededError

try:  # imported from the repo root (streamlit dashboard)
    from pit_stop_analysis import strategy_pick as s
except ImportError:  # run as a script from this folder
    import strategy_pick as s

ROOT = Path(__file__).parent
DATA = ROOT / "data"
RACES = DATA / "races"
RATE_LIMIT_WAIT_S = 60 * 60 + 60  # FastF1 counts calls over a rolling hour


def is_rate_limited(exc: Exception) -> bool:
    """session.load() swallows the limiter error and fails later, so also match on the message."""
    return isinstance(exc, RateLimitExceededError) or "calls/h" in str(exc)


def is_not_loaded(exc: Exception) -> bool:
    """What session.laps raises after the limiter silently blocked every request of load()."""
    return "has not been loaded yet" in str(exc)


def download_season(year: int, event_name: str | None = None) -> None:
    """Download the year's races, or only the one called event_name (nothing if it wasn't held that year)."""
    schedule = fastf1.get_event_schedule(year, include_testing=False)
    if event_name is not None:
        schedule = schedule[schedule["EventName"] == event_name]
    cutoff = pd.Timestamp.now("UTC").tz_localize(None) - pd.Timedelta(hours=6)

    not_loaded = 0
    for _, ev in schedule.iterrows():
        race_time = ev.get("Session5DateUtc")  # session 5 is the Grand Prix on every format
        if pd.isna(race_time) or race_time > cutoff:
            continue
        path = RACES / f"{year}_{int(ev['RoundNumber']):02d}.parquet"
        if path.exists():
            continue
        try:
            session = fastf1.get_session(year, int(ev["RoundNumber"]), "R")
            session.load(laps=True, telemetry=False, weather=False, messages=False)
            laps = s.slim_laps(session.laps)
        except Exception as exc:  # missing data for a race shouldn't stop the build
            if is_rate_limited(exc):
                raise RateLimitExceededError(str(exc)) from exc
            print(f"  ! skipped {year} {ev['EventName']}: {exc}")
            # load() swallows the limiter error, so a run of "not loaded" skips means we're blocked:
            # stop instead of burning through every remaining race
            not_loaded += 1 if is_not_loaded(exc) else -not_loaded
            if not_loaded >= 2:
                raise RateLimitExceededError("probably 500 calls/h - sessions stopped loading") from exc
            continue
        not_loaded = 0
        laps["RaceId"] = f"{year}-{int(ev['RoundNumber']):02d}"
        laps["Year"] = year
        laps["EventName"] = ev["EventName"]
        laps["Location"] = ev["Location"]
        laps.to_parquet(path, index=False)
        print(f"  saved {year} {ev['EventName']} ({len(laps)} laps)")


def build_tables() -> None:
    files = sorted(RACES.glob("*.parquet"))
    if not files:
        raise SystemExit("No race files downloaded.")
    meta = ["RaceId", "Year", "EventName", "Location"]

    stops, clean = [], []
    for f in files:
        laps = pd.read_parquet(f)
        info = laps[meta].iloc[0]
        st = s.extract_pit_stops(laps)
        stops.append(st.assign(**info))
        clean.append(s.clean_laps(laps))

    stops = pd.concat(stops, ignore_index=True)
    clean = pd.concat(clean, ignore_index=True)[
        meta + ["Driver", "Stint", "Compound", "TyreLife", "LapNumber", "LapTimeS"]
    ]
    stops.to_parquet(DATA / "pit_stops.parquet", index=False)
    clean.to_parquet(DATA / "clean_laps.parquet", index=False)
    print(f"{len(files)} races -> {len(stops)} pit stops, {len(clean)} clean laps")


def load_tables() -> tuple[pd.DataFrame, pd.DataFrame] | None:
    """Pit stops and clean laps built by build_tables(), or None if not built yet."""
    stops_path, clean_path = DATA / "pit_stops.parquet", DATA / "clean_laps.parquet"
    if not (stops_path.exists() and clean_path.exists()):
        return None
    return pd.read_parquet(stops_path), pd.read_parquet(clean_path)


def build_event(event_name: str, start: int = 2019, end: int | None = None) -> bool:
    """Download the selected event for every year (the cache must already be enabled) and rebuild the tables.

    Returns False if the rate limit stopped the download; races saved so far are still used.
    """
    RACES.mkdir(parents=True, exist_ok=True)
    complete = True
    for year in range(start, (end or datetime.now().year) + 1):
        try:
            download_season(year, event_name)
        except RateLimitExceededError:
            complete = False
            break
    if any(RACES.glob("*.parquet")):
        build_tables()
    return complete


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", type=int, default=2019)
    ap.add_argument("--end", type=int, default=datetime.now().year)
    ap.add_argument("--event", help='only this event each year, e.g. "Bahrain Grand Prix" (default: every race)')
    ap.add_argument("--wait", action="store_true", help="sleep through the API rate limit instead of stopping")
    args = ap.parse_args()

    RACES.mkdir(parents=True, exist_ok=True)
    # same cache as the dashboard's DataProcessor, so races it already loaded cost no API calls
    cache_dir = ROOT.parent / "fastf1_cache"
    cache_dir.mkdir(exist_ok=True)
    fastf1.Cache.configure(cache_dir=str(cache_dir))
    fastf1.set_log_level("WARNING")

    year = args.start
    while year <= args.end:
        print(f"Season {year}")
        try:
            download_season(year, args.event)
        except RateLimitExceededError as exc:
            if not args.wait:
                print(f"  ! FastF1 rate limit hit ({exc}). Saved races are kept - re-run in an hour to continue.")
                break
            print(f"  ! FastF1 rate limit hit ({exc}), waiting {RATE_LIMIT_WAIT_S // 60} min...")
            time.sleep(RATE_LIMIT_WAIT_S)
            continue  # retry the same season; races already saved are skipped
        year += 1
    build_tables()


if __name__ == "__main__":
    main()