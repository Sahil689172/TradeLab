"""Numerical tests for core technical indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.feature_engine.indicators.momentum import rsi
from app.feature_engine.indicators.price import compute_price_features
from app.feature_engine.indicators.trend import ema, macd
from app.feature_engine.indicators.volatility import atr


def make_prices(rows: int = 300) -> pd.DataFrame:
    close = pd.Series(np.arange(100.0, 100.0 + rows), dtype="float64")
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=rows),
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.5,
            "close": close,
            "adj_close": close,
            "volume": np.arange(1_000, 1_000 + rows, dtype="int64"),
        },
    )


def test_ema_matches_pandas_definition() -> None:
    close = make_prices()["close"]
    expected = close.ewm(span=9, adjust=False).mean()
    pd.testing.assert_series_equal(ema(close, 9), expected)


def test_rsi_is_100_for_persistent_gains() -> None:
    result = rsi(make_prices()["close"], 14)
    assert result.iloc[-1] == pytest.approx(100.0)


def test_atr_matches_constant_true_range() -> None:
    result = atr(make_prices(), 14)
    assert result.iloc[-1] == pytest.approx(2.5)


def test_macd_line_signal_and_histogram() -> None:
    close = make_prices()["close"]
    result = macd(close)
    expected_line = (
        close.ewm(span=12, adjust=False).mean()
        - close.ewm(span=26, adjust=False).mean()
    )
    expected_signal = expected_line.ewm(span=9, adjust=False).mean()

    assert result["macd"].iloc[-1] == pytest.approx(expected_line.iloc[-1])
    assert result["macd_signal"].iloc[-1] == pytest.approx(expected_signal.iloc[-1])
    assert result["macd_histogram"].iloc[-1] == pytest.approx(
        expected_line.iloc[-1] - expected_signal.iloc[-1],
    )


def test_return_calculations() -> None:
    data = make_prices(rows=3)
    result = compute_price_features(data)

    assert result["daily_return"].iloc[1] == pytest.approx(101 / 100 - 1)
    assert result["log_return"].iloc[1] == pytest.approx(np.log(101 / 100))
    assert result["gap_pct"].iloc[1] == pytest.approx(0.5)
