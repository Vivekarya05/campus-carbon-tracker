"""Run the whole pipeline: python -m pipeline.run
generate -> validate -> calculate -> grid timing -> pathway -> export. Every dashboard number comes from here."""
import pandas as pd

from . import calculate, export, generate, scenarios, validate
from .common import FYS, PROCESSED, RAW, REF


def main():
    if not (REF / "factors.csv").exists():
        raise SystemExit("data/reference/factors.csv is missing. Build it from the NGA workbook: "
                         "python -m pipeline.factors (see README, 'Reference data').")
    generate.main()
    log, clean, scores = validate.main()
    inv, em = calculate.main(clean)
    factors_df = pd.read_csv(REF / "factors.csv")
    f = dict(zip(factors_df.factor_id, factors_df.value))

    grid = calculate.load_grid_intensity()
    if grid is not None:
        fy = FYS[-1]
        e = clean["electricity"]
        e_fy = e[(e.interval_start >= f"{fy[2:6]}-07-01") & (e.interval_start < f"{int(fy[2:6]) + 1}-07-01")]
        gt = calculate.grid_timing(e_fy, grid)
        grid_source = f"AEMO dispatch data for VIC1, {fy}, processed with the nemed package"
    else:
        gt, grid_source = None, "AEMO data unavailable: using the flat NGA Victorian Scope 2 factor instead"

    kwp = pd.read_csv(RAW / "facilities_buildings.csv").solar_kwp.sum()
    yield_kwh_per_kwp = em[em.fy == FYS[-1]].solar_kwh.sum() / kwp
    path = scenarios.pathway(inv, em, clean["renewables"], f.get("elec_market_residual", f["elec_vic_s2"]),
                             yield_kwh_per_kwp)
    pd.DataFrame(path["summary"]).to_csv(PROCESSED / "scenario_summary.csv", index=False)
    export.export_all(inv, em, clean, scores, log, path, gt, grid_source, factors_df)
    print("dashboard data written to docs/data/")


if __name__ == "__main__":
    main()
