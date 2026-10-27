"""Emissions calculations (t CO2-e) to the GHG Protocol Corporate Standard, using factors from data/reference/factors.csv.

Formula everywhere: activity data x emission factor = emissions.
Output: one long table, one row per month x building x source, with location-based and market-based totals.
Scope 2 is the only place the two methods differ; for every other row t_market == t_location.
"""
import numpy as np
import pandas as pd

from .common import FYS, PROCESSED, RAW, REF, fy_of

SHORT_HAUL_KM = 3700  # DESNZ boundary between short-haul and long-haul flights


def load_factors(path=REF / "factors.csv") -> dict:
    df = pd.read_csv(path)
    return dict(zip(df.factor_id, df.value))


def row(month, building, source, scope, category, activity, unit, t_loc, t_mkt=None):
    return dict(month=month, building_id=building, source=source, scope=scope, category=category,
                activity=activity, activity_unit=unit, t_location=t_loc, t_market=t_loc if t_mkt is None else t_mkt)


def renewable_coverage(elec_monthly: pd.DataFrame, renewables: pd.DataFrame) -> pd.Series:
    """Share of each FY's grid electricity covered by surrendered renewable instruments (capped at 100%)."""
    grid_mwh = elec_monthly.groupby("fy").grid_kwh.sum() / 1000
    bought = renewables.groupby("fy").mwh.sum().reindex(grid_mwh.index, fill_value=0)
    return (bought / grid_mwh).clip(upper=1.0)


def electricity(elec_monthly: pd.DataFrame, renewables: pd.DataFrame, f: dict) -> list:
    """Scope 2 location-based = grid kWh x state factor. Market-based = uncovered grid kWh x market factor.
    Scope 3 cat. 3 = grid kWh x state Scope 3 factor (transmission losses and upstream fuel extraction)."""
    cover = renewable_coverage(elec_monthly, renewables)
    market_ef = f.get("elec_market_residual", f["elec_vic_s2"])
    out = []
    for r in elec_monthly.itertuples():
        kwh = r.grid_kwh
        out.append(row(r.month, r.building_id, "Grid electricity", 2, "Scope 2", kwh, "kWh",
                       kwh * f["elec_vic_s2"] / 1000, kwh * (1 - cover[r.fy]) * market_ef / 1000))
        out.append(row(r.month, r.building_id, "Electricity & gas supply chain", 3, "Cat 3 Fuel- and energy-related",
                       kwh, "kWh", kwh * f["elec_vic_s3"] / 1000))
    return out


def gas(gas_monthly: pd.DataFrame, f: dict) -> list:
    out = []
    for r in gas_monthly.itertuples():
        out.append(row(r.month, r.building_id, "Natural gas", 1, "Stationary combustion", r.gas_gj, "GJ",
                       r.gas_gj * f["gas_s1"] / 1000))
        out.append(row(r.month, r.building_id, "Electricity & gas supply chain", 3, "Cat 3 Fuel- and energy-related",
                       r.gas_gj, "GJ", r.gas_gj * f["gas_vic_s3"] / 1000))
    return out


def fleet(fleet_df: pd.DataFrame, f: dict) -> list:
    """litres / 1000 x energy content (GJ/kL) x factor (kg CO2-e/GJ) / 1000 = t CO2-e."""
    m = fleet_df.groupby(["month", "fuel_type"]).litres.sum().reset_index()
    out = []
    for r in m.itertuples():
        gj = r.litres / 1000 * f[f"{r.fuel_type}_energy"]
        out.append(row(r.month, "Campus", "Fleet fuel", 1, "Transport combustion", r.litres, "L",
                       gj * f[f"{r.fuel_type}_s1"] / 1000))
        out.append(row(r.month, "Campus", "Electricity & gas supply chain", 3, "Cat 3 Fuel- and energy-related",
                       r.litres, "L", gj * f[f"{r.fuel_type}_s3"] / 1000))
    return out


def refrigerant_gwp(gas_type: str, f: dict) -> float:
    """R-410A is a 50/50 blend (by mass) of HFC-32 and HFC-125."""
    if gas_type == "R-410A":
        return 0.5 * f["gwp_HFC-32"] + 0.5 * f["gwp_HFC-125"]
    return f[f"gwp_{gas_type}"]


def refrigerants(ref: pd.DataFrame, f: dict) -> list:
    """Top-up (refill) method: refrigerant added to equipment is assumed to replace what leaked."""
    return [row(str(r.event_date)[:7], r.building_id, "Refrigerant leaks", 1, "Fugitive emissions", r.kg_topped_up,
                "kg", r.kg_topped_up * refrigerant_gwp(r.gas_type, f) / 1000) for r in ref.itertuples()]


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0 * np.arcsin(np.sqrt(a))


def flights(fl: pd.DataFrame, airports: pd.DataFrame, f: dict) -> list:
    """Great-circle km (x2 for returns) x DESNZ passenger-km factor (with radiative forcing) by haul and cabin."""
    ap = airports.set_index("airport")
    km = haversine_km(ap.lat[fl.origin].to_numpy(), ap.lon[fl.origin].to_numpy(),
                      ap.lat[fl.destination].to_numpy(), ap.lon[fl.destination].to_numpy())
    d = fl.assign(pkm=km * np.where(fl.return_trip, 2, 1),
                  haul=np.where(km < SHORT_HAUL_KM, "short", "long"))
    d["t"] = d.pkm * [f[f"flight_{h}_{c}"] for h, c in zip(d.haul, d.cabin_class)] / 1000
    m = d.groupby("month").agg(pkm=("pkm", "sum"), t=("t", "sum")).reset_index()
    return [row(r.month, "Campus", "Business flights", 3, "Cat 6 Business travel", r.pkm, "passenger-km", r.t)
            for r in m.itertuples()]


