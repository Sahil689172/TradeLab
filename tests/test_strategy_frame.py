"""Tests for OHLCV + feature merge used by strategy runners."""

from __future__ import annotations

import pandas as pd
import pytest

from app.feature_engine.pipeline import FeaturePipeline
from app.feature_engine.strategy_frame import (
    features_include_ohlcv,
    merge_ohlcv_features,
)
from tests.test_indicators import make_prices


def test_pipeline_keeps_ohlcv() -> None:
    frame = FeaturePipeline().transform(make_prices(60))
    assert features_include_ohlcv(frame)
    assert "ema_20" in frame.columns


def test_merge_legacy_indicator_only_features() -> None:
    ohlcv = make_prices(40)
    # Simulate legacy feature files that only stored date + indicators
    legacy = FeaturePipeline().transform(ohlcv)[
        ["date", "ema_20", "ema_50", "atr_14", "rsi_14", "adx_14"]
    ]
    assert not features_include_ohlcv(legacy)
    merged = merge_ohlcv_features(ohlcv, legacy)
    assert features_include_ohlcv(merged)
    assert "ema_20" in merged.columns
    assert len(merged) == len(ohlcv)


def test_merge_rejects_empty_overlap() -> None:
    ohlcv = make_prices(10)
    other = make_prices(10)
    other["date"] = pd.date_range("2099-01-01", periods=10, freq="D")
    features = other[["date"]].copy()
    features["ema_20"] = 1.0
    with pytest.raises(ValueError, match="empty frame"):
        merge_ohlcv_features(ohlcv, features)
