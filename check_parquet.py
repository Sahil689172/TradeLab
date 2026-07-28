"""Verify RELIANCE.parquet schema after bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.market_data.utils.ohlcv_normalizer import assert_ohlcv_schema

PARQUET_PATH = PROJECT_ROOT / "backend/data/ohlcv/RELIANCE.parquet"

df = pd.read_parquet(PARQUET_PATH)

print("Schema:")
print(df.dtypes)
print()
print("Head:")
print(df.head())
print()
print("Tail:")
print(df.tail())

assert_ohlcv_schema(df)
print()
print("Schema verification PASSED.")
