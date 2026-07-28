"""Abstract market data provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date

import pandas as pd

from app.market_data.schemas.company_metadata import CompanyMetadata


class MarketDataProvider(ABC):
    """Download market data and metadata without knowing storage details."""

    @abstractmethod
    def download_history(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        """Return OHLCV history as a clean DataFrame."""

    @abstractmethod
    def download_metadata(self, symbol: str) -> CompanyMetadata:
        """Return normalized company metadata for a symbol."""

    @abstractmethod
    def download_company_info(self, symbol: str) -> dict[str, object]:
        """Return raw provider company information for a symbol."""
