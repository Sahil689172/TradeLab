"""Tests for feature persistence, caching, and incremental updates."""

from __future__ import annotations

import pandas as pd

from app.feature_engine.cache import FeatureCache
from app.feature_engine.feature_engine import FeatureEngine
from app.feature_engine.feature_repository import FeatureRepository
from tests.test_indicators import make_prices


class InMemoryMarketData:
    def __init__(self, data: pd.DataFrame) -> None:
        self.data = data

    def get_history(self, symbol: str) -> pd.DataFrame:
        return self.data.copy()


def test_feature_repository_uses_expected_filename(tmp_path) -> None:
    repository = FeatureRepository(tmp_path)
    path = repository.write(
        "RELIANCE.NS",
        pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=2),
                "ema_9": [100.0, 101.0],
            },
        ),
    )

    assert path.name == "RELIANCE_features.parquet"
    assert repository.read("RELIANCE.NS")["date"].dtype == "datetime64[ns]"


def test_feature_engine_uses_cache_when_source_is_unchanged(tmp_path) -> None:
    market_data = InMemoryMarketData(make_prices(220))
    engine = FeatureEngine(
        market_data,
        FeatureRepository(tmp_path),
        FeatureCache(tmp_path),
    )

    first = engine.generate("RELIANCE.NS")
    second = engine.generate("RELIANCE.NS")

    assert first.status == "generated"
    assert first.feature_rows == 220
    assert second.status == "cached"
    assert second.cache_hit is True
    assert second.rows_added == 0


def test_feature_engine_appends_new_source_dates(tmp_path) -> None:
    market_data = InMemoryMarketData(make_prices(220))
    repository = FeatureRepository(tmp_path)
    engine = FeatureEngine(market_data, repository, FeatureCache(tmp_path))
    engine.generate("RELIANCE.NS")

    market_data.data = make_prices(223)
    result = engine.generate("RELIANCE.NS")
    stored = repository.read("RELIANCE.NS")

    assert result.status == "updated"
    assert result.rows_added == 3
    assert len(stored) == 223
    assert stored["date"].duplicated().sum() == 0


def test_feature_engine_rebuilds_revised_history(tmp_path) -> None:
    market_data = InMemoryMarketData(make_prices(220))
    repository = FeatureRepository(tmp_path)
    engine = FeatureEngine(market_data, repository, FeatureCache(tmp_path))
    engine.generate("RELIANCE.NS")

    revised = make_prices(220)
    revised.loc[100, "close"] += 10
    market_data.data = revised
    result = engine.generate("RELIANCE.NS")

    assert result.status == "generated"
    assert result.rows_added == 220
