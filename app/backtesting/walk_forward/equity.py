"""Canonical walk-forward equity curves (market timestamps only).

The canonical equity curve represents account equity after realized trade-ledger
events (trade exits). It uses the same accounting as ``ClosedTradeRecord.net_profit``.
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone

import pandas as pd

from app.backtesting.order_execution.schemas import ClosedTradeRecord, ExecutionResult, RejectionReason


def _utc_ts(value: object) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _period_end_ts(period_end: date) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(period_end, time.max, tzinfo=timezone.utc))


def _period_start_ts(period_start: date) -> pd.Timestamp:
    return pd.Timestamp(datetime.combine(period_start, time.min, tzinfo=timezone.utc))


def _in_period(ts: pd.Timestamp, period_start: date, period_end: date) -> bool:
    start = _period_start_ts(period_start)
    end = _period_end_ts(period_end)
    return start <= ts <= end


def _last_market_event_ts(
    result: ExecutionResult,
    trades: list[ClosedTradeRecord],
    *,
    period_start: date,
    period_end: date,
) -> pd.Timestamp | None:
    candidates: list[pd.Timestamp] = []
    for attempt in result.attempts:
        ts = None
        if getattr(attempt, "fill", None) is not None:
            ts = _utc_ts(attempt.fill.filled_at)
        elif getattr(attempt, "rejected", None) is not None:
            if attempt.reason_code is RejectionReason.NO_ORDER_FOR_SIGNAL:
                continue
            ts = _utc_ts(attempt.rejected.timestamp)
        if ts is not None and _in_period(ts, period_start, period_end):
            candidates.append(ts)
    for trade in trades:
        for raw in (trade.entry_timestamp, trade.exit_timestamp):
            ts = _utc_ts(raw)
            if _in_period(ts, period_start, period_end):
                candidates.append(ts)
    if not candidates:
        return _period_end_ts(period_end)
    return max(candidates)


def ledger_equity_series(
    trades: list[ClosedTradeRecord],
    *,
    initial: float,
    period_start: date,
    period_end: date,
) -> pd.Series:
    """Equity from trade ledger: initial + cumulative net_profit at each exit."""
    start_ts = _period_start_ts(period_start)
    end_cap = _period_end_ts(period_end)
    points: list[tuple[pd.Timestamp, float]] = [(start_ts, float(initial))]
    running = float(initial)
    ordered = sorted(
        trades,
        key=lambda t: (_utc_ts(t.exit_timestamp), _utc_ts(t.entry_timestamp)),
    )
    for trade in ordered:
        exit_ts = _utc_ts(trade.exit_timestamp)
        if not _in_period(exit_ts, period_start, period_end):
            continue
        running += float(trade.net_profit)
        points.append((exit_ts, running))
    if len(points) == 1 and end_cap > start_ts:
        points.append((end_cap, float(initial)))
    frame = pd.DataFrame(points, columns=["ts", "equity"]).drop_duplicates("ts", keep="last")
    series = frame.set_index("ts")["equity"].astype(float).sort_index()
    return series[series.index <= end_cap]


def canonical_equity_series(
    trades: list[ClosedTradeRecord],
    *,
    initial: float,
    period_start: date,
    period_end: date,
) -> pd.Series:
    """Canonical OOS equity: trade-ledger net_profit, market exit timestamps only."""
    return ledger_equity_series(
        trades,
        initial=initial,
        period_start=period_start,
        period_end=period_end,
    )


def assert_ledger_equity_matches_trades(
    series: pd.Series,
    trades: list[ClosedTradeRecord],
    *,
    initial: float,
    tolerance: float = 1e-4,
) -> None:
    from app.backtesting.walk_forward.accounting import ledger_final_equity

    if series is None or series.empty:
        expected = ledger_final_equity(initial, trades)
        if trades and abs(expected - initial) > tolerance:
            raise AssertionError("empty equity series but trades have net P&L")
        return
    expected = ledger_final_equity(initial, trades)
    if abs(float(series.iloc[-1]) - expected) > tolerance:
        raise AssertionError(
            f"equity curve final {float(series.iloc[-1])} != "
            f"initial + sum(net_profit) {expected}",
        )


def market_equity_series(
    result: ExecutionResult,
    *,
    trades: list[ClosedTradeRecord],
    initial: float,
    period_start: date,
    period_end: date,
) -> pd.Series:
    """Build equity indexed only by market/backtest event timestamps."""
    points: list[tuple[pd.Timestamp, float]] = []
    for attempt in result.attempts:
        ts = None
        if getattr(attempt, "fill", None) is not None:
            ts = _utc_ts(attempt.fill.filled_at)
        elif getattr(attempt, "rejected", None) is not None:
            if attempt.reason_code is RejectionReason.NO_ORDER_FOR_SIGNAL:
                continue
            ts = _utc_ts(attempt.rejected.timestamp)
        if ts is None or not _in_period(ts, period_start, period_end):
            continue
        points.append((ts, float(attempt.account.equity)))

    final_equity = float(result.final_account.equity)
    end_cap = _period_end_ts(period_end)

    if not points:
        start_ts = _period_start_ts(period_start)
        index = pd.DatetimeIndex([start_ts, min(end_cap, start_ts + pd.Timedelta(days=1))])
        if index[0] == index[1]:
            return pd.Series([float(initial)], index=pd.DatetimeIndex([start_ts]))
        return pd.Series([float(initial), final_equity], index=index).sort_index()

    frame = pd.DataFrame(points, columns=["ts", "equity"]).drop_duplicates("ts", keep="last")
    series = frame.set_index("ts")["equity"].astype(float).sort_index()

    if float(series.iloc[0]) != float(initial):
        prepend = series.index[0] - pd.Timedelta(seconds=1)
        if prepend >= _period_start_ts(period_start):
            series = pd.concat([pd.Series([float(initial)], index=pd.DatetimeIndex([prepend])), series])
        else:
            series = pd.concat(
                [pd.Series([float(initial)], index=pd.DatetimeIndex([_period_start_ts(period_start)])), series],
            )

    last_market = _last_market_event_ts(result, trades, period_start=period_start, period_end=period_end)
    assert last_market is not None
    anchor = min(last_market, end_cap)
    if float(series.iloc[-1]) != final_equity or series.index[-1] != anchor:
        if series.index[-1] == anchor:
            series.iloc[-1] = final_equity
        elif anchor > series.index[-1]:
            series = pd.concat([series, pd.Series([final_equity], index=pd.DatetimeIndex([anchor]))])
        else:
            series.iloc[-1] = final_equity

    series = series[series.index <= end_cap]
    return series.sort_index()


def sanitize_equity_series(series: pd.Series, *, max_timestamp: pd.Timestamp | None = None) -> pd.Series:
    """Drop duplicate timestamps deterministically and cap at OOS end."""
    if series is None or series.empty:
        return series
    out = series.astype(float).copy()
    out = out[~out.index.duplicated(keep="last")].sort_index()
    if max_timestamp is not None:
        out = out[out.index <= max_timestamp]
    return out


def assert_market_timestamps_only(
    series: pd.Series,
    *,
    max_date: date | None = None,
    generated_at: datetime | None = None,
) -> None:
    """Raise if runtime/report timestamps appear in an equity series."""
    if series is None or series.empty:
        return
    if generated_at is not None:
        gen = _utc_ts(generated_at)
        if (series.index >= gen - pd.Timedelta(seconds=1)).any():
            raise AssertionError("equity curve contains report-generation timestamps")
    if max_date is not None:
        cap = _period_end_ts(max_date)
        if (series.index > cap).any():
            raise AssertionError("equity curve contains timestamps beyond OOS period end")


def combined_oos_end(windows: list[object]) -> date | None:
    if not windows:
        return None
    last = windows[-1]
    window = getattr(last, "window", last)
    return getattr(window, "test_end", None)
