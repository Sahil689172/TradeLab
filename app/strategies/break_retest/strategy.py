"""Break & Retest strategy.

Sequence detection lives in ``app.services.strategy_engine.break_retest`` —
reusable by future strategies. This module applies volume / structure filters
and TradePlan math.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.conditions import ConditionEngine
from app.core.logging import get_logger
from app.exit_engine import ExitConfig, ExitEngine, ExitMethod, make_state
from app.market_structure import MarketStructureService
from app.market_structure.schemas import MarketStructureResult, TrendDirection
from app.risk_engine.schemas import TradeDirection
from app.services.strategy_engine.break_retest import (
    BreakRetestEngine,
    BreakRetestEngineConfig,
    BreakRetestValidationError,
)
from app.services.strategy_engine.indicators.volume_analysis import (
    VolumeAnalysisService,
    VolumeValidationError,
)
from app.strategies.break_retest.config import BreakRetestStrategyConfig
from app.strategies.break_retest.evaluation import (
    assess_break_retest_setup,
    build_confidence,
    select_break_retest_stop,
    select_targets,
)
from app.strategies.break_retest.schemas import BreakRetestPlan, BreakRetestSetup
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyValidationError
from app.strategy_engine.filters.strategy_profiles import STRATEGY_FILTER_PROFILES
from app.strategy_engine.models import Signal, TradePlan

logger = get_logger(__name__)


class BreakRetestStrategy(BaseStrategy):
    """Resistance/support break → retest → confirmation strategy."""

    FILTER_PROFILE = STRATEGY_FILTER_PROFILES["break_retest"]

    def __init__(
        self,
        config: BreakRetestStrategyConfig | None = None,
        *,
        resistance: float | None = None,
        support: float | None = None,
        market_structure: MarketStructureResult | None = None,
        break_retest_engine: BreakRetestEngine | None = None,
        volume_service: VolumeAnalysisService | None = None,
        structure_service: MarketStructureService | None = None,
        condition_engine: ConditionEngine | None = None,
        exit_engine: ExitEngine | None = None,
    ) -> None:
        self._config = config or BreakRetestStrategyConfig()
        self._resistance = resistance
        self._support = support
        self._structure_override = market_structure
        self._engine = break_retest_engine or BreakRetestEngine(
            BreakRetestEngineConfig(
                lookback=self._config.lookback,
                retest_tolerance_pct=self._config.retest_tolerance_pct,
                min_body_ratio=self._config.min_body_ratio,
                open_column=self._config.open_column,
                high_column=self._config.high_column,
                low_column=self._config.low_column,
                close_column=self._config.close_column,
            ),
            condition_engine=condition_engine,
        )
        self._volume = volume_service or VolumeAnalysisService(
            volume_column=self._config.volume_column,
            relative_volume_20_column=self._config.relative_volume_column,
        )
        self._structure_service = structure_service or MarketStructureService(
            swing_length=self._config.structure_swing_length,
        )
        self._exits = exit_engine or ExitEngine(
            ExitConfig(
                max_bars=self._config.session_bars,
                enabled_methods=(ExitMethod.TIME_EXIT,),
            ),
        )
        self._cached_structure: MarketStructureResult | None = None
        self._last_detailed_plan: BreakRetestPlan | None = None
        self._last_setup: BreakRetestSetup | None = None
        self._assess_cache_key: int | None = None
        self._assess_cache: BreakRetestSetup | None = None

    @property
    def name(self) -> str:
        return self._config.strategy_name

    @property
    def config(self) -> BreakRetestStrategyConfig:
        return self._config

    @property
    def last_detailed_plan(self) -> BreakRetestPlan | None:
        return self._last_detailed_plan

    @property
    def last_setup(self) -> BreakRetestSetup | None:
        return self._last_setup

    def bind_levels(
        self,
        *,
        resistance: float | None = None,
        support: float | None = None,
    ) -> BreakRetestStrategy:
        """Inject explicit break levels (skips rolling lookback resolution)."""
        if resistance is not None:
            self._resistance = resistance
        if support is not None:
            self._support = support
        return self

    def bind_structure(self, structure: MarketStructureResult) -> BreakRetestStrategy:
        """Inject market structure (skips recompute)."""
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
                f"Break & Retest missing columns: {', '.join(missing)}",
            )
        if len(features) < self._config.min_history_bars:
            raise StrategyValidationError(
                f"Need at least {self._config.min_history_bars} bars",
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
        if self._config.relative_volume_column in frame.columns:
            frame[self._config.relative_volume_column] = pd.to_numeric(
                frame[self._config.relative_volume_column],
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
            if self._config.relative_volume_column not in frame.columns:
                frame = self._volume.attach(frame)
        except VolumeValidationError as exc:
            raise StrategyValidationError(str(exc)) from exc

        self._cached_structure = self._resolve_structure(frame)
        self._assess_cache_key = None
        self._assess_cache = None
        return frame

    def generate_signal(self, features: pd.DataFrame) -> Signal:
        setup = self._assess(features)
        self._last_setup = setup
        return Signal(
            symbol=self.active_symbol,
            timestamp=self._timestamp(features),
            signal=setup.signal,
            confidence=build_confidence(setup),
            reason="; ".join(setup.reasons) if setup.reasons else "Break/retest hold",
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
    ) -> BreakRetestPlan:
        setup = self._assess(features)
        self._last_setup = setup
        structure = self._require_structure()
        if signal is None:
            signal = Signal(
                symbol=self.active_symbol,
                timestamp=self._timestamp(features),
                signal=setup.signal,
                confidence=build_confidence(setup),
                reason="; ".join(setup.reasons) if setup.reasons else "Break/retest hold",
            )

        direction = setup.direction or TradeDirection.LONG
        sequence = (
            setup.long_sequence
            if direction is TradeDirection.LONG
            else setup.short_sequence
        )
        entry_price = float(features.iloc[-1][self._config.close_column])
        atr_value = self._latest_atr(features)
        stop_source, stop_loss = select_break_retest_stop(
            direction=direction,
            entry_price=entry_price,
            sequence=sequence,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_stop_multiplier,
        )
        take_profit_1, take_profit_2, realized_rr = select_targets(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_reward=self._config.risk_reward_1,
            atr_value=atr_value,
            atr_multiplier=self._config.atr_target_multiplier,
        )

        reasons = [
            *setup.reasons,
            f"Stop ({stop_source.value}): {stop_loss:.6g}",
            f"Target 1 (RR {realized_rr:g}): {take_profit_1:.6g}",
            f"Target 2 (ATR projection): {take_profit_2:.6g}",
            self._exit_note(features, entry_price, stop_loss, direction),
        ]

        plan = BreakRetestPlan(
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
            stop_source=stop_source,
            reasons=reasons,
            market_structure=structure.trend,
            sequence=sequence,
            setup=setup,
            timestamp=signal.timestamp,
        )
        logger.info(
            "Break/retest plan %s %s entry=%.4f stop=%.4f stage=%s",
            plan.signal.value,
            plan.symbol,
            plan.entry_price,
            plan.stop_loss,
            sequence.stage.value,
        )
        return plan

    def _assess(self, features: pd.DataFrame) -> BreakRetestSetup:
        cache_key = id(features)
        if self._assess_cache is not None and self._assess_cache_key == cache_key:
            return self._assess_cache

        try:
            long_seq, short_seq = self._engine.scan_both(
                features,
                resistance=self._resistance,
                support=self._support,
            )
        except BreakRetestValidationError as exc:
            raise StrategyValidationError(str(exc)) from exc

        volume_ok = False
        if self._config.relative_volume_column in features.columns:
            rvol = pd.to_numeric(
                features[self._config.relative_volume_column],
                errors="coerce",
            ).iloc[-1]
            volume_ok = bool(
                rvol is not None
                and not pd.isna(rvol)
                and float(rvol) > self._config.relative_volume_threshold
            )
        else:
            stats = self._volume.snapshot(features)
            volume_ok = self._volume.meets_relative_threshold(
                stats,
                threshold=self._config.relative_volume_threshold,
            )

        structure = self._require_structure()
        setup = assess_break_retest_setup(
            long_sequence=long_seq,
            short_sequence=short_seq,
            volume_ok=volume_ok,
            structure=structure.trend,
        )
        self._assess_cache_key = cache_key
        self._assess_cache = setup
        return setup

    def _resolve_structure(self, intraday: pd.DataFrame) -> MarketStructureResult:
        if self._structure_override is not None:
            return self._structure_override
        frame = intraday.copy()
        if "volume" not in frame.columns and self._config.volume_column in frame.columns:
            frame = frame.rename(columns={self._config.volume_column: "volume"})
        return self._structure_service.analyze(frame, symbol=self.active_symbol)

    def _require_structure(self) -> MarketStructureResult:
        if self._cached_structure is None:
            raise StrategyValidationError(
                "Market structure not available; call prepare() or bind_structure()",
            )
        return self._cached_structure

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
