"""Portfolio capital allocation.

Policies compute a *requested* budget from current book state. Quantity is
then derived with A5.2 ``quantity_from_budget``. Orders are not silently
resized unless ``LimitAction.SCALE`` is configured.
"""

from __future__ import annotations

from app.backtesting.order_execution.costs import execution_price, quantity_from_budget
from app.backtesting.order_execution.orders import OrderSide
from app.backtesting.portfolio_risk.schemas import (
    AllocationPolicy,
    PortfolioRiskConfig,
    PortfolioTrade,
)


def target_budget(
    *,
    policy: AllocationPolicy,
    equity: float,
    cash: float,
    position_percent: float,
    max_position_pct: float,
    allocatable: float,
    simultaneous_count: int,
) -> float:
    """Requested rupee budget for one candidate entry.

    Caps from ``PortfolioRiskLimits`` are applied in ``limits.check_entry_limits``,
    not here, so a reject-mode book does not silently shrink the request.

    ``equal_risk`` is equal notional: completed trades do not carry stop
    distance, so true risk-parity would require fabricating ATR/stop data.
    """
    _ = (max_position_pct, allocatable)
    n = max(int(simultaneous_count), 1)
    if cash <= 0.0 or equity <= 0.0:
        return 0.0
    if policy is AllocationPolicy.EQUAL_CAPITAL or policy is AllocationPolicy.EQUAL_RISK:
        return min(float(cash), float(cash) / n)
    return min(float(cash), float(equity) * (float(position_percent) / 100.0))


def quantity_for_budget(
    budget: float,
    entry_price: float,
    config: PortfolioRiskConfig,
) -> float:
    if budget <= 0.0 or entry_price <= 0.0:
        return 0.0
    buy_px = execution_price(OrderSide.BUY, entry_price, config.slippage_bps)
    qty = quantity_from_budget(budget, buy_px, config.brokerage_rate, config.brokerage_flat)
    if not config.allow_fractional_shares:
        qty = float(int(qty))
    if qty < config.min_quantity:
        return 0.0
    return qty


def min_share_cost(entry_price: float, config: PortfolioRiskConfig) -> float:
    buy_px = execution_price(OrderSide.BUY, entry_price, config.slippage_bps)
    qty = max(config.min_quantity, 1.0 if not config.allow_fractional_shares else config.min_quantity)
    notional = buy_px * qty
    return notional * (1.0 + config.brokerage_rate) + config.brokerage_flat


def batch_size(trades: list[PortfolioTrade]) -> dict[datetime, int]:
    counts: dict[datetime, int] = {}
    for trade in trades:
        counts[trade.entry_timestamp] = counts.get(trade.entry_timestamp, 0) + 1
    return counts
