"""Separate strategy signals from execution rejections for OOS reporting."""

from __future__ import annotations

from collections import Counter
from datetime import date

from app.backtesting.order_execution.schemas import ExecutionResult, RejectionReason
from app.backtesting.replay_engine.schemas import ReplayResult
from app.backtesting.walk_forward.schemas import ExecutionAttribution
from app.strategy_engine.models import SignalType


def _as_date(value: object) -> date:
    if hasattr(value, "date") and callable(value.date):
        try:
            return value.date()
        except Exception:
            pass
    import pandas as pd

    return pd.Timestamp(value).date()


def _in_period(ts: object, start: date, end: date) -> bool:
    day = _as_date(ts)
    return start <= day <= end


def build_execution_attribution(
    replay: ReplayResult,
    result: ExecutionResult,
    *,
    period_start: date,
    period_end: date,
    completed_trades: int,
) -> ExecutionAttribution:
    signals = 0
    holds = 0
    for step in replay.steps:
        if not _in_period(step.timestamp, period_start, period_end):
            continue
        if step.signal in (SignalType.BUY, SignalType.SELL):
            signals += 1
        elif step.signal is SignalType.HOLD:
            holds += 1

    rejected_by_reason: Counter[str] = Counter()
    orders_attempted = 0
    orders_filled = 0
    orders_rejected = 0
    no_order_for_signal = 0

    for attempt in result.attempts:
        ts = None
        if attempt.fill is not None:
            ts = attempt.fill.filled_at
        elif attempt.rejected is not None:
            ts = attempt.rejected.timestamp
        if ts is not None and not _in_period(ts, period_start, period_end):
            continue

        if attempt.reason_code is RejectionReason.NO_ORDER_FOR_SIGNAL:
            no_order_for_signal += 1
            continue
        if attempt.accepted:
            orders_attempted += 1
            orders_filled += 1
        else:
            orders_attempted += 1
            orders_rejected += 1
            code = attempt.reason_code or RejectionReason.VALIDATION_FAILURE
            rejected_by_reason[code.value] += 1

    return ExecutionAttribution(
        signals_generated=signals,
        hold_bars=holds,
        orders_attempted=orders_attempted,
        orders_filled=orders_filled,
        orders_rejected=orders_rejected,
        no_order_for_signal=no_order_for_signal,
        completed_trades=completed_trades,
        rejected_insufficient_cash=rejected_by_reason.get(RejectionReason.INSUFFICIENT_CASH.value, 0)
        + rejected_by_reason.get(RejectionReason.CAPITAL_INSUFFICIENT_ONE_SHARE.value, 0),
        rejected_below_min_quantity=rejected_by_reason.get(RejectionReason.BELOW_MIN_QUANTITY.value, 0),
        rejected_no_open_position=rejected_by_reason.get(RejectionReason.NO_OPEN_POSITION.value, 0),
        rejected_already_holding=rejected_by_reason.get(RejectionReason.ALREADY_HOLDING.value, 0),
        rejected_invalid_recommendation=rejected_by_reason.get(RejectionReason.INVALID_RECOMMENDATION.value, 0),
        rejected_validation_failure=rejected_by_reason.get(RejectionReason.VALIDATION_FAILURE.value, 0),
        rejected_other=sum(
            count
            for reason, count in rejected_by_reason.items()
            if reason
            not in {
                RejectionReason.INSUFFICIENT_CASH.value,
                RejectionReason.CAPITAL_INSUFFICIENT_ONE_SHARE.value,
                RejectionReason.BELOW_MIN_QUANTITY.value,
                RejectionReason.NO_OPEN_POSITION.value,
                RejectionReason.ALREADY_HOLDING.value,
                RejectionReason.INVALID_RECOMMENDATION.value,
                RejectionReason.VALIDATION_FAILURE.value,
            }
        ),
        rejected_by_reason=dict(sorted(rejected_by_reason.items())),
    )


def merge_attribution(rows: list[ExecutionAttribution]) -> ExecutionAttribution:
    if not rows:
        return ExecutionAttribution()
    merged_reason: Counter[str] = Counter()
    for row in rows:
        merged_reason.update(row.rejected_by_reason)
    return ExecutionAttribution(
        signals_generated=sum(r.signals_generated for r in rows),
        hold_bars=sum(r.hold_bars for r in rows),
        orders_attempted=sum(r.orders_attempted for r in rows),
        orders_filled=sum(r.orders_filled for r in rows),
        orders_rejected=sum(r.orders_rejected for r in rows),
        no_order_for_signal=sum(r.no_order_for_signal for r in rows),
        completed_trades=sum(r.completed_trades for r in rows),
        rejected_insufficient_cash=sum(r.rejected_insufficient_cash for r in rows),
        rejected_below_min_quantity=sum(r.rejected_below_min_quantity for r in rows),
        rejected_no_open_position=sum(r.rejected_no_open_position for r in rows),
        rejected_already_holding=sum(r.rejected_already_holding for r in rows),
        rejected_invalid_recommendation=sum(r.rejected_invalid_recommendation for r in rows),
        rejected_validation_failure=sum(r.rejected_validation_failure for r in rows),
        rejected_other=sum(r.rejected_other for r in rows),
        rejected_by_reason=dict(sorted(merged_reason.items())),
    )
