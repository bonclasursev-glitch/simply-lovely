# Import local libraries
from streamlit_dashboard.logger import get_logger
# Import Python libraries
import streamlit as st
import datetime


class DashboardOrchestrator:
    def _init_(self, config, data_processor, layout_manager, formatter):
        self.logger = get_logger(__name__)
        self.config = config
        self.data_processor = data_processor
        self.layout_manager = layout_manager
        self.formatter = formatter
        self.refresh_rate = int(config['DASHBOARD_DEFAULTS']['refresh_rate'])

    def run_dashboard(self):
        self.logger.info('Entering dashboard loop - Simply Lovely!')
        self.logger.info('Loading data...')
        # xxx = self.load_data_to_cache(self.data_processor)
    
    # # Using cache to store the data and improve dashboard reaction when navigating between pages
    # @staticmethod
    # @st.cache_data
    # def load_data_to_cache(_data_processor):
        