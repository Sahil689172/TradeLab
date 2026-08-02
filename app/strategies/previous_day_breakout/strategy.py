"""Previous Day High/Low (Magic Box) breakout strategy.

Daily timeframe defines PDH/PDL via the Levels Engine.
15-minute timeframe drives entry sequencing via the Condition Engine.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.indicator_adapter import IndicatorAdapter, IndicatorAdapterError
from app.levels import LevelsService
from app.levels.schemas import LevelsSnapshot
from app.market_structure import MarketStructureService
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.strategies.previous_day_breakout.config import PreviousDayBreakoutConfig
from app.strategies.previous_day_breakout.evaluation import (
    assess_long_setup,
    assess_short_setup,
    build_confidence,
    levels_used_from_snapshot,
    select_stop_loss,
    select_take_profit_2,
)
from app.strategies.previous_day_breakout.schemas import (
    PreviousDayBreakoutPlan,
    SetupAssessment,
    SetupStage,
)
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.models import Signal, SignalType, TradePlan

logger = get_logger(__name__)


class PreviousDayBreakoutStrategy(BaseStrategy):
    """Multi-timeframe Previous Day High/Low breakout (Magic Box) strategy."""

    def __init__(
        self,
        config: PreviousDayBreakoutConfig | None = None,
        *,
        daily_ohlcv: pd.DataFrame | None = None,
        levels: LevelsSnapshot | None = None,
        market_structure: MarketStructureResult | None = None,
        levels_service: LevelsService | None = None,
        structure_service: MarketStructureService | None = None,
        condition_engine: ConditionEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or PreviousDayBreakoutConfig()
        self._daily_ohlcv = daily_ohlcv
        self._levels_override = levels
        self._structure_override = market_structure
        self._levels_service = levels_service or LevelsService(opening_range_bars=1)
        self._structure_service = structure_service or MarketStructureService(
            swing_length=self._config.structure_swing_length,
        )
        self._conditions = condition_engine or ConditionEngine()
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                max_bars=self._config.session_bars,
                enabled_methods=(ExitMethod.TIME_EXIT,),
            ),
        )
        self._cached_levels: LevelsSnapshot | None = None
        self._cached_structure: MarketStructureResult | None = None
        self._last_detailed_plan: PreviousDayBreakoutPlan | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> PreviousDayBreakoutConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> PreviousDayBreakoutPlan | None:
        """Most recent rich plan produced by ``generate_trade_plan``."""
        return self._last_detailed_plan

    def bind_daily(self, daily_ohlcv: pd.DataFrame) -> PreviousDayBreakoutStrategy:
        """Attach daily OHLCV used to compute PDH/PDL via the Levels Engine."""
        self._daily_ohlcv = daily_ohlcv
        self._cached_levels = None
        return self

    def bind_levels(self, levels: LevelsSnapshot) -> PreviousDayBreakoutStrategy:
        """Inject a precomputed Levels snapshot (skips daily recompute)."""
        self._levels_override = levels
        self._cached_levels = levels
        return self

    def bind_structure(self, structure: MarketStructureResult) -> PreviousDayBreakoutStrategy:
        """Inject market structure (skips 15m structure recompute)."""
        self._structure_override = structure
        self._cached_structure = structure
        return self

    def validate(self, features: pd.DataFrame) -> None:
        if not isinstance(features, pd.DataFrame):
            raise StrategyValidationError("features must be a pandas DataFrame")
        if features.empty:
            raise StrategyValidationError("15-minute features must not be empty")

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
                f"Previous-day breakout missing 15m columns: {', '.join(missing)}",
            )
        if len(features) < self._config.min_history_bars:
            raise StrategyValidationError(
                f"Need at least {self._config.min_history_bars} 15m bars, got {len(features)}",
            )
        if self._levels_override is None and self._daily_ohlcv is None:
            raise StrategyValidationError(
                "Daily context required: call bind_daily(...) or bind_levels(...)",
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
        if len(frame) < 2:
            raise StrategyValidationError("Prepared 15m frame needs at least 2 valid bars")

        self._cached_levels = self._resolve_levels(frame)
        self._cached_structure = self._resolve_structure(frame)
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        long_setup, short_setup = self._assess_both(features)
        chosen = self._prefer_setup(long_setup, short_setup)
        timestamp = self._timestamp(features)
        confidence = build_confidence(chosen, self._config.confidence_weights).total / 100.0

        return Signal(
            symbol=self.active_symbol,
            timestamp=timestamp,
            signal=chosen.signal,
            confidence=confidence,
            reason="; ".join(chosen.reasons) if chosen.reasons else chosen.stage.value,
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
    ) -> PreviousDayBreakoutPlan:
        """Return the full Magic Box plan including structure and levels metadata."""
        levels = self._require_levels()
        structure = self._require_structure()
        long_setup, short_setup = self._assess_both(features)
        chosen = self._prefer_setup(long_setup, short_setup)
        if signal is None:
            signal = Signal(
                symbol=self.active_symbol,
                timestamp=self._timestamp(features),
                signal=chosen.signal,
                confidence=build_confidence(chosen, self._config.confidence_weights).total / 100.0,
                reason="; ".join(chosen.reasons) if chosen.reasons else chosen.stage.value,
            )

        entry_price = float(features.iloc[-1][self._config.close_column])
        direction = (
            TradeDirection.LONG
            if chosen.signal is SignalType.BUY
            else TradeDirection.SHORT
            if chosen.signal is SignalType.SELL
            else TradeDirection.LONG
        )
        if chosen.direction is not None:
            direction = chosen.direction

        previous = features.iloc[-2]
        atr_value = self._latest_atr(features)
        stop_source, stop_loss = select_stop_loss(
            direction=direction,
            entry_price=entry_price,
            previous_candle_low=float(previous[self._config.low_column]),
            previous_candle_high=float(previous[self._config.high_column]),
            previous_day_high=levels.previous_day_high,
            previous_day_low=levels.previous_day_low,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_stop_multiplier,
        )
        risk = abs(entry_price - stop_loss)
        if direction is TradeDirection.LONG:
            take_profit_1 = entry_price + risk * self._config.risk_reward_1
        else:
            take_profit_1 = entry_price - risk * self._config.risk_reward_1

        take_profit_2, tp2_label = select_take_profit_2(
            direction=direction,
            entry_price=entry_price,
            levels=levels,
            take_profit_1=take_profit_1,
        )
        # Ensure TP2 is beyond TP1 in the trade direction.
        if direction is TradeDirection.LONG and take_profit_2 <= take_profit_1:
            take_profit_2 = take_profit_1 + risk * 0.5
            tp2_label = f"{tp2_label} (extended beyond TP1)"
        if direction is TradeDirection.SHORT and take_profit_2 >= take_profit_1:
            take_profit_2 = take_profit_1 - risk * 0.5
            tp2_label = f"{tp2_label} (extended beyond TP1)"

        confidence_breakdown = build_confidence(chosen, self._config.confidence_weights)
        entry_level = (
            levels.previous_day_high
            if direction is TradeDirection.LONG
            else levels.previous_day_low
        )
        used = levels_used_from_snapshot(
            levels,
            entry_level=entry_level,
            target_2=take_profit_2,
            target_2_label=tp2_label,
        )

        exit_note = self._intraday_exit_note(features, entry_price, stop_loss, direction)
        reasons = [
            *chosen.reasons,
            f"Direction: {direction.value}",
            f"Stop ({stop_source.value}): {stop_loss:.6g}",
            f"Target 1 (RR {self._config.risk_reward_1:g}): {take_profit_1:.6g}",
            f"Target 2 ({tp2_label}): {take_profit_2:.6g}",
            f"Market structure: {structure.trend.value}",
            (
                f"Levels used: PDH={levels.previous_day_high:.6g}, "
                f"PDL={levels.previous_day_low:.6g}"
            ),
            *confidence_breakdown.reasons,
            exit_note,
            "Holding: intraday only — flatten before market close",
        ]

        plan = PreviousDayBreakoutPlan(
            strategy_name=self.name,
            symbol=self.active_symbol,
            entry_price=entry_price,
            direction=direction,
            signal=signal.signal,
            stop_loss=stop_loss,
            take_profit_1=take_profit_1,
            take_profit_2=take_profit_2,
            confidence=signal.confidence,
            risk_reward=self._config.risk_reward_1,
            expected_holding_bars=self._config.session_bars,
            stop_source=stop_source,
            reasons=reasons,
            market_structure=structure.trend,
            levels_used=used,
            confidence_breakdown=confidence_breakdown,
            setup=chosen,
            timestamp=signal.timestamp,
        )
        logger.info(
            "Magic Box plan %s %s entry=%.4f stop=%.4f tp1=%.4f tp2=%.4f conf=%.3f stage=%s",
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            plan.take_profit_1,
            plan.take_profit_2,
            plan.confidence,
            chosen.stage.value,
        )
        return plan

    def _assess_both(self, features: pd.DataFrame) -> tuple[SetupAssessment, SetupAssessment]:
        levels = self._require_levels()
        structure = self._require_structure()
        long_setup = assess_long_setup(
            features,
            pdh=levels.previous_day_high,
            config=self._config,
            structure_trend=structure.trend,
            conditions=self._conditions,
        )
        short_setup = assess_short_setup(
            features,
            pdl=levels.previous_day_low,
            config=self._config,
            structure_trend=structure.trend,
            conditions=self._conditions,
        )
        return long_setup, short_setup

    @staticmethod
    def _prefer_setup(
        long_setup: SetupAssessment,
        short_setup: SetupAssessment,
    ) -> SetupAssessment:
        if long_setup.stage is SetupStage.ENTRY and short_setup.stage is not SetupStage.ENTRY:
            return long_setup
        if short_setup.stage is SetupStage.ENTRY and long_setup.stage is not SetupStage.ENTRY:
            return short_setup
        if long_setup.stage is SetupStage.ENTRY and short_setup.stage is SetupStage.ENTRY:
            # Deterministic tie-break: prefer the setup that broke later.
            long_break = long_setup.break_index or -1
            short_break = short_setup.break_index or -1
            return long_setup if long_break >= short_break else short_setup

        rank = {
            SetupStage.FAILED_RETEST: 5,
            SetupStage.RETESTED: 4,
            SetupStage.BROKEN: 3,
            SetupStage.APPROACHED: 2,
            SetupStage.IDLE: 1,
            SetupStage.ENTRY: 6,
        }
        if rank[long_setup.stage] >= rank[short_setup.stage]:
            return long_setup
        return short_setup

    def _resolve_levels(self, intraday: pd.DataFrame) -> LevelsSnapshot:
        if self._levels_override is not None:
            return self._levels_override
        if self._daily_ohlcv is None:
            raise StrategyValidationError("Daily OHLCV is required to compute PDH/PDL")
        as_of = pd.Timestamp(intraday.iloc[-1][self._config.date_column])
        return self._levels_service.compute(
            self._daily_ohlcv,
            symbol=self.active_symbol,
            as_of=as_of,
        )

    def _resolve_structure(self, intraday: pd.DataFrame) -> MarketStructureResult:
        if self._structure_override is not None:
            return self._structure_override
        # MarketStructureService expects volume; ensure OHLCV columns exist.
        frame = intraday.copy()
        if "volume" not in frame.columns:
            # Relative volume is present; synthesize a positive volume proxy for structure only.
            frame["volume"] = (
                pd.to_numeric(frame[self._config.volume_column], errors="coerce")
                .fillna(1.0)
                .clip(lower=1.0)
                * 1_000
            ).astype("int64")
        return self._structure_service.analyze(frame, symbol=self.active_symbol)

    def _require_levels(self) -> LevelsSnapshot:
        if self._cached_levels is None:
            raise StrategyValidationError("Levels not prepared — call prepare() first")
        return self._cached_levels

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
        timestamp = pd.Timestamp(features.iloc[-1][self._config.date_column]).to_pydatetime()
        return timestamp

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
            extreme_low=min(entry_price, low, stop_loss)
            if direction is TradeDirection.LONG
            else min(entry_price, low),
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
        return f"Exit engine: {decision.reason} (close mark={close:.6g})"
