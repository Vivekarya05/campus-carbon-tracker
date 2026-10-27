"""Build half-hourly VIC1 grid emissions intensity for one month from AEMO data using `nemed`.

Usage: python scripts/fetch_vic1_intensity.py 2025-07 <month_offset 0-11> <out_dir>
Runs in GitHub Actions (see .github/workflows/fetch-reference-data.yml); needs internet access to nemweb.com.au.
"""
import sys
from pathlib import Path

import pandas as pd
from nemed import get_total_emissions

fy_start, offset, out = sys.argv[1], int(sys.argv[2]), Path(sys.argv[3])
start = pd.Timestamp(fy_start + "-01") + pd.DateOffset(months=offset)
end = start + pd.DateOffset(months=1)
cache = Path("nemed_cache")
cache.mkdir(exist_ok=True)
out.mkdir(parents=True, exist_ok=True)

# nemed returns 5-minute intervals labelled by interval END time (NEM time, AEST, no daylight saving).
df = get_total_emissions(
    start.strftime("%Y/%m/%d %H:%M:%S"), end.strftime("%Y/%m/%d %H:%M:%S"),
    str(cache), filter_regions=["VIC1"],
)
energy_col = [c for c in df.columns if "Energy" in c][0]
df["interval_start"] = (pd.to_datetime(df["TimeEnding"]) - pd.Timedelta(minutes=5)).dt.floor("30min")
hh = (df.groupby("interval_start")[[energy_col, "Total_Emissions"]].sum()
        .rename(columns={energy_col: "energy_mwh", "Total_Emissions": "emissions_t"}))
hh = hh[(hh.index >= start) & (hh.index < end)]
hh["intensity_kg_per_kwh"] = (hh["emissions_t"] / hh["energy_mwh"]).round(4)  # t/MWh == kg/kWh
hh.round(3).to_csv(out / f"vic1_{start:%Y_%m}.csv")
print(f"{start:%Y-%m}: {len(hh)} half-hours, mean intensity {hh['intensity_kg_per_kwh'].mean():.3f} kg/kWh")
