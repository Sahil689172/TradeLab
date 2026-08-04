"""Historical Replay Engine — candle-by-candle Strategy Engine feed."""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from app.backtesting.replay_engine.adapters import (
    ContextStrategyEvaluator,
    FrameworkStrategyFactory,
    ParquetFeatureFrameAdapter,
    ParquetMarketDataAdapter,
)
from app.backtesting.replay_engine.events import (
    NewCandle,
    RecommendationGenerated,
    ReplayCompleted,
    ReplayEvent,
    ReplayStarted,
    StrategyEvaluation,
)
from app.backtesting.replay_engine.exceptions import ReplayConfigurationError
from app.backtesting.replay_engine.protocols import (
    FeatureFramePort,
    MarketDataPort,
    ReplayEventListener,
    StrategyEvaluatorPort,
    StrategyFactoryPort,
)
from app.backtesting.replay_engine.replay_session import ReplaySession
from app.backtesting.replay_engine.scheduler import ReplayScheduler
from app.backtesting.replay_engine.schemas import (
    ReplayConfig,
    ReplayResult,
    ReplayStepResult,
)
from app.core.logging import get_logger
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError

logger = get_logger(__name__)


class _NullListener:
    def on_event(self, event: object) -> None:
        return None


class HistoricalReplayEngine:
    """Replay historical OHLCV into the existing Strategy Engine.

    Guarantees zero look-ahead: each evaluation receives only candles with
    ``date <= current replay timestamp``.

    No order execution, portfolio, or PnL — recommendations only.
    """

    def __init__(
        self,
        config: ReplayConfig,
        *,
        market_data: MarketDataPort | None = None,
        features: FeatureFramePort | None = None,
        evaluator: StrategyEvaluatorPort | None = None,
        strategy_factory: StrategyFactoryPort | None = None,
        scheduler: ReplayScheduler | None = None,
        listener: ReplayEventListener | None = None,
    ) -> None:
        self._config = config
        storage = config.storage_dir
        self._market_data = market_data or ParquetMarketDataAdapter(storage)
        self._features = features or ParquetFeatureFrameAdapter(storage)
        self._evaluator = evaluator or ContextStrategyEvaluator(
            storage_dir=storage,
            timeframe=config.timeframe,
        )
        self._strategy_factory = strategy_factory or FrameworkStrategyFactory(
            timeframe=config.timeframe,
        )
        self._scheduler = scheduler or ReplayScheduler(
            config.speed,
            realtime_sleep_seconds=config.realtime_sleep_seconds,
        )
        self._listener = listener or _NullListener()
        self._min_history_bars = config.min_history_bars

    @property
    def config(self) -> ReplayConfig:
        return self._config

    def run(self) -> ReplayResult:
        """Replay all configured symbols (sequential) and collect step results."""
        started_at = datetime.now(timezone.utc)
        strategies = self._strategy_factory.resolve(self._config.strategy_names)
        if not strategies:
            raise ReplayConfigurationError("No strategies resolved for replay")

        self._min_history_bars = max(
            [self._config.min_history_bars]
            + [
                _strategy_min_history(strategy, fallback=self._config.min_history_bars)
                for strategy in strategies
            ],
        )

        steps: list[ReplayStepResult] = []
        errors: list[str] = []
        candles_replayed = 0
        recommendations = 0

        for symbol in self._config.symbols:
            try:
                symbol_steps, advanced = self._run_symbol(symbol, strategies)
                steps.extend(symbol_steps)
                candles_replayed += advanced
                recommendations += len(symbol_steps)
            except Exception as exc:  # noqa: BLE001 — continue other symbols
                message = f"{symbol}: {type(exc).__name__}: {exc}"
                logger.exception("Replay failed for %s", symbol)
                errors.append(message)

        completed_at = datetime.now(timezone.utc)
        return ReplayResult(
            started_at=started_at,
            completed_at=completed_at,
            config=self._config,
            steps=steps,
            candles_replayed=candles_replayed,
            recommendations_generated=recommendations,
            symbols=list(self._config.symbols),
            errors=errors,
        )

    def create_session(self, symbol: str) -> ReplaySession:
        """Build a ready session for ``symbol`` with date filters applied."""
        frame = self._load_replay_frame(symbol)
        start_index = self._resolve_start_index(frame)
        return ReplaySession(
            symbol,
            frame,
            speed=self._config.speed,
            start_index=start_index,
        )

    def _run_symbol(
        self,
        symbol: str,
        strategies: list[BaseStrategy],
    ) -> tuple[list[ReplayStepResult], int]:
        session = self.create_session(symbol)
        feature_frame = self._features.load_features(symbol)

        self._emit(
            ReplayStarted(
                timestamp=datetime.now(timezone.utc),
                symbol=symbol,
                total_candles=session.total_candles - session.start_index,
                start_index=session.start_index,
            ),
        )
        session.start()

        steps: list[ReplayStepResult] = []
        previous_ts: datetime | None = None
        steps_taken = 0

        while session.has_more():
            if self._config.max_steps is not None and steps_taken >= self._config.max_steps:
                break

            candle = session.advance()
            ts = pd.Timestamp(candle["date"]).to_pydatetime()
            self._scheduler.wait_before_next(
                previous_timestamp=previous_ts,
                current_timestamp=ts,
            )
            previous_ts = ts
            steps_taken += 1

            self._emit(
                NewCandle(
                    timestamp=ts,
                    symbol=symbol,
                    replay_index=session.current_index,
                    open=float(candle["open"]),
                    high=float(candle["high"]),
                    low=float(candle["low"]),
                    close=float(candle["close"]),
                    volume=float(candle["volume"]),
                ),
            )

            # Warm-up: skip until the evaluation window satisfies strategy history
            window = self._build_evaluation_window(session, feature_frame)
            if len(window) < self._min_history_bars:
                continue

            close_price = float(candle["close"])

            for strategy in strategies:
                required = _strategy_min_history(strategy, fallback=self._config.min_history_bars)
                if len(window) < required:
                    continue

                self._emit(
                    StrategyEvaluation(
                        timestamp=ts,
                        symbol=symbol,
                        strategy_name=strategy.name,
                        replay_index=session.current_index,
                        window_size=len(window),
                    ),
                )
                try:
                    recommendation = self._evaluator.evaluate(
                        strategy=strategy,
                        symbol=symbol,
                        window=window,
                        timestamp=ts,
                        timeframe=self._config.timeframe,
                    )
                except StrategyValidationError as exc:
                    # Soft-skip warm-up / contract misses; do not abort the symbol.
                    message = str(exc).lower()
                    if "need at least" in message or "bars" in message:
                        logger.debug(
                            "Skipping %s @ %s for %s: %s",
                            strategy.name,
                            ts,
                            symbol,
                            exc,
                        )
                        continue
                    raise

                self._emit(
                    RecommendationGenerated(
                        timestamp=ts,
                        symbol=symbol,
                        strategy_name=strategy.name,
                        signal=recommendation.signal,
                        confidence=recommendation.confidence,
                        recommendation=recommendation,
                    ),
                )
                steps.append(
                    ReplayStepResult(
                        timestamp=ts,
                        symbol=symbol,
                        strategy_name=strategy.name,
                        current_close=close_price,
                        replay_index=session.current_index,
                        signal=recommendation.signal,
                        confidence=recommendation.confidence,
                        stop_loss=recommendation.stop_loss,
                        target_1=recommendation.target_1,
                        target_2=recommendation.target_2,
                        expected_holding_period=recommendation.expected_holding_period,
                        recommendation=recommendation,
                    ),
                )

        session.mark_completed()
        self._emit(
            ReplayCompleted(
                timestamp=datetime.now(timezone.utc),
                symbol=symbol,
                candles_replayed=steps_taken,
                recommendations_generated=len(steps),
            ),
        )
        return steps, steps_taken

    def _build_evaluation_window(
        self,
        session: ReplaySession,
        feature_frame: pd.DataFrame | None,
    ) -> pd.DataFrame:
        """Historical OHLCV window, optionally joined with causal feature rows."""
        ohlcv_window = session.historical_window()
        if feature_frame is None:
            return ohlcv_window
        clipped = session.slice_features_to_cursor(feature_frame)
        # Prefer feature frame when it already includes OHLCV; else merge on date
        from app.feature_engine.strategy_frame import (
            features_include_ohlcv,
            merge_ohlcv_features,
        )

        if features_include_ohlcv(clipped):
            session.assert_no_lookahead(clipped)
            return clipped
        if clipped.empty:
            return ohlcv_window
        merged = merge_ohlcv_features(ohlcv_window, clipped)
        session.assert_no_lookahead(merged)
        return merged

    def _load_replay_frame(self, symbol: str) -> pd.DataFrame:
        try:
            raw = self._market_data.get_history(symbol)
        except Exception as exc:  # noqa: BLE001
            raise ReplayConfigurationError(
                f"Unable to load OHLCV for {symbol}: {exc}",
            ) from exc
        frame = raw.copy()
        if "date" not in frame.columns:
            raise ReplayConfigurationError(f"{symbol}: OHLCV missing 'date' column")
        frame["date"] = pd.to_datetime(frame["date"])
        frame = (
            frame.dropna(subset=["date"])
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
        if frame.empty:
            raise ReplayConfigurationError(f"{symbol}: OHLCV history is empty")
        # Keep pre-start bars for warm-up; end_date still truncates the series.
        if self._config.end_date is not None:
            end_ts = (
                pd.Timestamp(self._config.end_date)
                + pd.Timedelta(days=1)
                - pd.Timedelta(nanoseconds=1)
            )
            frame = frame.loc[frame["date"] <= end_ts].reset_index(drop=True)
        if frame.empty:
            raise ReplayConfigurationError(
                f"{symbol}: no candles on or before end_date={self._config.end_date}",
            )
        return frame

    def _resolve_start_index(self, frame: pd.DataFrame) -> int:
        """First candle to *emit*; earlier rows remain available in the window."""
        if self._config.start_date is None:
            return 0
        start_ts = pd.Timestamp(self._config.start_date)
        matches = frame.index[frame["date"] >= start_ts].tolist()
        if not matches:
            raise ReplayConfigurationError(
                f"No candles on or after start_date={self._config.start_date}",
            )
        return int(matches[0])

    def _emit(self, event: ReplayEvent) -> None:
        self._listener.on_event(event)


def _strategy_min_history(strategy: BaseStrategy, *, fallback: int) -> int:
    """Read ``config.min_history_bars`` when present; otherwise ``fallback``."""
    config = getattr(strategy, "config", None)
    if config is None:
        config = getattr(strategy, "_config", None)
    if config is None:
        return fallback
    value = getattr(config, "min_history_bars", None)
    if value is None:
        return fallback
    try:
        return max(fallback, int(value))
    except (TypeError, ValueError):
        return fallback
