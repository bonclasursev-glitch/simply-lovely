# Import local modules
from streamlit_dashboard.logger import get_logger
from streamlit_dashboard.data_processor import DataProcessor
# Import Python libraries
import plotly.graph_objs as go
from plotly.subplots import make_subplots
import yaml
import streamlit as st
import pandas as pd


class Visualizer:
    def __init__(self, logger):
        self.logger = logger
        with open("C:/Users/boncl/Repos/simply-lovely/config/teams_drivers_info.yaml", "r") as file:
            self.config_info = yaml.safe_load(file)
        self.data_processor = DataProcessor

    def create_race_plot(self, race_event_laps, selected_event):
        race_plot = go.Figure()

        for driver in race_event_laps["Driver"].unique():
            driver_laps = race_event_laps[race_event_laps["Driver"] == driver]
            driver_team = race_event_laps.loc[race_event_laps['Driver']== driver, 'Team'].unique()[0]
            race_plot.add_scatter(
                x=driver_laps["LapNumber"],
                y=driver_laps["Position"],
                mode="lines",
                name=driver,
                line=dict(
                    color=f"rgba({self.config_info['teams'][driver_team]['drivers'][driver]['colour']})"
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
            driver_laps = race_event_laps[race_event_laps["Driver"] == driver]

            for _, lap in driver_laps.iterrows():
                tyre_strategy_plot.add_trace(
                    go.Bar(
                        x = [1],
                        y = [driver],
                        base = lap['LapNumber'] -1,
                        orientation='h',
                        marker_color = f"rgba({self.config_info['compound_colours'][lap['Compound']]})",
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
            driver_team = driver_laps['Team'].iat[0]
            driver_colour = self.config_info['teams'][driver_team]['drivers'][driver]['colour']

            laptime_violin_plot.add_trace(go.Violin(
                y=driver_laps['LapTime'].dt.total_seconds(),
                name= driver,
                showlegend= False,
                line=dict(color=f"rgba({driver_colour})")
            ))
            laptime_violin_plot.add_trace(go.Scatter(
                y = [driver_mean],
                x = [driver],
                mode ="markers",
                marker= dict(symbol="diamond", size = 5, color=f"rgba({driver_colour})"
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

    def create_quali_fastest_comparison_plot(self, quali_event_laps, selected_event, selected_drivers):
        quali_laps_all = quali_event_laps.dropna(subset=["LapTime"])
        fastest_by_driver = quali_laps_all.sort_values("LapTime").drop_duplicates(subset="Driver", keep = "first").sort_values("LapTime")

        quali_velocity_plot = go.Figure()
        hover_template = "Lap Time: %{customdata} s<br>Velocity: %{x} m/s<br>Distance: %{y} m"
        for driver in selected_drivers:
            driver_lap = fastest_by_driver[fastest_by_driver['Driver'] == driver]
            if driver_lap.empty:
                st.markdown(f"There are no fast laps recorded during the Qualifying session of {selected_event} for {driver}. Plotting velocity chart for other selected drivers.")
                continue
            driver_team = driver_lap['Team'].min()
            driver_colour = self.config_info['teams'][driver_team]['drivers'][driver]['colour']
            laptime = driver_lap['LapTime'].dt.total_seconds()
            telemetry = driver_lap.get_telemetry()
            quali_velocity_plot.add_trace(
                go.Scatter(
                    x=telemetry['Distance'],
                    y=telemetry['Speed'],
                    name=driver,
                    mode='lines',
                    line=dict(color=f"rgba({driver_colour})"),
                    hovertemplate = hover_template,
                    customdata=[laptime]*len(telemetry['Distance'])))

        quali_velocity_plot.update_layout(title=f"Velocity Trace over {selected_event} - Fastest Laps", xaxis_title="Distance (m)", yaxis_title="Velocity (m/s)")
        return quali_velocity_plot