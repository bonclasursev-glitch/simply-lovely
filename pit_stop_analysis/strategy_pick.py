"""Core race-strategy logic: pit-loss extraction and a simple tyre degradation model.

Everything here works on plain pandas DataFrames ("slim laps"), so it can be
tested without downloading anything and is shared by build_data.py and app.py.

Slim lap columns:
    Driver, LapNumber, Stint, Compound, TyreLife, LapTimeS,
    PitIn (bool), PitOut (bool), TrackStatus (str), IsAccurate (bool)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DRY_COMPOUNDS = ["SOFT", "MEDIUM", "HARD"]
CONDITIONS = ["Green", "Safety Car", "VSC"]


# --------------------------------------------------------------------------- #
# FastF1 -> slim laps
# --------------------------------------------------------------------------- #
def slim_laps(laps) -> pd.DataFrame:
    """Reduce a FastF1 Laps object to the few columns we need."""
    df = pd.DataFrame(
        {
            "Driver": laps["Driver"].astype(str),
            "LapNumber": laps["LapNumber"],
            "Stint": laps["Stint"],
            "Compound": laps["Compound"].astype(str).str.upper(),
            "TyreLife": laps["TyreLife"],
            "LapTimeS": laps["LapTime"].dt.total_seconds(),
            "PitIn": laps["PitInTime"].notna(),
            "PitOut": laps["PitOutTime"].notna(),
            "TrackStatus": laps["TrackStatus"].fillna("").astype(str),
            "IsAccurate": laps["IsAccurate"].fillna(False).astype(bool),
        }
    )
    df = df.dropna(subset=["LapNumber"])
    df["LapNumber"] = df["LapNumber"].astype(int)
    return df.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Pit loss
# --------------------------------------------------------------------------- #
def classify_status(status: str) -> str:
    """FastF1 track status codes: 1 green, 2 yellow, 4 SC, 5 red, 6 VSC, 7 VSC ending."""
    if "5" in status:
        return "Red flag"
    if "4" in status:
        return "Safety Car"
    if "6" in status or "7" in status:
        return "VSC"
    return "Green"


def extract_pit_stops(laps: pd.DataFrame, min_ref_cars: int = 3) -> pd.DataFrame:
    """Time lost per pit stop in one race.

    Pit loss = (pitting driver's in-lap + out-lap)
             - (median in-lap + out-lap time of the cars that did NOT pit on those two laps)

    Comparing against the rest of the field on the same two laps means the
    same formula works under green flag and under SC/VSC (where everyone is slow).
    """
    t = laps.pivot(index="LapNumber", columns="Driver", values="LapTimeS")
    t = t.reindex(range(1, int(t.index.max()) + 1))  # consecutive laps, so shift(-1) = next lap
    pitting = (
        laps.assign(_p=laps["PitIn"] | laps["PitOut"])
        .pivot(index="LapNumber", columns="Driver", values="_p")
        .reindex_like(t)
        .fillna(True)  # unknown lap -> don't use it as a reference
        .astype(bool)
    )

    pair = t + t.shift(-1)                      # lap n + lap n+1
    pair_pit = pitting | pitting.shift(-1, fill_value=True)
    clean_pair = pair.where(~pair_pit)
    field_ref = clean_pair.median(axis=1)
    ref_cars = clean_pair.notna().sum(axis=1)

    # In-lap (PitIn on lap n) joined to out-lap (PitOut on lap n+1)
    out = laps[["Driver", "LapNumber", "LapTimeS", "PitOut", "TrackStatus", "Compound"]].copy()
    out["LapNumber"] -= 1
    s = laps[laps["PitIn"]].merge(out, on=["Driver", "LapNumber"], suffixes=("_in", "_out"))
    s = s[s["PitOut_out"]]

    s["PitLoss"] = s["LapTimeS_in"] + s["LapTimeS_out"] - s["LapNumber"].map(field_ref)
    s["RefCars"] = s["LapNumber"].map(ref_cars)
    s["Condition"] = (s["TrackStatus_in"] + s["TrackStatus_out"]).map(classify_status)

    s = s[
        (s["RefCars"] >= min_ref_cars)
        & s["PitLoss"].between(5, 60)          # drops drive-throughs, penalties, broken data
        & (s["Condition"] != "Red flag")       # red-flag stops are free
    ]
    return s.rename(columns={"Compound_in": "FromCompound", "Compound_out": "ToCompound"})[
        ["Driver", "LapNumber", "FromCompound", "ToCompound", "Condition", "PitLoss"]
    ].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Tyre degradation
# --------------------------------------------------------------------------- #
def clean_laps(laps: pd.DataFrame, slow_lap_cutoff: float = 1.03) -> pd.DataFrame:
    """Representative green-flag dry laps: no pit laps, no lap 1, no traffic/mistake outliers."""
    d = laps[
        laps["IsAccurate"]
        & ~laps["PitIn"]
        & ~laps["PitOut"]
        & (laps["TrackStatus"] == "1")
        & (laps["LapNumber"] > 1)
        & laps["Compound"].isin(DRY_COMPOUNDS)
        & laps["LapTimeS"].notna()
        & laps["TyreLife"].notna()
    ]
    stint_median = d.groupby(["Driver", "Stint"])["LapTimeS"].transform("median")
    return d[d["LapTimeS"] < stint_median * slow_lap_cutoff]


def fit_degradation(
    laps: pd.DataFrame, fuel_s_per_lap: float = 0.05, min_stint_laps: int = 5, plot_points: int = 4000
):
    """Linear degradation per compound.

    1. Fuel correction: the car gets lighter every lap, so add back fuel_s_per_lap * LapNumber.
    2. Degradation (s/lap): compare each driver only to themselves within one stint
       (lap time vs tyre age, both centred on the stint average), pooled across all stints.
       This removes car/driver pace differences.
    3. Compound pace offset: each stint's implied 'brand-new tyre' pace, relative to the
       race median, then the median over all races. Expressed relative to MEDIUM.

    Expects columns RaceId, Driver, Stint, Compound, TyreLife, LapNumber, LapTimeS.
    Returns (model, points) where model is indexed by compound.
    """
    key = ["RaceId", "Driver", "Stint"]
    d = laps.copy()
    d["y"] = d["LapTimeS"] + fuel_s_per_lap * d["LapNumber"]
    d = d[d.groupby(key)["y"].transform("size") >= min_stint_laps]
    if d.empty:
        return pd.DataFrame(columns=["DegPerLap", "PaceOffset", "Stints", "Laps"]), d

    g = d.groupby(key)
    dx = d["TyreLife"] - g["TyreLife"].transform("mean")
    dy = d["y"] - g["y"].transform("mean")
    sums = pd.DataFrame({"xy": dx * dy, "xx": dx**2, "Compound": d["Compound"]}).groupby("Compound").sum()
    slope = (sums["xy"] / sums["xx"].replace(0, np.nan)).dropna()

    d = d[d["Compound"].isin(slope.index)]
    d["fresh"] = d["y"] - d["Compound"].map(slope) * d["TyreLife"]   # implied pace at tyre age 0
    stints = d.groupby(key + ["Compound"], as_index=False)["fresh"].mean()
    stints["rel"] = stints["fresh"] - stints.groupby("RaceId")["fresh"].transform("median")

    model = pd.DataFrame(
        {
            "DegPerLap": slope,
            "PaceOffset": stints.groupby("Compound")["rel"].median(),
            "Stints": stints.groupby("Compound").size(),
            "Laps": d.groupby("Compound").size(),
        }
    ).reindex([c for c in DRY_COMPOUNDS if c in slope.index])
    ref = "MEDIUM" if "MEDIUM" in model.index else model["PaceOffset"].idxmin()
    model["PaceOffset"] -= model.loc[ref, "PaceOffset"]

    # Points for the chart: lap time relative to that stint's own fresh-tyre pace
    d["RelPace"] = d["y"] - d.groupby(key)["fresh"].transform("mean")
    pts = d[["Compound", "TyreLife", "RelPace"]]
    if len(pts) > plot_points:
        pts = pts.sample(plot_points, random_state=0)
    return model, pts.reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Pit or stay out?
# --------------------------------------------------------------------------- #
def pit_vs_stay(model: pd.DataFrame, current: str, age: int, new: str, laps_left: int, pit_loss: float):
    """Cumulative time gained by pitting now vs staying out, lap by lap to the flag.

    Stay out, lap i:  offset[current] + deg[current] * (age + i)
    Pit now,  lap i:  offset[new]     + deg[new] * i          (+ pit loss once)
    Fuel load is the same either way, so it cancels out.
    """
    i = np.arange(1, laps_left + 1)
    stay = model.at[current, "PaceOffset"] + model.at[current, "DegPerLap"] * (age + i)
    pit = model.at[new, "PaceOffset"] + model.at[new, "DegPerLap"] * i
    return pd.DataFrame({"LapsAhead": i, "CumulativeGain": np.cumsum(stay - pit) - pit_loss})