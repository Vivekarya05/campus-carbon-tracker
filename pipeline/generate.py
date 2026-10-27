"""Generate SYNTHETIC campus activity data (fixed seed), one CSV per data owner, with injected data quality issues.

Nothing here is real campus data. Realism comes from simple physical drivers: a synthetic Melbourne-like
temperature series, a semester calendar, weekday/weekend occupancy and rooftop solar geometry.
"""
import numpy as np
import pandas as pd

from .common import END, RAW, START, months

SEED = 42

BUILDINGS = pd.DataFrame([
    # id, name, floor m2, base kW, occupancy kW, cooling kW/degC, heating kW/degC, solar kWp, gas base GJ/mo, gas GJ/HDD
    ("B01", "Learning Commons (Library)", 18000, 250, 450, 25, 8, 350, 380, 7),
    ("B02", "Engineering & Design", 22000, 350, 600, 30, 10, 0, 450, 9),
    ("B03", "Science & Health Labs", 16000, 600, 500, 30, 10, 0, 800, 11),
    ("B04", "Student Hub", 9000, 120, 300, 15, 5, 150, 220, 4),
    ("B05", "Administration", 7000, 80, 220, 12, 4, 0, 130, 4),
    ("B06", "Sports & Aquatic Centre", 6000, 250, 150, 8, 3, 0, 1300, 14),
], columns=["building_id", "name", "floor_area_m2", "base_kw", "occ_kw", "cool_kw", "heat_kw", "solar_kwp",
            "gas_base_gj", "gas_gj_per_hdd"])
BUILDINGS["max_demand_kw"] = ((BUILDINGS.base_kw + BUILDINGS.occ_kw + 15 * BUILDINGS.cool_kw) * 1.5).round(-1)

STUDENTS = {"FY2023-24": 24800, "FY2024-25": 25200, "FY2025-26": 25600}

# Injected data quality issues (the pipeline must find every one of these)
GAS_MISSING = [("B03", "2025-03"), ("B03", "2025-04")]
DUPLICATE_DAY = ("B02", "2024-09-12")
WH_UNIT_ERROR = ("B05", "2025-05")          # meter exported Wh but labelled kWh for a whole month
LATE_WASTE_MONTH = "2025-03"                # report arrives 45 days after its due date

AIRPORTS = {  # IATA: (lat, lon), real airport coordinates
    "MEL": (-37.673, 144.843), "SYD": (-33.946, 151.177), "BNE": (-27.384, 153.117), "CBR": (-35.307, 149.195),
    "ADL": (-34.945, 138.531), "PER": (-31.940, 115.967), "HBA": (-42.836, 147.510), "AKL": (-37.008, 174.792),
    "SIN": (1.364, 103.991), "HKG": (22.308, 113.918), "NRT": (35.772, 140.393), "LHR": (51.470, -0.454),
    "LAX": (33.942, -118.408), "DEL": (28.556, 77.100), "CDG": (49.010, 2.548), "YVR": (49.194, -123.184),
}
DEST_WEIGHTS = {"SYD": 30, "BNE": 10, "CBR": 10, "ADL": 8, "PER": 7, "HBA": 3, "AKL": 4, "SIN": 5, "HKG": 3,
                "NRT": 3, "LHR": 6, "LAX": 4, "DEL": 3, "CDG": 2, "YVR": 2}


def temperature(days: pd.DatetimeIndex, rng) -> np.ndarray:
    """Daily mean temperature (degC), Melbourne-like seasonality plus AR(1) weather noise."""
    doy = days.dayofyear.to_numpy()
    noise = np.zeros(len(days))
    for i in range(1, len(days)):
        noise[i] = 0.7 * noise[i - 1] + rng.normal(0, 1.6)
    return 15.5 + 5.5 * np.cos(2 * np.pi * (doy - 20) / 365) + noise


def occupancy_factor(day: pd.Timestamp) -> float:
    """Semester calendar: teaching = 1, exams ~0.85, breaks ~0.5, Christmas shutdown 0.1."""
    m, d = day.month, day.day
    if (m == 12 and d >= 24) or (m == 1 and d <= 2):
        return 0.1
    if m == 1 or (m == 2 and d < 26):
        return 0.4
    if m in (3, 4, 5) or m == 2:
        return 1.0
    if m == 6:
        return 0.85 if d <= 20 else 0.55
    if m == 7:
        return 0.55 if d < 22 else 1.0
    if m in (8, 9, 10):
        return 1.0
    if m == 11:
        return 0.85 if d <= 20 else 0.5
    return 0.5  # rest of December


