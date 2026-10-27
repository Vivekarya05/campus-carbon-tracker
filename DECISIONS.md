# Decisions

Choices made while building, so a reviewer can see what was assumed and why.

## Data and sources

1. **Reference data is downloaded by a GitHub Actions workflow** (`.github/workflows/fetch-reference-data.yml`).
   The build environment could not reach dcceew.gov.au or nemweb.com.au directly, so the official NGA Factors
   workbook, the UK DESNZ conversion factors and the AEMO dispatch data are fetched on GitHub's runners and committed
   to `data/reference/`. Anyone can rerun the workflow to refresh them.
2. **NGA Factors 2026** is the edition used (the latest DCCEEW publication at build time). The same factors are
   applied to all three years so year-on-year changes reflect activity, not factor updates. A real inventory would
   normally use the edition current for each reporting year; this is noted as a limitation.
3. **Grid intensity uses `nemed`** to rebuild half-hourly VIC1 emissions intensity from AEMO 5-minute dispatch data
   for FY2025-26 only (one year is enough for an hour-by-month heatmap and keeps the download manageable). It is
   intensity of generation located in Victoria; interconnector flows are not adjusted.
4. **Flights use UK DESNZ 2026 factors** (with radiative forcing), short-haul below 3,700 km and long-haul above,
   because the NGA Factors do not publish air travel factors. Great-circle distance is used as DESNZ instructs.
5. **Water is excluded**: neither the NGA Factors nor a cited Victorian water utility factor was used, and the brief
   said to exclude rather than guess.
6. **Recycling and organics count as zero** under the recycled-content cut-off approach unless the workbook gives a
   factor for that treatment.
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
    from grid kWh, pro rata across months and buildings, and counts the rest at the market factor in
    `factors.csv`. The Renewable Power Percentage is not modelled separately.
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
19. Dashboard: static HTML and Apache ECharts 5.5.1 from cdnjs (pinned exact version), no build step.
    Scope colours come from a categorical palette checked with a colour-vision-deficiency validator
    (Scope 1 orange, Scope 2 blue, Scope 3 aqua, all pairs separable in light and dark mode).
