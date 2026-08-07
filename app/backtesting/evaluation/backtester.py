"""Lightweight long-only backtester for EMA mode evaluation.

Uses StrategyRunner bar-by-bar — does not modify strategy logic.
Identical ExecutionConfig knobs for raw and professional runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.models import SignalType
from app.strategy_engine.symbols import attach_symbol, resolve_symbol_from_features


@dataclass
class EvalTrade:
    symbol: str
    entry_timestamp: datetime
    exit_timestamp: datetime
    entry_price: float
    exit_price: float
    quantity: float
    gross_profit: float
    brokerage: float
    slippage: float
    net_profit: float
    holding_days: int
    exit_reason: str
    strategy_name: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "entry_timestamp": self.entry_timestamp.isoformat(),
            "exit_timestamp": self.exit_timestamp.isoformat(),
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "quantity": self.quantity,
            "gross_profit": self.gross_profit,
            "brokerage": self.brokerage,
            "slippage": self.slippage,
            "net_profit": self.net_profit,
            "holding_days": self.holding_days,
            "exit_reason": self.exit_reason,
            "strategy_name": self.strategy_name,
        }


@dataclass
class BacktestResult:
    mode: str
    symbol: str
    trades: list[EvalTrade] = field(default_factory=list)
    equity_curve: pd.Series | None = None
    signal_counts: dict[str, int] = field(default_factory=dict)
    funnel: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


@dataclass
class BacktestSettings:
    initial_capital: float = 1_000_000.0
    percent: float = 95.0
    slippage_bps: float = 5.0
    brokerage_rate: float = 0.0003
    min_history_bars: int = 60
    stride: int = 1


def _apply_slippage(price: float, *, side: str, bps: float) -> float:
    adj = price * (bps / 10_000.0)
    if side == "BUY":
        return price + adj
    return price - adj


def _brokerage(notional: float, rate: float) -> float:
    return abs(notional) * rate


def run_long_only_backtest(
    strategy: BaseStrategy,
    features: pd.DataFrame,
    *,
    mode: str,
    settings: BacktestSettings | None = None,
    symbol: str | None = None,
) -> BacktestResult:
    """Walk features and simulate long-only fills for ``strategy``."""
    settings = settings or BacktestSettings()
    resolved = (
        symbol.strip().upper()
        if symbol
        else resolve_symbol_from_features(features) or strategy.active_symbol
    )
    frame = attach_symbol(features.copy(), resolved)
    result = BacktestResult(mode=mode, symbol=resolved)
    reset = getattr(strategy, "reset_session_funnel", None)
    if callable(reset):
        reset()

    cash = float(settings.initial_capital)
    qty = 0.0
    entry_price = 0.0
    entry_ts: datetime | None = None
    entry_brokerage = 0.0
    entry_slippage = 0.0
    equity_points: list[tuple[pd.Timestamp, float]] = []
    counts = {"BUY": 0, "SELL": 0, "HOLD": 0, "EXIT": 0}

    date_col = "date" if "date" in frame.columns else frame.columns[0]

    # Prepare once (avoid O(n²) copy/sort/dropna on every expanding window).
    # Evaluation fills only need SignalType — skip generate_trade_plan.
    try:
        strategy.validate(frame)
        prepared = strategy.prepare(frame)
        if resolve_symbol_from_features(prepared) is None:
            prepared = attach_symbol(prepared.copy(deep=False), resolved)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"prepare: {exc}")
        return result

    n = len(prepared)
    start = min(max(settings.min_history_bars, 2), n)
    stride = max(settings.stride, 1)

    for cut in range(start, n + 1, stride):
        window = prepared.iloc[:cut]
        row = window.iloc[-1]
        ts = pd.Timestamp(row[date_col]).to_pydatetime()
        close = float(row["close"])
        try:
            signal = strategy.generate_signal(window)
            sig = signal.signal
            counts[sig.value] = counts.get(sig.value, 0) + 1

            if sig is SignalType.BUY and qty <= 0:
                fill = _apply_slippage(close, side="BUY", bps=settings.slippage_bps)
                budget = cash * (settings.percent / 100.0)
                shares = int(budget // fill) if fill > 0 else 0
                if shares >= 1:
                    notional = shares * fill
                    slip_cost = abs(fill - close) * shares
                    broker = _brokerage(notional, settings.brokerage_rate)
                    cost = notional + broker
                    if cost <= cash:
                        cash -= cost
                        qty = float(shares)
                        entry_price = fill
                        entry_ts = ts
                        entry_brokerage = broker
                        entry_slippage = slip_cost

            elif sig in {SignalType.SELL, SignalType.EXIT} and qty > 0 and entry_ts is not None:
                fill = _apply_slippage(close, side="SELL", bps=settings.slippage_bps)
                notional = qty * fill
                slip_cost = abs(close - fill) * qty
                broker = _brokerage(notional, settings.brokerage_rate)
                cash += notional - broker
                gross = (fill - entry_price) * qty
                total_broker = entry_brokerage + broker
                total_slip = entry_slippage + slip_cost
                net = gross - total_broker - total_slip
                hold_days = max((ts.date() - entry_ts.date()).days, 0)
                result.trades.append(
                    EvalTrade(
                        symbol=resolved,
                        entry_timestamp=entry_ts,
                        exit_timestamp=ts,
                        entry_price=entry_price,
                        exit_price=fill,
                        quantity=qty,
                        gross_profit=gross,
                        brokerage=total_broker,
                        slippage=total_slip,
                        net_profit=net,
                        holding_days=hold_days,
                        exit_reason=sig.value,
                        strategy_name=strategy.name,
                    ),
                )
                qty = 0.0
                entry_price = 0.0
                entry_ts = None
                entry_brokerage = 0.0
                entry_slippage = 0.0

            mark = cash + qty * close
            equity_points.append((pd.Timestamp(ts), mark))
        except Exception as exc:  # noqa: BLE001 — continue evaluation
            result.errors.append(f"{ts}: {exc}")
            mark = cash + qty * close
            equity_points.append((pd.Timestamp(ts), mark))
            if len(result.errors) > 50:
                break

    # Flatten open position at end
    if qty > 0 and entry_ts is not None and len(prepared):
        row = prepared.iloc[-1]
        ts = pd.Timestamp(row[date_col]).to_pydatetime()
        close = float(row["close"])
        fill = _apply_slippage(close, side="SELL", bps=settings.slippage_bps)
        notional = qty * fill
        slip_cost = abs(close - fill) * qty
        broker = _brokerage(notional, settings.brokerage_rate)
        cash += notional - broker
        gross = (fill - entry_price) * qty
        net = gross - (entry_brokerage + broker) - (entry_slippage + slip_cost)
        result.trades.append(
            EvalTrade(
                symbol=resolved,
                entry_timestamp=entry_ts,
                exit_timestamp=ts,
                entry_price=entry_price,
                exit_price=fill,
                quantity=qty,
                gross_profit=gross,
                brokerage=entry_brokerage + broker,
                slippage=entry_slippage + slip_cost,
                net_profit=net,
                holding_days=max((ts.date() - entry_ts.date()).days, 0),
                exit_reason="Replay End",
                strategy_name=strategy.name,
            ),
        )
        equity_points.append((pd.Timestamp(ts), cash))

    if equity_points:
        idx, vals = zip(*equity_points, strict=False)
        # Deduplicate timestamps keeping last
        curve = pd.Series(vals, index=pd.DatetimeIndex(idx), dtype=float)
        curve = curve[~curve.index.duplicated(keep="last")].sort_index()
        result.equity_curve = curve

    result.signal_counts = counts
    funnel = getattr(strategy, "session_funnel", None)
    if funnel is not None and hasattr(funnel, "model_dump"):
        result.funnel = funnel.model_dump()
    return result
