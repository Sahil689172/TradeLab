"""Run a frozen strategy on a date window via A5.1 replay + A5.2 execution.

Indicator warmup uses candles with date <= period_end (including pre-start
history). Post-period candles are stripped by DateCapped adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.backtesting.evaluation.metrics import compute_performance
from app.backtesting.order_execution import ExecutionConfig, OrderExecutionEngine, PositionSizingMode
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.replay_engine import HistoricalReplayEngine, ReplayConfig, ReplaySpeed
from app.backtesting.walk_forward.isolation import DateCappedFeatures, DateCappedMarket, frame_max_date
from app.feature_engine.strategy_frame import ensure_strategy_indicators
from app.backtesting.walk_forward.schemas import CandidateMetrics, WalkForwardConfig
from app.backtesting.walk_forward.search import config_key, config_params
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy


class FrozenEMAFactory:
    """StrategyFactoryPort that always returns one frozen EMA configuration."""

    def __init__(self, config: EMATrendConfig) -> None:
        self._config = config

    def resolve(self, names: object) -> list[EMATrendStrategy]:
        _ = names
        return [EMATrendStrategy(self._config)]


def ensure_indicator_columns(frame: pd.DataFrame, config: EMATrendConfig) -> pd.DataFrame:
    """Fill missing indicator columns causally. Does not use future bars.

    Reuses Feature Engine ``ensure_strategy_indicators`` for canonical columns,
    then adds any extra EMA spans required by the frozen candidate (e.g. 12/26).
    """
    if frame is None or frame.empty:
        return frame
    out = ensure_strategy_indicators(frame)
    close = pd.to_numeric(out["close"], errors="coerce")
    periods = {int(config.fast_ema), int(config.slow_ema)}
    if config.ema200_filter or getattr(config, "trend_filter", False):
        periods.add(200)
    for period in sorted(periods):
        column = f"ema_{period}"
        if column not in out.columns:
            out[column] = close.ewm(span=period, adjust=False).mean()
    return out


class _EnsuringFeatures:
    def __init__(self, inner: object, config: EMATrendConfig, market: object) -> None:
        self._inner = inner
        self._config = config
        self._market = market

    def load_features(self, symbol: str) -> pd.DataFrame | None:
        frame = self._inner.load_features(symbol) if self._inner is not None else None
        if frame is None or getattr(frame, "empty", False):
            frame = self._market.get_history(symbol)
        if frame is None:
            return None
        return ensure_indicator_columns(frame, self._config)


@dataclass
class PeriodRun:
    trades: list[ClosedTradeRecord]
    equity: pd.Series
    metrics: CandidateMetrics
    used_max: date
    rejected_count: int = 0
    frozen_key: str = ""
    extras: dict[str, object] = field(default_factory=dict)


def run_period(
    *,
    symbol: str,
    strategy_config: EMATrendConfig,
    wf_config: WalkForwardConfig,
    start: date,
    end: date,
    market_data: object,
    features: object,
    initial_capital: float,
    evaluator: object | None = None,
    strategy_factory: object | None = None,
) -> PeriodRun:
    """Replay [start, end] with warmup bars <= end only. Never sees post-end bars."""
    market = DateCappedMarket(market_data, end)
    feats = _EnsuringFeatures(DateCappedFeatures(features, end), strategy_config, market)
    engine_kwargs: dict[str, object] = {
        "market_data": market,
        "features": feats,
        "strategy_factory": strategy_factory or FrozenEMAFactory(strategy_config),
    }
    if evaluator is not None:
        engine_kwargs["evaluator"] = evaluator
    replay = HistoricalReplayEngine(
        ReplayConfig(
            symbols=[symbol],
            strategy_names=[wf_config.strategy_alias],
            start_date=start,
            end_date=end,
            speed=ReplaySpeed.FAST,
            min_history_bars=wf_config.min_history_bars,
        ),
        **engine_kwargs,  # type: ignore[arg-type]
    ).run()
    execution = OrderExecutionEngine(
        ExecutionConfig(
            initial_capital=initial_capital,
            position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
            percent=wf_config.percent,
            slippage_bps=wf_config.slippage_bps,
            brokerage_rate=wf_config.brokerage_rate,
            allow_fractional_shares=wf_config.allow_fractional_shares,
            min_quantity=wf_config.min_quantity,
            close_open_at_replay_end=True,
        ),
    )
    result = execution.process_replay_result(replay)
    trades = [
        trade
        for trade in result.trade_log
        if _as_date(trade.entry_timestamp) >= start and _as_date(trade.entry_timestamp) <= end
    ]
    equity = _equity_series(result, initial_capital)
    metrics = _metrics_from_run(
        strategy_config,
        trades,
        equity,
        initial_capital,
        float(result.final_account.equity),
    )
    used_max = frame_max_date(market.get_history(symbol)) or end
    return PeriodRun(
        trades=trades,
        equity=equity,
        metrics=metrics,
        used_max=used_max,
        rejected_count=len(result.rejected_orders),
        frozen_key=config_key(strategy_config),
    )


def _as_date(value: object) -> date:
    if hasattr(value, "date") and callable(value.date):
        try:
            return value.date()
        except Exception:
            pass
    return pd.Timestamp(value).date()


def _equity_series(result: object, initial: float) -> pd.Series:
    points: list[tuple[pd.Timestamp, float]] = []
    for attempt in getattr(result, "attempts", []):
        ts = None
        if getattr(attempt, "fill", None) is not None:
            ts = pd.Timestamp(attempt.fill.filled_at)
        elif getattr(attempt, "rejected", None) is not None:
            ts = pd.Timestamp(attempt.rejected.timestamp)
        if ts is None:
            continue
        points.append((ts, float(attempt.account.equity)))
    completed = getattr(result, "completed_at", None)
    final_equity = float(getattr(result, "final_account").equity)
    if completed is not None:
        points.append((pd.Timestamp(completed), final_equity))
    if not points:
        ts = pd.Timestamp(completed) if completed is not None else pd.Timestamp.utcnow()
        return pd.Series([final_equity], index=pd.DatetimeIndex([ts]))
    frame = pd.DataFrame(points, columns=["ts", "equity"]).drop_duplicates("ts", keep="last")
    series = frame.set_index("ts")["equity"].astype(float).sort_index()
    if float(series.iloc[0]) != float(initial):
        first_ts = series.index[0] - pd.Timedelta(seconds=1)
        series = pd.concat([pd.Series([float(initial)], index=[first_ts]), series])
    return series


def _metrics_from_run(
    strategy_config: EMATrendConfig,
    trades: list[ClosedTradeRecord],
    equity: pd.Series,
    initial_capital: float,
    final_equity: float,
) -> CandidateMetrics:
    dumped = [trade.model_dump() for trade in trades]
    curve = equity if len(equity) >= 2 else None
    perf = compute_performance(
        mode="walk_forward",
        trades=dumped,
        equity_curve=curve,
        initial_capital=initial_capital,
    )
    pf = float(perf.profit_factor)
    if pf == float("inf"):
        pf = 1_000_000.0
    return_pct = (final_equity - initial_capital) / initial_capital if initial_capital else 0.0
    score = (
        float(perf.sharpe_ratio)
        + return_pct * 0.5
        - float(perf.max_drawdown)
        + min(int(perf.total_trades), 20) * 0.001
    )
    return CandidateMetrics(
        config_key=config_key(strategy_config),
        parameters=config_params(strategy_config),
        score=float(score),
        return_pct=float(return_pct),
        sharpe=float(perf.sharpe_ratio),
        sortino=float(perf.sortino_ratio),
        max_drawdown=float(perf.max_drawdown),
        win_rate=float(perf.win_rate),
        profit_factor=pf,
        trade_count=int(perf.total_trades),
        total_costs=float(perf.commission_paid) + float(perf.slippage_paid),
        net_profit=float(perf.net_profit),
        gross_profit=float(perf.gross_profit),
    )
