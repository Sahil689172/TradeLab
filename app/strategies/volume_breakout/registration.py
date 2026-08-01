"""Registration helpers for the Volume Breakout strategy."""

from __future__ import annotations

from app.levels.schemas import LevelsSnapshot
from app.market_structure.schemas import MarketStructureResult
from app.services.strategy_engine.indicators.volume_analysis import VolumeAnalysisService
from app.services.strategy_engine.indicators.vwap import VWAPService
from app.strategies.volume_breakout.config import VolumeBreakoutConfig
from app.strategies.volume_breakout.strategy import VolumeBreakoutStrategy
from app.strategy_engine.registry import StrategyRegistry


def build_volume_breakout_strategy(
    config: VolumeBreakoutConfig | None = None,
    *,
    volume_service: VolumeAnalysisService | None = None,
    vwap_service: VWAPService | None = None,
    market_structure: MarketStructureResult | None = None,
    levels: LevelsSnapshot | None = None,
) -> VolumeBreakoutStrategy:
    return VolumeBreakoutStrategy(
        config,
        volume_service=volume_service,
        vwap_service=vwap_service,
        market_structure=market_structure,
        levels=levels,
    )


def register_volume_breakout_strategy(
    registry: StrategyRegistry,
    config: VolumeBreakoutConfig | None = None,
    *,
    volume_service: VolumeAnalysisService | None = None,
    vwap_service: VWAPService | None = None,
    market_structure: MarketStructureResult | None = None,
    levels: LevelsSnapshot | None = None,
) -> VolumeBreakoutStrategy:
    strategy = build_volume_breakout_strategy(
        config,
        volume_service=volume_service,
        vwap_service=vwap_service,
        market_structure=market_structure,
        levels=levels,
    )
    registry.register(strategy)
    return strategy
