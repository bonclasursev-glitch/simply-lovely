"""Fill the shared dashboard cache so users never wait on FastF1 or the FIA site.

Run after each race weekend (or on a schedule); events already cached are skipped.

    uv run python preload_cache.py                              # latest season: every past event + standings + pit history
    uv run python preload_cache.py --year 2023                  # another season
    uv run python preload_cache.py --event "Monaco Grand Prix"  # one event only
    uv run python preload_cache.py --refresh                    # rebuild events that are already cached
    uv run python preload_cache.py --skip-pit                   # pit history downloads hit FastF1's rate limit
"""
# Import local modules
from streamlit_dashboard.logger import get_logger
from streamlit_dashboard.data_processor import DataProcessor
from pit_stop_analysis import pit_analysis_data
# Import Python libraries
import argparse
import time
import tomllib
from pathlib import Path

import fastf1


def run():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, help="season to preload (default: the latest season with data)")
    ap.add_argument("--event", help='only this event, e.g. "Monaco Grand Prix" (default: every past event)')
    ap.add_argument("--refresh", action="store_true", help="rebuild events that are already cached")
    ap.add_argument("--skip-pit", action="store_true", help="do not download pit stop history")
    args = ap.parse_args()

    logger = get_logger(__name__)
    config_path = Path(__file__).resolve().parent / 'config' / 'config.toml'
    with config_path.open('rb') as config_file:
        config = tomllib.load(config_file)
    fastf1.set_log_level("WARNING")
    data_processor = DataProcessor(config, logger)

    year = args.year or data_processor.get_available_seasons()[0]
    events = data_processor.get_season_events(year)['EventName'].tolist()
    if args.event:
        events = [event for event in events if event == args.event]
        if not events:
            raise SystemExit(f"{args.event} is not a past event of {year}")

    for event in events:
        if not args.refresh and data_processor.cache_store.has_bundle(year, event):
            logger.info(f"Cached already: {event}")
            continue
        start = time.perf_counter()
        try:
            event_data = data_processor.get_event_data(year, event, refresh=True)
        except Exception:
            logger.exception(f"Could not cache {event}")
            continue
        status = "no timing data yet" if event_data is None else f"cached in {time.perf_counter() - start:.0f}s"
        logger.info(f"{event}: {status}")

    if not args.event:
        logger.info(f"Refreshing {year} standings")
        data_processor.get_standings_vs_pu_elements_data(year, refresh=True)

    if not args.skip_pit:
        for event in events:
            logger.info(f"Pit stop history: {event}")
            # Races already saved are skipped, so only new ones cost FastF1 calls
            if not pit_analysis_data.build_event(event):
                logger.warning("FastF1 rate limit hit - re-run in an hour to download the remaining pit stop history")
                break

    logger.info("Cache ready")


if __name__ == '__main__':
    run()