def electricity(rng, daily_temp: pd.Series) -> pd.DataFrame:
    idx = pd.date_range(START, END, freq="30min", inclusive="left")
    day = idx.normalize()
    hour = idx.hour + idx.minute / 60
    doy = idx.dayofyear.to_numpy()
    weekday = idx.dayofweek < 5
    occ_day = pd.Series(day.unique()).map(occupancy_factor)
    occ_day.index = day.unique()
    occ = occ_day.reindex(day).to_numpy()
    # daytime occupancy shape: 7am-10pm on weekdays, lighter on weekends
    shape = np.clip(np.sin(np.pi * (hour - 7) / 15), 0, None) ** 0.7
    occ_profile = shape * np.where(weekday, occ, occ * 0.25)
    t_day = daily_temp.reindex(day).to_numpy()
    temp = t_day + 5 * np.sin(np.pi * (hour - 9) / 12) * (hour > 6)   # afternoon peak
    years = (idx - START).days.to_numpy() / 365.25
    efficiency = 1 - 0.02 * years                                       # 2%/yr energy efficiency trend
    # rooftop solar: clear-sky half-sine over the day length, seasonal amplitude, daily cloudiness
    daylen = 12.15 + 2.6 * np.cos(2 * np.pi * (doy - 355) / 365)
    sunrise = 12.33 - daylen / 2
    clear = np.clip(np.sin(np.pi * (hour + 0.25 - sunrise) / daylen), 0, None)
    amp = 0.78 + 0.22 * np.cos(2 * np.pi * (doy - 355) / 365)
    cloud_day = pd.Series(rng.beta(5, 2, len(day.unique())), index=day.unique())
    cloud = cloud_day.reindex(day).to_numpy()

    frames = []
    for b in BUILDINGS.itertuples():
        kw = (b.base_kw + b.occ_kw * occ_profile + b.cool_kw * np.clip(temp - 22, 0, None)
              + b.heat_kw * np.clip(16 - temp, 0, None) * shape)
        load = kw * 0.5 * efficiency * rng.lognormal(0, 0.05, len(idx))
        solar = b.solar_kwp * 0.8 * clear * amp * cloud * 0.5
        grid = np.clip(load - solar, 0, None)
        frames.append(pd.DataFrame({"building_id": b.building_id, "interval_start": idx,
                                    "grid_import_kwh": grid.round(2), "solar_generation_kwh": solar.round(2)}))
    df = pd.concat(frames, ignore_index=True)

    # injected issue: one meter reports Wh (x1000) for a month while still labelled kWh
    b, m = WH_UNIT_ERROR
    bad = (df.building_id == b) & (df.interval_start.dt.strftime("%Y-%m") == m)
    df.loc[bad, "grid_import_kwh"] = (df.loc[bad, "grid_import_kwh"] * 1000).round(0)
    # injected issue: one day of one meter delivered twice
    b, d = DUPLICATE_DAY
    dup = df[(df.building_id == b) & (df.interval_start.dt.strftime("%Y-%m-%d") == d)]
    df = pd.concat([df, dup], ignore_index=True).sort_values(["building_id", "interval_start"], kind="stable")
    df["unit"] = "kWh"
    return df


def received(rng, period_end: pd.Series, lo: int, hi: int) -> pd.Series:
    return (period_end + pd.to_timedelta(rng.integers(lo, hi, len(period_end)), unit="D")).dt.date


def gas(rng, hdd: pd.Series) -> pd.DataFrame:
    rows = []
    for b in BUILDINGS.itertuples():
        for m in months():
            gj = (b.gas_base_gj + b.gas_gj_per_hdd * hdd[m]) * rng.lognormal(0, 0.04)
            rows.append((b.building_id, m.strftime("%Y-%m"), round(gj, 1)))
    df = pd.DataFrame(rows, columns=["building_id", "month", "gas_gj"])
    df = df[~df[["building_id", "month"]].apply(tuple, axis=1).isin(GAS_MISSING)]
    month_end = pd.to_datetime(df.month) + pd.offsets.MonthEnd(0)
    df["report_received_date"] = received(rng, month_end, 8, 26)  # retailer bill, due 30 days after month end
    df["unit"] = "GJ"
    return df.reset_index(drop=True)


def fleet(rng) -> pd.DataFrame:
    rows = []
    for v in range(1, 16):
        fuel = "diesel" if v <= 6 else "petrol"
        base = 150 if fuel == "diesel" else 110
        for m in months():
            seasonal = 0.7 if m.month in (12, 1) else 1.0
            rows.append((f"V{v:02d}", fuel, m.strftime("%Y-%m"), round(base * seasonal * rng.lognormal(0, 0.15), 1)))
    df = pd.DataFrame(rows, columns=["vehicle_id", "fuel_type", "month", "litres"])
    df["report_received_date"] = received(rng, pd.to_datetime(df.month) + pd.offsets.MonthEnd(0), 3, 12)
    df["unit"] = "L"
    return df


def refrigerants(rng) -> pd.DataFrame:
    gases = [("HFC-134a", "Central chiller", 8, 40), ("R-410A", "Split system", 2, 12), ("HFC-32", "Split system", 1, 6)]
    rows = []
    for m in months():
        if rng.random() < 0.6:  # roughly 7 top-ups a year
            gas_type, equip, lo, hi = gases[rng.choice(3, p=[0.35, 0.45, 0.2])]
            day = m + pd.Timedelta(days=int(rng.integers(0, 27)))
            rows.append((day.date(), rng.choice(BUILDINGS.building_id), equip, gas_type, round(rng.uniform(lo, hi), 1)))
    df = pd.DataFrame(rows, columns=["event_date", "building_id", "equipment", "gas_type", "kg_topped_up"])
    df["report_received_date"] = received(rng, pd.to_datetime(df.event_date), 5, 25)
    df["unit"] = "kg"
    return df


