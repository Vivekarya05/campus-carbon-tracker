"""Data quality checks: completeness, timeliness, duplicates, unit/range, negatives, outliers.

Outputs data/processed/data_quality_log.csv, data/processed/data_quality_scores.csv and cleaned tables.
Every issue has a status: Corrected / Removed / Estimated / Late - included / Investigate.
"Estimated" and "Investigate" count as open issues (someone still has to act on them).
"""
import numpy as np
import pandas as pd

from .common import FYS, PROCESSED, RAW, REF, fy_of, months

OPEN_STATUSES = {"Estimated", "Investigate"}
VALIDITY_CHECKS = {"Duplicates", "Unit / range", "Negative values", "Outlier (rolling z-score)"}
Z_THRESHOLD = 4.0
MIN_REL_CHANGE = 0.3  # materiality floor: ignore statistically odd but small (<30%) moves


def issue(source, check, entity, period, records, detail, status, days_late=0):
    return dict(source=source, check=check, entity=entity, period=period, records=int(records),
                detail=detail, status=status, days_late=int(days_late))


def load_raw() -> dict:
    return {
        "electricity": pd.read_csv(RAW / "facilities_electricity_halfhourly.csv.gz", parse_dates=["interval_start"]),
        "gas": pd.read_csv(RAW / "facilities_gas_monthly.csv"),
        "refrigerants": pd.read_csv(RAW / "facilities_refrigerants.csv"),
        "fleet": pd.read_csv(RAW / "fleet_fuel_monthly.csv"),
        "renewables": pd.read_csv(RAW / "procurement_renewables.csv"),
        "flights": pd.read_csv(RAW / "travel_flights.csv"),
        "waste": pd.read_csv(RAW / "wastecontractor_waste_monthly.csv"),
        "buildings": pd.read_csv(RAW / "facilities_buildings.csv"),
    }


# ---------- individual checks (each returns a list of issue dicts) ----------

def check_duplicates(source, df, key, date_col):
    dup = df[df.duplicated(key, keep="first")]
    by_day = dup.groupby([dup[key[0]], pd.to_datetime(dup[date_col]).dt.strftime("%Y-%m-%d")]).size()
    return [issue(source, "Duplicates", e, day, n, f"{n} duplicate records for {e} on {day}; duplicates removed",
                  "Removed") for (e, day), n in by_day.items()]


def check_completeness(source, df, entity_col, expected_entities, period_col="month"):
    expected = pd.MultiIndex.from_product([list(expected_entities), months().strftime("%Y-%m")])
    got = pd.MultiIndex.from_frame(df[[entity_col, period_col]].astype(str))
    return [issue(source, "Completeness", e, p, 1, f"No {source} data received for {e} in {p}", "Estimated")
            for e, p in expected.difference(got)]


def check_timeliness(source, df, period_end: pd.Series, due_days: int):
    late_days = (pd.to_datetime(df.report_received_date) - (period_end + pd.Timedelta(days=due_days))).dt.days
    late = df.assign(days_late=late_days, period=period_end.dt.strftime("%Y-%m"))[late_days > 0]
    return [issue(source, "Timeliness", "report", p, len(g), f"Report for {p} arrived {g.days_late.max()} days "
                  f"after its due date ({due_days} days after period end)", "Late - included", g.days_late.max())
            for p, g in late.groupby("period")]


def check_negatives(source, df, value_col, date_col):
    neg = df[df[value_col] < 0]
    by_month = neg.groupby(pd.to_datetime(neg[date_col]).dt.strftime("%Y-%m")).size()
    return [issue(source, "Negative values", "all", m, n, f"{n} negative {value_col} values", "Investigate")
            for m, n in by_month.items()]


def check_electricity_range(df, buildings):
    """A half-hour reading above the building's max demand is physically impossible; ~1000x means Wh logged as kWh."""
    cap = df.building_id.map(buildings.set_index("building_id").max_demand_kw) * 0.5
    over = df[df.grid_import_kwh > cap]
    out = []
    for (b, m), g in over.groupby([over.building_id, over.interval_start.dt.strftime("%Y-%m")]):
        out.append(issue("electricity", "Unit / range", b, m, len(g),
                         f"{len(g)} half-hour readings above the {cap[g.index[0]] * 2:.0f} kW max demand "
                         f"(median {g.grid_import_kwh.median():,.0f}); looks like Wh recorded as kWh, divided by 1000",
                         "Corrected"))
    return out


