"""Yahoo Finance provider for market data ingestion."""

from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.market_data.exceptions import ProviderError
from app.market_data.providers.base_provider import MarketDataProvider
from app.market_data.schemas.company_metadata import CompanyMetadata

logger = get_logger(__name__)


class YFinanceProvider(MarketDataProvider):
    """Download OHLCV history and metadata from Yahoo Finance."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def download_history(
        self,
        symbol: str,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        period: str | None = None,
    ) -> pd.DataFrame:
        """Return normalized daily OHLCV history for ``symbol``."""
        ticker = self._ticker(symbol)
        try:
            history = ticker.history(
                start=start_date.isoformat() if start_date else None,
                end=end_date.isoformat() if end_date else None,
                period=period,
                auto_adjust=False,
                actions=False,
                timeout=self._settings.yfinance_timeout_seconds,
            )
        except Exception as exc:
            logger.exception("Yahoo Finance history download failed for %s", symbol)
            raise ProviderError(f"Failed to download history for '{symbol}': {exc}") from exc

        if history is None or history.empty:
            raise ProviderError(f"No historical data returned for '{symbol}'")

        frame = history.reset_index().copy()
        date_column = "Date" if "Date" in frame.columns else frame.columns[0]
        frame["date"] = pd.to_datetime(frame[date_column]).dt.date
        frame = frame.rename(
            columns={
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Adj Close": "adj_close",
                "Volume": "volume",
            },
        )
        required = ["date", "open", "high", "low", "close", "adj_close", "volume"]
        missing = [column for column in required if column not in frame.columns]
        if missing:
            raise ProviderError(
                f"Corrupted historical response for '{symbol}'; missing columns: {missing}",
            )
        clean = frame[required].sort_values("date").reset_index(drop=True)
        logger.info("Downloaded %d rows of history for %s", len(clean), symbol)
        return clean

    def download_metadata(self, symbol: str) -> CompanyMetadata:
        """Return normalized company metadata for ``symbol``."""
        info = self.download_company_info(symbol)
        name = self._pick_string(info, "longName", "shortName", "displayName")
        exchange = self._pick_string(info, "exchange", "fullExchangeName")
        currency = self._pick_string(info, "currency") or "INR"
        if not name or not exchange:
            raise ProviderError(f"Incomplete metadata returned for '{symbol}'")

        market_cap = info.get("marketCap")
        market_cap_value = float(market_cap) if market_cap is not None else None
        return CompanyMetadata(
            symbol=symbol.strip().upper(),
            company_name=name,
            sector=self._pick_string(info, "sector"),
            industry=self._pick_string(info, "industry"),
            exchange=exchange,
            currency=currency,
            market_cap=market_cap_value,
            market_cap_date=date.today(),
            last_updated=datetime.now(timezone.utc),
        )

    def download_company_info(self, symbol: str) -> dict[str, object]:
        """Return raw company information from Yahoo Finance."""
        ticker = self._ticker(symbol)
        try:
            info = ticker.info
        except Exception as exc:
            logger.exception("Yahoo Finance metadata download failed for %s", symbol)
            raise ProviderError(f"Failed to download metadata for '{symbol}': {exc}") from exc

        if not info:
            raise ProviderError(f"No metadata returned for '{symbol}'")
        return info

    @staticmethod
    def _ticker(symbol: str) -> yf.Ticker:
        cleaned = symbol.strip().upper()
        if not cleaned:
            raise ProviderError("Symbol must not be empty")
        return yf.Ticker(cleaned)

    @staticmethod
    def _pick_string(data: dict[str, object], *keys: str) -> str | None:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None
