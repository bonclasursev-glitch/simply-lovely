# Import local modules
from streamlit_dashboard.logger import get_logger
# Import Python libraries
import streamlit as st
from st_screen_stats import ScreenData

RACE_STRATEGY = "Race Strategy"
SEASON_OVERVIEW = "Season Overview"
EVENT_DETAILS = "Event Details"


class LayoutManager:
    def __init__(self, config, logger, visualizer):
        self.logger = logger
        self.config = config
        self.visualizer = visualizer
        self.dashboard_title = config['DASHBOARD_DEFAULTS']['dashboard_title']
        st.set_page_config(layout=config['DASHBOARD_DEFAULTS']['dashboard_layout'], page_title=self.dashboard_title)

    def format_dashboard(self):
        st.sidebar.image("images/F1_logo.jpg", output_format='auto')
        st.sidebar.title(self.dashboard_title)
        st.sidebar.markdown("Every season with FastF1 timing data, from 2018.")
        return st.sidebar.radio("Select Dashboard:", [RACE_STRATEGY, SEASON_OVERVIEW, EVENT_DETAILS], index=None, key="dashboard_selection")

    @staticmethod
    def keep_valid_selection(key, options, multiple=False):
        # Options change with the selected year or event, so a value that is no longer offered is dropped before the widget is drawn
        if key not in st.session_state:
            return
        if multiple:
            st.session_state[key] = [value for value in st.session_state[key] if value in options]
        elif st.session_state[key] not in options:
            del st.session_state[key]

    def select_year(self, seasons):
        if not seasons:
            return None
        self.keep_valid_selection("selected_year", seasons)
        # seasons are most recent first, so the default is the latest season
        return st.sidebar.selectbox("Select Year:", seasons, index=0, key="selected_year")

    def select_event(self, events_list):
        self.keep_valid_selection("selected_event", events_list)
        return st.sidebar.selectbox("Select Event:", events_list, index=None, placeholder="Choose an event", key="selected_event", disabled=not events_list)

    def select_drivers(self, drivers_list):
        self.keep_valid_selection("selected_drivers", drivers_list, multiple=True)
        st.sidebar.multiselect("Select Drivers:", drivers_list, key="selected_drivers", placeholder="All drivers")

    def format_submit_buttons(self, blocked_reason):
        # Submit stays disabled until the selection can be loaded, and the reason is shown under it
        submit_col, clear_col = st.sidebar.columns(2)
        submit_col.button("Submit", type="primary", on_click=self.submit_selection, use_container_width=True, disabled=blocked_reason is not None)
        clear_col.button("Clear", on_click=self.clear_selection, use_container_width=True)
        if blocked_reason is not None:
            st.sidebar.caption(blocked_reason)

    @staticmethod
    def get_submitted_selection(dashboard_selection):
        # The main page only follows the last submitted selection, so changing a widget does nothing until Submit
        submitted = st.session_state.get("submitted_selection")
        if submitted is None or submitted[0] != dashboard_selection:
            st.info(f"Choose the {dashboard_selection} options in the sidebar and press Submit")
            return None
        return submitted

    @staticmethod
    def submit_selection():
        st.session_state["submitted_selection"] = (
            st.session_state.get("dashboard_selection"),
            st.session_state.get("selected_year"),
            st.session_state.get("selected_event"),
            tuple(st.session_state.get("selected_drivers", [])),
        )

    @staticmethod
    def clear_selection():
        st.session_state["dashboard_selection"] = None
        for key in ["selected_year", "selected_event", "selected_drivers", "strategy_event"]:
            st.session_state.pop(key, None)
        st.session_state["submitted_selection"] = None

    @staticmethod
    def show_warnings(warnings):
        for warning in warnings:
            st.warning(warning)

    def create_season_overview_visuals(self, drivers_standings_vs_pu_elements, selected_year):
        self.logger.info("Creating Season Overview Structure...")
        if drivers_standings_vs_pu_elements.empty:
            st.info(f"No championship results available for {selected_year} yet.")
            return
        pu_elements_vs_standings_plot = self.visualizer.create_pu_elements_vs_standings_plot(drivers_standings_vs_pu_elements)
        st.plotly_chart(pu_elements_vs_standings_plot)

    def create_event_page_visuals(self, race_event_laps, quali_telemetry, plot_laps, status_changes, selected_event, selected_drivers, raceplot_long, bin_counts, segments):
        self.logger.info("Creating Event Page Structure...")
        screenD = ScreenData(setTimeout=1000)
        # The component returns None until the browser has reported its size
        screen_d = screenD.st_screen_data() or {"innerWidth": 1500}
        st.session_state["screen_d"] = screen_d
        if screen_d["innerWidth"]> 2000:
            col1, col2 = st.columns([1,1])
        else:
            col1 = st.container()
            col2 = st.container()
        with col1:
            race_plot = self.visualizer.create_race_plot(race_event_laps, selected_event)
            tyre_strategy_plot = self.visualizer.create_tyre_strategy_plot(race_event_laps, selected_event)
            laptime_violin_plot = self.visualizer.create_laptime_violin_chart(race_event_laps, selected_event)
            race_gaps_plot = self.visualizer.create_race_gaps_plot(raceplot_long, race_event_laps, selected_event)
            
            st.plotly_chart(race_plot)
            st.plotly_chart(tyre_strategy_plot)
            st.plotly_chart(laptime_violin_plot)
            st.plotly_chart(race_gaps_plot)
        with col2:
            # Missing qualifying or position data leaves these plots out with a note instead of drawing empty charts
            if plot_laps.empty:
                st.info(f"No qualifying timing data available for {selected_event}, so the qualifying plots are not shown.")
            else:
                quali_strategy_plot = self.visualizer.create_quali_strategy_plot(plot_laps, status_changes, selected_event)
                st.plotly_chart(quali_strategy_plot)
            if quali_telemetry.empty:
                if not plot_laps.empty:
                    st.info(f"No qualifying telemetry available for {selected_event}, so the velocity traces are not shown.")
            else:
                quali_velocity_plot = self.visualizer.create_quali_fastest_comparison_plot(quali_telemetry, selected_event, selected_drivers)
                st.plotly_chart(quali_velocity_plot)
            if not segments:
                st.info(f"No position data available for {selected_event}, so the overtake map is not shown.")
            else:
                overtake_heatmap_plot = self.visualizer.create_overtaking_heatmap_plot(bin_counts, segments)
                st.plotly_chart(overtake_heatmap_plot)

    def select_strategy_event(self, events_list, default_event):
        st.header("Pit or Stay Out?")
        if not events_list:
            st.info("No tracks available: no finished events or pit stop history found.")
            return None
        self.keep_valid_selection("strategy_event", events_list)
        default_index = events_list.index(default_event) if default_event in events_list else 0
        return st.selectbox("Track:", events_list, index=default_index, key="strategy_event")

    def format_pit_strategy_inputs(self, degradation_model, race_laps):
        if degradation_model is None or degradation_model.empty:
            st.info("No pit stop data yet - run pit_stop_analysis/pit_analysis_data.py to build it.")
            return None

        compounds = degradation_model.index.tolist()
        if race_laps is None:
            st.caption("Race length unknown at this track (no saved races), so lap inputs are not capped.")
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            current_compound = st.selectbox("Current tyre:", compounds, index=0)
        with col2:
            tyre_age = st.number_input("Tyre age (laps):", min_value=0, max_value=race_laps, value=15)
        with col3:
            new_compound = st.selectbox("New tyre:", compounds, index=len(compounds) - 1)
        with col4:
            laps_left = st.number_input("Laps left:", min_value=1, max_value=race_laps, value=min(25, race_laps or 25))
        with col5:
            condition = st.selectbox("Track condition:", ["Green", "Safety Car", "VSC"])

        return {
            'current_compound': current_compound,
            'tyre_age': int(tyre_age),
            'new_compound': new_compound,
            'laps_left': int(laps_left),
            'condition': condition,
        }

    def create_pit_strategy_visuals(self, pit_vs_stay, decision, strategy_inputs):
        self.logger.info("Creating Pit Strategy Structure...")
        col1, col2, col3 = st.columns(3)
        col1.metric("Decision", "PIT NOW" if decision['pit_now'] else "STAY OUT")
        col2.metric("Time gained by pitting at the flag", f"{decision['final_gain']:+.1f} s")
        col3.metric(f"Pit loss ({decision['pit_loss_source']}, {strategy_inputs['condition']})", f"{decision['pit_loss']:.1f} s")
        pit_vs_stay_plot = self.visualizer.create_pit_vs_stay_plot(pit_vs_stay, decision, strategy_inputs)
        st.plotly_chart(pit_vs_stay_plot)