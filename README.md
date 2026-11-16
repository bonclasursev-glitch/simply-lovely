# simply-lovely — F1 Race Strategy Dashboard

An interactive Streamlit dashboard that turns raw Formula 1 timing data ([FastF1](https://github.com/theOehrly/Fast-F1)) and official FIA documents into race-strategy insights. It covers every season with FastF1 timing data, from 2018 onwards.

## Why

The information you need to understand a Grand Prix is spread out: lap timing and telemetry come from the FastF1 API, which is slow and rate-limited, and power-unit usage only appears in FIA PDF reports. This project brings it all into one fast dashboard and adds a strategy tool that answers the classic pit-wall question: *should we pit now or stay out?*

## Features

The sidebar has three views:

### Race Strategy
- Pick a track, your current and new tyre compound, and the track condition (Green, Safety Car, VSC).
- Pit-loss figures are taken from historical races, and a tyre degradation model is fitted per compound.
- Shows a **pit-vs-stay** comparison and a recommended decision.

### Season Overview
- Driver standings plotted against **power-unit element usage**, which is scraped from FIA documents (HTML + PDF parsing).

### Event Details
Pick a year, an event and (optionally) some drivers to get:
- Race position chart with track-status changes (SC/VSC/flags)
- Tyre strategy (stints and compounds)
- Lap-time distribution (violin chart)
- Gaps to the leader over the race
- Overtaking heatmap
- Qualifying strategy and a comparison of the fastest qualifying laps using telemetry

### Performance
- A **two-level cache**: an in-memory Streamlit cache (10 min TTL) and a shared on-disk cache (`dashboard_cache/`) that every user reads.
- `preload_cache.py` fills the disk cache ahead of time, so users never wait on FastF1 or the FIA site.
- Errors are logged in full while the user sees a short message, so one failing source doesn't crash the app.

## Architecture

```
main.py                         Entry point: loads config, wires the components, runs the dashboard
streamlit_dashboard/
  dashboard_orchestrator.py     Routes the sidebar selection to a page, manages caching and errors
  data_processor.py             Fetches and transforms FastF1 / FIA data into DataFrames
  visualizer.py                 Plotly figures (race, tyre, gaps, heatmaps, pit-vs-stay, ...)
  layout_manager.py             Streamlit widgets, sidebar and page layout
  cache_store.py                On-disk cache of DataFrame "bundles" keyed by season/event
  logger.py                     Shared logging setup (writes to logs/)
pit_stop_analysis/
  strategy_pick.py              Pit-loss extraction and tyre degradation model (pure pandas)
  pit_analysis_data.py          Builds the historical pit-stop parquet data
fia_pu_elements_tracker.py      Scrapes FIA power-unit element reports (requests, BeautifulSoup, pypdf)
laptime_simulation_model.py     WIP physics-based lap-time simulator (drag, downforce, tyre grip, braking)
preload_cache.py                CLI that fills the shared cache after each race weekend
config/
  config.toml                   Dashboard settings and cache paths/ages
  lts_config.toml               Physical and vehicle parameters for the lap-time simulator
  teams_drivers_info.yaml       Team and driver reference data
discovery_ipynbs/               Exploration notebooks (race and qualifying)
```

The data, visualisation and layout layers are kept separate, and the orchestrator is the only piece that connects them.

## Getting started

Needs Python 3.13+ and [uv](https://github.com/astral-sh/uv).

### 1. Install

```bash
uv sync                          # install dependencies
```

### 2. Add your F1TV credentials (required)

FastF1 loads timing data from Formula 1's live-timing service, which needs you to sign in with an **F1 account that has an active F1TV subscription**. Without it, no data will load.

Copy the example file and fill in your login:

```bash
cp .env.example .env
```

```dotenv
F1_USERNAME=you@example.com
F1_PASSWORD=your-password
```

`.env` is git-ignored, so your credentials stay on your machine. After the first sign-in, FastF1 stores a token and reuses it until it expires. If the variables aren't set and you're running in a terminal, FastF1 asks for your login instead.

### 3. Run

```bash
uv run --env-file .env streamlit run main.py
```

### First run and caching

Data caches are **not** in the repository: they're several GB and specific to each machine. `fastf1_cache/` and `dashboard_cache/` are created locally on the first run. The first time you open a season or event, the data is downloaded, which can take a while. After that it loads straight from disk.

To skip the wait, preload the cache ahead of time (recommended):

```bash
uv run --env-file .env python preload_cache.py                              # latest season: past events + standings + pit history
uv run --env-file .env python preload_cache.py --year 2023                  # a different season
uv run --env-file .env python preload_cache.py --event "Monaco Grand Prix"  # one event only
uv run --env-file .env python preload_cache.py --refresh                    # rebuild events that are already cached
uv run --env-file .env python preload_cache.py --skip-pit                   # skip pit history (FastF1 rate limit)
```

FastF1 allows about 500 API calls per hour, so the first full preload may take a few runs.

## Configuration

`.env` holds your F1 account credentials (see `.env.example`).

`config/config.toml` controls the dashboard title, layout, refresh rate, cache directories and `season_max_age_hours`. Season tables are rebuilt from the FIA site once they're older than that age (12 h by default).

## Tech stack

Python · Streamlit · FastF1 · pandas · NumPy · Plotly · Matplotlib/Seaborn · BeautifulSoup · pypdf · uv

## Roadmap

- Finish the lap-time simulation model and connect it to the dashboard
