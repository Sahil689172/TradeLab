"""Quantitative Momentum strategy — trend persistence via historical returns.

Not RSI. Ranking/scoring live in reusable ``MomentumEngine`` for portfolio/AI.
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
from app.strategies.momentum.config import MomentumConfig
from app.strategies.momentum.ranking import in_top_percentile, lookup_rank
from app.strategies.momentum.schemas import (
    MomentumPlan,
    MomentumSetup,
    MomentumUniverseRanking,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import Signal, SignalType, TradePlan

logger = get_logger(__name__)


class MomentumStrategy(BaseStrategy):
    """BUY top-momentum names with EMA / RS / VWAP / volume confirmation."""

    def __init__(
        self,
        config: MomentumConfig | None = None,
        *,
        ranking: MomentumUniverseRanking | None = None,
        volume_service: VolumeAnalysisService | None = None,
        vwap_service: VWAPService | None = None,
        condition_engine: ConditionEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or MomentumConfig()
        self._ranking = ranking
        self._volume = volume_service or VolumeAnalysisService(
            volume_column=self._config.volume_column,
            spike_multiple=self._config.relative_volume_threshold,
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
        self._last_detailed_plan: MomentumPlan | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> MomentumConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> MomentumPlan | None:
        return self._last_detailed_plan

    def bind_ranking(self, ranking: MomentumUniverseRanking) -> MomentumStrategy:
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
                f"Momentum strategy missing columns: {', '.join(missing)}",
            )
        if self._ranking is None:
            raise StrategyValidationError(
                "Momentum ranking required — call bind_ranking() first",
            )

    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        frame = features.copy()
        frame[self._config.date_column] = pd.to_datetime(frame[self._config.date_column])
        for column in (self._config.close_column, self._config.volume_column):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
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
        for column in ("open", "high", "low"):
            if column not in frame.columns:
                frame[column] = frame[self._config.close_column]

        try:
            frame = self._volume.attach(frame)
            frame = self._vwap.attach(frame)
        except (VolumeValidationError, VWAPValidationError) as exc:
            raise StrategyValidationError(str(exc)) from exc
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        setup = self._assess(features)
        return Signal(
            symbol=self._config.symbol,
            timestamp=self._timestamp(features),
            signal=setup.signal,
            confidence=self._confidence(setup),
            reason="; ".join(setup.reasons) if setup.reasons else "Momentum hold",
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
    ) -> MomentumPlan:
        setup = self._assess(features)
        if signal is None:
            signal = Signal(
                symbol=self._config.symbol,
                timestamp=self._timestamp(features),
                signal=setup.signal,
                confidence=self._confidence(setup),
                reason="; ".join(setup.reasons) if setup.reasons else "Momentum hold",
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

        reasons = [
            *setup.reasons,
            f"Momentum score={setup.momentum_score}",
            f"Relative strength={setup.relative_strength}",
            f"Momentum rank={setup.momentum_rank}",
            f"Holding estimate: ~{self._config.session_bars} bars",
            self._exit_note(features, entry_price, stop_loss, direction),
        ]

        plan = MomentumPlan(
            strategy_name=self.name,
            symbol=self._config.symbol,
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
            momentum_score=setup.momentum_score,
            relative_strength=setup.relative_strength,
            momentum_rank=setup.momentum_rank,
            setup=setup,
            timestamp=signal.timestamp,
        )
        logger.info(
            "Momentum plan %s %s rank=%s score=%s conf=%.3f",
            plan.symbol,
            plan.signal.value,
            plan.momentum_rank,
            plan.momentum_score,
            plan.confidence,
        )
        return plan

    def _assess(self, features: pd.DataFrame) -> MomentumSetup:
        ranking = self._require_ranking()
        ranked = lookup_rank(ranking, self._config.symbol)
        if ranked is None:
            return MomentumSetup(
                signal=SignalType.HOLD,
                top_momentum=False,
                ema_trend_bullish=False,
                relative_strength_ok=False,
                above_vwap=False,
                volume_healthy=False,
                reasons=[f"{self._config.symbol} not in momentum ranking"],
            )

        top = in_top_percentile(
            ranked,
            self._config.top_percentile,
            universe_size=ranking.universe_size,
        )
        ema_bullish = self._ema_trend_bullish(features)
        ema_bearish = self._ema_trend_bearish(features)
        rs_ok = ranked.score.relative_strength > self._config.relative_strength_threshold
        vwap_ok = self._above_vwap(features)
        volume_ok = self._volume_healthy(features)
        score_weak = ranked.score.momentum_score < self._config.momentum_sell_threshold

        signal = SignalType.HOLD
        direction: TradeDirection | None = None
        reasons: list[str] = []

        if score_weak or ema_bearish:
            signal = SignalType.SELL
            direction = TradeDirection.SHORT
            if score_weak:
                reasons.append(
                    f"Momentum score {ranked.score.momentum_score:.4f} "
                    f"below threshold {self._config.momentum_sell_threshold:g}",
                )
            if ema_bearish:
                reasons.append("EMA trend turned bearish")
        elif top and ema_bullish and rs_ok and vwap_ok and volume_ok:
            signal = SignalType.BUY
            direction = TradeDirection.LONG
            reasons = [
                f"Top {self._config.top_percentile:.0%} momentum (rank {ranked.rank})",
                "EMA trend bullish",
                f"Relative strength {ranked.score.relative_strength:.4f} "
                f"> {self._config.relative_strength_threshold:g}",
                "Close above VWAP",
                "Volume healthy",
            ]
        else:
            if not top:
                reasons.append(f"Rank {ranked.rank} outside top momentum sleeve")
            if not ema_bullish:
                reasons.append("EMA trend not bullish")
            if not rs_ok:
                reasons.append("Relative strength below threshold")
            if not vwap_ok:
                reasons.append("Close not above VWAP")
            if not volume_ok:
                reasons.append("Volume not healthy")

        return MomentumSetup(
            signal=signal,
            direction=direction,
            top_momentum=top,
            ema_trend_bullish=ema_bullish,
            relative_strength_ok=rs_ok,
            above_vwap=vwap_ok,
            volume_healthy=volume_ok,
            momentum_score=ranked.score.momentum_score,
            relative_strength=ranked.score.relative_strength,
            momentum_rank=ranked.rank,
            reasons=reasons,
        )

    def _ema_trend_bullish(self, features: pd.DataFrame) -> bool:
        fast, slow = self._ema_pair(features)
        if fast is None or slow is None:
            return False
        close = float(features.iloc[-1][self._config.close_column])
        return (
            self._conditions.compare(close, ComparisonOperator.GT, slow).value
            and self._conditions.compare(fast, ComparisonOperator.GTE, slow).value
        )

    def _ema_trend_bearish(self, features: pd.DataFrame) -> bool:
        fast, slow = self._ema_pair(features)
        if fast is None or slow is None:
            return False
        close = float(features.iloc[-1][self._config.close_column])
        return close < slow and fast <= slow

    def _ema_pair(self, features: pd.DataFrame) -> tuple[float | None, float | None]:
        fast_col = self._config.ema_fast_column
        slow_col = self._config.ema_slow_column
        if fast_col not in features.columns or slow_col not in features.columns:
            return None, None
        try:
            adapter = IndicatorAdapter(features)
            return adapter.indicator(fast_col).latest_value, adapter.indicator(slow_col).latest_value
        except IndicatorAdapterError:
            return float(features.iloc[-1][fast_col]), float(features.iloc[-1][slow_col])

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
        return self._conditions.compare(close, ComparisonOperator.GT, vwap).value

    def _confidence(self, setup: MomentumSetup) -> float:
        points = 0.0
        if setup.top_momentum:
            points += 30.0
        if setup.ema_trend_bullish:
            points += 20.0
        if setup.relative_strength_ok:
            points += 20.0
        if setup.above_vwap:
            points += 15.0
        if setup.volume_healthy:
            points += 15.0
        return points / 100.0

    def _require_ranking(self) -> MomentumUniverseRanking:
        if self._ranking is None:
            raise StrategyValidationError("Momentum ranking not bound")
        return self._ranking

    def _latest_atr(self, features: pd.DataFrame) -> float | None:
        if self._config.atr_column not in features.columns:
            return None
        values = pd.to_numeric(features[self._config.atr_column], errors="coerce").dropna()
        return float(values.iloc[-1]) if not values.empty else None

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
