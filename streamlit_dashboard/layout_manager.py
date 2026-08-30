# Import local modules
from streamlit_dashboard.logger import get_logger
# Import Python libraries
import streamlit as st


class LayoutManager:
    def __init__(self, config, logger, visualizer):
        self.logger = logger
        self.config = config
        self.visualizer = visualizer
        self.dashboard_title = config['DASHBOARD_DEFAULTS']['dashboard_title']
        st.set_page_config(layout=config['DASHBOARD_DEFAULTS']['dashboard_layout'], page_title=self.dashboard_title)

    def format_dashboard(self, events_list, drivers_list):
        st.sidebar.image("images/F1_logo.jpg", output_format='auto')
        st.sidebar.title(self.dashboard_title)
        st.sidebar.markdown("This dashboard only shows 2026 data. More TBA!")
        selected_event = st.sidebar.selectbox("Select Event:", events_list)
        selected_drivers = st.sidebar.multiselect("Select Drivers:", drivers_list)
        if not selected_drivers:
            selected_drivers = drivers_list

        return selected_event, selected_drivers

    def create_event_page_visuals(self, race_event_laps, quali_event_laps, plot_laps, status_changes, selected_event, selected_drivers):
        self.logger.info("Creating Event Page Structure...")
        col1, col2 = st.columns([1,1])
        with col1:
            race_plot = self.visualizer.create_race_plot(race_event_laps, selected_event)
            tyre_strategy_plot = self.visualizer.create_tyre_strategy_plot(race_event_laps, selected_event)
            laptime_violin_plot = self.visualizer.create_laptime_violin_chart(race_event_laps, selected_event)
            st.plotly_chart(race_plot)
            st.plotly_chart(tyre_strategy_plot)
            st.plotly_chart(laptime_violin_plot)
        with col2:
            quali_strategy_plot = self.visualizer.create_quali_strategy_plot(plot_laps, status_changes, selected_event)
            quali_velocity_plot = self.visualizer.create_quali_fastest_comparison_plot(quali_event_laps, selected_event, selected_drivers)
            st.plotly_chart(quali_strategy_plot)
            st.plotly_chart(quali_velocity_plot)