def waste(w: pd.DataFrame, f: dict) -> list:
    """Tonnes x waste factor by stream. Recycling and composting factors are only applied if listed in factors.csv
    (otherwise 0 under the recycled-content cut-off approach, see methodology)."""
    return [row(r.month, "Campus", "Waste", 3, "Cat 5 Waste", r.tonnes, "t",
                r.tonnes * f.get(f"waste_{r.stream}", 0.0)) for r in w.itertuples()]


def monthly_electricity(e: pd.DataFrame) -> pd.DataFrame:
    m = (e.assign(month=e.interval_start.dt.strftime("%Y-%m"))
           .groupby(["month", "building_id"])[["grid_import_kwh", "solar_generation_kwh"]].sum().reset_index()
           .rename(columns={"grid_import_kwh": "grid_kwh", "solar_generation_kwh": "solar_kwh"}))
    m["fy"] = fy_of(pd.to_datetime(m.month))
    return m


def inventory(clean: dict, f: dict, airports: pd.DataFrame):
    em = monthly_electricity(clean["electricity"])
    rows = (electricity(em, clean["renewables"], f) + gas(clean["gas"], f) + fleet(clean["fleet"], f)
            + refrigerants(clean["refrigerants"], f) + flights(clean["flights"], airports, f) + waste(clean["waste"], f))
    inv = pd.DataFrame(rows)
    inv["fy"] = fy_of(pd.to_datetime(inv.month))
    return inv, em


# ---------- grid timing: when is campus electricity dirtiest? ----------

def grid_timing(e: pd.DataFrame, grid: pd.DataFrame, shift_share=0.10, n_slots=6) -> dict:
    """Join half-hourly campus grid import to half-hourly VIC1 intensity (kg CO2-e/kWh).
    Load shifting: each day, move `shift_share` of the load in the day's `n_slots` dirtiest half-hours into its
    `n_slots` cleanest half-hours (same total kWh). Saving = shifted kWh x (dirty - clean intensity).
    Uses average (not marginal) grid intensity, so it is an indicator, not an inventory number."""
    load = e.groupby("interval_start").grid_import_kwh.sum().rename("kwh")
    j = grid.join(load, how="inner").dropna()
    j["day"] = j.index.normalize()
    j["kg"] = j.kwh * j.intensity_kg_per_kwh
    rank = j.groupby("day").intensity_kg_per_kwh.rank(method="first")
    n_day = j.groupby("day").intensity_kg_per_kwh.transform("size")
    dirty, clean = rank > n_day - n_slots, rank <= n_slots
    shifted = (j.kwh * shift_share).where(dirty, 0).groupby(j.day).sum()
    dirty_kg = (j.kwh * shift_share * j.intensity_kg_per_kwh).where(dirty, 0).groupby(j.day).sum()
    clean_int = j.intensity_kg_per_kwh.where(clean).groupby(j.day).mean()
    saved_t = float((dirty_kg - shifted * clean_int).sum() / 1000)

    j["hour"], j["month"] = j.index.hour, j.index.strftime("%Y-%m")
    by_hour = j.groupby("hour").agg(intensity=("intensity_kg_per_kwh", "mean"), kwh=("kwh", "sum"), kg=("kg", "sum"))
    by_hour["load_share"] = by_hour.kwh / by_hour.kwh.sum()
    by_hour["emissions_share"] = by_hour.kg / by_hour.kg.sum()
    heat = j.groupby(["month", "hour"]).intensity_kg_per_kwh.mean().unstack()
    return dict(heatmap=heat, by_hour=by_hour, saved_t=saved_t, shifted_mwh=float(shifted.sum() / 1000),
                timing_weighted_t=float(j.kg.sum() / 1000), kwh=float(j.kwh.sum()),
                annual_avg_intensity=float(j.kg.sum() / j.kwh.sum()))


def load_grid_intensity():
    """Real AEMO-derived VIC1 half-hourly intensity if present, else None (caller falls back to the NGA factor)."""
    p = REF / "aemo" / "vic1_intensity_halfhourly.csv"
    if not p.exists():
        return None
    g = pd.read_csv(p, parse_dates=["interval_start"]).set_index("interval_start")
    return g[g.energy_mwh > 0]


def main(clean=None):
    from .validate import load_raw, validate
    if clean is None:
        _, clean, _ = validate(load_raw(), pd.read_csv(REF / "data_owners.csv"))
    f = load_factors()
    inv, em = inventory(clean, f, pd.read_csv(RAW / "travel_airports.csv"))
    inv.to_csv(PROCESSED / "emissions_inventory.csv", index=False)
    em.to_csv(PROCESSED / "electricity_monthly.csv", index=False)
    print(inv.groupby(["fy", "scope"])[["t_location", "t_market"]].sum().round(0))
    return inv, em


if __name__ == "__main__":
    main()
