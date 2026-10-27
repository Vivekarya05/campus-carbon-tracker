"""Every deliberately injected data quality issue must be caught, and nothing else flagged on the clean data.
Run: python -m pytest   (or: python -m unittest)"""
import unittest

import pandas as pd

from pipeline import generate, validate
from pipeline.common import RAW, REF


def setUpModule():
    global LOG, CLEAN, SCORES, RAW_DATA
    if not (RAW / "facilities_electricity_halfhourly.csv.gz").exists():
        generate.main()
    RAW_DATA = validate.load_raw()
    LOG, CLEAN, SCORES = validate.validate(RAW_DATA, pd.read_csv(REF / "data_owners.csv"))


def found(source, check, entity, period):
    return LOG[(LOG.source == source) & (LOG.check == check) & (LOG.entity == entity) & (LOG.period == period)]


class InjectedIssues(unittest.TestCase):
    def test_missing_gas_months(self):
        for b, m in generate.GAS_MISSING:
            self.assertEqual(len(found("gas", "Completeness", b, m)), 1, (b, m))

    def test_missing_gas_months_are_estimated_not_dropped(self):
        g = CLEAN["gas"]
        for b, m in generate.GAS_MISSING:
            est = g[(g.building_id == b) & (g.month == m)]
            self.assertEqual(len(est), 1)
            self.assertTrue(bool(est.estimated.iloc[0]))
        self.assertEqual(len(g), 6 * 36)

    def test_duplicate_electricity_day(self):
        b, d = generate.DUPLICATE_DAY
        hit = found("electricity", "Duplicates", b, d)
        self.assertEqual(hit.records.sum(), 48)
        self.assertFalse(CLEAN["electricity"].duplicated(["building_id", "interval_start"]).any())

    def test_wh_unit_error(self):
        b, m = generate.WH_UNIT_ERROR
        hit = found("electricity", "Unit / range", b, m)
        self.assertEqual(len(hit), 1)
        e = CLEAN["electricity"]
        fixed = e[(e.building_id == b) & (e.interval_start.dt.strftime("%Y-%m") == m)].grid_import_kwh
        self.assertLess(fixed.max(), 720 / 2)  # back under the B05 max demand after dividing by 1000

    def test_late_waste_report(self):
        hit = found("waste", "Timeliness", "report", generate.LATE_WASTE_MONTH)
        self.assertEqual(len(hit), 1)
        self.assertEqual(int(hit.days_late.iloc[0]), 45)

    def test_no_false_positives(self):
        """Exactly the four injected problems (five log rows: two missing gas months) and nothing else."""
        self.assertEqual(len(LOG), 5, LOG[["source", "check", "entity", "period"]].to_string())

    def test_scores_and_status(self):
        s = SCORES.set_index(["source", "fy"])
        self.assertEqual(s.loc[("gas", "FY2024-25"), "status"], "Missing")
        self.assertEqual(s.loc[("gas", "FY2024-25"), "completeness_pct"], round(100 * 10 / 12, 1))
        self.assertEqual(s.loc[("waste", "FY2024-25"), "status"], "Check")
        self.assertEqual(s.loc[("fleet", "FY2024-25"), "status"], "Good")
        self.assertTrue(((SCORES.score >= 0) & (SCORES.score <= 100)).all())


class CheckFunctions(unittest.TestCase):
    def test_outlier_check_catches_a_1000x_spike(self):
        s = pd.Series([100.0 + i % 3 for i in range(40)], index=pd.date_range("2024-01-01", periods=40))
        s.iloc[30] *= 1000
        hits = validate.check_outliers("x", s, "meter", 28)
        self.assertEqual([h["period"] for h in hits], ["2024-01-31"])

    def test_outlier_check_ignores_small_moves(self):
        s = pd.Series([100.0, 101, 99, 100, 102, 98, 100, 101, 99, 100, 112, 100],
                      index=[f"2024-{m:02d}" for m in range(1, 13)])
        self.assertEqual(validate.check_outliers("x", s, "e", 6), [])

    def test_negative_values(self):
        df = pd.DataFrame({"month": ["2024-01", "2024-02"], "litres": [10.0, -5.0]})
        hits = validate.check_negatives("fleet", df, "litres", "month")
        self.assertEqual([(h["period"], h["records"]) for h in hits], [("2024-02", 1)])

    def test_timeliness_on_time_is_not_flagged(self):
        df = pd.DataFrame({"report_received_date": ["2024-02-10", "2024-03-30"]})
        ends = pd.to_datetime(pd.Series(["2024-01-31", "2024-02-29"]))
        hits = validate.check_timeliness("waste", df, ends, 15)
        self.assertEqual([(h["period"], h["days_late"]) for h in hits], [("2024-02", 15)])


if __name__ == "__main__":
    unittest.main()
