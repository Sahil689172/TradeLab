"""EMA Trend Following strategy — production implementation.

Uses only:
    Strategy Foundation, Indicator Adapter, Condition Engine,
    Risk Engine, Exit Engine, Confluence Engine.

Indicators are read from Feature Engine columns via IndicatorAdapter.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine, ComparisonOperator
from app.confluence import ConfluenceConfig, ConfluenceEngine, ModuleWeights
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.indicator_adapter import IndicatorAdapter
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine import RiskConfig, RiskEngine, StopMethod, TradeDirection
from app.strategies.ema_trend.config import EMATrendConfig
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import Signal, SignalType, TradePlan

logger = get_logger(__name__)


class EMATrendStrategy(BaseStrategy):
    """EMA20/EMA50 trend-following strategy with ATR risk and confluence confidence."""

    def __init__(
        self,
        config: EMATrendConfig | None = None,
        *,
        condition_engine: ConditionEngine | None = None,
        risk_engine: RiskEngine | None = None,
        exit_engine: ExitEngine | None = None,
        confluence_engine: ConfluenceEngine | None = None,
    ) -> None:
        self._config = config or EMATrendConfig()
        self._conditions = condition_engine or ConditionEngine()
        self._risk = risk_engine or RiskEngine(
            RiskConfig(
                preferred_stop=StopMethod.ATR,
                atr_column=self._config.atr_column,
                atr_multiplier=self._config.atr_stop_multiplier,
                risk_reward=self._config.risk_reward_1,
                time_stop_bars=self._config.holding_period_default,
            ),
        )
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                atr_column=self._config.atr_column,
                atr_multiplier=self._config.atr_stop_multiplier,
                trailing_atr_multiplier=self._config.trailing_atr_multiplier,
                ema_column=self._config.ema_fast_column,
                max_bars=self._config.holding_period_max,
                enabled_methods=(
                    ExitMethod.TRAILING_STOP,
                    ExitMethod.EMA_EXIT,
                    ExitMethod.TIME_EXIT,
                ),
            ),
        )
        self._confluence = confluence_engine or ConfluenceEngine(
            ConfluenceConfig(
                weights=ModuleWeights(
                    ema=25,
                    rsi=10,
                    volume=10,
                    structure=0,
                    atr=15,
                    levels=0,
                    trend=40,
                ),
                ema_fast_column=self._config.ema_fast_column,
                ema_slow_column=self._config.ema_slow_column,
                atr_column=self._config.atr_column,
                adx_column=self._config.adx_column,
                close_column=self._config.close_column,
                adx_trend_threshold=self._config.adx_threshold,
            ),
        )

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> EMATrendConfig:
        return self._config

    def validate(self, features: pd.DataFrame) -> None:
        if not isinstance(features, pd.DataFrame):
            raise StrategyValidationError("features must be a pandas DataFrame")
        if features.empty:
            raise StrategyValidationError("features must not be empty")

        required = {
            self._config.date_column,
            self._config.close_column,
            self._config.ema_fast_column,
            self._config.ema_slow_column,
            self._config.adx_column,
            self._config.atr_column,
        }
        missing = sorted(column for column in required if column not in features.columns)
        if missing:
            raise StrategyValidationError(
                f"EMA trend strategy missing required columns: {', '.join(missing)}",
            )
        if len(features) < self._config.min_history_bars:
            raise StrategyValidationError(
                f"Need at least {self._config.min_history_bars} bars, got {len(features)}",
            )

    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        frame = features.copy()
        frame[self._config.date_column] = pd.to_datetime(frame[self._config.date_column])
        numeric_cols = [
            self._config.close_column,
            self._config.ema_fast_column,
            self._config.ema_slow_column,
            self._config.adx_column,
            self._config.atr_column,
        ]
        for column in numeric_cols:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = (
            frame.drop_duplicates(subset=[self._config.date_column], keep="last")
            .sort_values(self._config.date_column)
            .reset_index(drop=True)
        )
        # Keep rows where the strategy inputs are defined.
        frame = frame.dropna(subset=numeric_cols).reset_index(drop=True)
        if len(frame) < 2:
            raise StrategyValidationError(
                "Prepared features need at least 2 rows with valid EMA/ADX/ATR/close",
            )
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        snapshot = self._snapshot(features)
        timestamp = snapshot.timestamp
        symbol = self._config.symbol

        if snapshot.cross_below.value:
            return Signal(
                symbol=symbol,
                timestamp=timestamp,
                signal=SignalType.EXIT,
                confidence=max(0.55, snapshot.confidence),
                reason=(
                    f"Exit: {snapshot.cross_below.reason}; "
                    f"planned ATR trailing also monitored"
                ),
            )

        entry_ok = (
            snapshot.cross_above.value
            and snapshot.adx_ok.value
            and snapshot.close_above_slow.value
        )
        if entry_ok:
            return Signal(
                symbol=symbol,
                timestamp=timestamp,
                signal=SignalType.BUY,
                confidence=snapshot.confidence,
                reason=(
                    f"Entry: {snapshot.cross_above.reason}; "
                    f"{snapshot.adx_ok.reason}; {snapshot.close_above_slow.reason}"
                ),
            )

        reasons = []
        if not snapshot.cross_above.value:
            reasons.append(snapshot.cross_above.reason)
        if not snapshot.adx_ok.value:
            reasons.append(snapshot.adx_ok.reason)
        if not snapshot.close_above_slow.value:
            reasons.append(snapshot.close_above_slow.reason)
        return Signal(
            symbol=symbol,
            timestamp=timestamp,
            signal=SignalType.HOLD,
            confidence=min(0.5, snapshot.confidence),
            reason="Hold: " + "; ".join(reasons),
        )

    def generate_trade_plan(self, features: pd.DataFrame, signal: Signal) -> TradePlan:
        snapshot = self._snapshot(features)
        entry_price = snapshot.close
        risk_plan = self._risk.compute(
            entry_price=entry_price,
            direction=TradeDirection.LONG,
            features=features,
            market_structure=_neutral_structure(len(features)),
            config=RiskConfig(
                preferred_stop=StopMethod.ATR,
                atr_column=self._config.atr_column,
                atr_multiplier=self._config.atr_stop_multiplier,
                risk_reward=self._config.risk_reward_1,
                time_stop_bars=self._holding_period(snapshot.atr),
            ),
        )

        risk_distance = abs(entry_price - risk_plan.stop_loss)
        take_profit_1 = entry_price + risk_distance * self._config.risk_reward_1
        take_profit_2 = entry_price + risk_distance * self._config.risk_reward_2

        exit_decision = self._evaluate_planned_exit(features, entry_price, risk_plan.stop_loss)
        entry_reasons = self._entry_reasons(snapshot, signal)
        exit_reasons = self._exit_reasons(snapshot, exit_decision.reason)

        reasons = [
            *[f"Entry: {reason}" for reason in entry_reasons],
            *[f"Exit: {reason}" for reason in exit_reasons],
            f"Risk: ATR x {self._config.atr_stop_multiplier:g} stop at {risk_plan.stop_loss:.6g}",
            (
                f"Targets: TP1={take_profit_1:.6g} (RR {self._config.risk_reward_1:g}), "
                f"TP2={take_profit_2:.6g} (RR {self._config.risk_reward_2:g})"
            ),
        ]

        plan = TradePlan(
            symbol=self._config.symbol,
            entry_price=entry_price,
            signal=signal.signal,
            stop_loss=risk_plan.stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            holding_period=self._holding_period(snapshot.atr),
            risk_reward=self._config.risk_reward_1,
            confidence=signal.confidence,
            reasons=reasons,
            strategy_name=self.name,
        )
        logger.info(
            "EMA trend plan %s %s entry=%.4f stop=%.4f tp1=%.4f tp2=%.4f conf=%.3f",
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            plan.take_profit_1,
            plan.take_profit_2,
            plan.confidence,
        )
        return plan

    def _snapshot(self, features: pd.DataFrame) -> _BarSnapshot:
        adapter = IndicatorAdapter(features)
        ema_fast = adapter.indicator(self._config.ema_fast_column)
        ema_slow = adapter.indicator(self._config.ema_slow_column)
        adx = adapter.indicator("adx" if self._config.adx_column == "adx_14" else self._config.adx_column)
        atr = adapter.indicator("atr" if self._config.atr_column == "atr_14" else self._config.atr_column)

        if ema_fast.latest_value is None or ema_slow.latest_value is None:
            raise StrategyValidationError("EMA values are unavailable on the latest bar")
        if len(ema_fast.points) < 2 or len(ema_slow.points) < 2:
            raise StrategyValidationError("Need prior and current EMA points for cross detection")

        fast_prev = ema_fast.points[-2].value
        fast_curr = ema_fast.points[-1].value
        slow_prev = ema_slow.points[-2].value
        slow_curr = ema_slow.points[-1].value
        if None in (fast_prev, fast_curr, slow_prev, slow_curr):
            raise StrategyValidationError("EMA cross requires non-null previous/current values")

        close = float(features.iloc[-1][self._config.close_column])
        adx_value = adx.latest_value
        atr_value = atr.latest_value
        if adx_value is None or atr_value is None:
            raise StrategyValidationError("ADX/ATR unavailable on the latest bar")

        cross_above = self._conditions.cross_above(
            float(fast_prev),
            float(fast_curr),
            float(slow_prev),
            float(slow_curr),
            left_label=self._config.ema_fast_column,
            right_label=self._config.ema_slow_column,
        )
        cross_below = self._conditions.cross_below(
            float(fast_prev),
            float(fast_curr),
            float(slow_prev),
            float(slow_curr),
            left_label=self._config.ema_fast_column,
            right_label=self._config.ema_slow_column,
        )
        adx_ok = self._conditions.compare(
            float(adx_value),
            ComparisonOperator.GT,
            self._config.adx_threshold,
            left_label=self._config.adx_column,
            right_label="adx_threshold",
        )
        close_above_slow = self._conditions.compare(
            close,
            ComparisonOperator.GT,
            float(slow_curr),
            left_label=self._config.close_column,
            right_label=self._config.ema_slow_column,
        )

        confluence = self._confluence.evaluate(
            features=features,
            symbol=self._config.symbol,
        )
        # Map confluence (-100..100) to confidence (0..1), floored for actionable signals.
        confidence = max(0.0, min(1.0, (confluence.total_score + 100.0) / 200.0))

        timestamp = pd.Timestamp(features.iloc[-1][self._config.date_column]).to_pydatetime()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=None)

        return _BarSnapshot(
            timestamp=timestamp,
            close=close,
            atr=float(atr_value),
            adx=float(adx_value),
            ema_fast=float(fast_curr),
            ema_slow=float(slow_curr),
            cross_above=cross_above,
            cross_below=cross_below,
            adx_ok=adx_ok,
            close_above_slow=close_above_slow,
            confidence=confidence,
            confluence_explanation=confluence.explanation,
        )

    def _evaluate_planned_exit(
        self,
        features: pd.DataFrame,
        entry_price: float,
        stop_loss: float,
    ):
        close = float(features.iloc[-1][self._config.close_column])
        high = float(features.iloc[-1]["high"]) if "high" in features.columns else close
        low = float(features.iloc[-1]["low"]) if "low" in features.columns else close
        state = make_state(
            entry_price=entry_price,
            direction=TradeDirection.LONG,
            bars_held=0,
            extreme_high=max(entry_price, high),
            extreme_low=min(entry_price, low, stop_loss),
        )
        return self._exits.evaluate(
            state=state,
            market=features,
            config=ExitConfig(
                initial_stop=stop_loss,
                atr_column=self._config.atr_column,
                atr_multiplier=self._config.atr_stop_multiplier,
                trailing_atr_multiplier=self._config.trailing_atr_multiplier,
                ema_column=self._config.ema_fast_column,
                max_bars=self._config.holding_period_max,
                enabled_methods=(
                    ExitMethod.TRAILING_STOP,
                    ExitMethod.EMA_EXIT,
                    ExitMethod.TIME_EXIT,
                ),
            ),
        )

    def _holding_period(self, atr: float) -> int:
        """Return configured holding estimate clamped to the 5–20 day window."""
        _ = atr  # reserved for future volatility-scaled holding models
        return int(
            min(
                self._config.holding_period_max,
                max(self._config.holding_period_min, self._config.holding_period_default),
            ),
        )

    @staticmethod
    def _entry_reasons(snapshot: _BarSnapshot, signal: Signal) -> list[str]:
        reasons = [
            snapshot.cross_above.reason,
            snapshot.adx_ok.reason,
            snapshot.close_above_slow.reason,
            f"Confluence confidence={snapshot.confidence:.3f}",
        ]
        if signal.signal is SignalType.BUY:
            return reasons
        return [signal.reason, *reasons]

    @staticmethod
    def _exit_reasons(snapshot: _BarSnapshot, exit_engine_reason: str) -> list[str]:
        return [
            (
                f"{snapshot.cross_below.reason}"
                if snapshot.cross_below.value
                else f"Monitor {snapshot.cross_below.operator}: EMA20 cross below EMA50"
            ),
            "ATR trailing stop (exit engine)",
            exit_engine_reason,
        ]


class _BarSnapshot:
    """Internal latest-bar evaluation bundle."""

    __slots__ = (
        "timestamp",
        "close",
        "atr",
        "adx",
        "ema_fast",
        "ema_slow",
        "cross_above",
        "cross_below",
        "adx_ok",
        "close_above_slow",
        "confidence",
        "confluence_explanation",
    )

    def __init__(
        self,
        *,
        timestamp: datetime,
        close: float,
        atr: float,
        adx: float,
        ema_fast: float,
        ema_slow: float,
        cross_above,
        cross_below,
        adx_ok,
        close_above_slow,
        confidence: float,
        confluence_explanation: str,
    ) -> None:
        self.timestamp = timestamp
        self.close = close
        self.atr = atr
        self.adx = adx
        self.ema_fast = ema_fast
        self.ema_slow = ema_slow
        self.cross_above = cross_above
        self.cross_below = cross_below
        self.adx_ok = adx_ok
        self.close_above_slow = close_above_slow
        self.confidence = confidence
        self.confluence_explanation = confluence_explanation


def _neutral_structure(bar_count: int) -> MarketStructureResult:
    """Minimal structure stub so RiskEngine can prefer ATR stops."""
    return MarketStructureResult(
        swing_length=1,
        bar_count=bar_count,
        trend=TrendDirection.SIDEWAYS,
        swings=[],
        events=[],
        last_swing_high=None,
        last_swing_low=None,
    )
