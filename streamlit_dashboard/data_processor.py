
# Import local modules
from streamlit_dashboard.logger import get_logger
from streamlit_dashboard.cache_store import CacheStore, REPO_ROOT, resolve_path
from pit_stop_analysis import pit_analysis_data
from pit_stop_analysis import strategy_pick
from fia_pu_elements_tracker import get_pu_season_table
# Import Python libraries
import fastf1
import pandas as pd
import numpy as np
import yaml
from scipy.spatial import cKDTree
import re
import pickle
from difflib import SequenceMatcher

# FastF1 has full timing data from this season onwards
FIRST_SEASON = 2018
# fia_pu_elements_tracker only scrapes this season's FIA documents
PU_ELEMENTS_YEAR = 2026
PU_COLUMNS = ['ICE', 'TC', 'MGU-H', 'MGU-K', 'ES', 'CE']
# Hours after the race start before FastF1 has usually published its data
DATA_DELAY_HOURS = 4
NEUTRAL_COLOUR = '150,150,150,1'
# Earlier names of the teams in teams_drivers_info.yaml, so older seasons get their team's colour
TEAM_ALIASES = {
    'Toro Rosso': 'Racing Bulls', 'Scuderia Toro Rosso': 'Racing Bulls', 'AlphaTauri': 'Racing Bulls',
    'RB': 'Racing Bulls', 'Visa Cash App RB': 'Racing Bulls',
    'Force India': 'Aston Martin', 'Racing Point': 'Aston Martin',
    'Renault': 'Alpine',
    'Sauber': 'Audi', 'Alfa Romeo Racing': 'Audi', 'Alfa Romeo': 'Audi', 'Kick Sauber': 'Audi',
}


def event_points_csv(year):
    return REPO_ROOT / 'downloads' / f'event_points_{year}.csv'