def rolling_z(series: pd.Series, window: int) -> pd.Series:
    """Robust z-score of each point against the previous `window` points (median and MAD)."""
    med = series.shift(1).rolling(window, min_periods=window // 2).median()
    mad = (series.shift(1) - med).abs().rolling(window, min_periods=window // 2).median() * 1.4826
    return (series - med) / mad.replace(0, np.nan)


def check_outliers(source, series: pd.Series, entity, window, skip_periods=()):
    """Flag points far from their trailing median. Pass a series already free of known seasonality."""
    z = rolling_z(series, window)
    rel = (series / series.shift(1).rolling(window, min_periods=window // 2).median() - 1).abs()
    flagged = z[(z.abs() > Z_THRESHOLD) & (rel > MIN_REL_CHANGE) & ~z.index.isin(skip_periods)]
    return [issue(source, "Outlier (rolling z-score)", entity, str(p)[:10], 1,
                  f"{rel[p]:.0%} away from the trailing {window}-period median ({z[p]:+.1f} robust z-scores)",
                  "Investigate") for p in flagged.index]


def deseasonalise(monthly: pd.Series) -> pd.Series:
    """Divide each month by the average of the same calendar month across all years (index = 'YYYY-MM')."""
    return monthly / monthly.groupby(monthly.index.str[5:]).transform("mean")


def month_end(month_col: pd.Series) -> pd.Series:
    return pd.to_datetime(month_col) + pd.offsets.MonthEnd(0)


# ---------- run everything ----------

def validate(raw: dict, owners: pd.DataFrame):
    due = owners.set_index("source").due_days_after_period
    issues, clean = [], {}

    # electricity: duplicates -> range (and fix) -> outliers on each meter's share of the campus total
    e = raw["electricity"]
    issues += check_duplicates("electricity", e, ["building_id", "interval_start"], "interval_start")
    e = e.drop_duplicates(["building_id", "interval_start"]).copy()
    issues += check_negatives("electricity", e, "grid_import_kwh", "interval_start")
    range_issues = check_electricity_range(e, raw["buildings"])
    issues += range_issues
    for i in range_issues:
        bad = (e.building_id == i["entity"]) & (e.interval_start.dt.strftime("%Y-%m") == i["period"])
        e.loc[bad, "grid_import_kwh"] /= 1000
    daily = e.pivot_table(index=e.interval_start.dt.normalize(), columns="building_id",
                          values="grid_import_kwh", aggfunc="sum")
    share = daily.div(daily.sum(axis=1), axis=0)  # semester/weather swings cancel out; meter faults don't
    fixed = share.index[share.index.strftime("%Y-%m").isin({i["period"] for i in range_issues})]
    for b in share:
        issues += check_outliers("electricity", share[b], b, 28, skip_periods=fixed)
    clean["electricity"] = e

    # gas
    g = raw["gas"].copy()
    issues += check_duplicates("gas", g, ["building_id", "month"], "month")
    issues += check_negatives("gas", g, "gas_gj", "month")
    missing = check_completeness("gas", g, "building_id", raw["buildings"].building_id)
    issues += missing
    issues += check_timeliness("gas", g, month_end(g.month), due["gas"])
    for b, s in g.groupby("building_id"):
        issues += check_outliers("gas", deseasonalise(s.set_index("month").gas_gj), b, 12)
    g["estimated"] = False
    est = []
    for i in missing:  # estimate = average of the same calendar month in the other years (documented method)
        same = g[(g.building_id == i["entity"]) & (g.month.str[5:] == i["period"][5:])].gas_gj.mean()
        est.append(dict(building_id=i["entity"], month=i["period"], gas_gj=round(same, 1), unit="GJ", estimated=True))
        i["detail"] += f"; estimated at {same:,.1f} GJ from the same month in other years"
    clean["gas"] = pd.concat([g, pd.DataFrame(est)], ignore_index=True).sort_values(["building_id", "month"])

    # fleet
    f = raw["fleet"].copy()
    issues += check_duplicates("fleet", f, ["vehicle_id", "month"], "month")
    issues += check_negatives("fleet", f, "litres", "month")
    issues += check_completeness("fleet", f, "vehicle_id", sorted(f.vehicle_id.unique()))
    issues += check_timeliness("fleet", f, month_end(f.month), due["fleet"])
    for fuel, s in f.groupby("fuel_type"):
        issues += check_outliers("fleet", deseasonalise(s.groupby("month").litres.sum()), fuel, 12)
    clean["fleet"] = f

    # refrigerants (event-based: completeness cannot be tested from the data itself, see methodology)
    r = raw["refrigerants"].copy()
    issues += check_duplicates("refrigerants", r, ["event_date", "building_id", "equipment", "gas_type"], "event_date")
    issues += check_negatives("refrigerants", r, "kg_topped_up", "event_date")
    issues += check_timeliness("refrigerants", r, pd.to_datetime(r.event_date), due["refrigerants"])
    clean["refrigerants"] = r

    # renewables (annual)
    rn = raw["renewables"].copy()
    fy_end = pd.to_datetime((rn.fy.str[2:6].astype(int) + 1).astype(str) + "-06-30")
    issues += check_duplicates("renewables", rn.assign(fy_end=fy_end), ["fy", "instrument"], "fy_end")
    issues += check_negatives("renewables", rn.assign(fy_end=fy_end), "mwh", "fy_end")
    issues += check_timeliness("renewables", rn, fy_end, due["renewables"])
    clean["renewables"] = rn

    # flights (monthly booking report: every month should contain bookings)
    fl = raw["flights"].copy()
    fl["month"] = fl.departure_date.str[:7]
    issues += check_completeness("flights", fl.assign(entity="booking report"), "entity", ["booking report"])
    issues += check_timeliness("flights", fl, month_end(fl.month), due["flights"])
    clean["flights"] = fl

    # waste
    w = raw["waste"].copy()
    issues += check_duplicates("waste", w, ["stream", "month"], "month")
    issues += check_negatives("waste", w, "tonnes", "month")
    issues += check_completeness("waste", w, "stream", ["landfill", "recycling", "organics"])
    issues += check_timeliness("waste", w, month_end(w.month), due["waste"])
    for stream, s in w.groupby("stream"):
        issues += check_outliers("waste", deseasonalise(s.set_index("month").tonnes), stream, 12)
    clean["waste"] = w

    log = pd.DataFrame(issues, columns=list(issue("", "", "", "", 0, "", "").keys()))
    log["month"] = log.period.str[:7]
    log["fy"] = fy_of(pd.to_datetime(log.month)) if len(log) else []
    log["open"] = log.status.isin(OPEN_STATUSES)
    return log, clean, scores(raw, log, owners)


def scores(raw: dict, log: pd.DataFrame, owners: pd.DataFrame) -> pd.DataFrame:
    """0-100 score per source and FY, measured on reporting months:
    40% completeness (months with all data) + 30% validity (months with no validity issue)
    + 30% timeliness (months whose report arrived on time)."""
    rows = []
    for source in owners.source:
        for fy in FYS:
            lg = log[(log.source == source) & (log.fy == fy)]
            n_months = 12
            c = 1 - lg[lg.check == "Completeness"].month.nunique() / n_months
            v = 1 - lg[lg.check.isin(VALIDITY_CHECKS)].month.nunique() / n_months
            t = 1 - lg[lg.check == "Timeliness"].month.nunique() / n_months
            rows.append(dict(source=source, fy=fy, completeness_pct=round(100 * c, 1), validity_pct=round(100 * v, 1),
                             timeliness_pct=round(100 * t, 1), max_days_late=int(lg.days_late.max()) if len(lg) else 0,
                             issues=len(lg), open_issues=int(lg.open.sum()),
                             score=round(100 * (0.4 * c + 0.3 * v + 0.3 * t), 1),
                             status="Missing" if c < 1 else ("Check" if len(lg) else "Good")))
    return pd.DataFrame(rows).merge(owners[["source", "data_owner"]], on="source")


def main():
    owners = pd.read_csv(REF / "data_owners.csv")
    log, clean, sc = validate(load_raw(), owners)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    log.to_csv(PROCESSED / "data_quality_log.csv", index=False)
    sc.to_csv(PROCESSED / "data_quality_scores.csv", index=False)
    for name, df in clean.items():
        if name == "electricity":
            df.to_csv(PROCESSED / "electricity_halfhourly_clean.csv.gz", index=False,
                      compression={"method": "gzip", "mtime": 0})
        else:
            df.to_csv(PROCESSED / f"{name}_clean.csv", index=False)
    print(f"{len(log)} data quality issues logged; average score by FY: "
          f"{sc.groupby('fy').score.mean().round(1).to_dict()}")
    return log, clean, sc


if __name__ == "__main__":
    main()
