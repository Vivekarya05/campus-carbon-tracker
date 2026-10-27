"""Export compact JSON files for the dashboard (docs/data/). The dashboard only reads these files."""
import json

import pandas as pd

from .common import BASELINE_FY, CAMPUS, DOCS_DATA, FYS, RAW, REF

SCOPE_KEYS = {1: "s1", 3: "s3"}


def _r(x, n=1):
    return None if x is None or pd.isna(x) else round(float(x), n)


def summary(inv, em, renewables, scores, buildings, students, pathway) -> dict:
    out = {}
    base = inv[inv.fy == BASELINE_FY]
    base_total = base.t_market.sum()
    base_s12 = base[base.scope.isin([1, 2])].t_market.sum()
    required_cut = base_s12 - pathway["target_2030"]
    for fy in FYS:
        i = inv[inv.fy == fy]
        e = em[em.fy == fy]
        s12 = i[i.scope.isin([1, 2])].t_market.sum()
        total = i.t_market.sum()
        consumption = e.grid_kwh.sum() + e.solar_kwh.sum()
        renewable_kwh = min(renewables[renewables.fy == fy].mwh.sum() * 1000, e.grid_kwh.sum()) + e.solar_kwh.sum()
        months = sorted(i.month.unique())
        by_month = i.pivot_table(index="month", columns="scope", values=["t_location", "t_market"], aggfunc="sum")
        src = (i.groupby("source")[["t_market", "t_location"]].sum().sort_values("t_market", ascending=False))
        bld = (i[(i.building_id != "Campus") & i.scope.isin([1, 2])].groupby("building_id").t_location.sum().to_frame("t")
                 .join(buildings.set_index("building_id")[["name", "floor_area_m2"]]))
        bld["kg_per_m2"] = bld.t * 1000 / bld.floor_area_m2
        bld = bld.sort_values("kg_per_m2", ascending=False)
        sc = scores[scores.fy == fy]
        out[fy] = dict(
            kpis=dict(
                total_t=_r(total, 0), total_location_t=_r(i.t_location.sum(), 0),
                change_vs_baseline_pct=_r(100 * (total / base_total - 1)),
                scope12_t=_r(s12, 0), progress_to_2030_pct=_r(100 * (base_s12 - s12) / required_cut),
                per_student_kg=_r(total * 1000 / students[fy], 0), students=int(students[fy]),
                renewable_share_pct=_r(100 * renewable_kwh / consumption),
                dq_score=_r(sc.score.mean()),
            ),
            monthly=dict(
                months=months,
                s1=[_r(by_month.loc[m, ("t_market", 1)]) for m in months],
                s2_market=[_r(by_month.loc[m, ("t_market", 2)]) for m in months],
                s2_location=[_r(by_month.loc[m, ("t_location", 2)]) for m in months],
                s3=[_r(by_month.loc[m, ("t_market", 3)]) for m in months],
            ),
            scope_totals=dict(
                market={k: _r(v) for k, v in i.groupby("scope").t_market.sum().rename(lambda s: f"s{s}").items()},
                location={k: _r(v) for k, v in i.groupby("scope").t_location.sum().rename(lambda s: f"s{s}").items()},
            ),
            sources=[dict(source=s, scope=int(i[i.source == s].scope.iloc[0]), t=_r(r.t_market),
                          t_location=_r(r.t_location)) for s, r in src.iterrows()],
            buildings=[dict(id=b, name=r["name"], t=_r(r.t), floor_area_m2=int(r.floor_area_m2),
                            kg_per_m2=_r(r.kg_per_m2)) for b, r in bld.iterrows()],
            energy=dict(grid_mwh=_r(e.grid_kwh.sum() / 1000, 0), solar_mwh=_r(e.solar_kwh.sum() / 1000, 0),
                        renewable_purchased_mwh=_r(renewables[renewables.fy == fy].mwh.sum(), 0)),
        )
    return out


def grid_json(gt: dict | None, grid_source: str, nga_ef: float) -> dict:
    if gt is None:
        return dict(source=grid_source, available=False, fallback_intensity=nga_ef)
    heat = gt["heatmap"]
    bh = gt["by_hour"]
    return dict(
        source=grid_source, available=True, months=list(heat.index), hours=list(range(24)),
        values=[[_r(heat.loc[m, h], 3) for h in range(24)] for m in heat.index],
        by_hour=[dict(hour=int(h), intensity=_r(r.intensity, 3), load_share=_r(100 * r.load_share, 2),
                      emissions_share=_r(100 * r.emissions_share, 2)) for h, r in bh.iterrows()],
        cleanest_hour=int(bh.intensity.idxmin()), dirtiest_hour=int(bh.intensity.idxmax()),
        cleanest_intensity=_r(bh.intensity.min(), 3), dirtiest_intensity=_r(bh.intensity.max(), 3),
        load_shift_saved_t=_r(gt["saved_t"]), load_shift_mwh=_r(gt["shifted_mwh"]),
        timing_weighted_t=_r(gt["timing_weighted_t"], 0), campus_grid_mwh=_r(gt["kwh"] / 1000, 0),
        avg_intensity=_r(gt["annual_avg_intensity"], 3), nga_factor=nga_ef,
    )


def health_json(scores, log, owners) -> dict:
    own = owners.set_index("source")
    out = {}
    for fy in FYS:
        rows = []
        for r in scores[scores.fy == fy].itertuples():
            lg = log[(log.source == r.source) & (log.fy == fy)]
            rows.append(dict(source=r.source, owner=own.data_owner[r.source], role=own.owner_role[r.source],
                             frequency=own.frequency[r.source], completeness_pct=r.completeness_pct,
                             days_late=r.max_days_late, issues=r.issues, open_issues=r.open_issues,
                             score=r.score, status=r.status,
                             flagged=[dict(check=x.check, period=x.period, entity=x.entity, detail=x.detail,
                                           status=x.status) for x in lg.itertuples()]))
        out[fy] = rows
    return out


def write(name, obj):
    DOCS_DATA.mkdir(parents=True, exist_ok=True)
    with open(DOCS_DATA / name, "w") as fh:
        json.dump(obj, fh, separators=(",", ":"), allow_nan=False)


def export_all(inv, em, clean, scores, log, pathway, gt, grid_source, factors_df):
    owners = pd.read_csv(REF / "data_owners.csv")
    buildings = pd.read_csv(RAW / "facilities_buildings.csv")
    students = pd.read_csv(RAW / "facilities_campus_stats.csv").set_index("fy").students_headcount
    f = dict(zip(factors_df.factor_id, factors_df.value))
    write("summary.json", dict(
        campus=CAMPUS, fys=FYS, baseline_fy=BASELINE_FY, synthetic=True,
        factor_sources=sorted(factors_df.source_publication.unique()),
        by_fy=summary(inv, em, clean["renewables"], scores, buildings, students, pathway)))
    write("pathway.json", pathway)
    write("grid.json", grid_json(gt, grid_source, f["elec_vic_s2"]))
    write("data_health.json", health_json(scores, log, owners))
    write("factors.json", factors_df.where(factors_df.notna(), None).to_dict(orient="records"))
    write("governance.json", {name: pd.read_csv(REF / f"{name}.csv").fillna("").to_dict(orient="records")
                              for name in ("data_owners", "data_dictionary", "evidence_register")})
