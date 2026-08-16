"""Shared-book overlay of completed trades using A5.2 SimulatedBroker.

Entries are re-sized from current cash. Independent-sleeve historical
quantities are not replayed as a live portfolio. Exit prices are applied only
when the exit event fires (no mark-to-market from future exit prices).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from app.backtesting.order_execution import (
    ExecutionConfig,
    MarketOrder,
    OrderSide,
    PositionSizingMode,
    SimulatedBroker,
)
from app.backtesting.order_execution.costs import execution_price
from app.backtesting.order_execution.exceptions import OrderRejectedError
from app.backtesting.portfolio_risk.allocation import (
    min_share_cost,
    quantity_for_budget,
    target_budget,
)
from app.backtesting.portfolio_risk.limits import check_entry_limits
from app.backtesting.portfolio_risk.schemas import (
    AllocationDecision,
    AllocationPolicy,
    AllocationStatus,
    BookReplayResult,
    ExposureSnapshot,
    LimitAction,
    PortfolioRejectReason,
    PortfolioRiskConfig,
    PortfolioTrade,
)


def replay_book(
    trades: Sequence[PortfolioTrade],
    config: PortfolioRiskConfig,
) -> BookReplayResult:
    """Process completed trades on one shared cash book."""
    broker = SimulatedBroker(_execution_config(config))
    open_lots: dict[str, _OpenLot] = {}
    executed: list[PortfolioTrade] = []
    rejections: list[AllocationDecision] = []
    snapshots: list[ExposureSnapshot] = []
    peak = float(config.initial_capital)
    day_start_equity = float(config.initial_capital)
    current_date = None

    events = _events(trades)
    snapshots.append(_snapshot(broker, open_lots, peak, events[0][0] if events else None, config))

    i = 0
    while i < len(events):
        timestamp, kind, trade, _seq = events[i]
        day = timestamp.date()
        if current_date is None:
            current_date = day
            day_start_equity = broker.snapshot().equity
        elif day != current_date:
            current_date = day
            day_start_equity = broker.snapshot().equity

        if kind == "exit":
            closed = _exit_lot(broker, open_lots, trade, timestamp)
            if closed is not None:
                executed = _patch_executed(executed, trade.trade_id, closed)
            snap = broker.snapshot()
            peak = max(peak, snap.equity)
            snapshots.append(_snapshot(broker, open_lots, peak, timestamp, config))
            i += 1
            continue

        batch: list[PortfolioTrade] = []
        while i < len(events) and events[i][0] == timestamp and events[i][1] == "entry":
            batch.append(events[i][2])
            i += 1
        snap0 = broker.snapshot()
        for candidate in batch:
            decision = _enter(
                broker=broker,
                open_lots=open_lots,
                trade=candidate,
                timestamp=timestamp,
                config=config,
                peak=peak,
                day_start_equity=day_start_equity,
                simultaneous=len(batch),
                frozen_cash=snap0.cash,
                frozen_equity=snap0.equity,
            )
            if decision.status is AllocationStatus.REJECTED:
                rejections.append(decision)
                continue
            snap = broker.snapshot()
            pos = snap.positions.get(candidate.symbol)
            qty = float(pos.quantity) if pos is not None else decision.quantity
            buy_px = execution_price(OrderSide.BUY, candidate.entry_price, config.slippage_bps)
            allocated = buy_px * qty
            open_lots[candidate.symbol] = _OpenLot(
                trade_id=candidate.trade_id,
                symbol=candidate.symbol,
                strategy=candidate.strategy,
                quantity=qty,
                entry_price=buy_px,
                source=candidate,
            )
            executed.append(
                candidate.model_copy(
                    update={
                        "quantity": qty,
                        "requested_notional": decision.requested_budget,
                        "allocated_notional": allocated,
                    },
                ),
            )
            if decision.status is AllocationStatus.PARTIAL:
                rejections.append(decision)
        snap = broker.snapshot()
        peak = max(peak, snap.equity)
        snapshots.append(_snapshot(broker, open_lots, peak, timestamp, config))

    final = broker.snapshot()
    equity_ts = [s.timestamp for s in snapshots if s.timestamp is not None]
    equity_vs = [s.equity for s in snapshots]
    return BookReplayResult(
        initial_capital=config.initial_capital,
        final_equity=final.equity,
        final_cash=final.cash,
        net_return=(final.equity - config.initial_capital) / config.initial_capital,
        executed_trades=executed,
        rejections=rejections,
        snapshots=snapshots,
        equity_timestamps=equity_ts,
        equity_values=equity_vs,
    )


class _OpenLot:
    __slots__ = ("trade_id", "symbol", "strategy", "quantity", "entry_price", "source")

    def __init__(
        self,
        trade_id: str,
        symbol: str,
        strategy: str,
        quantity: float,
        entry_price: float,
        source: PortfolioTrade,
    ) -> None:
        self.trade_id = trade_id
        self.symbol = symbol
        self.strategy = strategy
        self.quantity = quantity
        self.entry_price = entry_price
        self.source = source


def _execution_config(config: PortfolioRiskConfig) -> ExecutionConfig:
    return ExecutionConfig(
        initial_capital=config.initial_capital,
        position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
        percent=min(config.position_percent, 100.0),
        slippage_bps=config.slippage_bps,
        brokerage_rate=config.brokerage_rate,
        brokerage_flat=config.brokerage_flat,
        allow_fractional_shares=config.allow_fractional_shares,
        min_quantity=config.min_quantity,
        close_open_at_replay_end=False,
    )


def _events(
    trades: Sequence[PortfolioTrade],
) -> list[tuple[datetime, str, PortfolioTrade, int]]:
    events: list[tuple[datetime, str, PortfolioTrade, int]] = []
    for i, trade in enumerate(trades):
        if trade.entry_price <= 0 or trade.exit_price <= 0:
            continue
        if trade.entry_timestamp > trade.exit_timestamp:
            continue
        events.append((trade.entry_timestamp, "entry", trade, i))
        events.append((trade.exit_timestamp, "exit", trade, i))
    # Exits before entries at the same timestamp so cash is freed first.
    events.sort(key=lambda e: (e[0], 0 if e[1] == "exit" else 1, e[2].symbol, e[2].strategy, e[3]))
    return events


def _enter(
    *,
    broker: SimulatedBroker,
    open_lots: dict[str, _OpenLot],
    trade: PortfolioTrade,
    timestamp: datetime,
    config: PortfolioRiskConfig,
    peak: float,
    day_start_equity: float,
    simultaneous: int,
    frozen_cash: float | None = None,
    frozen_equity: float | None = None,
) -> AllocationDecision:
    snap = broker.snapshot()
    equity = float(frozen_equity if frozen_equity is not None else snap.equity)
    cash_for_request = float(frozen_cash if frozen_cash is not None else snap.cash)
    cash = snap.cash
    gross = _gross_exposure(open_lots)
    dd = 0.0 if peak <= 0 else max(peak - equity, 0.0) / peak
    daily_loss = 0.0 if day_start_equity <= 0 else max(day_start_equity - equity, 0.0) / day_start_equity
    symbol_notional = open_lots[trade.symbol].quantity * open_lots[trade.symbol].entry_price if trade.symbol in open_lots else 0.0
    strategy_notional = sum(
        lot.quantity * lot.entry_price for lot in open_lots.values() if lot.strategy == trade.strategy
    )
    max_book = equity * (config.limits.max_exposure_pct / 100.0)
    allocatable = max(min(cash, max_book - gross), 0.0)
    requested = target_budget(
        policy=config.allocation_policy,
        equity=equity,
        cash=cash_for_request,
        position_percent=config.position_percent,
        max_position_pct=config.limits.max_position_pct,
        allocatable=allocatable,
        simultaneous_count=simultaneous,
    )

    reason, message, allowed = check_entry_limits(
        limits=config.limits,
        open_positions=len(open_lots),
        already_holding=trade.symbol in open_lots,
        equity=equity,
        gross_exposure=gross,
        proposed_notional=requested,
        symbol=trade.symbol,
        strategy=trade.strategy,
        symbol_notional=symbol_notional,
        strategy_notional=strategy_notional,
        drawdown_pct=dd,
        daily_loss_pct=daily_loss,
    )

    budget = requested
    status = AllocationStatus.FILLED
    if reason is not None:
        if config.limits.limit_action is LimitAction.SCALE and allowed > 0.0:
            budget = min(requested, allowed)
            status = AllocationStatus.PARTIAL
        else:
            return AllocationDecision(
                trade_id=trade.trade_id,
                symbol=trade.symbol,
                strategy=trade.strategy,
                timestamp=timestamp,
                status=AllocationStatus.REJECTED,
                reason_code=reason,
                reason=message,
                requested_budget=requested,
                allocated_budget=0.0,
                quantity=0.0,
            )

    if cash + 1e-9 < min_share_cost(trade.entry_price, config):
        return AllocationDecision(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            strategy=trade.strategy,
            timestamp=timestamp,
            status=AllocationStatus.REJECTED,
            reason_code=PortfolioRejectReason.CANNOT_AFFORD_MIN_QUANTITY,
            reason=(
                f"cash ₹{cash:,.2f} cannot buy min quantity of {trade.symbol} "
                f"at ₹{trade.entry_price:,.2f}"
            ),
            requested_budget=requested,
            allocated_budget=0.0,
            quantity=0.0,
        )

    budget = min(budget, cash, allowed if allowed > 0 else budget)
    qty = quantity_for_budget(budget, trade.entry_price, config)
    if qty <= 0.0:
        return AllocationDecision(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            strategy=trade.strategy,
            timestamp=timestamp,
            status=AllocationStatus.REJECTED,
            reason_code=PortfolioRejectReason.CANNOT_AFFORD_MIN_QUANTITY,
            reason=f"sized quantity below minimum for {trade.symbol}",
            requested_budget=requested,
            allocated_budget=0.0,
            quantity=0.0,
        )

    if config.allocation_policy is AllocationPolicy.EQUAL_RISK:
        # Documented fallback: equal notional. Do not invent stop distances.
        pass

    try:
        broker.submit_market_order(
            MarketOrder(
                symbol=trade.symbol,
                side=OrderSide.BUY,
                quantity=qty,
                submitted_at=timestamp,
                reference_price=trade.entry_price,
                strategy_name=trade.strategy,
                recommendation_trade_id=trade.trade_id,
            ),
        )
    except OrderRejectedError as exc:
        mapped = _map_exec_reason(exc)
        return AllocationDecision(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            strategy=trade.strategy,
            timestamp=timestamp,
            status=AllocationStatus.REJECTED,
            reason_code=mapped,
            reason=str(exc),
            requested_budget=requested,
            allocated_budget=0.0,
            quantity=0.0,
        )

    if status is AllocationStatus.PARTIAL:
        return AllocationDecision(
            trade_id=trade.trade_id,
            symbol=trade.symbol,
            strategy=trade.strategy,
            timestamp=timestamp,
            status=AllocationStatus.PARTIAL,
            reason_code=reason,
            reason=message or "scaled to remaining limit",
            requested_budget=requested,
            allocated_budget=budget,
            quantity=qty,
        )
    return AllocationDecision(
        trade_id=trade.trade_id,
        symbol=trade.symbol,
        strategy=trade.strategy,
        timestamp=timestamp,
        status=AllocationStatus.FILLED,
        requested_budget=requested,
        allocated_budget=budget,
        quantity=qty,
    )


def _exit_lot(
    broker: SimulatedBroker,
    open_lots: dict[str, _OpenLot],
    trade: PortfolioTrade,
    timestamp: datetime,
):
    lot = None
    for candidate in list(open_lots.values()):
        if candidate.trade_id == trade.trade_id:
            lot = candidate
            break
    if lot is None:
        return None
    before = len(broker.closed_trades)
    try:
        broker.submit_market_order(
            MarketOrder(
                symbol=lot.symbol,
                side=OrderSide.SELL,
                quantity=lot.quantity,
                submitted_at=timestamp,
                reference_price=trade.exit_price,
                strategy_name=lot.strategy,
                recommendation_trade_id=lot.trade_id,
            ),
        )
    except OrderRejectedError:
        return None
    open_lots.pop(lot.symbol, None)
    closed = broker.closed_trades
    if len(closed) > before:
        return closed[-1]
    return None


def _patch_executed(
    executed: list[PortfolioTrade],
    trade_id: str,
    closed,
) -> list[PortfolioTrade]:
    out: list[PortfolioTrade] = []
    for trade in executed:
        if trade.trade_id != trade_id:
            out.append(trade)
            continue
        qty = float(closed.quantity)
        entry = float(closed.entry_price)
        exit_px = float(closed.exit_price)
        ret = exit_px / entry - 1.0 if entry > 0 else 0.0
        out.append(
            trade.model_copy(
                update={
                    "quantity": qty,
                    "entry_price": entry,
                    "exit_price": exit_px,
                    "gross_pnl": float(closed.gross_profit),
                    "net_pnl": float(closed.net_profit),
                    "trade_return": ret,
                    "brokerage": float(closed.brokerage),
                    "slippage": float(closed.slippage),
                    "execution_costs": float(closed.brokerage) + float(closed.slippage),
                    "allocated_notional": entry * qty,
                },
            ),
        )
    return out


def _gross_exposure(open_lots: dict[str, _OpenLot]) -> float:
    return float(sum(lot.quantity * lot.entry_price for lot in open_lots.values()))


def _snapshot(
    broker: SimulatedBroker,
    open_lots: dict[str, _OpenLot],
    peak: float,
    timestamp: datetime | None,
    config: PortfolioRiskConfig,
) -> ExposureSnapshot:
    _ = config
    snap = broker.snapshot()
    gross = _gross_exposure(open_lots)
    equity = snap.equity
    util = 0.0 if equity <= 0 else gross / equity * 100.0
    weights: dict[str, float] = {}
    strat: dict[str, float] = {}
    if equity > 0:
        for lot in open_lots.values():
            w = lot.quantity * lot.entry_price / equity
            weights[lot.symbol] = weights.get(lot.symbol, 0.0) + w
            key = lot.strategy or "unknown"
            strat[key] = strat.get(key, 0.0) + w
    largest = max(weights.values()) * 100.0 if weights else 0.0
    hhi = float(sum(w * w for w in weights.values()))
    dd = 0.0 if peak <= 0 else equity / peak - 1.0
    ts = timestamp
    if ts is None:
        from datetime import timezone

        ts = datetime(1970, 1, 1, tzinfo=timezone.utc)
    return ExposureSnapshot(
        timestamp=ts,
        cash=snap.cash,
        equity=equity,
        gross_exposure=gross,
        net_exposure=gross,
        invested_capital=gross,
        utilization_pct=util,
        open_positions=len(open_lots),
        largest_position_pct=largest,
        symbol_weights={k: v * 100.0 for k, v in weights.items()},
        strategy_weights={k: v * 100.0 for k, v in strat.items()},
        hhi=hhi,
        peak_equity=peak,
        drawdown=dd,
    )


def _map_exec_reason(exc: OrderRejectedError) -> PortfolioRejectReason:
    code = getattr(exc, "reason_code", None)
    name = getattr(code, "name", "") if code is not None else ""
    mapping = {
        "INSUFFICIENT_CASH": PortfolioRejectReason.INSUFFICIENT_CASH,
        "CAPITAL_INSUFFICIENT_ONE_SHARE": PortfolioRejectReason.CANNOT_AFFORD_MIN_QUANTITY,
        "BELOW_MIN_QUANTITY": PortfolioRejectReason.CANNOT_AFFORD_MIN_QUANTITY,
        "ALREADY_HOLDING": PortfolioRejectReason.ALREADY_HOLDING,
    }
    return mapping.get(name, PortfolioRejectReason.EXECUTION_REJECTED)
