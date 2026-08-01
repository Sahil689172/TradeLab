"""Tests for feature pipeline composition."""

from __future__ import annotations

import pandas as pd
import pytest

from app.feature_engine.pipeline import FeaturePipeline
from tests.test_indicators import make_prices


def test_pipeline_outputs_all_feature_groups() -> None:
    result = FeaturePipeline().transform(make_prices())

    expected_columns = {
        "date",
        "ema_9",
        "ema_20",
        "ema_21",
        "ema_50",
        "ema_200",
        "sma_20",
        "sma_50",
        "sma_200",
        "macd",
        "macd_signal",
        "macd_histogram",
        "adx_14",
        "rsi_14",
        "roc_12",
        "momentum_10",
        "cci_20",
        "williams_r_14",
        "stochastic_k_14",
        "stochastic_d_3",
        "atr_14",
        "bollinger_middle_20",
        "bollinger_upper_20",
        "bollinger_lower_20",
        "bollinger_bandwidth_20",
        "historical_volatility_20",
        "obv",
        "money_flow_index_14",
        "volume_sma_20",
        "relative_volume_20",
        "daily_return",
        "log_return",
        "gap_pct",
        "high_low_pct",
        "open_close_pct",
        "body_pct",
        "upper_wick_pct",
        "lower_wick_pct",
    }
    assert set(result.columns) == expected_columns
    assert len(result) == 300
    assert result["date"].is_monotonic_increasing


def test_pipeline_normalizes_dates_and_duplicates() -> None:
    source = make_prices(rows=5)
    duplicate = source.iloc[[2]].copy()
    duplicate["close"] = 999.0
    shuffled = pd.concat([source.iloc[::-1], duplicate], ignore_index=True)

    result = FeaturePipeline().transform(shuffled)

    assert len(result) == 5
    assert result["date"].is_monotonic_increasing


def test_pipeline_rejects_missing_ohlcv_column() -> None:
    source = make_prices().drop(columns=["volume"])
    with pytest.raises(ValueError, match="Missing OHLCV columns"):
        FeaturePipeline().transform(source)
