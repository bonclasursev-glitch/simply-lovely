# Import local libraries
from streamlit_dashboard.logger import get_logger
from streamlit_dashboard.layout_manager import RACE_STRATEGY, SEASON_OVERVIEW, EVENT_DETAILS
# Import Python libraries
import streamlit as st

# In-memory caches are shared by every session of this server process. They expire so that data saved to the
# shared disk cache (e.g. by preload_cache.py) or published after a race is picked up without a restart
MEMORY_CACHE_TTL = 600


class DashboardOrchestrator:
    def __init__(self, config, data_processor, layout_manager):
        self.logger = get_logger(__name__)
        self.config = config
        self.data_processor = data_processor
        self.layout_manager = layout_manager
        self.refresh_rate = int(config['DASHBOARD_DEFAULTS']['refresh_rate'])

    def run_dashboard(self):
        self.logger.info('Entering dashboard loop - Simply Lovely!')
        dashboard_selection = self.layout_manager.format_dashboard()
        if dashboard_selection is None:
            st.info("Select a dashboard view to start")
            return
        try:
            if dashboard_selection == RACE_STRATEGY:
                self.run_race_strategy()
            else:
                self.run_submitted_page(dashboard_selection)
        except Exception:
            # FastF1 and the FIA site can fail in many ways, the details go to the log and the user gets a short message
            self.logger.exception(f"Could not load {dashboard_selection}")
            st.error("Something went wrong while loading this page. Please try again later or pick another selection.")
        self.logger.info("Checkered flag!")

    def run_race_strategy(self):
        # Loads straight away, the track is picked on the page itself
        seasons = self.load_seasons_to_cache(self.data_processor)
        events_list, default_event = self.load_strategy_events_to_cache(self.data_processor, seasons[0] if seasons else None)
        selected_event = self.layout_manager.select_strategy_event(events_list, default_event)
        if selected_event is None:
            return
        degradation_model, pit_stops, race_laps = self.load_pit_strategy_to_cache(self.data_processor, selected_event)
        strategy_inputs = self.layout_manager.format_pit_strategy_inputs(degradation_model, race_laps)
        if strategy_inputs is not None:
            pit_vs_stay, decision = self.data_processor.get_pit_decision(degradation_model, pit_stops, selected_event, **strategy_inputs)
            self.layout_manager.create_pit_strategy_visuals(pit_vs_stay, decision, strategy_inputs)

    def run_submitted_page(self, dashboard_selection):
        seasons = self.load_seasons_to_cache(self.data_processor)
        selected_year = self.layout_manager.select_year(seasons)
        events_list = self.load_season_events_to_cache(self.data_processor, selected_year) if selected_year else []

        if dashboard_selection == EVENT_DETAILS:
            selected_event = self.layout_manager.select_event(events_list)
            drivers, _ = self.load_event_drivers_to_cache(self.data_processor, selected_year, selected_event) if selected_event else (None, [])
        else:
            selected_event = None
            drivers, _ = self.load_season_drivers_to_cache(self.data_processor, selected_year) if selected_year else (None, [])
        self.layout_manager.select_drivers(drivers['Driver'].tolist() if drivers is not None else [])

        if not seasons:
            blocked_reason = "No season with FastF1 data could be found, please try again later."
        elif not events_list:
            blocked_reason = f"No event of {selected_year} has data yet."
        elif dashboard_selection == EVENT_DETAILS and selected_event is None:
            blocked_reason = "Choose an event to continue."
        else:
            blocked_reason = None
        self.layout_manager.format_submit_buttons(blocked_reason)

        submitted = self.layout_manager.get_submitted_selection(dashboard_selection)
        if submitted is None:
            return
        _, selected_year, selected_event, selected_drivers = submitted
        self.logger.info(f"Submitted: {dashboard_selection} | {selected_year} | {selected_event} | {len(selected_drivers)} drivers")
        if dashboard_selection == SEASON_OVERVIEW:
            self.show_season_overview(selected_year, selected_drivers)
        else:
            self.show_event_details(selected_year, selected_event, selected_drivers)

    def show_season_overview(self, selected_year, selected_drivers):
        drivers, warnings = self.load_season_drivers_to_cache(self.data_processor, selected_year)
        self.layout_manager.show_warnings(warnings)
        self.layout_manager.visualizer.set_driver_colours(drivers.set_index('Driver')['Colour'])
        drivers_standings_vs_pu_elements = self.load_standings_vs_pu_elements_to_cache(self.data_processor, selected_year)
        if selected_drivers:
            drivers_standings_vs_pu_elements = drivers_standings_vs_pu_elements[drivers_standings_vs_pu_elements['Driver'].isin(selected_drivers)]
        self.layout_manager.create_season_overview_visuals(drivers_standings_vs_pu_elements, selected_year)

    def show_event_details(self, selected_year, selected_event, selected_drivers):
        event_data = self.load_to_cache(self.data_processor, selected_year, selected_event)
        if event_data is None:
            st.warning(f"No race timing data available for {selected_year} {selected_event}. Please pick another event.")
            return
        drivers, warnings = self.load_event_drivers_to_cache(self.data_processor, selected_year, selected_event)
        self.layout_manager.show_warnings(warnings)
        self.layout_manager.visualizer.set_driver_colours(drivers.set_index('Driver')['Colour'])
        race_event_laps, quali_telemetry, plot_laps, status_changes, raceplot_long, bin_counts, segments = event_data
        # No driver filter means every driver of the event, taken from the timing data if the driver list is unavailable
        selected_drivers = list(selected_drivers) or drivers['Driver'].tolist() or race_event_laps['Driver'].unique().tolist()
        self.layout_manager.create_event_page_visuals(race_event_laps, quali_telemetry, plot_laps, status_changes, selected_event, selected_drivers, raceplot_long, bin_counts, segments)

    @staticmethod
    @st.cache_data(ttl=MEMORY_CACHE_TTL, show_spinner="Finding seasons with data...")
    def load_seasons_to_cache(_data_processor):
        return _data_processor.get_available_seasons()

    @staticmethod
    @st.cache_data(ttl=MEMORY_CACHE_TTL, show_spinner="Loading the season calendar...")
    def load_season_events_to_cache(_data_processor, selected_year):
        return _data_processor.get_season_events(selected_year)['EventName'].tolist()

    @staticmethod
    @st.cache_data(ttl=MEMORY_CACHE_TTL, show_spinner="Loading tracks...")
    def load_strategy_events_to_cache(_data_processor, latest_season):
        return _data_processor.get_strategy_events(latest_season)

    @staticmethod
    @st.cache_data(ttl=MEMORY_CACHE_TTL, max_entries=100, show_spinner="Loading drivers...")
    def load_event_drivers_to_cache(_data_processor, selected_year, selected_event):
        return _data_processor.get_event_drivers(selected_year, selected_event)

    @staticmethod
    @st.cache_data(ttl=MEMORY_CACHE_TTL, max_entries=20, show_spinner="Loading the season's drivers...")
    def load_season_drivers_to_cache(_data_processor, selected_year):
        return _data_processor.get_season_drivers(selected_year)

    @staticmethod
    @st.cache_data(ttl=MEMORY_CACHE_TTL, max_entries=30, show_spinner="Loading event data...")
    def load_to_cache(_data_processor, selected_year, selected_event):
        return _data_processor.get_event_data(selected_year, selected_event)

    @staticmethod
    @st.cache_data(ttl=MEMORY_CACHE_TTL, max_entries=30, show_spinner="Loading pit stop history...")
    def load_pit_strategy_to_cache(_data_processor, selected_event):
        return _data_processor.get_pit_strategy_data(selected_event)

    @staticmethod
    @st.cache_data(ttl=MEMORY_CACHE_TTL, max_entries=20, show_spinner="Loading season standings...")
    def load_standings_vs_pu_elements_to_cache(_data_processor, selected_year):
        return _data_processor.get_standings_vs_pu_elements_data(selected_year)
