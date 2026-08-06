"""EMA Trend Following strategy — raw + professional modes.

Uses only:
    Strategy Foundation, Indicator Adapter, Condition Engine,
    Risk Engine, Exit Engine, Confluence Engine.

``mode="raw"`` preserves the original EMA20/50 + ADX + close-above-slow behaviour.
``mode="professional"`` adds institutional crossover gates with filter diagnostics.
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
from app.strategies.ema_trend.diagnostics import FilterRejection, SignalFunnel, empty_funnel
from app.strategies.ema_trend.professional import (
    apply_professional_gates,
    atr_stop_price,
    atr_trailing_stop_price,
    read_optional_float,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.filters.strategy_profiles import STRATEGY_FILTER_PROFILES
from app.strategy_engine.models import Signal, SignalType, TradePlan

logger = get_logger(__name__)


class EMATrendStrategy(BaseStrategy):
    """EMA trend-following strategy with optional professional filter stack."""

    FILTER_PROFILE = STRATEGY_FILTER_PROFILES["ema_trend"]

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
        exit_methods = (
            ExitMethod.TRAILING_STOP,
            ExitMethod.EMA_EXIT,
            ExitMethod.TIME_EXIT,
        )
        if self._config.mode == "professional" and not self._config.atr_trailing:
            exit_methods = (ExitMethod.EMA_EXIT, ExitMethod.TIME_EXIT)
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                atr_column=self._config.atr_column,
                atr_multiplier=self._config.atr_stop_multiplier,
                trailing_atr_multiplier=self._config.trailing_atr_multiplier,
                ema_column=self._config.ema_fast_column,
                max_bars=self._config.holding_period_max,
                enabled_methods=exit_methods,
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
        self._last_rejections: list[FilterRejection] = []
        self._last_funnel: SignalFunnel = empty_funnel()
        self._last_emitted_side: SignalType | None = None
        self._session_funnel: SignalFunnel = empty_funnel()

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> EMATrendConfig:
        return self._config

    @property
    def last_rejections(self) -> list[FilterRejection]:
        return list(self._last_rejections)

    @property
    def last_funnel(self) -> SignalFunnel:
        return self._last_funnel

    @property
    def session_funnel(self) -> SignalFunnel:
        """Accumulated funnel across evaluations (audit / multi-bar walks)."""
        return self._session_funnel

    def reset_session_funnel(self) -> None:
        self._session_funnel = empty_funnel()
        self._last_emitted_side = None

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
        if self._config.mode == "professional" and (
            self._config.ema200_filter or self._config.trend_filter
        ):
            required.add(self._config.ema200_column)

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
        if self._config.ema200_column in frame.columns:
            numeric_cols.append(self._config.ema200_column)
        for column in numeric_cols:
            if column in frame.columns:
                frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = (
            frame.drop_duplicates(subset=[self._config.date_column], keep="last")
            .sort_values(self._config.date_column)
            .reset_index(drop=True)
        )
        drop_subset = [
            self._config.close_column,
            self._config.ema_fast_column,
            self._config.ema_slow_column,
            self._config.adx_column,
            self._config.atr_column,
        ]
        frame = frame.dropna(subset=drop_subset).reset_index(drop=True)
        if len(frame) < 2:
            raise StrategyValidationError(
                "Prepared features need at least 2 rows with valid EMA/ADX/ATR/close",
            )
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        self._last_rejections = []
        self._last_funnel = empty_funnel()
        if self._config.mode == "professional":
            return self._generate_signal_professional(features)
        return self._generate_signal_raw(features)

    def generate_trade_plan(self, features: pd.DataFrame, signal: Signal) -> TradePlan:
        snapshot = self._snapshot(features)
        entry_price = snapshot.close
        direction = (
            TradeDirection.SHORT
            if signal.signal is SignalType.SELL
            else TradeDirection.LONG
        )
        multiplier = self._config.atr_stop_multiplier
        if self._config.mode == "professional" and self._config.atr_stop:
            stop_loss = atr_stop_price(
                entry=entry_price,
                atr=snapshot.atr,
                multiplier=multiplier,
                side=signal.signal if signal.signal in {SignalType.BUY, SignalType.SELL} else SignalType.BUY,
            )
        else:
            risk_plan = self._risk.compute(
                entry_price=entry_price,
                direction=TradeDirection.LONG,
                features=features,
                market_structure=_neutral_structure(len(features)),
                config=RiskConfig(
                    preferred_stop=StopMethod.ATR,
                    atr_column=self._config.atr_column,
                    atr_multiplier=multiplier,
                    risk_reward=self._config.risk_reward_1,
                    time_stop_bars=self._holding_period(snapshot.atr),
                ),
            )
            stop_loss = risk_plan.stop_loss

        risk_distance = abs(entry_price - stop_loss)
        if direction is TradeDirection.SHORT or signal.signal is SignalType.SELL:
            take_profit_1 = entry_price - risk_distance * self._config.risk_reward_1
            take_profit_2 = entry_price - risk_distance * self._config.risk_reward_2
        else:
            take_profit_1 = entry_price + risk_distance * self._config.risk_reward_1
            take_profit_2 = entry_price + risk_distance * self._config.risk_reward_2

        # Ensure positive prices for TradePlan constraints
        take_profit_1 = max(take_profit_1, 0.01)
        take_profit_2 = max(take_profit_2, 0.01)
        stop_loss = max(stop_loss, 0.01)

        exit_decision = self._evaluate_planned_exit(features, entry_price, stop_loss, signal.signal)
        entry_reasons = self._entry_reasons(snapshot, signal)
        exit_reasons = self._exit_reasons(snapshot, exit_decision.reason)

        reasons = [
            *[f"Entry: {reason}" for reason in entry_reasons],
            *[f"Exit: {reason}" for reason in exit_reasons],
            f"Risk: ATR x {multiplier:g} stop at {stop_loss:.6g}",
            (
                f"Targets: TP1={take_profit_1:.6g} (RR {self._config.risk_reward_1:g}), "
                f"TP2={take_profit_2:.6g} (RR {self._config.risk_reward_2:g})"
            ),
            f"Mode: {self._config.mode}",
        ]
        if self._config.mode == "professional" and self._config.atr_trailing:
            trail = atr_trailing_stop_price(
                extreme=entry_price,
                atr=snapshot.atr,
                multiplier=self._config.trailing_atr_multiplier,
                side=signal.signal if signal.signal in {SignalType.BUY, SignalType.SELL} else SignalType.BUY,
            )
            reasons.append(
                f"ATR trailing armed (x{self._config.trailing_atr_multiplier:g}) "
                f"initial_trail={trail:.6g}",
            )
        for rejection in self._last_rejections:
            reasons.append(
                f"Filter rejected: [{rejection.rejected_by.value}] {rejection.reason}",
            )

        plan = TradePlan(
            symbol=self.active_symbol,
            entry_price=entry_price,
            signal=signal.signal,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            holding_period=self._holding_period(snapshot.atr),
            risk_reward=self._config.risk_reward_1,
            confidence=signal.confidence,
            reasons=reasons,
            strategy_name=self.name,
        )
        logger.info(
            "EMA trend plan mode=%s %s %s entry=%.4f stop=%.4f tp1=%.4f tp2=%.4f conf=%.3f",
            self._config.mode,
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            plan.take_profit_1,
            plan.take_profit_2,
            plan.confidence,
        )
        return plan

    def _generate_signal_raw(self, features: pd.DataFrame) -> Signal:
        snapshot = self._snapshot(features)
        timestamp = snapshot.timestamp
        symbol = self.active_symbol

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

    def _generate_signal_professional(self, features: pd.DataFrame) -> Signal:
        snapshot = self._snapshot(features)
        timestamp = snapshot.timestamp
        symbol = self.active_symbol

        raw_signal = SignalType.HOLD
        if snapshot.cross_above.value:
            raw_signal = SignalType.BUY
        elif snapshot.cross_below.value:
            raw_signal = SignalType.SELL

        if raw_signal is SignalType.HOLD:
            self._last_funnel = empty_funnel()
            return Signal(
                symbol=symbol,
                timestamp=timestamp,
                signal=SignalType.HOLD,
                confidence=min(0.5, snapshot.confidence),
                reason=(
                    f"Hold: no true EMA cross "
                    f"({self._config.ema_fast_column}/{self._config.ema_slow_column})"
                ),
            )

        bar_closed = True
        if "bar_closed" in features.attrs:
            bar_closed = bool(features.attrs.get("bar_closed"))
        elif self._config.confirm_on_close:
            # Feature frames are closed candles; allow override via attrs.
            bar_closed = True

        ema200 = read_optional_float(features, self._config.ema200_column)
        rvol = read_optional_float(features, self._config.relative_volume_column)
        volume = read_optional_float(features, self._config.volume_column)
        volume_sma = read_optional_float(features, self._config.volume_sma_column)

        result = apply_professional_gates(
            config=self._config,
            symbol=symbol,
            timestamp=timestamp,
            raw_signal=raw_signal,
            close=snapshot.close,
            ema200=ema200,
            adx=snapshot.adx,
            relative_volume=rvol,
            volume=volume,
            volume_sma=volume_sma,
            atr=snapshot.atr,
            bar_closed=bar_closed,
            last_emitted=self._last_emitted_side,
        )
        self._last_rejections = list(result.rejections)
        self._last_funnel = result.funnel
        self._session_funnel = self._session_funnel.merge(result.funnel)

        if result.final_signal in {SignalType.BUY, SignalType.SELL}:
            self._last_emitted_side = result.final_signal
            reason = (
                f"Professional {result.final_signal.value}: {snapshot.cross_above.reason if raw_signal is SignalType.BUY else snapshot.cross_below.reason}; "
                + "; ".join(result.notes)
            )
            return Signal(
                symbol=symbol,
                timestamp=timestamp,
                signal=result.final_signal,
                confidence=max(0.55, snapshot.confidence),
                reason=reason,
            )

        reject_txt = "; ".join(r.reason for r in result.rejections) or "filtered"
        return Signal(
            symbol=symbol,
            timestamp=timestamp,
            signal=SignalType.HOLD,
            confidence=min(0.35, snapshot.confidence),
            reason=f"Hold after filters: {reject_txt}",
        )

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
            symbol=self.active_symbol,
        )
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
        signal_type: SignalType,
    ):
        close = float(features.iloc[-1][self._config.close_column])
        high = float(features.iloc[-1]["high"]) if "high" in features.columns else close
        low = float(features.iloc[-1]["low"]) if "low" in features.columns else close
        direction = (
            TradeDirection.SHORT
            if signal_type is SignalType.SELL
            else TradeDirection.LONG
        )
        methods = (
            ExitMethod.TRAILING_STOP,
            ExitMethod.EMA_EXIT,
            ExitMethod.TIME_EXIT,
        )
        if self._config.mode == "professional" and not self._config.atr_trailing:
            methods = (ExitMethod.EMA_EXIT, ExitMethod.TIME_EXIT)
        elif self._config.mode == "professional" and self._config.atr_trailing:
            methods = (
                ExitMethod.TRAILING_STOP,
                ExitMethod.EMA_EXIT,
                ExitMethod.TIME_EXIT,
            )

        state = make_state(
            entry_price=entry_price,
            direction=direction,
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
                enabled_methods=methods,
            ),
        )

    def _holding_period(self, atr: float) -> int:
        """Return configured holding estimate clamped to the min–max window."""
        _ = atr
        return int(
            min(
                self._config.holding_period_max,
                max(self._config.holding_period_min, self._config.holding_period_default),
            ),
        )

    def _entry_reasons(self, snapshot: _BarSnapshot, signal: Signal) -> list[str]:
        reasons = [
            snapshot.cross_above.reason,
            snapshot.adx_ok.reason,
            snapshot.close_above_slow.reason,
            f"Confluence confidence={snapshot.confidence:.3f}",
            f"mode={self._config.mode}",
        ]
        if signal.signal in {SignalType.BUY, SignalType.SELL}:
            return reasons
        return [signal.reason, *reasons]

    def _exit_reasons(self, snapshot: _BarSnapshot, exit_engine_reason: str) -> list[str]:
        pair = f"{self._config.ema_fast_column}/{self._config.ema_slow_column}"
        return [
            (
                f"{snapshot.cross_below.reason}"
                if snapshot.cross_below.value
                else f"Monitor cross below on {pair}"
            ),
            (
                "ATR trailing stop (exit engine)"
                if self._config.mode == "raw" or self._config.atr_trailing
                else "ATR trailing disabled"
            ),
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
