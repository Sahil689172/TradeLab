"""Walk-forward accounting model and invariants.

TradeLab A5.2 accounting (discovered from SimulatedBroker):

- ``entry_price`` / ``exit_price``: slippage-adjusted execution prices
  (``execution_price()``), not raw reference closes.
- ``gross_profit``: ``(exit_price - entry_price) × quantity`` at those
  execution prices.
- ``brokerage``: round-trip entry + exit brokerage.
- ``slippage``: explicit slippage attribution vs reference prices on entry
  and exit. Execution prices already embed slippage in cash flows.
- ``net_profit``: ``gross_profit - brokerage - slippage`` (trade-ledger P&L).

Broker ``equity`` is ``cash + mark-to-market(positions)`` using cash flows at
execution prices. For a fully closed book:

    broker_equity_change ≈ Σ(gross_profit - brokerage)
                         = Σ(net_profit) + Σ(slippage)

Canonical walk-forward equity uses the **trade ledger** (one source of truth
with ``ClosedTradeRecord.net_profit``):

    equity = initial_capital + Σ realized net_profit

Never subtract slippage twice on the ledger path.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.backtesting.order_execution.schemas import ClosedTradeRecord

ACCOUNTING_MODEL = "trade_ledger_net_profit"
SHARPE_METHODOLOGY = "canonical_equity_step_returns"
SORTINO_METHODOLOGY = "canonical_equity_step_returns"
DEFAULT_ACCOUNTING_TOLERANCE = 1e-4

ACCOUNTING_NOTE = (
    "Canonical equity follows the trade ledger: each exit adds net_profit "
    "(gross - brokerage - slippage). Broker snapshots can differ by Σ(slippage) "
    "because execution prices embed slippage while net_profit also deducts it "
    "explicitly."
)


def sum_net_profit(trades: Sequence[ClosedTradeRecord]) -> float:
    return float(sum(float(t.net_profit) for t in trades))


def sum_gross_profit(trades: Sequence[ClosedTradeRecord]) -> float:
    return float(sum(float(t.gross_profit) for t in trades))


def sum_brokerage(trades: Sequence[ClosedTradeRecord]) -> float:
    return float(sum(float(t.brokerage) for t in trades))


def sum_slippage(trades: Sequence[ClosedTradeRecord]) -> float:
    return float(sum(float(t.slippage) for t in trades))


def ledger_final_equity(initial: float, trades: Sequence[ClosedTradeRecord]) -> float:
    return float(initial) + sum_net_profit(trades)


def broker_equivalent_from_ledger(trades: Sequence[ClosedTradeRecord], initial: float) -> float:
    """Cash-style equity change (gross - brokerage only); differs from ledger by slippage."""
    return float(initial) + sum_gross_profit(trades) - sum_brokerage(trades)


def assert_ledger_invariant(
    *,
    initial: float,
    trades: Sequence[ClosedTradeRecord],
    final_equity: float,
    tolerance: float = DEFAULT_ACCOUNTING_TOLERANCE,
) -> None:
    expected = ledger_final_equity(initial, trades)
    delta = abs(float(final_equity) - expected)
    if delta > tolerance:
        slip = sum_slippage(trades)
        raise AssertionError(
            "ledger accounting invariant failed: "
            f"final_equity={final_equity}, "
            f"initial + sum(net_profit)={expected}, "
            f"delta={delta}, sum(slippage)={slip}",
        )


def assert_costs_not_double_counted(trades: Sequence[ClosedTradeRecord], tolerance: float = 1e-4) -> None:
    for trade in trades:
        assert_trade_ledger_identity(trade, tolerance=tolerance)


def assert_trade_ledger_identity(
    trade: ClosedTradeRecord,
    *,
    tolerance: float = DEFAULT_ACCOUNTING_TOLERANCE,
) -> None:
    """Verify gross at execution prices and net deducts brokerage/slippage exactly once."""
    gross_at_exec = (float(trade.exit_price) - float(trade.entry_price)) * float(trade.quantity)
    if abs(gross_at_exec - float(trade.gross_profit)) > tolerance:
        raise AssertionError(
            f"gross_profit mismatch on {trade.symbol}: "
            f"(exit-entry)*qty={gross_at_exec}, gross_profit={trade.gross_profit}",
        )
    recomputed = float(trade.gross_profit) - float(trade.brokerage) - float(trade.slippage)
    if abs(recomputed - float(trade.net_profit)) > tolerance:
        raise AssertionError(
            f"net_profit mismatch on {trade.symbol}: "
            f"gross-brokerage-slippage={recomputed}, net_profit={trade.net_profit}",
        )
