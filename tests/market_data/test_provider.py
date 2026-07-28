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
