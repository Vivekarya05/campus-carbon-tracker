"""Paths and campus constants shared by every pipeline step."""
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
REF = ROOT / "data" / "reference"
PROCESSED = ROOT / "data" / "processed"
DOCS_DATA = ROOT / "docs" / "data"

CAMPUS = "Kingsford Technical University"
FYS = ["FY2023-24", "FY2024-25", "FY2025-26"]
BASELINE_FY = "FY2023-24"
START, END = pd.Timestamp("2023-07-01"), pd.Timestamp("2026-07-01")  # end exclusive


def fy_of(ts) -> pd.Series:
    """Australian financial year label (July-June) for a datetime Series."""
    ts = pd.to_datetime(ts)
    start_year = ts.dt.year - (ts.dt.month < 7)
    return "FY" + start_year.astype(str) + "-" + ((start_year + 1) % 100).astype(str).str.zfill(2)


def months() -> pd.DatetimeIndex:
    return pd.date_range(START, END, freq="MS", inclusive="left")
