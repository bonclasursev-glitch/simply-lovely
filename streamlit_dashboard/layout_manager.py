# Import local modules
from streamlit_dashboard.logger import get_logger
# Import Python libraries
import streamlit as st


class LayoutManager:
    def __init__(self, config, logger, visualizer):
        self.logger = logger
        self.config = config
        self.visualizer = visualizer
        self.dashboard_title = config['DASHBOARD_DEFAULTS']['dasboard_title']
        st.set_page_config(layout=config['DASHBOARD_DEFAULTS']['dashboard_layout'], page_title=self.dashboard_title)