class DataProcessor:
    def __init__(self, config, logger):
        self.logger = logger
        self.config = config
        with open(REPO_ROOT / 'config' / 'teams_drivers_info.yaml', "r") as file:
            self.config_teams_info = yaml.safe_load(file)
        self.fastf1_cache_dir = resolve_path(config['CACHE']['fastf1_cache_dir'])
        fastf1.Cache.configure(cache_dir=str(self.fastf1_cache_dir))
        self.cache_store = CacheStore(config['CACHE']['dashboard_cache_dir'])
        self.season_max_age_hours = float(config['CACHE']['season_max_age_hours'])

    def get_available_seasons(self):
        # Seasons with at least one finished race, most recent first
        seasons = []
        for year in range(pd.Timestamp.now().year, FIRST_SEASON - 1, -1):
            try:
                if not self.get_season_events(year).empty:
                    seasons.append(year)
            except Exception:
                self.logger.exception(f"Could not load the {year} schedule")
        return seasons

    def get_season_events(self, year):
        # add .env file with F1_USERNAME and F1_PASSWORD to avoid rate limit
        # Events whose race has finished long enough ago for FastF1 to have its data, in calendar order
        season = fastf1.get_event_schedule(year, include_testing=False)
        cutoff = pd.Timestamp.now('UTC').tz_localize(None) - pd.Timedelta(hours=DATA_DELAY_HOURS)
        # Session 5 is the Grand Prix on every format
        return season[season['Session5DateUtc'] < cutoff].reset_index(drop=True)

    def get_team_colour(self, team):
        team = TEAM_ALIASES.get(team, team)
        team_info = self.config_teams_info['teams'].get(team)
        return team_info['teaminfo']['colour'] if team_info else None

    @staticmethod
    def shade_colour(colour, shade):
        # Mixes an "r,g,b,a" colour with white (shade > 0) or black (shade < 0)
        r, g, b, a = (float(value) for value in colour.split(','))
        target = 255 if shade > 0 else 0
        r, g, b = (round(value + (target - value) * abs(shade)) for value in (r, g, b))
        return f"{r},{g},{b},{a:g}"

    def assign_driver_colours(self, drivers):
        # The first driver of a team gets the team colour and team mates get lighter and darker versions of it,
        # starting with the direction that stays readable (dark team colours are lightened first)
        drivers = drivers.copy()
        drivers['Colour'] = NEUTRAL_COLOUR
        for team, team_drivers in drivers.groupby('Team', sort=False):
            team_colour = self.get_team_colour(team)
            if team_colour is None:
                continue
            r, g, b = (float(value) for value in team_colour.split(',')[:3])
            direction = -1 if (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.6 else 1
            shades = [0, 0.45 * direction, -0.35 * direction, 0.7 * direction, -0.6 * direction]
            order = team_drivers.sort_values('RacingNumber', key=lambda numbers: pd.to_numeric(numbers, errors='coerce')).index
            for position, index in enumerate(order):
                drivers.loc[index, 'Colour'] = self.shade_colour(team_colour, shades[position % len(shades)])
        return drivers

    def read_driver_info(self, year, event, identifier):
        # driver_info.ff1pkl of one session in the FastF1 cache, fetched with a light load if it is not cached yet
        try:
            session = fastf1.get_session(year, event, identifier)
        except Exception:
            self.logger.exception(f"No {identifier} session for {year} {event}")
            return None
        # FastF1 saves each API response under the session's api path without its leading '/static/'
        path = self.fastf1_cache_dir / session.api_path.removeprefix('/static/') / 'driver_info.ff1pkl'
        if not path.exists():
            try:
                session.load(laps=False, telemetry=False, weather=False, messages=False)
            except Exception:
                self.logger.exception(f"Could not load driver info for {year} {event} {identifier}")
        if not path.exists():
            return None
        try:
            with open(path, 'rb') as file:
                return pickle.load(file).get('data') or None
        except Exception:
            self.logger.exception(f"Unreadable driver info file {path}")
            return None

    def get_event_drivers(self, year, event):
        # Drivers and teams of a GP from its race driver_info.ff1pkl (qualifying's if the race one is missing),
        # with a colour per driver. Returns the drivers and the warnings to show the user
        warnings = []
        columns = ['Driver', 'FullName', 'Team', 'RacingNumber', 'Colour']
        entries = self.read_driver_info(year, event, 'R')
        if entries is None:
            entries = self.read_driver_info(year, event, 'Q')
            if entries is None:
                warnings.append(f"Driver list unavailable for {year} {event}: drivers are shown as found in the timing data, in grey.")
                return pd.DataFrame(columns=columns), warnings
            warnings.append(f"Race driver list unavailable for {year} {event}, using the qualifying one.")

        drivers = pd.DataFrame([
            {'Driver': entry.get('Tla'), 'FullName': entry.get('FullName'), 'Team': entry.get('TeamName') or None,
             'RacingNumber': entry.get('RacingNumber') or number}
            for number, entry in entries.items()
        ])
        if drivers['Driver'].isna().any():
            warnings.append(f"{int(drivers['Driver'].isna().sum())} entries without a driver code were left out for {year} {event}.")
            drivers = drivers.dropna(subset=['Driver'])
        for driver in drivers.loc[drivers['Team'].isna(), 'Driver']:
            warnings.append(f"Unknown team for {driver} at {year} {event}, drawn in grey.")
        for team in drivers['Team'].dropna().unique():
            if self.get_team_colour(team) is None:
                warnings.append(f"No colour for team {team}, its drivers are drawn in grey.")
        return self.assign_driver_colours(drivers)[columns].reset_index(drop=True), warnings

    def get_season_drivers(self, year):
        # Every driver who raced in the season with their latest team, from each finished GP's driver info
        tables, warnings = [], []
        for _, event in self.get_season_events(year).iterrows():
            drivers, event_warnings = self.get_event_drivers(year, event['EventName'])
            warnings += event_warnings
            tables.append(drivers.assign(RoundNumber=event['RoundNumber']))
        if not tables or all(table.empty for table in tables):
            return pd.DataFrame(columns=['Driver', 'FullName', 'Team', 'RacingNumber', 'Colour']), warnings
        drivers = pd.concat(tables, ignore_index=True).sort_values('RoundNumber').drop_duplicates('Driver', keep='last')
        # Colours are worked out again so drivers who shared a team over the season stay distinguishable
        drivers = self.assign_driver_colours(drivers.drop(columns=['RoundNumber', 'Colour']))
        return drivers.reset_index(drop=True), list(dict.fromkeys(warnings))

    def get_event_data(self, year, selected_event, refresh=False):
        # Plot ready data for the event from the shared cache, built from FastF1 and saved there on the first request
        frames = None if refresh else self.cache_store.load_bundle(year, selected_event)
        if frames is None:
            frames = self.build_event_bundle(year, selected_event)
            if frames is None:
                return None
            self.cache_store.save_bundle(frames, year, selected_event)
        return self.unpack_event_bundle(frames)

    def build_event_bundle(self, year, selected_event):
        # Everything that needs FastF1 sessions or telemetry is done here once, so the cached bundle is plain DataFrames
        event_sessions = self.load_event_sessions(year, selected_event)
        if event_sessions is None:
            return None
        race_event_laps, quali_event_laps, plot_laps, status_changes = event_sessions
        try:
            bin_counts, segments = self.get_overtakes_data(race_event_laps)
        except Exception:
            # Usually missing position data, the overtake map is then left out
            self.logger.exception(f"Could not work out the overtakes of {year} {selected_event}")
            bin_counts, segments = pd.Series(dtype='int64'), []
        segments = pd.DataFrame(
            [{'bin': seg['bin'], 'count': seg['count'], 'x': x, 'y': y} for seg in segments for x, y in zip(seg['x'], seg['y'])],
            columns=['bin', 'count', 'x', 'y'],
        )
        return {
            'race_laps': pd.DataFrame(race_event_laps),
            'quali_telemetry': self.get_quali_fastest_telemetry(quali_event_laps) if quali_event_laps is not None else pd.DataFrame(columns=['Driver', 'Team', 'LapTimeS', 'Distance', 'Speed']),
            'plot_laps': pd.DataFrame(plot_laps),
            'status_changes': status_changes,
            'raceplot_long': self.get_race_gaps_data(race_event_laps),
            'overtake_bins': bin_counts.rename_axis('Bin').reset_index(name='Count'),
            'track_segments': segments,
        }

    @staticmethod
    def unpack_event_bundle(frames):
        # Laps methods such as pick_quicklaps only need the lap columns, not the FastF1 session
        race_event_laps = fastf1.core.Laps(frames['race_laps'])
        bin_counts = frames['overtake_bins'].set_index('Bin')['Count'] if not frames['overtake_bins'].empty else pd.Series(dtype='int64')
        segments = [
            {'bin': bin_number, 'x': seg['x'].to_numpy(), 'y': seg['y'].to_numpy(), 'count': seg['count'].iat[0]}
            for bin_number, seg in frames['track_segments'].groupby('bin', sort=True)
        ]
        return (race_event_laps, frames['quali_telemetry'], frames['plot_laps'], frames['status_changes'],
                frames['raceplot_long'], bin_counts, segments)

    def get_quali_fastest_telemetry(self, quali_event_laps):
        # Speed trace of each driver's fastest qualifying lap, the only telemetry the velocity plot needs
        quali_laps_all = quali_event_laps.dropna(subset=["LapTime"])
        fastest_by_driver = quali_laps_all.sort_values("LapTime").drop_duplicates(subset="Driver", keep="first")
        traces = []
        for _, lap in fastest_by_driver.iterlaps():
            try:
                telemetry = lap.get_telemetry()
            except Exception:
                self.logger.exception(f"No telemetry for {lap['Driver']}'s fastest qualifying lap")
                continue
            traces.append(pd.DataFrame({
                'Driver': lap['Driver'],
                'Team': lap['Team'],
                'LapTimeS': lap['LapTime'].total_seconds(),
                'Distance': telemetry['Distance'].to_numpy(),
                'Speed': telemetry['Speed'].to_numpy(),
            }))
        if not traces:
            return pd.DataFrame(columns=['Driver', 'Team', 'LapTimeS', 'Distance', 'Speed'])
        return pd.concat(traces, ignore_index=True)

    def load_event_sessions(self, year, selected_event):
        # FastF1 only logs a warning when timing data is unavailable (future or not yet published sessions),
        # and the laps then raise when read. Without race laps there is nothing to show
        try:
            race_event = fastf1.get_session(year, selected_event, 'R')
            race_event.load()
            race_event_laps = race_event.laps
        except Exception:
            self.logger.exception(f"No race timing data available for {year} {selected_event}")
            return None
        if race_event_laps.empty:
            self.logger.warning(f"No race laps for {year} {selected_event}")
            return None

        # The qualifying plots are left out (empty frames) when its data is missing
        try:
            quali_event_laps, plot_laps, status_changes = self.load_quali_session(year, selected_event)
        except Exception:
            self.logger.exception(f"No qualifying data available for {year} {selected_event}")
            quali_event_laps, plot_laps, status_changes = None, pd.DataFrame(), pd.DataFrame()
        return race_event_laps, quali_event_laps, plot_laps, status_changes

    def load_quali_session(self, year, selected_event):
        quali_event = fastf1.get_session(year, selected_event, 'Q')
        quali_event.load()
        quali_event_laps = quali_event.laps.pick_quicklaps()

        quali_session_status = quali_event.session_status

        quali_session_status = quali_event_laps.merge(
            quali_session_status,
            on=['Time'],
            how='outer'
        )
        quali_session_status['Status'] = quali_session_status['Status'].ffill()


        quali_session_status = quali_session_status.copy()

        # LapTime is required to draw a rectangle
        quali_session_status['LapTime'] = pd.to_timedelta(
            quali_session_status['LapTime'],
            errors='coerce'
        )

        # LapStartTime is also required
        quali_session_status['LapStartTime'] = pd.to_timedelta(
            quali_session_status['LapStartTime'],
            errors='coerce'
        )

        # Keep only rows that actually represent a timed lap
        plot_laps = quali_session_status.dropna(
            subset=['LapTime', 'LapStartTime']
        ).copy()

        plot_laps['LapEndTime'] = (
            plot_laps['LapStartTime'] +
            plot_laps['LapTime']
        )

        status_changes = (
            quali_session_status[['Time', 'Status']]
            .drop_duplicates()
            .sort_values('Time')
        )

        status_changes = status_changes[
            status_changes['Status'] != status_changes['Status'].shift()
        ]

        gaps = []

        finish_time = None

        for _, row in status_changes.iterrows():

            if row['Status'] == 'Finished':
                finish_time = pd.Timedelta(row['Time'])

            elif row['Status'] == 'Started' and finish_time is not None:

                # Laps that started before the official session finished
                session_laps = plot_laps[
                    plot_laps['LapStartTime'] <= finish_time
                ]

                # The latest time any of those laps actually finished
                actual_finish_time = session_laps['LapEndTime'].max()

                gaps.append(
                    (actual_finish_time, pd.Timedelta(row['Time']))
                )

                finish_time = None

        def compress_time(time):

            time = pd.Timedelta(time)

            offset = pd.Timedelta(0)

            for gap_start, gap_end in gaps:

                if time <= gap_start:
                    break

                offset += min(time, gap_end) - gap_start

            return time - offset

        plot_laps['CompressedLapStartTime'] = (
            plot_laps['LapStartTime']
            .apply(compress_time)
        )
        status_changes['CompressedTime'] = (
            status_changes['Time']
            .apply(compress_time)
        )

        # Convert to numeric seconds for Plotly
        plot_laps['CompressedLapStartSeconds'] = (
            plot_laps['CompressedLapStartTime']
            .dt.total_seconds()
        )
        return quali_event_laps, plot_laps, status_changes
    
    def get_race_gaps_data(self, race_event_laps):
        sector_cols = [
            "Sector1SessionTime",
            "Sector2SessionTime",
            "Sector3SessionTime",
        ]

        # Find the fastest sector time on each lap
        leader_sector_times = race_event_laps.groupby("LapNumber")[sector_cols].transform("min")

        # Calculate gap to fastest sector time
        gaps = race_event_laps[sector_cols].sub(leader_sector_times)

        gaps = gaps.apply(lambda column: column.dt.total_seconds())
        gaps.columns = ["GapS1", "GapS2", "GapS3"]

        # Create long dataframe
        raceplot_long = pd.concat(
            [
                race_event_laps[["Driver", "LapNumber"]],
                gaps,
            ],
            axis=1,
        ).melt(
            id_vars=["Driver", "LapNumber"],
            value_vars=["GapS1", "GapS2", "GapS3"],
            var_name="Sector",
            value_name="GapToLeader",
        )

        # Give each sector its chronological position
        sector_order = {
            "GapS1": 1,
            "GapS2": 2,
            "GapS3": 3,
        }

        raceplot_long["SectorOrder"] = raceplot_long["Sector"].map(sector_order)

        # Position along the continuous race timeline
        raceplot_long["RacePosition"] = (
            (raceplot_long["LapNumber"] - 1) * 3
            + raceplot_long["SectorOrder"]
        )

        # Sort so Plotly connects the points in the correct order
        raceplot_long = raceplot_long.sort_values(
            ["Driver", "RacePosition"]
        )

        return raceplot_long

    def add_track_distance(self, telemetry, tree, ref_distance):

        xy = np.column_stack([
            telemetry["X"].to_numpy(),
            telemetry["Y"].to_numpy()
        ])

        _, idx = tree.query(xy)

        telemetry = telemetry.copy()

        telemetry["TrackDistance"] = ref_distance[idx]

        return telemetry

    def get_overtakes_data(self, race_event_laps):
        ref_lap = race_event_laps.pick_fastest()
        race_event_laps = race_event_laps.sort_values(by=['Driver', 'LapNumber'])

        race_event_laps['Previous_Position'] = race_event_laps.groupby('Driver')['Position'].shift(1)
        race_event_laps['Position_Change'] = race_event_laps['Previous_Position'] - race_event_laps['Position']

        gained_places = race_event_laps[race_event_laps['Position_Change'] > 0]
        lost_places   = race_event_laps[race_event_laps['Position_Change'] < 0]

        # --- Detect overtakes ---
        overtakes = []

        for _, gain in gained_places.iterrows():
            lap = gain["LapNumber"]
            old_pos = gain["Previous_Position"]
            new_pos = gain["Position"]

            candidate = lost_places[
                (lost_places["LapNumber"] == lap)
                & (lost_places["Previous_Position"] == new_pos)
                & (lost_places["Position"] == old_pos)
            ]

            if candidate.empty:
                continue

            overtakes.append({
                "LapNumber": lap,
                "PassingDriver": gain["Driver"],
                "PassedDriver": candidate.iloc[0]["Driver"],
                "OldPosition": old_pos,
                "NewPosition": new_pos
            })

        overtakes = pd.DataFrame(overtakes)

        # --- Build KDTree for track distance mapping ---

        ref_tel = ref_lap.get_telemetry()

        ref_xy = np.column_stack([
            ref_tel["X"].to_numpy(),
            ref_tel["Y"].to_numpy()
        ])

        tree = cKDTree(ref_xy)

        ref_distance = ref_tel["Distance"].to_numpy()

        # --- Attach telemetry for each overtake ---
        overtake_details = []

        for _, row in overtakes.iterrows():
            lap = row["LapNumber"]
            passing = row["PassingDriver"]
            passed  = row["PassedDriver"]

            passing_tel = race_event_laps[(race_event_laps['LapNumber']==lap) & (race_event_laps['Driver']==passing)].iloc[0].get_telemetry()
            passed_tel  = race_event_laps[(race_event_laps['LapNumber']==lap) & (race_event_laps['Driver']==passed)].iloc[0].get_telemetry()

            passing_tel = self.add_track_distance(passing_tel, tree, ref_distance)
            passed_tel  = self.add_track_distance(passed_tel, tree, ref_distance)

            overtake_details.append({
                "LapNumber": lap,
                "PassingDriver": passing,
                "PassedDriver": passed,
                "PassingTelemetry": passing_tel,
                "PassedTelemetry": passed_tel
            })

        overtake_points = []

        for item in overtake_details:
            passing = item["PassingTelemetry"]
            passed  = item["PassedTelemetry"]

            # Align both telemetry frames by time index
            merged = passing[["Time", "TrackDistance", "X", "Y"]].merge(
                passed[["Time", "TrackDistance", "X", "Y"]],
                on="Time",
                suffixes=("_passing", "_passed")
            )

            # Find the first moment passing driver is ahead
            ahead = merged[merged["TrackDistance_passing"] > merged["TrackDistance_passed"]]

            if ahead.empty:
                continue

            overtake_moment = ahead.iloc[0]

            overtake_points.append({
                "LapNumber": item["LapNumber"],
                "PassingDriver": item["PassingDriver"],
                "PassedDriver": item["PassedDriver"],
                "X": overtake_moment["X_passing"],
                "Y": overtake_moment["Y_passing"],
                "TrackDistance": overtake_moment["TrackDistance_passing"]
            })
        overtake_points = pd.DataFrame(overtake_points, columns=["LapNumber", "PassingDriver", "PassedDriver", "X", "Y", "TrackDistance"])

        track_x = ref_tel["X"].to_numpy()
        track_y = ref_tel["Y"].to_numpy()
        track_dist = ref_tel["Distance"].to_numpy()

        # Choose bin size (smaller = more detailed)
        bin_size = 100  # metres

        max_dist = track_dist.max()
        bins = np.arange(0, max_dist + bin_size, bin_size)

        # Count overtakes per bin
        overtake_points["Bin"] = np.digitize(overtake_points["TrackDistance"], bins)

        bin_counts = overtake_points.groupby("Bin").size().reindex(range(len(bins)), fill_value=0)

        track_bins = np.digitize(track_dist, bins)
        segments = []

        for i in range(1, len(bins)):
            mask = track_bins == i
            if not mask.any():
                continue

            segments.append({
                "bin": i,
                "x": track_x[mask],
                "y": track_y[mask],
                "count": bin_counts.iloc[i]
            })

        return bin_counts, segments

    def get_pit_strategy_data(self, selected_event, refresh=False):
        tables = pit_analysis_data.load_tables()
        # Past races are saved to disk, so FastF1 is only asked when this event has none yet (or on a preload refresh)
        if refresh or tables is None or selected_event not in set(tables[1]['EventName']):
            # only fetches this event's past races (already-saved ones are skipped)
            if not pit_analysis_data.build_event(selected_event):
                self.logger.warning("FastF1 rate limit hit - pit strategy uses the races downloaded so far")
            tables = pit_analysis_data.load_tables()
        if tables is None:
            self.logger.warning(f"No pit stop data for {selected_event}")
            return None, None, None
        pit_stops, clean_laps = tables
        degradation_model, _ = strategy_pick.fit_degradation(clean_laps)
        # Race length at this track from its latest race in the pit history, None if it has no saved races
        event_laps = clean_laps[clean_laps['EventName'] == selected_event]
        race_laps = int(event_laps.loc[event_laps['Year'] == event_laps['Year'].max(), 'LapNumber'].max()) if not event_laps.empty else None
        return degradation_model, pit_stops, race_laps

    def get_strategy_events(self, latest_season):
        # Tracks for the strategy page: the latest season's finished events in calendar order, then every
        # other track already in the pit history. The default is the latest season's most recent race
        events = self.get_season_events(latest_season)['EventName'].tolist() if latest_season else []
        tables = pit_analysis_data.load_tables()
        history = sorted(set(tables[1]['EventName']) - set(events)) if tables is not None else []
        return events + history, (events[-1] if events else None)

    def get_pit_decision(self, degradation_model, pit_stops, selected_event, current_compound, tyre_age, new_compound, laps_left, condition):
        # Median pit loss at this track, falling back to every track if it has no stops under this condition
        condition_stops = pit_stops[pit_stops['Condition'] == condition]
        event_stops = condition_stops[condition_stops['EventName'] == selected_event]
        reference_stops = event_stops if not event_stops.empty else condition_stops
        pit_loss = reference_stops['PitLoss'].median() if not reference_stops.empty else pit_stops['PitLoss'].median()

        pit_vs_stay = strategy_pick.pit_vs_stay(degradation_model, current_compound, tyre_age, new_compound, laps_left, pit_loss)
        final_gain = pit_vs_stay['CumulativeGain'].iloc[-1]
        positive_laps = pit_vs_stay.loc[pit_vs_stay['CumulativeGain'] > 0, 'LapsAhead']
        decision = {
            'pit_now': final_gain > 0,
            'final_gain': final_gain,
            'pit_loss': pit_loss,
            'pit_loss_source': selected_event if not event_stops.empty else 'all tracks',
            'break_even_lap': int(positive_laps.iloc[0]) if not positive_laps.empty else None,
        }
        return pit_vs_stay, decision

    def get_event_points(self, year):
        # Points per driver per round (race + sprint) from FastF1. Rounds already saved are not reloaded,
        # and the first round without results stops the loop because later rounds have not happened yet
        if event_points_csv(year).exists():
            saved = pd.read_csv(event_points_csv(year))
        else:
            saved = pd.DataFrame(columns=['RoundNumber', 'EventName', 'Abbreviation', 'Points'])

        schedule = fastf1.get_event_schedule(year, include_testing=False)
        new_points = []
        for _, event in schedule.iterrows():
            if event['RoundNumber'] in set(saved['RoundNumber']):
                continue
            identifiers = ['R'] + (['S'] if 'sprint' in event['EventFormat'] else [])
            try:
                results = []
                for identifier in identifiers:
                    session = fastf1.get_session(year, event['RoundNumber'], identifier)
                    session.load(laps=False, telemetry=False, weather=False, messages=False)
                    results.append(session.results[['Abbreviation', 'Points']])
            except Exception as exc:
                self.logger.info(f"Stopping points download at {event['EventName']}: results not available ({exc})")
                break

            round_points = pd.concat(results).groupby('Abbreviation', as_index=False)['Points'].sum()
            round_points.insert(0, 'EventName', event['EventName'])
            round_points.insert(0, 'RoundNumber', event['RoundNumber'])
            new_points.append(round_points)

        points = pd.concat([saved, *new_points], ignore_index=True)
        return points

    @staticmethod
    def match_event_names(fia_names, schedule):
        # FIA event names (e.g. "Barcelona-Catalunya Grand Prix") rarely equal FastF1's EventName, so each one is
        # matched to the schedule row whose location appears in it, or else whose name is most similar
        matches = {}
        for fia_name in fia_names:
            fia_lower = fia_name.lower()
            scores = []
            for _, event in schedule.iterrows():
                location_words = [word for word in re.split(r'[\s-]+', event['Location'].lower()) if len(word) > 3]
                if any(word in fia_lower for word in location_words):
                    scores.append(1.0)
                else:
                    scores.append(max(SequenceMatcher(None, fia_lower, event[column].lower()).ratio() for column in ['EventName', 'Location']))
            matches[fia_name] = schedule.iloc[int(np.argmax(scores))]['EventName']
        return matches

    def get_standings_vs_pu_elements_data(self, year, refresh=False):
        # Scraping the FIA site is slow, so the table is shared from the cache until it is season_max_age_hours old.
        # Past seasons no longer change, so their cached table is always used
        age = self.cache_store.bundle_age_hours(year, 'standings_vs_pu_elements')
        if not refresh and age is not None and (age < self.season_max_age_hours or year < pd.Timestamp.now().year):
            return self.cache_store.load_bundle(year, 'standings_vs_pu_elements')['standings']
        try:
            standings = self.build_standings_vs_pu_elements(year)
        except Exception:
            if age is None:
                raise
            self.logger.exception("Could not refresh standings vs PU elements, using the cached table")
            return self.cache_store.load_bundle(year, 'standings_vs_pu_elements')['standings']
        self.cache_store.save_bundle({'standings': standings}, year, 'standings_vs_pu_elements')
        return standings

    def build_standings_vs_pu_elements(self, year):
        points = self.get_event_points(year)
        schedule = fastf1.get_event_schedule(year, include_testing=False)

        # Points are cumulative per driver, so the championship total after each event is the running sum
        points = points.sort_values('RoundNumber')
        points['Points'] = points.groupby('Abbreviation')['Points'].cumsum()

        if year != PU_ELEMENTS_YEAR:
            # The FIA PU element reports are only scraped for one season, other seasons get the standings alone
            drivers, _ = self.get_season_drivers(year)
            standings = points.rename(columns={'Abbreviation': 'Driver', 'EventName': 'Event'})
            standings['Team'] = standings['Driver'].map(drivers.set_index('Driver')['Team'])
            standings = standings.reindex(columns=['Driver', 'Team', 'Event', 'RoundNumber', 'Points', *PU_COLUMNS])
            return standings.reset_index(drop=True)

        pu_table = get_pu_season_table()

        pu_table['Event'] = pu_table['Event'].map(self.match_event_names(pu_table['Event'].unique(), schedule))
        drivers_standings_vs_pu_elements = pu_table.merge(points, left_on=['Event', 'Abbreviation'], right_on=['EventName', 'Abbreviation'], how='left')
        drivers_standings_vs_pu_elements['Points'] = drivers_standings_vs_pu_elements['Points'].fillna(0)
        drivers_standings_vs_pu_elements['Driver'] = drivers_standings_vs_pu_elements['Abbreviation']
        drivers_standings_vs_pu_elements = drivers_standings_vs_pu_elements.sort_values('RoundNumber').reset_index(drop=True)
        drivers_standings_vs_pu_elements = drivers_standings_vs_pu_elements[['Driver', 'Team', 'Event', 'RoundNumber', 'Points', 'ICE', 'TC', 'MGU-H', 'MGU-K', 'ES', 'CE']]

        return drivers_standings_vs_pu_elements