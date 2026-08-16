"""A5.2 execution-price and brokerage formulas (shared with A5.7).

These functions are the canonical cost math. SimulatedBroker and path-dependent
Monte Carlo must call them rather than duplicating P&L formulas.
"""

from __future__ import annotations

from app.backtesting.order_execution.orders import OrderSide


def execution_price(side: OrderSide, reference: float, slippage_bps: float) -> float:
    """Market fill price after configured slippage (A5.2)."""
    slip = float(reference) * (float(slippage_bps) / 10_000.0)
    if side is OrderSide.BUY:
        return float(reference) + slip
    return max(float(reference) - slip, 1e-12)


def brokerage_charge(notional: float, rate: float, flat: float = 0.0) -> float:
    """Brokerage on a fill notional (A5.2)."""
    return abs(float(notional)) * float(rate) + float(flat)


def quantity_from_budget(
    budget: float,
    exec_price: float,
    brokerage_rate: float,
    brokerage_flat: float = 0.0,
) -> float:
    """Shares affordable from a cash budget after estimated brokerage (A5.2)."""
    if budget <= 0 or exec_price <= 0:
        return 0.0
    effective = float(budget) / (1.0 + float(brokerage_rate)) - float(brokerage_flat)
    if effective <= 0:
        return 0.0
    return effective / float(exec_price)
