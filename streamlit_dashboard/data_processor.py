
# Import local modules
from streamlit_dashboard.logger import get_logger
# Import Python libraries
import fastf1
import pandas as pd
import numpy as np
import yaml


class DataProcessor:
    def __init__(self, config, logger):
        self.logger = logger
        self.config = config
        with open("C:/Users/boncl/Repos/simply-lovely/config/teams_drivers_info.yaml", "r") as file:
            self.config_teams_info = yaml.safe_load(file)
        fastf1.Cache.enable_cache('C:/Users/boncl/Repos/simply-lovely/fastf1_cache')

    def get_season_info_data(self):
        season = fastf1.get_event_schedule(2026)
        season = season[season['EventFormat'].isin(['conventional', 'sprint_shootout'])]
        events_list = season['EventName']
        drivers_list = []

        for team, team_data in self.config_teams_info['teams'].items():
            for driver, driver_data in team_data['drivers'].items():
                drivers_list.append(driver)

        return season, events_list, drivers_list

    def get_event_data(self, selected_event):
        race_event = fastf1.get_session(2026, selected_event, 'R')
        race_event.load()
        race_event_laps = race_event.laps

        quali_event = fastf1.get_session(2026, selected_event, 'Q')
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

        return race_event_laps, quali_event_laps, plot_laps, status_changes
    
