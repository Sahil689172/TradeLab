"""Opening Range Breakout (ORB) strategy.

Intraday strategy: configurable opening range (5/15/30 minutes) via Levels Engine,
entries filtered by volume, structure, trend, and session risk controls.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine, ComparisonOperator
from app.confluence import ConfluenceConfig, ConfluenceEngine, ModuleWeights
from app.confluence.exceptions import ConfluenceValidationError
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.indicator_adapter import IndicatorAdapter, IndicatorAdapterError
from app.levels.exceptions import LevelsValidationError
from app.market_structure import MarketStructureService
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.risk_engine.stops import take_profit_from_risk
from app.strategies.opening_range_breakout.config import OpeningRangeBreakoutConfig
from app.strategies.opening_range_breakout.evaluation import (
    assess_orb_setup,
    atr_projection_target,
    build_confidence,
    resolve_opening_range,
    select_orb_stop,
)
from app.strategies.opening_range_breakout.schemas import (
    OpeningRangeBreakoutPlan,
    OpeningRangeLevels,
    ORBSetupAssessment,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import Signal, SignalType, TradePlan

logger = get_logger(__name__)


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Configurable Opening Range Breakout strategy (intraday only)."""

    def __init__(
        self,
        config: OpeningRangeBreakoutConfig | None = None,
        *,
        market_structure: MarketStructureResult | None = None,
        structure_service: MarketStructureService | None = None,
        condition_engine: ConditionEngine | None = None,
        confluence_engine: ConfluenceEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or OpeningRangeBreakoutConfig()
        self._structure_override = market_structure
        self._structure_service = structure_service or MarketStructureService(
            swing_length=self._config.structure_swing_length,
        )
        self._conditions = condition_engine or ConditionEngine()
        self._confluence = confluence_engine or ConfluenceEngine(
            ConfluenceConfig(
                weights=ModuleWeights(
                    ema=0,
                    rsi=0,
                    volume=0,
                    structure=0,
                    atr=0,
                    levels=0,
                    trend=100,
                ),
                ema_fast_column=self._config.ema_fast_column,
                ema_slow_column=self._config.ema_slow_column,
                close_column=self._config.close_column,
            ),
        )
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                max_bars=self._config.session_bars,
                enabled_methods=(ExitMethod.TIME_EXIT,),
            ),
        )
        self._cached_opening: OpeningRangeLevels | None = None
        self._cached_structure: MarketStructureResult | None = None
        self._last_detailed_plan: OpeningRangeBreakoutPlan | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> OpeningRangeBreakoutConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> OpeningRangeBreakoutPlan | None:
        return self._last_detailed_plan

    def bind_structure(self, structure: MarketStructureResult) -> OpeningRangeBreakoutStrategy:
        self._structure_override = structure
        self._cached_structure = structure
        return self

    def validate(self, features: pd.DataFrame) -> None:
        if not isinstance(features, pd.DataFrame):
            raise StrategyValidationError("features must be a pandas DataFrame")
        if features.empty:
            raise StrategyValidationError("features must not be empty")

        required = {
            self._config.date_column,
            self._config.open_column,
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
            self._config.volume_column,
        }
        missing = sorted(column for column in required if column not in features.columns)
        if missing:
            raise StrategyValidationError(
                f"ORB strategy missing columns: {', '.join(missing)}",
            )
        if len(features) < max(self._config.min_history_bars, self._config.opening_range_bars + 1):
            raise StrategyValidationError(
                f"Need enough bars for OR ({self._config.opening_range_bars}) "
                f"plus history (min {self._config.min_history_bars})",
            )

    def prepare(self, features: pd.DataFrame) -> pd.DataFrame:
        frame = features.copy()
        frame[self._config.date_column] = pd.to_datetime(frame[self._config.date_column])
        for column in (
            self._config.open_column,
            self._config.high_column,
            self._config.low_column,
            self._config.close_column,
            self._config.volume_column,
        ):
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
        if self._config.atr_column in frame.columns:
            frame[self._config.atr_column] = pd.to_numeric(
                frame[self._config.atr_column],
                errors="coerce",
            )

        frame = (
            frame.dropna(
                subset=[
                    self._config.open_column,
                    self._config.high_column,
                    self._config.low_column,
                    self._config.close_column,
                    self._config.volume_column,
                ],
            )
            .drop_duplicates(subset=[self._config.date_column], keep="last")
            .sort_values(self._config.date_column)
            .reset_index(drop=True)
        )
        try:
            self._cached_opening = resolve_opening_range(frame, config=self._config)
        except (StrategyValidationError, LevelsValidationError) as exc:
            raise StrategyValidationError(str(exc)) from exc
        self._cached_structure = self._resolve_structure(frame)
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        setup = self._assess(features)
        confidence = build_confidence(setup, self._config.confidence_weights).total / 100.0
        return Signal(
            symbol=self._config.symbol,
            timestamp=self._timestamp(features),
            signal=setup.signal,
            confidence=confidence,
            reason="; ".join(setup.reasons) if setup.reasons else "ORB hold",
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
    ) -> OpeningRangeBreakoutPlan:
        opening = self._require_opening()
        structure = self._require_structure()
        setup = self._assess(features)
        if signal is None:
            signal = Signal(
                symbol=self._config.symbol,
                timestamp=self._timestamp(features),
                signal=setup.signal,
                confidence=build_confidence(setup, self._config.confidence_weights).total / 100.0,
                reason="; ".join(setup.reasons) if setup.reasons else "ORB hold",
            )

        entry_price = float(features.iloc[-1][self._config.close_column])
        direction = setup.direction or TradeDirection.LONG
        atr_value = self._latest_atr(features)
        swing = (
            structure.last_swing_low.price
            if direction is TradeDirection.LONG and structure.last_swing_low is not None
            else structure.last_swing_high.price
            if direction is TradeDirection.SHORT and structure.last_swing_high is not None
            else None
        )
        stop_source, stop_loss = select_orb_stop(
            direction=direction,
            entry_price=entry_price,
            opening=opening,
            previous_swing=swing,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_stop_multiplier,
        )
        risk = abs(entry_price - stop_loss)
        take_profit_1, realized_rr = take_profit_from_risk(
            entry_price,
            stop_loss,
            direction,
            self._config.risk_reward_1,
        )

        take_profit_2 = atr_projection_target(
            direction=direction,
            entry_price=entry_price,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_target_multiplier,
            take_profit_1=take_profit_1,
        )
        if direction is TradeDirection.LONG and take_profit_2 <= take_profit_1:
            take_profit_2 = take_profit_1 + risk * 0.5
        if direction is TradeDirection.SHORT and take_profit_2 >= take_profit_1:
            take_profit_2 = take_profit_1 - risk * 0.5

        confidence_breakdown = build_confidence(setup, self._config.confidence_weights)
        exit_note = self._intraday_exit_note(features, entry_price, stop_loss, direction)
        reasons = [
            *setup.reasons,
            (
                f"Opening range ({opening.minutes}m / {opening.bars} bars): "
                f"H={opening.high:.6g} L={opening.low:.6g} Mid={opening.mid:.6g}"
            ),
            f"Stop ({stop_source.value}): {stop_loss:.6g}",
            f"Target 1 (RR {realized_rr:g}): {take_profit_1:.6g}",
            f"Target 2 (ATR projection): {take_profit_2:.6g}",
            f"Market structure: {structure.trend.value}",
            *confidence_breakdown.reasons,
            exit_note,
            "Holding: intraday only — exit before market close",
        ]

        plan = OpeningRangeBreakoutPlan(
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
            stop_source=stop_source,
            reasons=reasons,
            market_structure=structure.trend,
            opening_range=opening,
            confidence_breakdown=confidence_breakdown,
            setup=setup,
            timestamp=signal.timestamp,
        )
        logger.info(
            "ORB plan %s %s entry=%.4f stop=%.4f tp1=%.4f tp2=%.4f conf=%.3f or=%dm",
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            plan.take_profit_1,
            plan.take_profit_2,
            plan.confidence,
            opening.minutes,
        )
        return plan

    def _assess(self, features: pd.DataFrame) -> ORBSetupAssessment:
        opening = self._require_opening()
        structure = self._require_structure()
        trend_bullish, trend_bearish = self._trend_filters(features)
        return assess_orb_setup(
            features,
            opening=opening,
            config=self._config,
            structure=structure,
            trend_bullish=trend_bullish,
            trend_bearish=trend_bearish,
            conditions=self._conditions,
        )

    def _trend_filters(self, features: pd.DataFrame) -> tuple[bool, bool]:
        """Bullish/bearish trend via Indicator Adapter EMAs and Confluence trend score."""
        bullish = False
        bearish = False
        fast_col = self._config.ema_fast_column
        slow_col = self._config.ema_slow_column
        if fast_col in features.columns and slow_col in features.columns:
            try:
                adapter = IndicatorAdapter(features)
                fast = adapter.indicator(fast_col).latest_value
                slow = adapter.indicator(slow_col).latest_value
                close = float(features.iloc[-1][self._config.close_column])
                if fast is not None and slow is not None:
                    above = self._conditions.compare(
                        close,
                        ComparisonOperator.GT,
                        slow,
                        left_label="close",
                        right_label=slow_col,
                    )
                    stack = self._conditions.compare(
                        fast,
                        ComparisonOperator.GTE,
                        slow,
                        left_label=fast_col,
                        right_label=slow_col,
                    )
                    bullish = above.value and stack.value
                    bearish = (not above.value) and (fast <= slow)
            except IndicatorAdapterError:
                pass

        # Confluence trend module reinforces the filter when EMA columns exist.
        if {fast_col, slow_col, "rsi_14"}.issubset(features.columns):
            try:
                result = self._confluence.evaluate(features=features, symbol=self._config.symbol)
                if result.total_score >= 25:
                    bullish = True
                if result.total_score <= -25:
                    bearish = True
            except ConfluenceValidationError:
                pass
        return bullish, bearish

    def _resolve_structure(self, frame: pd.DataFrame) -> MarketStructureResult:
        if self._structure_override is not None:
            return self._structure_override
        structure_frame = frame.copy()
        if "volume" not in structure_frame.columns:
            structure_frame["volume"] = (
                pd.to_numeric(structure_frame[self._config.volume_column], errors="coerce")
                .fillna(1.0)
                .clip(lower=1.0)
                * 1_000
            ).astype("int64")
        return self._structure_service.analyze(structure_frame, symbol=self._config.symbol)

    def _require_opening(self) -> OpeningRangeLevels:
        if self._cached_opening is None:
            raise StrategyValidationError("Opening range not prepared — call prepare() first")
        return self._cached_opening

    def _require_structure(self) -> MarketStructureResult:
        if self._cached_structure is None:
            raise StrategyValidationError("Structure not prepared — call prepare() first")
        return self._cached_structure

    def _latest_atr(self, features: pd.DataFrame) -> float | None:
        if self._config.atr_column not in features.columns:
            return None
        values = pd.to_numeric(features[self._config.atr_column], errors="coerce").dropna()
        if values.empty:
            return None
        try:
            adapter = IndicatorAdapter(features)
            name = "atr" if self._config.atr_column == "atr_14" else self._config.atr_column
            latest = adapter.indicator(name).latest_value
            return latest if latest is not None else float(values.iloc[-1])
        except IndicatorAdapterError:
            return float(values.iloc[-1])

    def _timestamp(self, features: pd.DataFrame) -> datetime:
        return pd.Timestamp(features.iloc[-1][self._config.date_column]).to_pydatetime()

    def _intraday_exit_note(
        self,
        features: pd.DataFrame,
        entry_price: float,
        stop_loss: float,
        direction: TradeDirection,
    ) -> str:
        close = float(features.iloc[-1][self._config.close_column])
        high = float(features.iloc[-1][self._config.high_column])
        low = float(features.iloc[-1][self._config.low_column])
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
        return f"Exit engine: {decision.reason} (mark={close:.6g})"
