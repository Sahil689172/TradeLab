"""Validate Monte Carlo inputs. Reject NaN/inf before they contaminate paths."""

from __future__ import annotations

import math
from collections.abc import Sequence

from app.backtesting.monte_carlo.exceptions import MonteCarloConfigError, MonteCarloDataError
from app.backtesting.monte_carlo.schemas import CapitalMode, MonteCarloConfig, MonteCarloTrade


def validate_config(config: MonteCarloConfig) -> None:
    if config.simulations <= 0:
        raise MonteCarloConfigError("simulations must be > 0")
    if config.initial_capital <= 0:
        raise MonteCarloConfigError("initial_capital must be > 0")
    if config.ruin_threshold <= 0:
        raise MonteCarloConfigError("ruin_threshold must be > 0")
    if not math.isfinite(config.initial_capital):
        raise MonteCarloConfigError("initial_capital must be finite")
    if config.block_size < 1:
        raise MonteCarloConfigError("block_size must be >= 1")


def validate_trades(
    trades: Sequence[MonteCarloTrade],
    *,
    capital_mode: CapitalMode,
) -> None:
    if capital_mode not in (
        CapitalMode.ADDITIVE_PNL,
        CapitalMode.RETURN_BASED,
        CapitalMode.PATH_DEPENDENT_EQUITY,
    ):
        raise MonteCarloConfigError(f"unsupported capital_mode: {capital_mode}")
    for index, trade in enumerate(trades):
        if not math.isfinite(trade.pnl):
            raise MonteCarloDataError(f"trade[{index}] pnl is not finite: {trade.pnl!r}")
        if not math.isfinite(trade.return_pct):
            raise MonteCarloDataError(
                f"trade[{index}] return_pct is not finite: {trade.return_pct!r}",
            )
        if not math.isfinite(trade.gross_pnl):
            raise MonteCarloDataError(f"trade[{index}] gross_pnl is not finite")


def series_for_mode(
    trades: Sequence[MonteCarloTrade],
    *,
    capital_mode: CapitalMode,
) -> tuple[CapitalMode, list[str]]:
    """Select additive P&L or returns. Never mix. Fall back if returns are missing."""
    warnings: list[str] = []
    if capital_mode is CapitalMode.ADDITIVE_PNL:
        return CapitalMode.ADDITIVE_PNL, warnings

    usable = True
    nonzero_pnl_zero_return = False
    for trade in trades:
        notional = trade.quantity * trade.entry_price
        if notional <= 0 and trade.pnl != 0:
            usable = False
            break
        if trade.pnl != 0 and trade.return_pct == 0.0:
            nonzero_pnl_zero_return = True
    if not usable or nonzero_pnl_zero_return:
        warnings.append(
            "RETURN_BASED requested but some trades lack a valid notional/"
            "return_pct; remaining in ADDITIVE_PNL. The two capital modes "
            "are not interchangeable.",
        )
        return CapitalMode.ADDITIVE_PNL, warnings
    return CapitalMode.RETURN_BASED, warnings
