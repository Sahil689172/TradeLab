"""Reusable Break & Retest detection for strategies."""

from app.services.strategy_engine.break_retest.detection import (
    detect_break,
    detect_confirmation_candle,
    detect_failed_retest,
    detect_retest,
    resolve_break_level,
)
from app.services.strategy_engine.break_retest.engine import (
    BreakRetestEngine,
    BreakRetestEngineConfig,
    BreakRetestValidationError,
)
from app.services.strategy_engine.break_retest.schemas import (
    BreakEvent,
    BreakRetestSequence,
    BreakRetestStage,
    ConfirmationCandle,
    RetestEvent,
)

__all__ = [
    "BreakEvent",
    "BreakRetestEngine",
    "BreakRetestEngineConfig",
    "BreakRetestSequence",
    "BreakRetestStage",
    "BreakRetestValidationError",
    "ConfirmationCandle",
    "RetestEvent",
    "detect_break",
    "detect_confirmation_candle",
    "detect_failed_retest",
    "detect_retest",
    "resolve_break_level",
]
