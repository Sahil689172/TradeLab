"""Portfolio risk-limit checks. Limits reject or scale; they never mutate A5.2."""

from __future__ import annotations

from app.backtesting.portfolio_risk.schemas import (
    LimitAction,
    PortfolioRejectReason,
    PortfolioRiskLimits,
)


def check_entry_limits(
    *,
    limits: PortfolioRiskLimits,
    open_positions: int,
    already_holding: bool,
    equity: float,
    gross_exposure: float,
    proposed_notional: float,
    symbol: str,
    strategy: str,
    symbol_notional: float,
    strategy_notional: float,
    drawdown_pct: float,
    daily_loss_pct: float,
) -> tuple[PortfolioRejectReason | None, str, float]:
    """Return (reason, message, allowed_notional).

    ``allowed_notional`` is the largest notional that would still pass caps.
    Caller REJECTS if action is REJECT and allowed < proposed (beyond cash
    rounding). SCALE uses allowed_notional.
    """
    if already_holding:
        return (
            PortfolioRejectReason.ALREADY_HOLDING,
            f"{symbol} is already open in the shared book",
            0.0,
        )
    if proposed_notional <= 0.0:
        return (
            PortfolioRejectReason.INSUFFICIENT_CASH,
            "requested allocation is not positive",
            0.0,
        )
    if open_positions >= limits.max_open_positions:
        return (
            PortfolioRejectReason.MAX_OPEN_POSITIONS,
            f"open positions {open_positions} >= max {limits.max_open_positions}",
            0.0,
        )
    if equity <= 0.0:
        return (
            PortfolioRejectReason.INSUFFICIENT_CASH,
            "equity is not positive",
            0.0,
        )
    if limits.max_portfolio_drawdown_pct is not None:
        if drawdown_pct * 100.0 >= limits.max_portfolio_drawdown_pct:
            return (
                PortfolioRejectReason.MAX_PORTFOLIO_DRAWDOWN,
                f"drawdown {drawdown_pct:.2%} exceeds max "
                f"{limits.max_portfolio_drawdown_pct:.2f}%",
                0.0,
            )
    if limits.max_daily_loss_pct is not None:
        if daily_loss_pct * 100.0 >= limits.max_daily_loss_pct:
            return (
                PortfolioRejectReason.MAX_DAILY_LOSS,
                f"daily loss {daily_loss_pct:.2%} exceeds max "
                f"{limits.max_daily_loss_pct:.2f}%",
                0.0,
            )

    max_pos = equity * (limits.max_position_pct / 100.0)
    max_book = equity * (limits.max_exposure_pct / 100.0)
    headroom = max(max_book - gross_exposure, 0.0)
    allowed = min(proposed_notional, max_pos, headroom)

    if allowed <= 0.0:
        return (
            PortfolioRejectReason.MAX_PORTFOLIO_EXPOSURE,
            "no remaining exposure headroom",
            0.0,
        )

    proposed_symbol = symbol_notional + proposed_notional
    if proposed_symbol / equity * 100.0 > limits.max_symbol_concentration_pct + 1e-9:
        cap = equity * (limits.max_symbol_concentration_pct / 100.0) - symbol_notional
        if cap <= 0.0:
            return (
                PortfolioRejectReason.MAX_SYMBOL_CONCENTRATION,
                f"{symbol} would exceed max symbol concentration "
                f"{limits.max_symbol_concentration_pct:.2f}%",
                0.0,
            )
        allowed = min(allowed, cap)
        if limits.limit_action is LimitAction.REJECT and allowed + 1e-6 < proposed_notional:
            return (
                PortfolioRejectReason.MAX_SYMBOL_CONCENTRATION,
                f"{symbol} requested notional exceeds max symbol concentration",
                allowed,
            )

    proposed_strategy = strategy_notional + proposed_notional
    if proposed_strategy / equity * 100.0 > limits.max_strategy_concentration_pct + 1e-9:
        cap = equity * (limits.max_strategy_concentration_pct / 100.0) - strategy_notional
        if cap <= 0.0:
            return (
                PortfolioRejectReason.MAX_STRATEGY_CONCENTRATION,
                f"{strategy or 'strategy'} would exceed max strategy concentration "
                f"{limits.max_strategy_concentration_pct:.2f}%",
                0.0,
            )
        allowed = min(allowed, cap)
        if limits.limit_action is LimitAction.REJECT and allowed + 1e-6 < proposed_notional:
            return (
                PortfolioRejectReason.MAX_STRATEGY_CONCENTRATION,
                f"{strategy or 'strategy'} requested notional exceeds max strategy concentration",
                allowed,
            )

    if proposed_notional > max_pos + 1e-6:
        if limits.limit_action is LimitAction.REJECT:
            return (
                PortfolioRejectReason.MAX_POSITION_PERCENT,
                f"requested position {proposed_notional / equity:.2%} exceeds "
                f"max position {limits.max_position_pct:.2f}%",
                min(allowed, max_pos),
            )
        allowed = min(allowed, max_pos)

    if gross_exposure + proposed_notional > max_book + 1e-6:
        if limits.limit_action is LimitAction.REJECT:
            return (
                PortfolioRejectReason.MAX_PORTFOLIO_EXPOSURE,
                f"requested book would exceed max exposure {limits.max_exposure_pct:.2f}%",
                min(allowed, headroom),
            )
        allowed = min(allowed, headroom)

    return None, "", max(allowed, 0.0)
