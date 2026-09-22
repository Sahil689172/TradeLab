"""Stock universe listing for the dashboard."""

from __future__ import annotations

import csv
import time
from functools import lru_cache
from pathlib import Path

from app.core.config import Settings, get_settings
from app.market_data.schemas.company_metadata import CompanyMetadata
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.market_data.universe.nifty500 import DEFAULT_SYMBOLS_FILE
from app.market_data.utils.symbols import parquet_basename
from app.services.dashboard.schemas import StockSummary

# How long (seconds) the per-symbol price/metadata cache stays warm.
# Keeps /stocks fast on repeated loads while still reflecting refreshes.
_PRICE_CACHE_TTL = 60.0


@lru_cache(maxsize=1)
def _load_csv_candidates(symbols_file: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    with symbols_file.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = str(row.get("Symbol", "")).strip().upper()
            name = str(row.get("Company Name", "")).strip()
            if symbol and name:
                rows.append((symbol, name))
    return rows


class _PriceEntry:
    """One cached price snapshot for a single yahoo symbol."""

    __slots__ = ("last_price", "daily_change_pct", "history_available",
                 "last_data_date", "sector", "industry", "company_name",
                 "fetched_at")

    def __init__(
        self,
        *,
        last_price: float | None,
        daily_change_pct: float | None,
        history_available: bool,
        last_data_date: object,
        sector: str | None,
        industry: str | None,
        company_name: str,
        fetched_at: float,
    ) -> None:
        self.last_price = last_price
        self.daily_change_pct = daily_change_pct
        self.history_available = history_available
        self.last_data_date = last_data_date
        self.sector = sector
        self.industry = industry
        self.company_name = company_name
        self.fetched_at = fetched_at


# Process-wide cache: yahoo_symbol → _PriceEntry
_price_cache: dict[str, _PriceEntry] = {}


def invalidate_price_cache(yahoo_symbol: str | None = None) -> None:
    """Force cache invalidation after a market-data refresh.

    Call with a specific yahoo_symbol to drop one entry, or with None to
    clear everything (e.g. after a bulk bootstrap).
    """
    if yahoo_symbol is None:
        _price_cache.clear()
    else:
        _price_cache.pop(yahoo_symbol, None)


class UniverseService:
    """Expose the NIFTY 500 universe with optional live metadata enrichment."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._symbols_file = DEFAULT_SYMBOLS_FILE

    def list_stocks(
        self,
        *,
        gateway: MarketDataGateway | None = None,
        query: str = "",
        holdings: set[str] | None = None,
        watchlist: set[str] | None = None,
        favorites: set[str] | None = None,
        limit: int = 501,
    ) -> list[StockSummary]:
        holdings = holdings or set()
        watchlist = watchlist or set()
        favorites = favorites or set()
        needle = query.strip().upper()
        out: list[StockSummary] = []
        for symbol, company_name in _load_csv_candidates(self._symbols_file):
            yahoo = f"{symbol}.NS"
            if needle and needle not in symbol and needle not in company_name.upper():
                continue
            summary = self._build_summary(
                symbol,
                yahoo,
                company_name,
                gateway=gateway,
                holdings=holdings,
                watchlist=watchlist,
                favorites=favorites,
            )
            out.append(summary)
            if len(out) >= limit:
                break
        return out

    def get_stock(
        self,
        symbol: str,
        *,
        gateway: MarketDataGateway | None = None,
        favorites: set[str] | None = None,
    ) -> StockSummary | None:
        base = parquet_basename(symbol).upper()
        for csv_symbol, company_name in _load_csv_candidates(self._symbols_file):
            if csv_symbol == base:
                yahoo = f"{csv_symbol}.NS"
                return self._build_summary(
                    csv_symbol,
                    yahoo,
                    company_name,
                    gateway=gateway,
                    favorites=favorites,
                )
        return None

    def count(self) -> int:
        return len(_load_csv_candidates(self._symbols_file))

    def _fetch_price_data(
        self,
        yahoo_symbol: str,
        company_name: str,
        gateway: MarketDataGateway,
    ) -> _PriceEntry:
        """Read price / metadata from the gateway and cache the result.

        Subsequent calls within _PRICE_CACHE_TTL return the cached entry
        without touching the filesystem, eliminating the N×Parquet reads
        that previously happened on every /stocks request.
        """
        now = time.monotonic()
        cached = _price_cache.get(yahoo_symbol)
        if cached is not None and (now - cached.fetched_at) < _PRICE_CACHE_TTL:
            return cached

        last_price: float | None = None
        daily_change_pct: float | None = None
        history_available = False
        last_data_date = None
        sector: str | None = None
        industry: str | None = None

        try:
            metadata: CompanyMetadata | None = gateway.get_metadata(yahoo_symbol)
            history_available = gateway.history_exists(yahoo_symbol)
            if history_available:
                frame = gateway.get_history(yahoo_symbol)
                if len(frame) >= 2:
                    last_row = frame.iloc[-1]
                    prev_row = frame.iloc[-2]
                    last_price = float(last_row["close"])
                    prev_close = float(prev_row["close"])
                    if prev_close:
                        daily_change_pct = (last_price - prev_close) / prev_close
                    last_data_date = (
                        last_row["date"].to_pydatetime()
                        if hasattr(last_row["date"], "to_pydatetime")
                        else last_row["date"]
                    )
                elif len(frame) == 1:
                    last_price = float(frame.iloc[-1]["close"])
                    last_data_date = frame.iloc[-1]["date"]
        except Exception:  # noqa: BLE001 — best-effort, never crash the listing
            metadata = None

        if metadata is not None:
            company_name = metadata.company_name or company_name
            sector = metadata.sector
            industry = metadata.industry

        entry = _PriceEntry(
            last_price=last_price,
            daily_change_pct=daily_change_pct,
            history_available=history_available,
            last_data_date=last_data_date,
            sector=sector,
            industry=industry,
            company_name=company_name,
            fetched_at=now,
        )
        _price_cache[yahoo_symbol] = entry
        return entry

    def _build_summary(
        self,
        symbol: str,
        yahoo_symbol: str,
        company_name: str,
        *,
        gateway: MarketDataGateway | None,
        holdings: set[str] | None = None,
        watchlist: set[str] | None = None,
        favorites: set[str] | None = None,
    ) -> StockSummary:
        holdings = holdings or set()
        watchlist = watchlist or set()
        favorites = favorites or set()

        last_price: float | None = None
        daily_change_pct: float | None = None
        history_available = False
        last_data_date = None
        sector: str | None = None
        industry: str | None = None

        if gateway is not None:
            entry = self._fetch_price_data(yahoo_symbol, company_name, gateway)
            last_price = entry.last_price
            daily_change_pct = entry.daily_change_pct
            history_available = entry.history_available
            last_data_date = entry.last_data_date
            sector = entry.sector
            industry = entry.industry
            company_name = entry.company_name

        return StockSummary(
            symbol=symbol,
            yahoo_symbol=yahoo_symbol,
            company_name=company_name,
            sector=sector,
            industry=industry,
            last_price=last_price,
            daily_change_pct=daily_change_pct,
            history_available=history_available,
            last_data_date=last_data_date,
            is_holding=symbol in holdings,
            is_watchlist=symbol in watchlist,
            is_favorite=symbol in favorites,
        )


def get_universe_service(settings: Settings | None = None) -> UniverseService:
    return UniverseService(settings)
