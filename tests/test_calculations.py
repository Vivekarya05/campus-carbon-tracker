"""Hand-checked calculation examples. The factor values here are round test numbers, NOT NGA factors,
so each expected answer can be worked out on paper."""
import unittest

import numpy as np
import pandas as pd

from pipeline import calculate as c
from pipeline import scenarios as s

F = {"elec_vic_s2": 0.8, "elec_vic_s3": 0.1, "gas_s1": 50.0, "gas_vic_s3": 10.0,
     "diesel_energy": 38.6, "diesel_s1": 70.0, "diesel_s3": 17.0, "petrol_energy": 34.2, "petrol_s1": 67.0,
     "petrol_s3": 16.0, "gwp_HFC-134a": 1300, "gwp_HFC-32": 675, "gwp_HFC-125": 3500,
     "waste_landfill": 1.5, "flight_short_economy": 0.2, "flight_short_business": 0.3,
     "flight_long_economy": 0.15, "flight_long_business": 0.45}


class Scope1(unittest.TestCase):
    def test_gas(self):
        rows = c.gas(pd.DataFrame({"month": ["2024-07"], "building_id": ["B01"], "gas_gj": [100.0]}), F)
        self.assertAlmostEqual(rows[0]["t_location"], 5.0)        # 100 GJ x 50 kg/GJ = 5,000 kg
        self.assertAlmostEqual(rows[1]["t_location"], 1.0)        # Scope 3: 100 x 10 = 1,000 kg

    def test_fleet_diesel(self):
        df = pd.DataFrame({"month": ["2024-07"], "fuel_type": ["diesel"], "litres": [1000.0]})
        rows = c.fleet(df, F)
        self.assertAlmostEqual(rows[0]["t_location"], 2.702)      # 1 kL x 38.6 GJ/kL x 70 kg/GJ = 2,702 kg
        self.assertAlmostEqual(rows[1]["t_location"], 0.6562)     # 38.6 GJ x 17 kg/GJ = 656.2 kg

    def test_refrigerant_blend(self):
        self.assertAlmostEqual(c.refrigerant_gwp("R-410A", F), 2087.5)  # (675 + 3500) / 2
        df = pd.DataFrame({"event_date": ["2024-08-01"], "building_id": ["B01"], "kg_topped_up": [10.0],
                           "gas_type": ["R-410A"]})
        self.assertAlmostEqual(c.refrigerants(df, F)[0]["t_location"], 20.875)


class Scope2(unittest.TestCase):
    def setUp(self):
        self.em = pd.DataFrame({"month": ["2024-07", "2024-08"], "building_id": ["B01", "B01"],
                                "grid_kwh": [10_000.0, 30_000.0], "fy": ["FY2024-25"] * 2})

    def test_location_based(self):
        rows = c.electricity(self.em, pd.DataFrame({"fy": [], "mwh": []}), F)
        self.assertAlmostEqual(rows[0]["t_location"], 8.0)        # 10,000 kWh x 0.8 kg/kWh = 8 t
        self.assertAlmostEqual(rows[0]["t_market"], 8.0)          # nothing bought -> same as location

    def test_market_based_nets_off_renewables(self):
        ren = pd.DataFrame({"fy": ["FY2024-25"], "mwh": [10.0]})  # covers 10 of 40 MWh = 25%
        rows = c.electricity(self.em, ren, F)
        self.assertAlmostEqual(rows[0]["t_market"], 6.0)          # 8 t x 75%
        self.assertAlmostEqual(rows[2]["t_market"], 18.0)         # 24 t x 75%
        self.assertAlmostEqual(rows[1]["t_location"], 1.0)        # Scope 3 cat 3 unaffected: 10,000 x 0.1

    def test_market_based_never_negative(self):
        ren = pd.DataFrame({"fy": ["FY2024-25"], "mwh": [999.0]})
        self.assertEqual(c.renewable_coverage(self.em, ren).iloc[0], 1.0)
        self.assertAlmostEqual(c.electricity(self.em, ren, F)[0]["t_market"], 0.0)


class Scope3(unittest.TestCase):
    def test_haversine_mel_syd(self):
        km = c.haversine_km(-37.673, 144.843, -33.946, 151.177)
        self.assertAlmostEqual(float(km), 705, delta=5)            # published MEL-SYD great-circle ~705 km

    def test_flights(self):
        ap = pd.DataFrame({"airport": ["A", "B"], "lat": [0.0, 0.0], "lon": [0.0, 1.0]})
        fl = pd.DataFrame({"month": ["2024-07"], "origin": ["A"], "destination": ["B"],
                           "cabin_class": ["economy"], "return_trip": [True]})
        km = 2 * np.pi * 6371 / 360                                # 1 degree of longitude on the equator
        r = c.flights(fl, ap, F)[0]
        self.assertAlmostEqual(r["activity"], 2 * km, places=3)
        self.assertAlmostEqual(r["t_location"], 2 * km * 0.2 / 1000, places=6)

    def test_waste_streams(self):
        w = pd.DataFrame({"month": ["2024-07"] * 2, "stream": ["landfill", "recycling"], "tonnes": [10.0, 4.0]})
        rows = c.waste(w, F)
        self.assertAlmostEqual(rows[0]["t_location"], 15.0)
        self.assertEqual(rows[1]["t_location"], 0.0)               # no factor listed -> cut-off approach


class GridTiming(unittest.TestCase):
    def test_load_shift_saving(self):
        idx = pd.date_range("2025-07-01", periods=48, freq="30min")
        intensity = np.where(np.arange(48) < 6, 1.0, np.where(np.arange(48) >= 42, 0.2, 0.5))
        grid = pd.DataFrame({"intensity_kg_per_kwh": intensity}, index=idx)
        e = pd.DataFrame({"interval_start": idx, "grid_import_kwh": 100.0})
        r = c.grid_timing(e, grid, shift_share=0.1, n_slots=6)
        # 6 dirty slots x 100 kWh x 10% = 60 kWh moved from 1.0 to 0.2 kg/kWh -> 48 kg
        self.assertAlmostEqual(r["saved_t"], 0.048)
        self.assertAlmostEqual(r["shifted_mwh"], 0.06)


class Pathway(unittest.TestCase):
    def test_scope12_measures(self):
        comp = dict(gas_gj=1000.0, gas_t=50.0, other_s1_t=10.0, grid_kwh=100_000.0, renewable_kwh=20_000.0,
                    solar_kwh=0.0)
        self.assertAlmostEqual(s.scope12(comp, 0.8), 50 + 10 + 64)             # 80,000 kWh uncovered x 0.8
        self.assertAlmostEqual(s.scope12(comp, 0.8, full_ppa=True), 60)
        self.assertAlmostEqual(s.scope12(comp, 0.8, solar_kwh=30_000), 60 + 40)
        # 80% of 1,000 GJ to heat pumps (COP 3): +74,074 kWh electricity, -40 t gas
        hp = s.scope12(comp, 0.8, electrify=0.8)
        self.assertAlmostEqual(hp, 10 + 10 + (80_000 + 800 * 277.777_78 / 3) * 0.8 / 1000, places=3)

    def test_fy_year(self):
        self.assertEqual(s.fy_year("FY2023-24"), 2024)


if __name__ == "__main__":
    unittest.main()
