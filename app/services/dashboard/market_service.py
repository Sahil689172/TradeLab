"""Market data reads and refresh orchestration for the dashboard."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.market_data.utils.symbols import parquet_basename
from app.services.dashboard.schemas import OHLCVBar, OHLCVResponse, RefreshStatus
from app.services.dashboard.timeframes import get_timeframe, resample_ohlcv


class DashboardMarketService:
    """Read OHLCV from local storage and trigger provider refresh via gateway."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._last_refresh: datetime | None = None
        self._refresh_in_progress = False

    @property
    def last_refresh(self) -> datetime | None:
        return self._last_refresh

    @property
    refresh_in_progress(self) -> bool:
        return self._refresh_in_progress

    def normalize_symbol(self, symbol: str) -> str:
        base = parquet_basename(symbol).upper()
        return f"{base}.NS"

    def get_ohlcv(
        self,
        symbol: str,
        *,
        interval: str,
        gateway: MarketDataGateway,
        limit: int = 500,
    ) -> OHLCVResponse:
        spec = get_timeframe(interval)
        yahoo = self.normalize_symbol(symbol)
        if not spec.supported:
            return OHLCVResponse(
                symbol=parquet_basename(symbol).upper(),
                interval=spec.code,
                interval_label=spec.label,
                bars=[],
                message=spec.reason,
            )
        if not gateway.history_exists(yahoo):
            return OHLCVResponse(
                symbol=parquet_basename(symbol).upper(),
                interval=spec.code,
                interval_label=spec.label,
                bars=[],
                message="No local OHLCV history. Bootstrap or refresh this symbol first.",
            )
        frame = gateway.get_history(yahoo)
        frame = resample_ohlcv(frame, rule=spec.resample_rule)
        if limit > 0:
            frame = frame.tail(limit)
        bars = [_bar_from_row(row) for _, row in frame.iterrows()]
        last_ts = bars[-1].date if bars else None
        return OHLCVResponse(
            symbol=parquet_basename(symbol).upper(),
            interval=spec.code,
            interval_label=spec.label,
            bars=bars,
            delayed=True,
            last_bar_timestamp=last_ts,
            message="End-of-day Yahoo Finance history stored locally (not live tick data).",
        )

    def latest_close(self, symbol: str, *, gateway: MarketDataGateway) -> float | None:
        yahoo = self.normalize_symbol(symbol)
        if not gateway.history_exists(yahoo):
            return None
        frame = gateway.get_history(yahoo)
        if frame.empty:
            return None
        return float(frame.iloc[-1]["close"])

    def refresh_symbol(self, symbol: str, *, gateway: MarketDataGateway) -> RefreshStatus:
        if self._refresh_in_progress:
            return RefreshStatus(
                success=False,
                in_progress=True,
                message="Refresh already in progress",
                last_refresh=self._last_refresh,
            )
        self._refresh_in_progress = True
        try:
            yahoo = self.normalize_symbol(symbol)
            if gateway.history_exists(yahoo):
                result = gateway.update_symbol(yahoo)
            else:
                result = gateway.bootstrap_symbol(yahoo)
            self._last_refresh = datetime.now(timezone.utc)
            ok = result.status in {"downloaded", "updated", "up_to_date", "skipped"}
            return RefreshStatus(
                success=ok,
                message=result.message,
                last_refresh=self._last_refresh,
                symbols_updated=1 if ok else 0,
                symbols_failed=0 if ok else 1,
            )
        except Exception as exc:
            return RefreshStatus(
                success=False,
                message=str(exc),
                last_refresh=self._last_refresh,
                symbols_failed=1,
            )
        finally:
            self._refresh_in_progress = False

    def refresh_universe_sample(
        self,
        symbols: list[str],
        *,
        gateway: MarketDataGateway,
        max_symbols: int = 25,
    ) -> RefreshStatus:
        if self._refresh_in_progress:
            return RefreshStatus(
                success=False,
                in_progress=True,
                message="Refresh already in progress",
                last_refresh=self._last_refresh,
            )
        self._refresh_in_progress = True
        updated = failed = 0
        messages: list[str] = []
        try:
            for raw in symbols[:max_symbols]:
                yahoo = self.normalize_symbol(raw)
                try:
                    if gateway.history_exists(yahoo):
                        result = gateway.update_symbol(yahoo)
                    else:
                        result = gateway.bootstrap_symbol(yahoo)
                    if result.status in {"downloaded", "updated", "up_to_date", "skipped"}:
                        updated += 1
                    else:
                        failed += 1
                        messages.append(f"{yahoo}: {result.message}")
                except Exception as exc:
                    failed += 1
                    messages.append(f"{yahoo}: {exc}")
            self._last_refresh = datetime.now(timezone.utc)
            return RefreshStatus(
                success=failed == 0,
                message="; ".join(messages) if messages else f"Refreshed {updated} symbol(s)",
                last_refresh=self._last_refresh,
                symbols_updated=updated,
                symbols_failed=failed,
            )
        finally:
            self._refresh_in_progress = False


def _bar_from_row(row: pd.Series) -> OHLCVBar:
    ts = row["date"]
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    return OHLCVBar(
        date=ts,
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=float(row.get("volume", 0.0)),
        adj_close=float(row["adj_close"]) if "adj_close" in row and pd.notna(row["adj_close"]) else None,
    )


_market_service: DashboardMarketService | None = None


def get_market_service() -> DashboardMarketService:
    global _market_service
    if _market_service is None:
        _market_service = DashboardMarketService()
    return _market_service
