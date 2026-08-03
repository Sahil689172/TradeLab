"""Schemas for strategy execution context."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult
from app.strategies.momentum.schemas import MomentumUniverseRanking
from app.strategies.relative_strength.schemas import UniverseRanking


class ContextRequirement(str, Enum):
    """Named context assets a strategy may need."""

    FEATURES = "FEATURES"
    DAILY_OHLCV = "DAILY_OHLCV"
    INTRADAY_FEATURES = "INTRADAY_FEATURES"
    LEVELS = "LEVELS"
    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    RS_RANKING = "RS_RANKING"
    MOMENTUM_RANKING = "MOMENTUM_RANKING"
    VWAP_READY = "VWAP_READY"
    RELATIVE_VOLUME = "RELATIVE_VOLUME"


class StrategyContext(BaseModel):
    """Prepared execution context for one strategy run.

    ``features`` is the frame passed to ``StrategyRunner`` / ``validate`` /
    ``prepare``. Optional artifacts are applied onto the strategy via public
    ``bind_*`` APIs by ``StrategyContextProvider.apply`` — strategies do not
    load data themselves.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True, extra="forbid")

    strategy_name: str
    symbol: str
    timeframe: str = "15 Minute"
    prepared_at: datetime
    features: pd.DataFrame
    daily_ohlcv: pd.DataFrame | None = None
    levels: LevelsSnapshot | None = None
    market_structure: MarketStructureResult | None = None
    rs_ranking: UniverseRanking | None = None
    momentum_ranking: MomentumUniverseRanking | None = None
    requirements: tuple[ContextRequirement, ...] = ()
    notes: list[str] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


class ContextProviderConfig(BaseModel):
    """Tunable paths and knobs for context assembly."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    storage_dir: str | None = None
    timeframe: str = "15 Minute"
    opening_range_bars: int = Field(default=1, ge=1)
    structure_swing_length: int = Field(default=2, ge=1)
    allow_synthetic_features: bool = True
    synthetic_bars: int = Field(default=120, ge=40)
    # Minimum bars required in the latest session for ORB / intraday strategies
    min_session_bars: int = Field(default=12, ge=4)
    intraday_bar_minutes: int = Field(default=5, ge=1)
    # Architectural cache (symbol artifacts + rankings). Does not change outputs.
    enable_context_cache: bool = True
