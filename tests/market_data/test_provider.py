"""Tests for Yahoo Finance provider normalization using mocks."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.market_data.exceptions import ProviderError
from app.market_data.providers.yfinance_provider import YFinanceProvider


class _FakeTicker:
    def __init__(self, history_frame: pd.DataFrame, info: dict[str, object]) -> None:
        self._history_frame = history_frame
        self.info = info

    def history(self, **_: object) -> pd.DataFrame:
        return self._history_frame


def test_yfinance_provider_normalizes_history(monkeypatch) -> None:
    """Provider converts Yahoo Finance history columns into storage columns."""
    history = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
            "Open": [100.0, 101.0],
            "High": [105.0, 106.0],
            "Low": [95.0, 96.0],
            "Close": [102.0, 103.0],
            "Adj Close": [102.0, 103.0],
            "Volume": [1000.0, 1100.0],
        },
    )
    info = {
        "longName": "Reliance Industries Ltd",
        "sector": "Energy",
        "industry": "Oil & Gas",
        "exchange": "NSE",
        "currency": "INR",
        "marketCap": 123456.0,
    }
    monkeypatch.setattr(
        "app.market_data.providers.yfinance_provider.yf.Ticker",
        lambda _: _FakeTicker(history, info),
    )

    provider = YFinanceProvider()
    frame = provider.download_history("RELIANCE")

    assert list(frame.columns) == [
        "date",
        "open",
        "high",
        "low",
        "close",
        "adj_close",
        "volume",
    ]
    metadata = provider.download_metadata("RELIANCE")
    assert metadata.company_name == "Reliance Industries Ltd"


def test_yfinance_provider_rejects_empty_history(monkeypatch) -> None:
    """Empty history is treated as a provider failure."""
    monkeypatch.setattr(
        "app.market_data.providers.yfinance_provider.yf.Ticker",
        lambda _: _FakeTicker(pd.DataFrame(), {"longName": "Name", "exchange": "NSE"}),
    )

    provider = YFinanceProvider()
    with pytest.raises(ProviderError, match="No historical data"):
        provider.download_history("RELIANCE", start_date=date(2024, 1, 1))


def test_yfinance_provider_cleans_nan_rows_and_missing_adj_close(monkeypatch) -> None:
    """Provider drops unusable rows and fills optional fields before validation."""
    history = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "Open": [100.0, float("nan"), 101.0],
            "High": [105.0, 106.0, 106.0],
            "Low": [95.0, 96.0, 96.0],
            "Close": [102.0, 103.0, 103.0],
            "Volume": [1000.0, float("nan"), 1100.0],
        },
    )
    monkeypatch.setattr(
        "app.market_data.providers.yfinance_provider.yf.Ticker",
        lambda _: _FakeTicker(history, {"longName": "Reliance Industries Ltd", "exchange": "NSE"}),
    )

    provider = YFinanceProvider()
    frame = provider.download_history("RELIANCE.NS")

    assert len(frame) == 2
    assert frame["adj_close"].equals(frame["close"])
    assert frame["volume"].tolist() == [1000.0, 1100.0]


def test_yfinance_provider_metadata_fallback_for_nse_symbol(monkeypatch) -> None:
    """Metadata uses sensible defaults when Yahoo returns sparse info payloads."""
    monkeypatch.setattr(
        "app.market_data.providers.yfinance_provider.yf.Ticker",
        lambda _: _FakeTicker(pd.DataFrame(), {}),
    )

    provider = YFinanceProvider()
    metadata = provider.download_metadata("RELIANCE.NS")

    assert metadata.symbol == "RELIANCE.NS"
    assert metadata.company_name == "RELIANCE"
    assert metadata.exchange == "NSE"
    assert metadata.currency == "INR"


def test_metadata_failure_returns_partial_metadata(monkeypatch) -> None:
    """Metadata failure does not invalidate a confirmed price ticker."""

    class FailingMetadataTicker:
        @property
        def info(self):
            raise TimeoutError("metadata endpoint timed out")

    monkeypatch.setattr(
        "app.market_data.providers.yfinance_provider.yf.Ticker",
        lambda _: FailingMetadataTicker(),
    )

    metadata = YFinanceProvider().download_metadata("TATAMOTORS.NS")

    assert metadata.symbol == "TATAMOTORS.NS"
    assert metadata.company_name == "TATAMOTORS"
    assert metadata.exchange == "NSE"
    assert metadata.currency == "INR"