def renewables() -> pd.DataFrame:
    return pd.DataFrame([
        ("FY2023-24", "GreenPower", 1500), ("FY2024-25", "GreenPower", 1500),
        ("FY2024-25", "LGCs voluntarily surrendered", 3000),
        ("FY2025-26", "GreenPower", 1500), ("FY2025-26", "PPA (LGCs surrendered)", 9000),
    ], columns=["fy", "instrument", "mwh"]).assign(
        report_received_date=lambda d: d.fy.str[2:6].astype(int).add(1).astype(str) + "-08-10", unit="MWh")


def flights(rng) -> pd.DataFrame:
    dests, w = list(DEST_WEIGHTS), np.array(list(DEST_WEIGHTS.values()), float)
    rows = []
    for m in months():
        occ = np.mean([occupancy_factor(m + pd.Timedelta(days=d)) for d in range(28)])
        n = rng.poisson(60 * (0.5 + occ) * (1 + 0.05 * (m.year - 2023)))
        for _ in range(n):
            dest = rng.choice(dests, p=w / w.sum())
            long = dest in ("LHR", "LAX", "DEL", "CDG", "YVR", "NRT", "HKG", "SIN")
            cls = "business" if rng.random() < (0.15 if long else 0.04) else "economy"
            day = m + pd.Timedelta(days=int(rng.integers(0, 27)))
            rows.append((day.date(), rng.choice(["Engineering", "Science", "Business", "Arts", "Admin"]),
                         "MEL", dest, cls, rng.random() < 0.9))
    df = pd.DataFrame(rows, columns=["departure_date", "department", "origin", "destination", "cabin_class", "return_trip"])
    df["report_received_date"] = received(rng, pd.to_datetime(df.departure_date) + pd.offsets.MonthEnd(0), 5, 18)
    return df


def waste(rng) -> pd.DataFrame:
    streams = {"landfill": (55, -0.03), "recycling": (28, 0.01), "organics": (12, 0.08)}
    rows = []
    for m in months():
        occ = np.mean([occupancy_factor(m + pd.Timedelta(days=d)) for d in range(28)])
        yrs = (m - START).days / 365.25
        for s, (base, trend) in streams.items():
            rows.append((m.strftime("%Y-%m"), s, round(base * (0.5 + 0.6 * occ) * (1 + trend) ** yrs
                                                          * rng.lognormal(0, 0.06), 2)))
    df = pd.DataFrame(rows, columns=["month", "stream", "tonnes"])
    month_end = pd.to_datetime(df.month) + pd.offsets.MonthEnd(0)
    df["report_received_date"] = received(rng, month_end, 4, 14)  # due 15 days after month end
    late = df.month == LATE_WASTE_MONTH
    df.loc[late, "report_received_date"] = (month_end[late] + pd.Timedelta(days=60)).dt.date
    df["unit"] = "t"
    return df


def main():
    rng = np.random.default_rng(SEED)
    RAW.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(START, END, freq="D", inclusive="left")
    daily_temp = pd.Series(temperature(days, rng), index=days)
    hdd = (18 - daily_temp).clip(lower=0).resample("MS").sum()

    BUILDINGS[["building_id", "name", "floor_area_m2", "solar_kwp", "max_demand_kw"]].to_csv(
        RAW / "facilities_buildings.csv", index=False)
    pd.DataFrame(STUDENTS.items(), columns=["fy", "students_headcount"]).to_csv(RAW / "facilities_campus_stats.csv", index=False)
    electricity(rng, daily_temp).to_csv(RAW / "facilities_electricity_halfhourly.csv.gz", index=False,
                                     compression={"method": "gzip", "mtime": 0})  # mtime 0 = byte-identical reruns
    gas(rng, hdd).to_csv(RAW / "facilities_gas_monthly.csv", index=False)
    refrigerants(rng).to_csv(RAW / "facilities_refrigerants.csv", index=False)
    fleet(rng).to_csv(RAW / "fleet_fuel_monthly.csv", index=False)
    renewables().to_csv(RAW / "procurement_renewables.csv", index=False)
    flights(rng).to_csv(RAW / "travel_flights.csv", index=False)
    waste(rng).to_csv(RAW / "wastecontractor_waste_monthly.csv", index=False)
    pd.DataFrame({"airport": list(AIRPORTS), "lat": [v[0] for v in AIRPORTS.values()],
                  "lon": [v[1] for v in AIRPORTS.values()]}).to_csv(RAW / "travel_airports.csv", index=False)
    print(f"synthetic raw data written to {RAW}")


if __name__ == "__main__":
    main()
