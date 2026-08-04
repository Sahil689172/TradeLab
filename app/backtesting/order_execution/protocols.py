"""Protocols for Dependency Injection into order execution."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol, runtime_checkable

from app.backtesting.order_execution.orders import Fill, MarketOrder
from app.backtesting.order_execution.schemas import (
    AccountSnapshot,
    ClosedTradeRecord,
    FillLogEntry,
    TradeLogEntry,
)
from app.services.trade_recommendation.schemas import TradeRecommendation


@runtime_checkable
class BrokerPort(Protocol):
    """Simulated broker capable of filling market orders."""

    def submit_market_order(self, order: MarketOrder) -> Fill:
        """Fill or raise ``OrderRejectedError``."""

    def mark_to_market(self, prices: dict[str, float]) -> AccountSnapshot:
        """Refresh unrealized PnL from latest prices."""

    def snapshot(self) -> AccountSnapshot:
        ...

    @property
    def trade_log(self) -> list[TradeLogEntry]:
        ...

    @property
    def fill_log(self) -> list[FillLogEntry]:
        ...

    @property
    def closed_trades(self) -> list[ClosedTradeRecord]:
        ...


@runtime_checkable
class RecommendationExecutorPort(Protocol):
    """Map a TradeRecommendation + market price into broker activity."""

    def process(
        self,
        recommendation: TradeRecommendation,
        *,
        market_price: float,
        timestamp: datetime | None = None,
    ) -> object:
        ...
