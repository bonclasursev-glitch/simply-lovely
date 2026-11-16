# Import local modules
from streamlit_dashboard.logger import get_logger
from streamlit_dashboard.data_processor import DataProcessor, NEUTRAL_COLOUR, PU_COLUMNS
from streamlit_dashboard.cache_store import REPO_ROOT
# Import Python libraries
import plotly.graph_objs as go
import plotly.colors as pc
import yaml
import streamlit as st


class Visualizer:
    def __init__(self, logger):
        self.logger = logger
        with open(REPO_ROOT / "config" / "teams_drivers_info.yaml", "r") as file:
            self.config_info = yaml.safe_load(file)
        self.data_processor = DataProcessor
        self.driver_colours = {}

    def set_driver_colours(self, driver_colours):
        # Colours of the selected event's (or season's) drivers, worked out by the DataProcessor from FastF1's driver info
        self.driver_colours = dict(driver_colours)

    def driver_colour(self, driver):
        # Drivers missing from the driver info are drawn in a neutral colour rather than guessed
        return f"rgba({self.driver_colours.get(driver, NEUTRAL_COLOUR)})"

    def create_race_plot(self, race_event_laps, selected_event):
        race_plot = go.Figure()

        for driver in race_event_laps["Driver"].unique():
            driver_laps = race_event_laps[race_event_laps["Driver"] == driver]
            race_plot.add_scatter(
                x=driver_laps["LapNumber"],
                y=driver_laps["Position"],
                mode="lines",
                name=driver,
                line=dict(
                    color=self.driver_colour(driver)
                ))

        race_plot.update_yaxes(autorange="reversed", range=[22.5,0.5])
        race_plot.update_layout(title=f"Race Plot - Drivers Positions over {selected_event}", xaxis_title="Laps", yaxis_title="Position")
        return race_plot

    def create_tyre_strategy_plot(self, race_event_laps, selected_event):
        tyre_strategy_plot = go.Figure()

        driver_order = (
            race_event_laps.groupby("Driver")["Position"]
            .last()
            .sort_values()
            .index
            .tolist()
        )

        for driver in race_event_laps["Driver"].unique():
            driver_laps = race_event_laps[race_event_laps["Driver"] == driver].sort_values("LapNumber")
            # One bar per run of consecutive laps on the same compound instead of one per lap, which keeps the
            # figure to a few dozen traces so it builds and renders quickly
            compound = driver_laps["Compound"].fillna("")
            new_run = (compound != compound.shift()) | (driver_laps["LapNumber"].diff() != 1)

            for _, run in driver_laps.groupby(new_run.cumsum()):
                tyre_strategy_plot.add_trace(
                    go.Bar(
                        x = [len(run)],
                        y = [driver],
                        base = run['LapNumber'].iat[0] -1,
                        orientation='h',
                        # FastF1 leaves Compound empty on some laps (e.g. not recorded), these are drawn grey
                        marker_color = f"rgba({self.config_info['compound_colours'].get(run['Compound'].iat[0], '150,150,150,1')})",
                        marker_line_width=0,
                        showlegend= False
                    )
                )

        tyre_strategy_plot.update_layout(
            barmode="stack",
            xaxis_title="Lap",
            yaxis_title="Driver",
            title = f"Tyre strategies over {selected_event}",
            template="plotly_white",
            bargap=0.2,
            height = 600
        )

        tyre_strategy_plot.update_yaxes(
            categoryorder="array",
            categoryarray=driver_order,
            autorange="reversed"
        )
        tyre_strategy_plot.update_xaxes(showgrid = True, gridwidth = 1, gridcolor = 'lightgrey')

        return tyre_strategy_plot

    def create_laptime_violin_chart(self, race_event_laps, selected_event):
        laptime_violin_plot = go.Figure()
        laps_violin = race_event_laps.pick_quicklaps()
        # fastest_lap_overall = laps_violin['LapTime'].dt.total_seconds().min()
        # fastest_driver = laps_violin.loc[laps_violin['LapTime'] == fastest_lap_overall, 'Driver']

        average_lap_time_overall = laps_violin['LapTime'].dt.total_seconds().mean()

        for driver in laps_violin['Driver'].unique():
            driver_laps = laps_violin[laps_violin['Driver'] == driver]
            driver_mean = driver_laps['LapTime'].dt.total_seconds().mean()
            driver_colour = self.driver_colour(driver)

            laptime_violin_plot.add_trace(go.Violin(
                y=driver_laps['LapTime'].dt.total_seconds(),
                name= driver,
                showlegend= False,
                line=dict(color=driver_colour)
            ))
            laptime_violin_plot.add_trace(go.Scatter(
                y = [driver_mean],
                x = [driver],
                mode ="markers",
                marker= dict(symbol="diamond", size = 5, color=driver_colour
                        ),
                showlegend = False)
            )

        laptime_violin_plot.add_hline(y = average_lap_time_overall, line_dash="dash", line_color = "red", annotation_text=f"Average Grid Lap Time: {average_lap_time_overall} s")
        laptime_violin_plot.update_yaxes(title="Lap Time in s")
        laptime_violin_plot.update_xaxes(title= "Driver")
        laptime_violin_plot.update_layout(title = f"Spread of Lap Times over {selected_event}")

        return laptime_violin_plot

    def create_quali_strategy_plot(self, plot_laps, status_changes, selected_event):
        quali_strategy_plot = go.Figure()

        # Fastest valid qualifying lap
        fastest_quali_lap = plot_laps['LapTime'].min()

        # Drivers with at least one valid timed lap
        drivers = plot_laps['Driver'].unique()

        # Numerical y position for each driver
        driver_positions = {
            driver: i for i, driver in enumerate(drivers)
        }

        for driver in drivers:

            driver_quali_laps = plot_laps[
                plot_laps['Driver'] == driver
            ]

            driver_fastest_quali_lap = driver_quali_laps['LapTime'].min()

            y_pos = driver_positions[driver]

            for _, lap in driver_quali_laps.iterrows():

                # Decide rectangle colour
                if lap['LapTime'] == fastest_quali_lap:
                    colour = 'purple'

                elif lap['LapTime'] == driver_fastest_quali_lap:
                    colour = 'green'

                else:
                    colour = 'yellow'

                # Start in compressed session time
                start_time = lap['CompressedLapStartSeconds']

                # LapTime is a Timedelta -> convert to seconds
                lap_duration = lap['LapTime'].total_seconds()

                end_time = start_time + lap_duration

                quali_strategy_plot.add_trace(
                    go.Scatter(
                        x=[
                            start_time,
                            end_time,
                            end_time,
                            start_time,
                            start_time
                        ],

                        y=[
                            y_pos - 0.35,
                            y_pos - 0.35,
                            y_pos + 0.35,
                            y_pos + 0.35,
                            y_pos - 0.35
                        ],

                        mode='lines',
                        fill='toself',
                        fillcolor=colour,
                        line=dict(
                            color=colour,
                            width=1
                        ),
                        showlegend=False,

                        hovertemplate=(
                            f"Driver: {driver}<br>"
                            f"Lap: {lap['LapNumber']}<br>"
                            f"Lap time: {lap['LapTime']}<extra></extra>"
                        )
                    )
                )

        qualifying_starts = status_changes[
            status_changes['Status'] == 'Started'
        ].iloc[:3]

        tickvals = (
            qualifying_starts['CompressedTime']
            .dt.total_seconds()
            .tolist()
        )

        quali_strategy_plot.update_layout(
            height=700,
            xaxis=dict(
                title='Qualifying Session Time',
                tickmode='array',
                tickvals=tickvals,
                ticktext=[
                    'Q1 Start',
                    'Q2 Start',
                    'Q3 Start'
                ],
                showgrid=True
            ),
            yaxis=dict(
                tickmode='array',
                tickvals=list(driver_positions.values()),
                ticktext=list(driver_positions.keys()),
                autorange='reversed'
            ),
            title = dict(text = f"{selected_event} Quali Plot", font = dict( size = 20)
        ))
        return quali_strategy_plot

    def create_quali_fastest_comparison_plot(self, quali_telemetry, selected_event, selected_drivers):
        # quali_telemetry holds the speed trace of each driver's fastest lap, precomputed by the DataProcessor
        quali_velocity_plot = go.Figure()
        hover_template = "Lap Time: %{customdata} s<br>Velocity: %{x} m/s<br>Distance: %{y} m"
        for driver in selected_drivers:
            telemetry = quali_telemetry[quali_telemetry['Driver'] == driver]
            if telemetry.empty:
                st.markdown(f"There are no fast laps recorded during the Qualifying session of {selected_event} for {driver}. Plotting velocity chart for other selected drivers.")
                continue
            laptime = telemetry['LapTimeS'].iat[0]
            quali_velocity_plot.add_trace(
                go.Scatter(
                    x=telemetry['Distance'],
                    y=telemetry['Speed'],
                    name=driver,
                    mode='lines',
                    line=dict(color=self.driver_colour(driver)),
                    hovertemplate = hover_template,
                    customdata=[laptime]*len(telemetry['Distance'])))

        quali_velocity_plot.update_layout(title=f"Velocity Trace over {selected_event} - Fastest Laps", xaxis_title="Distance (m)", yaxis_title="Velocity (m/s)")
        return quali_velocity_plot

    def create_race_gaps_plot(self, raceplot_long, race_event_laps, selected_event):
        
        driver_order = (
            race_event_laps.sort_values("LapNumber")
            .groupby("Driver")["Position"]
            .last()
            .sort_values()
            .index
            .tolist()
        )

        race_gaps_plot = go.Figure()

        for driver in driver_order:

            df = raceplot_long[
                raceplot_long["Driver"] == driver
            ]

            race_gaps_plot.add_trace(
                go.Scatter(
                    x=df["RacePosition"],
                    y=df["GapToLeader"],
                    mode="lines",
                    name=driver,

                    line=dict(
                        color=self.driver_colour(driver)
                    ),

                    customdata=df[["LapNumber", "Sector"]],

                    hovertemplate=(
                        "Lap %{customdata[0]}<br>"
                        "%{customdata[1]}<br>"
                        "Gap: %{y:.3f}s"
                        "<extra>%{fullData.name}</extra>"
                    ),
                )
            )

        race_gaps_plot.update_layout(
            title=f"Gap to Leader by Sector over {selected_event}",
            xaxis_title="Lap",
            yaxis_title="Gap to Leader (s)",
            height=700,
            width=1000,
        )
        race_gaps_plot.update_yaxes(autorange="reversed")

        return race_gaps_plot

    def create_overtaking_heatmap_plot(self, bin_counts, segments):
        colorscale = pc.sequential.Reds
        def map_to_color(value, vmin, vmax, colorscale):
            # Normalize 0–1
            t = (value - vmin) / (vmax - vmin) if vmax > vmin else 0
            # Pick index
            idx = int(t * (len(colorscale) - 1))
            return colorscale[idx]

        vmin = bin_counts.min()
        vmax = bin_counts.max()

        fig = go.Figure()

        for seg in segments:
            color_hex = map_to_color(seg["count"], vmin, vmax, colorscale)

            fig.add_trace(
                go.Scatter(
                    x=seg["x"],
                    y=seg["y"],
                    mode="lines",
                    line=dict(color=color_hex, width=6),
                    hoverinfo="text",
                    text=f"Overtakes: {seg['count']}"
                )
            )

        fig.update_layout(
            title="Overtake Density Track Map",
            xaxis=dict(scaleanchor="y", scaleratio=1),
            width=900,
            height=700,
            showlegend=False
        )
        return fig

    def create_pit_vs_stay_plot(self, pit_vs_stay, decision, strategy_inputs):
        pit_vs_stay_plot = go.Figure()
        decision_colour = "green" if decision['pit_now'] else "red"

        pit_vs_stay_plot.add_scatter(
            x=pit_vs_stay["LapsAhead"],
            y=pit_vs_stay["CumulativeGain"],
            mode="lines",
            name="Pit now vs stay out",
            line=dict(color=decision_colour, width=3),
            fill="tozeroy",
            hovertemplate="Lap +%{x}: %{y:+.1f} s<extra></extra>",
        )
        pit_vs_stay_plot.add_hline(y=0, line_dash="dash", line_color="grey")
        if decision['break_even_lap'] is not None:
            pit_vs_stay_plot.add_vline(
                x=decision['break_even_lap'],
                line_dash="dot",
                line_color="grey",
                annotation_text=f"Break-even: lap +{decision['break_even_lap']}",
            )

        pit_vs_stay_plot.update_layout(
            title=(
                f"{'PIT NOW' if decision['pit_now'] else 'STAY OUT'} - "
                f"{strategy_inputs['current_compound']} ({strategy_inputs['tyre_age']} laps old) -> "
                f"{strategy_inputs['new_compound']}, {strategy_inputs['laps_left']} laps to go"
            ),
            xaxis_title="Laps from now",
            yaxis_title="Cumulative time gained by pitting (s)",
            template="plotly_white",
            showlegend=False,
        )
        return pit_vs_stay_plot

    def create_pu_elements_vs_standings_plot(self, drivers_standings_vs_pu_elements):
        pu_elements_vs_standings_plot = go.Figure()
        # PU element counts only exist for the season the FIA reports are scraped for, other seasons show the standings alone
        has_pu_elements = drivers_standings_vs_pu_elements[PU_COLUMNS].notna().any().any()

        for driver in drivers_standings_vs_pu_elements['Driver'].unique():
            print(f"Creating plot for {driver}")
            driver_data = drivers_standings_vs_pu_elements[drivers_standings_vs_pu_elements['Driver'] == driver]
            # x axis should be the events in chronological order, y axis should be the championship points, and the size of the marker should be the number of power unit elements used
            pu_elements = driver_data[PU_COLUMNS].sum(axis=1)
            if not has_pu_elements:
                pu_elements_vs_standings_plot.add_trace(
                    go.Scatter(
                        x=driver_data['Event'],
                        y=driver_data['Points'],
                        mode='lines+markers',
                        name=driver,
                        line=dict(color=self.driver_colour(driver)),
                        hovertemplate="Event: %{x}<br>Championship Points: %{y}<extra></extra>",
                    )
                )
                continue
            pu_elements_vs_standings_plot.add_trace(
                go.Scatter(
                    x=driver_data['Event'],
                    y=driver_data['Points'],
                    mode='lines+markers',
                    name=driver,
                    line=dict(color=self.driver_colour(driver)),
                    marker=dict(size=pu_elements, sizemode='area', sizeref=2.*max(max(pu_elements), 1)/(40.**2), sizemin=4),
                    hovertemplate="Event: %{x}<br>Championship Points: %{y}<br>PU Elements: %{customdata}<extra></extra>",
                    customdata=pu_elements
                )
            )

        pu_elements_vs_standings_plot.update_layout(
            title="Drivers Championship Standings vs Power Unit Elements Used" if has_pu_elements else "Drivers Championship Standings",
            xaxis_title="Events",
            yaxis_title="Championship Points"
        )

        return pu_elements_vs_standings_plot