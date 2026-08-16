"""Canonical portfolio-trade aggregation from A5.2 completed trades."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

from app.backtesting.monte_carlo.schemas import MonteCarloTrade
from app.backtesting.order_execution.schemas import ClosedTradeRecord, ExitReason
from app.backtesting.portfolio_risk.exceptions import PortfolioDataError
from app.backtesting.portfolio_risk.schemas import PortfolioTrade
from app.backtesting.position_manager.schemas import Position, PositionStatus


def portfolio_trades_from_sources(sources: Sequence[Any]) -> list[PortfolioTrade]:
    """Adapt ClosedTradeRecord / closed Position / dict / MonteCarloTrade.

    Open lots are ignored. Source objects are never mutated.
    """
    out: list[PortfolioTrade] = []
    for index, item in enumerate(sources):
        converted = _one(item, index=index)
        if converted is not None:
            out.append(converted)
    out.sort(key=lambda t: (t.entry_timestamp, t.symbol, t.strategy, t.trade_id))
    return out


def _one(item: Any, *, index: int) -> PortfolioTrade | None:
    if isinstance(item, PortfolioTrade):
        return item
    if isinstance(item, ClosedTradeRecord):
        return _from_closed(item, index=index)
    if isinstance(item, Position):
        if item.status is not PositionStatus.CLOSED:
            return None
        return _from_position(item, index=index)
    if isinstance(item, MonteCarloTrade):
        return _from_monte_carlo(item, index=index)
    if isinstance(item, dict):
        return _from_mapping(item, index=index)
    return _from_eval_like(item, index=index)


def _from_closed(trade: ClosedTradeRecord, *, index: int) -> PortfolioTrade:
    if trade.entry_timestamp > trade.exit_timestamp:
        raise PortfolioDataError(
            f"trade[{index}] entry_timestamp is after exit_timestamp",
        )
    notional = float(trade.quantity) * float(trade.entry_price)
    costs = float(trade.brokerage) + float(trade.slippage)
    ret = (float(trade.exit_price) / float(trade.entry_price) - 1.0) if trade.entry_price > 0 else 0.0
    return PortfolioTrade(
        trade_id=_tid(trade.symbol, trade.strategy_name, trade.entry_timestamp, index),
        symbol=trade.symbol.strip().upper(),
        strategy=str(trade.strategy_name or ""),
        entry_timestamp=_aware(trade.entry_timestamp),
        exit_timestamp=_aware(trade.exit_timestamp),
        entry_price=float(trade.entry_price),
        exit_price=float(trade.exit_price),
        quantity=float(trade.quantity),
        gross_pnl=float(trade.gross_profit),
        net_pnl=float(trade.net_profit),
        trade_return=ret,
        brokerage=float(trade.brokerage),
        slippage=float(trade.slippage),
        execution_costs=costs,
        holding_period=int(trade.holding_days),
        requested_notional=notional,
        allocated_notional=notional,
        exit_reason=trade.exit_reason.value if isinstance(trade.exit_reason, ExitReason) else str(trade.exit_reason),
    )


def _from_position(position: Position, *, index: int) -> PortfolioTrade:
    exit_ts = position.exit_timestamp or position.last_updated_timestamp
    if position.entry_timestamp > exit_ts:
        raise PortfolioDataError(f"position[{index}] entry is after exit")
    entry = float(position.entry_price)
    exit_px = float(position.exit_price or 0.0)
    ret = (exit_px / entry - 1.0) if entry > 0 and exit_px > 0 else 0.0
    qty = float(position.quantity)
    costs = max(float(position.gross_realized_pnl) - float(position.realized_pnl), 0.0)
    return PortfolioTrade(
        trade_id=_tid(position.symbol, position.strategy_name, position.entry_timestamp, index),
        symbol=position.symbol.strip().upper(),
        strategy=str(position.strategy_name or ""),
        entry_timestamp=_aware(position.entry_timestamp),
        exit_timestamp=_aware(exit_ts),
        entry_price=entry,
        exit_price=exit_px,
        quantity=qty,
        gross_pnl=float(position.gross_realized_pnl),
        net_pnl=float(position.realized_pnl),
        trade_return=ret,
        brokerage=0.0,
        slippage=0.0,
        execution_costs=costs,
        holding_period=int(position.holding_period_days),
        requested_notional=qty * entry,
        allocated_notional=qty * entry,
        exit_reason=str(position.exit_reason or ""),
    )


def _from_monte_carlo(trade: MonteCarloTrade, *, index: int) -> PortfolioTrade | None:
    entry_ts, exit_ts = _timestamps_from_source_id(trade.source_trade_id, index)
    if trade.entry_price <= 0 or trade.exit_price <= 0:
        return None
    ret = trade.exit_price / trade.entry_price - 1.0
    return PortfolioTrade(
        trade_id=trade.source_trade_id or f"MC:{index}",
        symbol=(trade.symbol or "UNKNOWN").strip().upper(),
        strategy="",
        entry_timestamp=entry_ts,
        exit_timestamp=exit_ts,
        entry_price=float(trade.entry_price),
        exit_price=float(trade.exit_price),
        quantity=float(trade.quantity),
        gross_pnl=float(trade.gross_pnl),
        net_pnl=float(trade.pnl),
        trade_return=ret if trade.return_pct == 0.0 else float(trade.return_pct),
        brokerage=float(trade.brokerage),
        slippage=float(trade.slippage),
        execution_costs=float(trade.costs),
        holding_period=int(trade.holding_period),
        requested_notional=float(trade.quantity) * float(trade.entry_price),
        allocated_notional=float(trade.quantity) * float(trade.entry_price),
    )


def _from_mapping(row: dict[str, Any], *, index: int) -> PortfolioTrade | None:
    if "entry_price" not in row and "net_profit" not in row and "pnl" not in row:
        return None
    symbol = str(row.get("symbol") or "UNKNOWN").strip().upper()
    strategy = str(row.get("strategy") or row.get("strategy_name") or "")
    entry_px = float(row.get("entry_price") or 0.0)
    exit_px = float(row.get("exit_price") or 0.0)
    qty = float(row.get("quantity") or 0.0)
    if entry_px <= 0 or exit_px <= 0:
        return None
    entry_ts = _parse_ts(row.get("entry_timestamp"), index)
    exit_ts = _parse_ts(row.get("exit_timestamp"), index, default_days=int(row.get("holding_days") or 1))
    if entry_ts > exit_ts:
        raise PortfolioDataError(f"trade[{index}] entry_timestamp is after exit_timestamp")
    brokerage = float(row.get("brokerage") or 0.0)
    slippage = float(row.get("slippage") or 0.0)
    gross = float(row.get("gross_profit", row.get("gross_pnl", (exit_px - entry_px) * qty)))
    net = float(row.get("net_profit", row.get("pnl", gross - brokerage - slippage)))
    return PortfolioTrade(
        trade_id=str(row.get("trade_id") or _tid(symbol, strategy, entry_ts, index)),
        symbol=symbol,
        strategy=strategy,
        entry_timestamp=entry_ts,
        exit_timestamp=exit_ts,
        entry_price=entry_px,
        exit_price=exit_px,
        quantity=qty,
        gross_pnl=gross,
        net_pnl=net,
        trade_return=exit_px / entry_px - 1.0,
        brokerage=brokerage,
        slippage=slippage,
        execution_costs=brokerage + slippage,
        holding_period=int(row.get("holding_days") or row.get("holding_period") or max((exit_ts - entry_ts).days, 0)),
        requested_notional=qty * entry_px,
        allocated_notional=qty * entry_px,
        exit_reason=str(row.get("exit_reason") or ExitReason.SELL_RECOMMENDATION.value),
    )


def _from_eval_like(item: Any, *, index: int) -> PortfolioTrade | None:
    entry = getattr(item, "entry_price", None)
    exit_px = getattr(item, "exit_price", None)
    if entry is None or exit_px is None:
        return None
    mapping = {
        "symbol": getattr(item, "symbol", "UNKNOWN"),
        "strategy_name": getattr(item, "strategy_name", ""),
        "entry_timestamp": getattr(item, "entry_timestamp", None),
        "exit_timestamp": getattr(item, "exit_timestamp", None),
        "entry_price": entry,
        "exit_price": exit_px,
        "quantity": getattr(item, "quantity", 0.0),
        "gross_profit": getattr(item, "gross_profit", 0.0),
        "net_profit": getattr(item, "net_profit", 0.0),
        "brokerage": getattr(item, "brokerage", 0.0),
        "slippage": getattr(item, "slippage", 0.0),
        "holding_days": getattr(item, "holding_days", 0),
        "exit_reason": getattr(item, "exit_reason", ""),
    }
    return _from_mapping(mapping, index=index)


def _tid(symbol: str, strategy: str, ts: datetime, index: int) -> str:
    stamp = ts.isoformat() if isinstance(ts, datetime) else str(ts)
    return f"{symbol}:{strategy}:{stamp}:{index}"


def _aware(ts: datetime) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def _parse_ts(value: Any, index: int, *, default_days: int = 0) -> datetime:
    if isinstance(value, datetime):
        return _aware(value)
    if isinstance(value, str) and value:
        return _aware(datetime.fromisoformat(value.replace("Z", "+00:00")))
    base = datetime(2022, 1, 1, tzinfo=timezone.utc)
    from datetime import timedelta

    return base + timedelta(days=index + max(default_days, 0))


def _timestamps_from_source_id(source_id: str, index: int) -> tuple[datetime, datetime]:
    parts = (source_id or "").split(":")
    if len(parts) >= 3:
        try:
            entry = _aware(datetime.fromisoformat(parts[1].replace("Z", "+00:00")))
            exit_ts = _aware(datetime.fromisoformat(parts[2].replace("Z", "+00:00")))
            return entry, exit_ts
        except ValueError:
            pass
    from datetime import timedelta

    entry = datetime(2022, 1, 1, tzinfo=timezone.utc) + timedelta(days=index)
    return entry, entry + timedelta(days=1)
