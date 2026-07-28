"""Tests for OHLCV schema normalization."""

from __future__ import annotations

from datetime import date

import pandas as pd

from app.market_data.utils.ohlcv_normalizer import assert_ohlcv_schema, normalize_ohlcv_frame
from app.market_data.validators.ohlcv_validator import OHLCVValidator
from tests.market_data.conftest import make_ohlcv_dataframe


def test_normalize_ohlcv_frame_casts_schema() -> None:
    raw = pd.DataFrame(
        {
            "date": [date(2024, 1, 2), "2024-01-01"],
            "open": [101, 100.0],
            "high": [106, 105.0],
            "low": [96, 95.0],
            "close": [103, 102.0],
            "adj_close": [103, 102.0],
            "volume": [1100.9, 1000.0],
        },
    )

    normalized = normalize_ohlcv_frame(raw)

    assert len(normalized) == 2
    assert normalized.iloc[0]["date"] == pd.Timestamp("2024-01-01")
    assert normalized.iloc[1]["date"] == pd.Timestamp("2024-01-02")
    assert_ohlcv_schema(normalized)


def test_normalize_ohlcv_frame_deduplicates_dates() -> None:
    raw = pd.DataFrame(
        {
            "date": [date(2024, 1, 1), date(2024, 1, 1)],
            "open": [100.0, 999.0],
            "high": [105.0, 999.0],
            "low": [95.0, 999.0],
            "close": [102.0, 999.0],
            "adj_close": [102.0, 999.0],
            "volume": [1000, 888],
        },
    )

    normalized = normalize_ohlcv_frame(raw)

    assert len(normalized) == 1
    assert normalized.iloc[0]["open"] == 999.0


def test_validator_accepts_normalized_frame() -> None:
    OHLCVValidator().validate(make_ohlcv_dataframe())
