# Import local libraries
from streamlit_dashboard.logger import get_logger
# Import Python libraries
import streamlit as st
import datetime


class DashboardOrchestrator:
    def __init__(self, config, data_processor, layout_manager):
        self.logger = get_logger(__name__)
        self.config = config
        self.data_processor = data_processor
        self.layout_manager = layout_manager
        self.refresh_rate = int(config['DASHBOARD_DEFAULTS']['refresh_rate'])

    def run_dashboard(self):
        self.logger.info('Entering dashboard loop - Simply Lovely!')
        self.logger.info('Loading data...')
        season, events_list, drivers_list = self.data_processor.get_season_info_data()
        selected_event, selected_drivers = self.layout_manager.format_dashboard(events_list, drivers_list)
        race_event_laps, quali_event_laps, plot_laps, status_changes = self.load_to_cache(self.data_processor, selected_event)
        self.layout_manager.create_event_page_visuals(race_event_laps, quali_event_laps, plot_laps, status_changes, selected_event, selected_drivers)
        self.logger.info("Checkered flag!")

    @staticmethod
    @st.cache_data()
    def load_to_cache(_data_processor, selected_event):
        return _data_processor.get_event_data(selected_event)
