"""Unit tests for the read-only indicator adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.feature_engine.feature_repository import FeatureRepository
from app.feature_engine.pipeline import FeaturePipeline
from app.indicator_adapter import (
    IndicatorAdapter,
    IndicatorNotFoundError,
    IndicatorSeries,
    IndicatorValidationError,
    MacdIndicator,
)
from tests.test_indicators import make_prices


@pytest.fixture
def features():
    return FeaturePipeline().transform(make_prices(220))


@pytest.fixture
def adapter(features) -> IndicatorAdapter:
    return IndicatorAdapter(features)


def test_indicator_rsi_alias(adapter: IndicatorAdapter) -> None:
    result = adapter.indicator("rsi")

    assert isinstance(result, IndicatorSeries)
    assert result.name == "rsi"
    assert result.column == "rsi_14"
    assert len(result.points) == 220
    assert result.latest is not None
    assert result.latest_value == pytest.approx(100.0)


def test_indicator_atr_alias(adapter: IndicatorAdapter) -> None:
    result = adapter.indicator("atr")

    assert isinstance(result, IndicatorSeries)
    assert result.column == "atr_14"
    assert result.latest_value is not None
    assert result.latest_value > 0


def test_indicator_ema_by_exact_column(adapter: IndicatorAdapter) -> None:
    # Feature engine ships ema_9/21/50/200 (not ema_20).
    result = adapter.indicator("ema_21")

    assert isinstance(result, IndicatorSeries)
    assert result.name == "ema_21"
    assert result.column == "ema_21"
    assert result.latest_value is not None


def test_indicator_ema_20_missing_raises_helpful_error(adapter: IndicatorAdapter) -> None:
    with pytest.raises(IndicatorNotFoundError, match="ema_20") as exc_info:
        adapter.indicator("ema_20")

    assert "ema_21" in str(exc_info.value) or "ema_9" in str(exc_info.value)


def test_indicator_macd_returns_bundle(adapter: IndicatorAdapter) -> None:
    result = adapter.indicator("macd")

    assert isinstance(result, MacdIndicator)
    assert result.kind.value == "MACD"
    assert result.line.column == "macd"
    assert result.signal.column == "macd_signal"
    assert result.histogram.column == "macd_histogram"
    assert len(result.line.points) == len(result.signal.points) == len(result.histogram.points)
    assert result.latest_line is not None
    assert result.latest_signal is not None
    assert result.latest_histogram is not None


def test_indicator_does_not_recalculate(features, adapter: IndicatorAdapter) -> None:
    rsi = adapter.indicator("rsi")
    expected = features["rsi_14"].iloc[-1]

    assert rsi.latest_value == pytest.approx(float(expected))
    assert adapter.indicator("macd").line.latest_value == pytest.approx(float(features["macd"].iloc[-1]))


def test_indicator_result_is_cached(adapter: IndicatorAdapter) -> None:
    first = adapter.indicator("rsi")
    second = adapter.indicator("rsi")

    assert first is second
    assert adapter.cache.stats()["indicator_hits"] >= 1
    assert adapter.cache.stats()["indicator_misses"] >= 1


def test_available_and_aliases(adapter: IndicatorAdapter) -> None:
    available = adapter.available()
    aliases = adapter.aliases()

    assert "rsi_14" in available
    assert "atr_14" in available
    assert "macd" in available
    assert aliases["rsi"] == "rsi_14"
    assert aliases["atr"] == "atr_14"


def test_bind_required_before_indicator() -> None:
    adapter = IndicatorAdapter()

    with pytest.raises(IndicatorValidationError, match="No feature data bound"):
        adapter.indicator("rsi")


def test_for_symbol_loads_and_caches_frame(tmp_path: Path, features) -> None:
    repository = FeatureRepository(tmp_path)
    repository.write("RELIANCE", features)
    cache_adapter = IndicatorAdapter(repository=repository)

    first = cache_adapter.for_symbol("RELIANCE.NS")
    rsi_a = first.indicator("rsi")
    second = cache_adapter.for_symbol("RELIANCE")
    rsi_b = second.indicator("rsi")

    assert rsi_a.latest_value == pytest.approx(rsi_b.latest_value)
    assert cache_adapter.cache.stats()["frame_hits"] >= 1
    assert cache_adapter.cache.stats()["frame_misses"] >= 1


def test_for_symbol_requires_repository(features) -> None:
    adapter = IndicatorAdapter(features)

    with pytest.raises(IndicatorValidationError, match="FeatureRepository"):
        adapter.for_symbol("RELIANCE")


def test_clear_cache(adapter: IndicatorAdapter) -> None:
    adapter.indicator("atr")
    assert adapter.cache.stats()["indicator_size"] >= 1

    adapter.clear_cache()

    assert adapter.cache.stats()["indicator_size"] == 0
    assert adapter.cache.stats()["indicator_hits"] == 0
