"""Illustrative Net Zero pathway for Scope 1 + Scope 2 (market-based).

Target (illustrative, not a real commitment): 50% below the FY2023-24 baseline by FY2029-30, net zero by FY2034-35.
Each abatement scenario starts from the latest actual year, ramps in linearly to full effect by FY2029-30 and then holds.
"""
import pandas as pd

GJ_TO_KWH = 1e6 / 3600          # 1 GJ = 277.78 kWh (exact unit conversion)
SOLAR_ADD_KWP = 1500            # new rooftop PV across remaining roofs
ELECTRIFY_SHARE = 0.8           # share of gas heating replaced by heat pumps
HEAT_PUMP_COP = 3.0             # seasonal coefficient of performance (assumption)
TARGET_YEAR, NET_ZERO_YEAR, TARGET_CUT = 2030, 2035, 0.5


def fy_year(fy: str) -> int:
    """'FY2025-26' -> 2026 (the year the financial year ends)."""
    return int(fy[2:6]) + 1


def components(inv: pd.DataFrame, em: pd.DataFrame, renewables: pd.DataFrame, fy: str) -> dict:
    i = inv[inv.fy == fy]
    return dict(
        gas_gj=i[i.source == "Natural gas"].activity.sum(),
        gas_t=i[i.source == "Natural gas"].t_market.sum(),
        other_s1_t=i[(i.scope == 1) & (i.source != "Natural gas")].t_market.sum(),
        grid_kwh=em[em.fy == fy].grid_kwh.sum(),
        solar_kwh=em[em.fy == fy].solar_kwh.sum(),
        renewable_kwh=renewables[renewables.fy == fy].mwh.sum() * 1000,
    )


def scope12(c: dict, market_ef: float, solar_kwh=0.0, electrify=0.0, full_ppa=False) -> float:
    """Scope 1 + market-based Scope 2 (t) for a year after the given abatement measures."""
    gas_t = c["gas_t"] * (1 - electrify)
    grid = c["grid_kwh"] - solar_kwh + c["gas_gj"] * electrify * GJ_TO_KWH / HEAT_PUMP_COP
    covered = grid if full_ppa else c["renewable_kwh"]
    return gas_t + c["other_s1_t"] + max(grid - covered, 0) * market_ef / 1000


def pathway(inv, em, renewables, market_ef, solar_yield_kwh_per_kwp) -> dict:
    s12 = inv[inv.scope.isin([1, 2])].groupby("fy").t_market.sum()
    fys = sorted(s12.index)
    baseline, last = s12[fys[0]], fys[-1]
    base_year, last_year = fy_year(fys[0]), fy_year(last)
    years = list(range(base_year, NET_ZERO_YEAR + 1))

    def target(y):
        if y <= TARGET_YEAR:
            return baseline * (1 - TARGET_CUT * (y - base_year) / (TARGET_YEAR - base_year))
        return baseline * (1 - TARGET_CUT) * (1 - (y - TARGET_YEAR) / (NET_ZERO_YEAR - TARGET_YEAR))

    c = components(inv, em, renewables, last)
    new_solar = SOLAR_ADD_KWP * solar_yield_kwh_per_kwp
    full = {
        "Business as usual": scope12(c, market_ef),
        "Rooftop solar expansion": scope12(c, market_ef, solar_kwh=new_solar),
        "Gas to heat pumps": scope12(c, market_ef, electrify=ELECTRIFY_SHARE),
        "100% renewable PPA": scope12(c, market_ef, full_ppa=True),
        "All three combined": scope12(c, market_ef, new_solar, ELECTRIFY_SHARE, True),
    }
    start = s12[last]

    def ramp(end_value, y):
        if y < last_year:
            return None
        k = min((y - last_year) / (TARGET_YEAR - last_year), 1.0)
        return start + (end_value - start) * k

    scen = {name: [None if y < last_year else round(ramp(v, y), 1) for y in years] for name, v in full.items()}
    tgt30 = target(TARGET_YEAR)
    summary = [dict(scenario=n, t_2030=round(v, 1), abated_vs_bau_t=round(full["Business as usual"] - v, 1),
                    gap_to_2030_target_t=round(max(v - tgt30, 0), 1), gap_to_net_zero_t=round(v, 1),
                    meets_2030=bool(v <= tgt30)) for n, v in full.items()]
    return dict(
        years=years,
        actual=[round(s12[f], 1) if f in s12 else None for f in [f"FY{y - 1}-{y % 100:02d}" for y in years]],
        target=[round(target(y), 1) for y in years],
        scenarios=scen, summary=summary, baseline=round(baseline, 1), target_2030=round(tgt30, 1),
        assumptions=dict(solar_add_kwp=SOLAR_ADD_KWP, solar_yield_kwh_per_kwp=round(solar_yield_kwh_per_kwp),
                         electrify_share=ELECTRIFY_SHARE, heat_pump_cop=HEAT_PUMP_COP, target_cut=TARGET_CUT,
                         target_year=TARGET_YEAR, net_zero_year=NET_ZERO_YEAR, from_fy=last),
    )
