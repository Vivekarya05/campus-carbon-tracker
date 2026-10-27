# Decisions

Choices made while building, so a reviewer can see what was assumed and why.

## Data and sources

1. **Emission factors were transcribed, not downloaded.** dcceew.gov.au refused automated downloads (from this
   build environment and from GitHub's runners, where the request hung), and its robots rules block web fetching.
   So NGA 2026 values were transcribed from the emiz.com.au library of the NGA 2026 workbook, with the Victorian
   electricity factors cross-checked against a second source citing NGA 2026 Table 1; diesel and petrol energy
   contents come from the official NGA July 2017 PDF (Table 4), unchanged since. Every row of `factors.csv` records
   where it came from and what to verify. Swap in the official workbook values when available: no code changes.
   No official website is contacted by the pipeline.
2. **NGA Factors 2026** is the edition used (the latest DCCEEW publication at build time). The same factors are
   applied to all three years so year-on-year changes reflect activity, not factor updates. A real inventory would
   normally use the edition current for each reporting year; this is noted as a limitation.
3. **Grid timing falls back to the flat NGA Victorian factor.** Half-hourly AEMO data was not downloaded (by
   choice, no official websites were contacted), so, as the brief specifies, every half-hour uses the NGA
   Victorian Scope 2 factor and the dashboard says so. The code is ready for real data: drop a CSV at
   `data/reference/aemo/vic1_intensity_halfhourly.csv` (columns `interval_start, energy_mwh, emissions_t,
   intensity_kg_per_kwh`, e.g. built with the `nemed` package) and rerun `python -m pipeline.run`; the heatmap and
   load-shifting estimate then appear automatically.
4. **Flights use UK DESNZ 2026 factors** (with radiative forcing), short-haul below 3,700 km and long-haul above,
   because the NGA Factors do not publish air travel factors. Great-circle distance is used as DESNZ instructs.
5. **Water is excluded**: neither the NGA Factors nor a cited Victorian water utility factor was used, and the brief
   said to exclude rather than guess.
6. **Waste factors**: landfill uses the NGA commercial and industrial waste stream factor (a university is a C&I
   generator, not a household); organics use the NGA composting factor; recycling counts as zero under the
   recycled-content cut-off approach.
7. **R-410A GWP** = mean of the HFC-32 and HFC-125 GWPs listed in the NGA Factors (it is a 50/50 blend by mass).

## Synthetic data

8. Fixed seed (42). Half-hourly electricity is built from a synthetic Melbourne-like temperature series, a
   semester calendar, weekday/weekend occupancy, a 2%/year efficiency trend and rooftop solar on two buildings.
9. Electricity is stored gzipped (`*.csv.gz`, written with `mtime=0` so reruns are byte-identical) to keep the
   repo small; pandas reads it directly.
10. Four injected data quality issues: B03 gas missing for March and April 2025, B02 electricity duplicated on
    12 September 2024, B05 recorded in Wh for May 2025, and the March 2025 waste report arriving 45 days late.

## Method

11. **Market-based Scope 2** deducts GreenPower and voluntarily surrendered LGCs (including PPA certificates)
    from grid kWh, pro rata across months and buildings, and counts the rest at the NGA national residual mix
    factor (0.79), which is higher than the Victorian location-based factor (0.74) because renewables already
    claimed elsewhere are removed from the mix. The Renewable Power Percentage is not modelled separately.
12. **Missing gas months are estimated** (mean of the same calendar month in the other years) and stay open
    issues until real bills arrive. The Wh error is corrected (divide by 1,000) because the evidence is unambiguous.
13. **Outlier detection** uses a robust rolling z-score on deseasonalised series (monthly series divided by their
    calendar-month mean; each electricity meter as a share of the campus daily total), plus a 30% materiality
    floor. Without this, every semester start and winter heating month was flagged.
14. **Data quality score** is measured on reporting months, not records, so one bad month counts as 1/12 of a
    year rather than being diluted by 17,520 half-hours.
15. **Targets are illustrative** (50% below FY2023-24 by 2030, net zero by 2035) and cover Scope 1 and
    market-based Scope 2, which is how most Australian universities frame operational targets.
16. **Scenario assumptions**: +1,500 kWp solar at the campus's own modelled yield; 80% of gas to heat pumps at
    COP 3.0; PPA covering all remaining grid electricity. Each ramps in linearly to 2030.
17. **Load shifting** uses average intensity and moves 10% of the load in each day's six dirtiest half-hours into
    its six cleanest; it is an indicator, not part of the inventory.

## Tooling

18. Tests use `unittest` so they run with no extra install (`python -m unittest`); `pytest` also discovers them.
19. Dashboard: static HTML and Apache ECharts 5.5.1 from jsDelivr (pinned exact version with a subresource-integrity hash, checked against the
    file in the official apache/echarts 5.5.1 release; cdnjs does not host 5.5.1), no build step.
    Scope colours come from a categorical palette checked with a colour-vision-deficiency validator
    (Scope 1 orange, Scope 2 blue, Scope 3 aqua, all pairs separable in light and dark mode).
