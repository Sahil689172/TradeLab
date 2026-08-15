"""Copy completed historical trades into MonteCarloTrade records.

Canonical source: A5.2 ``ClosedTradeRecord``.
Canonical P&L: ``net_profit`` (brokerage + slippage already subtracted).
Open positions are ignored — only completed round-trips enter a simulation.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.backtesting.monte_carlo.exceptions import MonteCarloDataError
from app.backtesting.monte_carlo.schemas import MonteCarloTrade
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.position_manager.schemas import Position, PositionStatus


def trades_from_sources(sources: Sequence[Any]) -> list[MonteCarloTrade]:
    """Adapt ClosedTradeRecord / EvalTrade / closed Position / dict. Never mutates ``sources``."""
    out: list[MonteCarloTrade] = []
    for index, item in enumerate(sources):
        converted = _one(item, index=index)
        if converted is not None:
            out.append(converted)
    return out


def _one(item: Any, *, index: int) -> MonteCarloTrade | None:
    if isinstance(item, MonteCarloTrade):
        return item
    if isinstance(item, ClosedTradeRecord):
        return _from_closed(item, index=index)
    if isinstance(item, Position):
        if item.status is not PositionStatus.CLOSED:
            return None
        return _from_position(item, index=index)
    if isinstance(item, dict):
        return _from_mapping(item, index=index)
    return _from_eval_like(item, index=index)


def _from_closed(trade: ClosedTradeRecord, *, index: int) -> MonteCarloTrade:
    if trade.entry_timestamp > trade.exit_timestamp:
        raise MonteCarloDataError(
            f"trade[{index}] entry_timestamp is after exit_timestamp",
        )
    notional = trade.quantity * trade.entry_price
    costs = float(trade.brokerage) + float(trade.slippage)
    pnl = float(trade.net_profit)
    return MonteCarloTrade(
        pnl=pnl,
        return_pct=_return_pct(pnl, notional),
        costs=costs,
        brokerage=float(trade.brokerage),
        slippage=float(trade.slippage),
        gross_pnl=float(trade.gross_profit),
        holding_period=int(trade.holding_days),
        win_loss=_wl(pnl),
        source_trade_id=_id(
            trade.symbol,
            trade.entry_timestamp,
            trade.exit_timestamp,
            index,
        ),
        symbol=trade.symbol,
        quantity=float(trade.quantity),
        entry_price=float(trade.entry_price),
        exit_price=float(trade.exit_price),
    )


def _from_position(position: Position, *, index: int) -> MonteCarloTrade:
    notional = position.quantity * position.entry_price
    pnl = float(position.realized_pnl)
    gross = float(position.gross_realized_pnl)
    costs = max(gross - pnl, 0.0)
    exit_ts = position.exit_timestamp or position.last_updated_timestamp
    return MonteCarloTrade(
        pnl=pnl,
        return_pct=_return_pct(pnl, notional),
        costs=costs,
        brokerage=0.0,
        slippage=0.0,
        gross_pnl=gross,
        holding_period=int(position.holding_period_days),
        win_loss=_wl(pnl),
        source_trade_id=_id(position.symbol, position.entry_timestamp, exit_ts, index),
        symbol=position.symbol,
        quantity=float(position.quantity),
        entry_price=float(position.entry_price),
        exit_price=float(position.exit_price or 0.0),
    )


def _from_mapping(row: dict[str, Any], *, index: int) -> MonteCarloTrade | None:
    if "net_profit" not in row and "pnl" not in row:
        return None
    pnl = float(row.get("pnl", row.get("net_profit", 0.0)))
    qty = float(row.get("quantity", 0.0) or 0.0)
    entry = float(row.get("entry_price", 0.0) or 0.0)
    brokerage = float(row.get("brokerage", 0.0) or 0.0)
    slippage = float(row.get("slippage", 0.0) or 0.0)
    gross = float(row.get("gross_profit", row.get("gross_pnl", pnl + brokerage + slippage)))
    symbol = str(row.get("symbol", "") or "")
    return MonteCarloTrade(
        pnl=pnl,
        return_pct=_return_pct(pnl, qty * entry),
        costs=brokerage + slippage,
        brokerage=brokerage,
        slippage=slippage,
        gross_pnl=gross,
        holding_period=int(row.get("holding_days", row.get("holding_period", 0)) or 0),
        win_loss=_wl(pnl),
        source_trade_id=str(row.get("source_trade_id") or _id(symbol, row.get("entry_timestamp"), row.get("exit_timestamp"), index)),
        symbol=symbol,
        quantity=qty,
        entry_price=entry,
        exit_price=float(row.get("exit_price", 0.0) or 0.0),
    )


def _from_eval_like(item: Any, *, index: int) -> MonteCarloTrade | None:
    pnl = getattr(item, "net_profit", None)
    if pnl is None:
        return None
    qty = float(getattr(item, "quantity", 0.0) or 0.0)
    entry = float(getattr(item, "entry_price", 0.0) or 0.0)
    brokerage = float(getattr(item, "brokerage", 0.0) or 0.0)
    slippage = float(getattr(item, "slippage", 0.0) or 0.0)
    symbol = str(getattr(item, "symbol", "") or "")
    return MonteCarloTrade(
        pnl=float(pnl),
        return_pct=_return_pct(float(pnl), qty * entry),
        costs=brokerage + slippage,
        brokerage=brokerage,
        slippage=slippage,
        gross_pnl=float(getattr(item, "gross_profit", float(pnl) + brokerage + slippage)),
        holding_period=int(getattr(item, "holding_days", 0) or 0),
        win_loss=_wl(float(pnl)),
        source_trade_id=_id(
            symbol,
            getattr(item, "entry_timestamp", None),
            getattr(item, "exit_timestamp", None),
            index,
        ),
        symbol=symbol,
        quantity=qty,
        entry_price=entry,
        exit_price=float(getattr(item, "exit_price", 0.0) or 0.0),
    )


def with_cost_perturbation(
    trades: Sequence[MonteCarloTrade],
    *,
    slippage_bps: float,
    base_slippage_bps: float,
    commission_mult: float = 1.0,
) -> list[MonteCarloTrade]:
    """Rebuild net P&L from gross under an alternate cost assumption.

    Historical ``net_profit`` already includes brokerage and slippage.
    This function copies trades and reconstructs ``gross - new_brokerage - new_slippage``.
    It never subtracts costs from already-netted P&L.
    """
    adjusted: list[MonteCarloTrade] = []
    for trade in trades:
        new_brokerage = trade.brokerage * commission_mult
        new_slippage = _scaled_slippage(
            trade,
            slippage_bps=slippage_bps,
            base_slippage_bps=base_slippage_bps,
        )
        new_costs = max(new_brokerage, 0.0) + max(new_slippage, 0.0)
        new_pnl = reconstruct_net_pnl(trade.gross_pnl, new_brokerage, new_slippage)
        notional = trade.quantity * trade.entry_price
        adjusted.append(
            trade.model_copy(
                update={
                    "pnl": new_pnl,
                    "return_pct": _return_pct(new_pnl, notional),
                    "costs": new_costs,
                    "brokerage": max(new_brokerage, 0.0),
                    "slippage": max(new_slippage, 0.0),
                    "win_loss": 1 if new_pnl > 0 else (-1 if new_pnl < 0 else 0),
                },
            ),
        )
    return adjusted


def reconstruct_net_pnl(gross_pnl: float, brokerage: float, slippage: float) -> float:
    """Rebuild net P&L from gross and a cost scenario.

    Input trade logs already store ``net_profit`` with costs embedded.
    Sensitivity must reconstruct from gross — never subtract the same costs
    from already-netted P&L.
    """
    return float(gross_pnl) - max(float(brokerage), 0.0) - max(float(slippage), 0.0)


def _scaled_slippage(
    trade: MonteCarloTrade,
    *,
    slippage_bps: float,
    base_slippage_bps: float,
) -> float:
    if base_slippage_bps > 0 and trade.slippage > 0:
        return trade.slippage * (slippage_bps / base_slippage_bps)
    notional = trade.quantity * (trade.entry_price + trade.exit_price)
    if notional <= 0:
        notional = 2.0 * trade.quantity * trade.entry_price
    return max(notional, 0.0) * (slippage_bps / 10_000.0)


def _return_pct(pnl: float, notional: float) -> float:
    if notional <= 0:
        return 0.0
    return float(pnl) / float(notional)


def _wl(pnl: float) -> int:
    if pnl > 0:
        return 1
    if pnl < 0:
        return -1
    return 0


def _id(symbol: str, entry: Any, exit_: Any, index: int) -> str:
    return f"{symbol or 'TRADE'}:{_ts(entry)}:{_ts(exit_)}:{index}"


def _ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if value is None:
        return ""
    return str(value)
