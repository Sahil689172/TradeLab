"""Relative Strength strategy — trade top-ranked names vs NIFTY50 benchmark.

This is cross-sectional strength vs the universe, NOT the RSI oscillator.
Ranking/scoring live in ``scoring.py`` / ``ranking.py`` / ``screener.py``.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine, ComparisonOperator
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.indicator_adapter import IndicatorAdapter, IndicatorAdapterError
from app.risk_engine.schemas import TradeDirection
from app.risk_engine.stops import take_profit_from_risk
from app.services.strategy_engine.indicators.volume_analysis import (
    VolumeAnalysisService,
    VolumeValidationError,
)
from app.services.strategy_engine.indicators.vwap import VWAPService, VWAPValidationError
from app.strategies.relative_strength.config import RelativeStrengthConfig
from app.strategies.relative_strength.ranking import (
    below_sell_percentile,
    in_top_percentile,
    lookup_rank,
)
from app.strategies.relative_strength.schemas import (
    RelativeStrengthPlan,
    RelativeStrengthSetup,
    UniverseRanking,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import Signal, SignalType, TradePlan

logger = get_logger(__name__)


class RelativeStrengthStrategy(BaseStrategy):
    """BUY top-percentile RS names with EMA / volume / VWAP confirmation."""

    def __init__(
        self,
        config: RelativeStrengthConfig | None = None,
        *,
        ranking: UniverseRanking | None = None,
        volume_service: VolumeAnalysisService | None = None,
        vwap_service: VWAPService | None = None,
        condition_engine: ConditionEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or RelativeStrengthConfig()
        self._ranking = ranking
        self._volume = volume_service or VolumeAnalysisService(
            volume_column=self._config.volume_column,
            spike_multiple=self._config.relative_volume_threshold,
            relative_volume_20_column="relative_volume_20",
        )
        self._vwap = vwap_service or VWAPService(
            date_column=self._config.date_column,
            close_column=self._config.close_column,
            volume_column=self._config.volume_column,
            vwap_column=self._config.vwap_column,
        )
        self._conditions = condition_engine or ConditionEngine()
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                max_bars=self._config.session_bars,
                enabled_methods=(ExitMethod.TIME_EXIT,),
            ),
        )
        self._last_detailed_plan: RelativeStrengthPlan | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> RelativeStrengthConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> RelativeStrengthPlan | None:
        return self._last_detailed_plan

    def bind_ranking(self, ranking: UniverseRanking) -> RelativeStrengthStrategy:
        self._ranking = ranking
        return self

    def validate(self, features: pd.DataFrame) -> None:
        if not isinstance(features, pd.DataFrame):
            raise StrategyValidationError("features must be a pandas DataFrame")
        if features.empty:
            raise StrategyValidationError("features must not be empty")
        required = {
            self._config.date_column,
            self._config.close_column,
            self._config.volume_column,
        }
        missing = sorted(column for column in required if column not in features.columns)
        if missing:
            raise StrategyValidationError(
                f"Relative strength missing columns: {', '.join(missing)}",
            )
        if self._ranking is None:
            raise StrategyValidationError(
                "Universe ranking required — call bind_ranking() first",
            )

    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        frame = features.copy()
        frame[self._config.date_column] = pd.to_datetime(frame[self._config.date_column])
        frame[self._config.close_column] = pd.to_numeric(
            frame[self._config.close_column],
            errors="coerce",
        )
        frame[self._config.volume_column] = pd.to_numeric(
            frame[self._config.volume_column],
            errors="coerce",
        )
        for column in ("open", "high", "low"):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")
        for column in (
            self._config.ema_fast_column,
            self._config.ema_slow_column,
            self._config.atr_column,
        ):
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = (
            frame.dropna(subset=[self._config.close_column, self._config.volume_column])
            .drop_duplicates(subset=[self._config.date_column], keep="last")
            .sort_values(self._config.date_column)
            .reset_index(drop=True)
        )
        # Ensure OHLC present for VWAP (use close as proxy when missing)
        for column in ("open", "high", "low"):
            if column not in frame.columns:
                frame[column] = frame[self._config.close_column]

        try:
            frame = self._volume.attach(frame)
        except VolumeValidationError as exc:
            raise StrategyValidationError(str(exc)) from exc
        try:
            frame = self._vwap.attach(frame)
        except VWAPValidationError as exc:
            raise StrategyValidationError(str(exc)) from exc
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        setup = self._assess(features)
        confidence = self._confidence(setup)
        return Signal(
            symbol=self.active_symbol,
            timestamp=self._timestamp(features),
            signal=setup.signal,
            confidence=confidence,
            reason="; ".join(setup.reasons) if setup.reasons else "RS hold",
        )

    def generate_trade_plan(self, features: pd.DataFrame, signal: Signal) -> TradePlan:
        detailed = self.generate_detailed_trade_plan(features, signal)
        self._last_detailed_plan = detailed
        return TradePlan(
            symbol=detailed.symbol,
            entry_price=detailed.entry_price,
            signal=detailed.signal,
            stop_loss=detailed.stop_loss,
            take_profit_1=detailed.take_profit_1,
            take_profit_2=detailed.take_profit_2,
            holding_period=detailed.expected_holding_bars,
            risk_reward=detailed.risk_reward,
            confidence=detailed.confidence,
            reasons=detailed.reasons,
            strategy_name=detailed.strategy_name,
        )

    def generate_detailed_trade_plan(
        self,
        features: pd.DataFrame,
        signal: Signal | None = None,
    ) -> RelativeStrengthPlan:
        setup = self._assess(features)
        if signal is None:
            signal = Signal(
                symbol=self.active_symbol,
                timestamp=self._timestamp(features),
                signal=setup.signal,
                confidence=self._confidence(setup),
                reason="; ".join(setup.reasons) if setup.reasons else "RS hold",
            )

        entry_price = float(features.iloc[-1][self._config.close_column])
        direction = setup.direction or TradeDirection.LONG
        atr_value = self._latest_atr(features)
        if atr_value is not None and atr_value > 0:
            stop_loss = (
                entry_price - atr_value * self._config.atr_stop_multiplier
                if direction is TradeDirection.LONG
                else entry_price + atr_value * self._config.atr_stop_multiplier
            )
        else:
            stop_loss = entry_price * (0.97 if direction is TradeDirection.LONG else 1.03)

        take_profit_1, realized_rr = take_profit_from_risk(
            entry_price,
            stop_loss,
            direction,
            self._config.risk_reward_1,
        )
        take_profit_2 = (
            take_profit_1 + abs(take_profit_1 - entry_price) * 0.5
            if direction is TradeDirection.LONG
            else take_profit_1 - abs(entry_price - take_profit_1) * 0.5
        )

        ranked = lookup_rank(self._require_ranking(), self.active_symbol)
        score = ranked.score if ranked is not None else None
        benchmark_comparison = None
        sector_comparison = None
        if score is not None:
            benchmark_comparison = (
                f"RS 3m={score.rs_3m:.2%} 6m={score.rs_6m:.2%} 12m={score.rs_12m:.2%} "
                f"vs {self._config.benchmark_symbol}"
            )
            if score.sector and score.sector_strength is not None:
                sector_comparison = (
                    f"Sector {score.sector} strength={score.sector_strength:.4f}; "
                    f"stock strength={score.strength_score:.4f}"
                )

        exit_note = self._exit_note(features, entry_price, stop_loss, direction)
        reasons = [
            *setup.reasons,
            f"Current rank={setup.current_rank} previous={setup.previous_rank}",
            f"Strength score={score.strength_score if score else 'n/a'}",
            f"Momentum score={score.relative_momentum if score else 'n/a'}",
            benchmark_comparison or "Benchmark comparison unavailable",
            sector_comparison or "Sector comparison unavailable",
            exit_note,
        ]

        plan = RelativeStrengthPlan(
            strategy_name=self.name,
            symbol=self.active_symbol,
            entry_price=entry_price,
            direction=direction,
            signal=signal.signal,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confidence=signal.confidence,
            risk_reward=realized_rr,
            expected_holding_bars=self._config.session_bars,
            reasons=reasons,
            current_rank=setup.current_rank,
            previous_rank=setup.previous_rank,
            strength_score=score.strength_score if score else None,
            momentum_score=score.relative_momentum if score else None,
            benchmark_comparison=benchmark_comparison,
            sector_comparison=sector_comparison,
            setup=setup,
            timestamp=signal.timestamp,
        )
        logger.info(
            "RS plan %s %s rank=%s signal=%s conf=%.3f",
            plan.symbol,
            plan.signal.value,
            plan.current_rank,
            plan.signal.value,
            plan.confidence,
        )
        return plan

    def _assess(self, features: pd.DataFrame) -> RelativeStrengthSetup:
        ranking = self._require_ranking()
        ranked = lookup_rank(ranking, self.active_symbol)
        reasons: list[str] = []
        if ranked is None:
            return RelativeStrengthSetup(
                signal=SignalType.HOLD,
                in_top_percentile=False,
                ema_trend_bullish=False,
                volume_healthy=False,
                above_vwap=False,
                reasons=[f"{self.active_symbol} not found in universe ranking"],
            )

        top = in_top_percentile(
            ranked,
            self._config.top_percentile,
            universe_size=ranking.universe_size,
        )
        sell = below_sell_percentile(
            ranked,
            self._config.sell_rank_percentile,
            universe_size=ranking.universe_size,
        )
        ema_ok = self._ema_trend_bullish(features)
        volume_ok = self._volume_healthy(features)
        vwap_ok = self._above_vwap(features)

        signal = SignalType.HOLD
        direction: TradeDirection | None = None

        if sell and not top:
            signal = SignalType.SELL
            direction = TradeDirection.SHORT
            reasons = [
                f"Rank {ranked.rank}/{ranking.universe_size} fell below sell band "
                f"(percentile cut {self._config.sell_rank_percentile:.0%})",
            ]
        elif top and ema_ok and volume_ok and vwap_ok:
            signal = SignalType.BUY
            direction = TradeDirection.LONG
            reasons = [
                f"Top {self._config.top_percentile:.0%} RS (rank {ranked.rank})",
                "EMA trend bullish",
                "Volume healthy",
                "Close above VWAP",
            ]
        else:
            if not top:
                reasons.append(
                    f"Rank {ranked.rank} outside top {self._config.top_percentile:.0%}",
                )
            if not ema_ok:
                reasons.append("EMA trend not bullish")
            if not volume_ok:
                reasons.append("Volume not healthy")
            if not vwap_ok:
                reasons.append("Close not above VWAP")

        return RelativeStrengthSetup(
            signal=signal,
            direction=direction,
            in_top_percentile=top,
            ema_trend_bullish=ema_ok,
            volume_healthy=volume_ok,
            above_vwap=vwap_ok,
            current_rank=ranked.rank,
            previous_rank=ranked.previous_rank,
            percentile=ranked.percentile,
            reasons=reasons,
        )

    def _ema_trend_bullish(self, features: pd.DataFrame) -> bool:
        fast_col = self._config.ema_fast_column
        slow_col = self._config.ema_slow_column
        if fast_col not in features.columns or slow_col not in features.columns:
            return False
        try:
            adapter = IndicatorAdapter(features)
            fast = adapter.indicator(fast_col).latest_value
            slow = adapter.indicator(slow_col).latest_value
        except IndicatorAdapterError:
            fast = float(features.iloc[-1][fast_col])
            slow = float(features.iloc[-1][slow_col])
        if fast is None or slow is None:
            return False
        close = float(features.iloc[-1][self._config.close_column])
        above_slow = self._conditions.compare(
            close,
            ComparisonOperator.GT,
            slow,
            left_label="close",
            right_label=slow_col,
        ).value
        stack = self._conditions.compare(
            fast,
            ComparisonOperator.GTE,
            slow,
            left_label=fast_col,
            right_label=slow_col,
        ).value
        return above_slow and stack

    def _volume_healthy(self, features: pd.DataFrame) -> bool:
        stats = self._volume.snapshot(features)
        return self._volume.meets_relative_threshold(
            stats,
            threshold=self._config.relative_volume_threshold,
        ) or stats.above_average_20

    def _above_vwap(self, features: pd.DataFrame) -> bool:
        if self._config.vwap_column not in features.columns:
            return False
        close = float(features.iloc[-1][self._config.close_column])
        vwap = float(features.iloc[-1][self._config.vwap_column])
        return self._conditions.compare(
            close,
            ComparisonOperator.GT,
            vwap,
            left_label="close",
            right_label="VWAP",
        ).value

    def _confidence(self, setup: RelativeStrengthSetup) -> float:
        points = 0.0
        if setup.in_top_percentile:
            points += 40.0
        if setup.ema_trend_bullish:
            points += 20.0
        if setup.volume_healthy:
            points += 20.0
        if setup.above_vwap:
            points += 20.0
        return points / 100.0

    def _require_ranking(self) -> UniverseRanking:
        if self._ranking is None:
            raise StrategyValidationError("Universe ranking not bound")
        return self._ranking

    def _latest_atr(self, features: pd.DataFrame) -> float | None:
        if self._config.atr_column not in features.columns:
            return None
        values = pd.to_numeric(features[self._config.atr_column], errors="coerce").dropna()
        if values.empty:
            return None
        return float(values.iloc[-1])

    def _timestamp(self, features: pd.DataFrame) -> datetime:
        return pd.Timestamp(features.iloc[-1][self._config.date_column]).to_pydatetime()

    def _exit_note(
        self,
        features: pd.DataFrame,
        entry_price: float,
        stop_loss: float,
        direction: TradeDirection,
    ) -> str:
        close = float(features.iloc[-1][self._config.close_column])
        high = float(features.iloc[-1]["high"]) if "high" in features.columns else close
        low = float(features.iloc[-1]["low"]) if "low" in features.columns else close
        state = make_state(
            entry_price=entry_price,
            direction=direction,
            bars_held=self._config.session_bars,
            extreme_high=max(entry_price, high),
            extreme_low=min(entry_price, low),
        )
        decision = self._exits.evaluate(
            state=state,
            market=features,
            config=ExitConfig(
                initial_stop=stop_loss,
                max_bars=self._config.session_bars,
                enabled_methods=(ExitMethod.TIME_EXIT,),
            ),
        )
        return f"Exit engine: {decision.reason}"
