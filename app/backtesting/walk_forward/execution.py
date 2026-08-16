"""Run a frozen strategy on a date window via A5.1 replay + A5.2 execution.

Indicator warmup uses candles with date <= period_end (including pre-start
history). Post-period candles are stripped by DateCapped adapters.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from app.backtesting.evaluation.metrics import compute_performance
from app.backtesting.order_execution import ExecutionConfig, OrderExecutionEngine, PositionSizingMode
from app.backtesting.order_execution.schemas import ClosedTradeRecord
from app.backtesting.replay_engine import HistoricalReplayEngine, ReplayConfig, ReplayResult, ReplaySpeed
from app.backtesting.replay_engine.adapters import ContextStrategyEvaluator
from app.backtesting.walk_forward.isolation import DateCappedFeatures, DateCappedMarket, frame_max_date
from app.backtesting.walk_forward.schemas import CandidateMetrics, WalkForwardConfig
from app.backtesting.walk_forward.search import config_key, config_params
from app.feature_engine.strategy_frame import ensure_strategy_indicators
from app.market_structure.schemas import TrendDirection
from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategy_engine.models import SignalType


class _HoldOnErrorEvaluator:
    """Keep a multi-candidate train replay alive if one bar fails confluence."""

    def __init__(self, inner: object) -> None:
        self._inner = inner

    def evaluate(self, *, strategy, symbol, window, timestamp, timeframe):  # noqa: ANN001
        try:
            return self._inner.evaluate(
                strategy=strategy,
                symbol=symbol,
                window=window,
                timestamp=timestamp,
                timeframe=timeframe,
            )
        except Exception:
            close = max(float(window.iloc[-1]["close"]), 0.01)
            return TradeRecommendation(
                strategy_name=getattr(strategy, "name", "ema_trend"),
                symbol=symbol,
                timeframe=timeframe or "1 Day",
                timestamp=timestamp,
                signal=SignalType.HOLD,
                entry_price=close,
                stop_loss=close * 0.98,
                target_1=close * 1.02,
                target_2=close * 1.04,
                risk_reward=1.0,
                confidence=0.0,
                expected_holding_period=1,
                reasons=["walk-forward skipped a bar that failed evaluation"],
                trend_direction=TrendDirection.SIDEWAYS,
                market_structure=TrendDirection.SIDEWAYS,
            )


class FrozenEMAFactory:
    """StrategyFactoryPort that always returns frozen EMA configuration(s)."""

    def __init__(self, configs: EMATrendConfig | list[EMATrendConfig]) -> None:
        if isinstance(configs, list):
            self._configs = configs
        else:
            self._configs = [configs]

    def resolve(self, names: object) -> list[EMATrendStrategy]:
        _ = names
        return [EMATrendStrategy(config) for config in self._configs]


def ensure_indicator_columns(
    frame: pd.DataFrame,
    config: EMATrendConfig,
    extra_periods: tuple[int, ...] = (),
) -> pd.DataFrame:
    """Fill missing indicator columns causally. Does not use future bars.

    Reuses Feature Engine ``ensure_strategy_indicators`` for canonical columns,
    then adds any extra EMA spans required by the frozen candidate (e.g. 12/26).
    """
    if frame is None or frame.empty:
        return frame
    out = ensure_strategy_indicators(frame)
    close = pd.to_numeric(out["close"], errors="coerce")
    periods = {int(config.fast_ema), int(config.slow_ema), *extra_periods}
    if config.ema200_filter or getattr(config, "trend_filter", False):
        periods.add(200)
    for period in sorted(periods):
        column = f"ema_{period}"
        if column not in out.columns:
            out[column] = close.ewm(span=period, adjust=False).mean()
    if "rsi_14" not in out.columns:
        out["rsi_14"] = 50.0
    else:
        out["rsi_14"] = pd.to_numeric(out["rsi_14"], errors="coerce")
        if out["rsi_14"].dropna().empty:
            out["rsi_14"] = 50.0
    return out


class _EnsuringFeatures:
    def __init__(
        self,
        inner: object,
        config: EMATrendConfig,
        market: object,
        extra_periods: tuple[int, ...] = (),
        cache: dict[tuple, pd.DataFrame] | None = None,
        until: date | None = None,
    ) -> None:
        self._inner = inner
        self._config = config
        self._market = market
        self._extra_periods = extra_periods
        self._cache = cache
        self._until = until

    def load_features(self, symbol: str) -> pd.DataFrame | None:
        key = (symbol.strip().upper(), self._until, self._extra_periods)
        if self._cache is not None and key in self._cache:
            return self._cache[key].copy()
        frame = self._inner.load_features(symbol) if self._inner is not None else None
        if frame is None or getattr(frame, "empty", False):
            frame = self._market.get_history(symbol)
        if frame is None:
            return None
        prepared = ensure_indicator_columns(frame, self._config, extra_periods=self._extra_periods)
        if self._cache is not None:
            self._cache[key] = prepared
        return prepared


@dataclass
class PeriodRun:
    trades: list[ClosedTradeRecord]
    equity: pd.Series
    metrics: CandidateMetrics
    used_max: date
    rejected_count: int = 0
    frozen_key: str = ""
    extras: dict[str, object] = field(default_factory=dict)


@contextmanager
def quiet_strategy_logs():
    """Drop per-candle INFO logs. They dominate walk-forward runtime on Windows."""
    names = (
        "app.strategy_engine.runner",
        "app.backtesting.replay_engine.engine",
        "app.backtesting.order_execution.broker",
        "app.backtesting.order_execution.engine",
        "app.services.strategy_context",
        "app.confluence",
        "app.strategies.ema_trend",
    )
    previous: list[tuple[logging.Logger, int]] = []
    for name in names:
        log = logging.getLogger(name)
        previous.append((log, log.level))
        log.setLevel(logging.ERROR)
    try:
        yield
    finally:
        for log, level in previous:
            log.setLevel(level)


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
    frame_cache: dict[tuple, pd.DataFrame] | None = None,
) -> PeriodRun:
    """Replay [start, end] with warmup bars <= end only. Never sees post-end bars."""
    with quiet_strategy_logs():
        replay, market = _replay(
            symbol=symbol,
            configs=[strategy_config],
            wf_config=wf_config,
            start=start,
            end=end,
            market_data=market_data,
            features=features,
            evaluator=evaluator,
            strategy_factory=strategy_factory,
            frame_cache=frame_cache,
        )
        return _execute_replay(
            replay,
            strategy_config=strategy_config,
            wf_config=wf_config,
            start=start,
            end=end,
            initial_capital=initial_capital,
            used_max=frame_max_date(market.get_history(symbol)) or end,
        )


def score_train_grid(
    *,
    symbol: str,
    candidates: list[EMATrendConfig],
    wf_config: WalkForwardConfig,
    start: date,
    end: date,
    market_data: object,
    features: object,
    initial_capital: float,
    frame_cache: dict[tuple, pd.DataFrame] | None = None,
) -> list[tuple[EMATrendConfig, PeriodRun]]:
    """One A5.1 pass for every declared candidate, then A5.2 per strategy.

    Avoids walking the same train candles once per parameter set. Broker state
    is still isolated: each candidate is filled in its own OrderExecutionEngine.
    """
    if not candidates:
        return []
    tagged: list[EMATrendConfig] = []
    for index, config in enumerate(candidates):
        tagged.append(config.model_copy(update={"strategy_name": f"wf{index:02d}"}))
    with quiet_strategy_logs():
        replay, market = _replay(
            symbol=symbol,
            configs=tagged,
            wf_config=wf_config,
            start=start,
            end=end,
            market_data=market_data,
            features=features,
            frame_cache=frame_cache,
        )
        used_max = frame_max_date(market.get_history(symbol)) or end
        out: list[tuple[EMATrendConfig, PeriodRun]] = []
        for original, tagged_config in zip(candidates, tagged):
            subset = replay.model_copy(
                update={
                    "steps": [step for step in replay.steps if step.strategy_name == tagged_config.strategy_name],
                },
            )
            period = _execute_replay(
                subset,
                strategy_config=original,
                wf_config=wf_config,
                start=start,
                end=end,
                initial_capital=initial_capital,
                used_max=used_max,
            )
            out.append((original, period))
        return out


def _replay(
    *,
    symbol: str,
    configs: list[EMATrendConfig],
    wf_config: WalkForwardConfig,
    start: date,
    end: date,
    market_data: object,
    features: object,
    evaluator: object | None = None,
    strategy_factory: object | None = None,
    frame_cache: dict[tuple, pd.DataFrame] | None = None,
) -> tuple[ReplayResult, DateCappedMarket]:
    extra_periods = tuple(sorted({int(cfg.fast_ema) for cfg in configs} | {int(cfg.slow_ema) for cfg in configs}))
    market = DateCappedMarket(market_data, end)
    feats = _EnsuringFeatures(
        DateCappedFeatures(features, end),
        configs[0],
        market,
        extra_periods=extra_periods,
        cache=frame_cache,
        until=end,
    )
    engine_kwargs: dict[str, object] = {
        "market_data": market,
        "features": feats,
        "strategy_factory": strategy_factory or FrozenEMAFactory(configs),
    }
    if evaluator is not None:
        engine_kwargs["evaluator"] = evaluator
    else:
        engine_kwargs["evaluator"] = _HoldOnErrorEvaluator(ContextStrategyEvaluator(timeframe="1 Day"))
    min_history = int(wf_config.min_history_bars)
    if evaluator is None:
        min_history = max(min_history, 15)
    replay = HistoricalReplayEngine(
        ReplayConfig(
            symbols=[symbol],
            strategy_names=[wf_config.strategy_alias],
            start_date=start,
            end_date=end,
            speed=ReplaySpeed.FAST,
            min_history_bars=min_history,
        ),
        **engine_kwargs,  # type: ignore[arg-type]
    ).run()
    return replay, market


def _execute_replay(
    replay: ReplayResult,
    *,
    strategy_config: EMATrendConfig,
    wf_config: WalkForwardConfig,
    start: date,
    end: date,
    initial_capital: float,
    used_max: date,
) -> PeriodRun:
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


def _utc_ts(value: object) -> pd.Timestamp:
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        return stamp.tz_localize("UTC")
    return stamp.tz_convert("UTC")


def _equity_series(result: object, initial: float) -> pd.Series:
    points: list[tuple[pd.Timestamp, float]] = []
    for attempt in getattr(result, "attempts", []):
        ts = None
        if getattr(attempt, "fill", None) is not None:
            ts = _utc_ts(attempt.fill.filled_at)
        elif getattr(attempt, "rejected", None) is not None:
            ts = _utc_ts(attempt.rejected.timestamp)
        if ts is None:
            continue
        points.append((ts, float(attempt.account.equity)))
    completed = getattr(result, "completed_at", None)
    final_equity = float(getattr(result, "final_account").equity)
    if completed is not None:
        points.append((_utc_ts(completed), final_equity))
    if not points:
        ts = _utc_ts(completed) if completed is not None else pd.Timestamp.utcnow()
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return pd.Series([final_equity], index=pd.DatetimeIndex([ts]))
    frame = pd.DataFrame(points, columns=["ts", "equity"]).drop_duplicates("ts", keep="last")
    series = frame.set_index("ts")["equity"].astype(float).sort_index()
    if float(series.iloc[0]) != float(initial):
        first_ts = series.index[0] - pd.Timedelta(seconds=1)
        series = pd.concat([pd.Series([float(initial)], index=pd.DatetimeIndex([first_ts])), series])
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
