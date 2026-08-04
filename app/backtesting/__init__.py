"""Historical Replay Engine — feed candles to the Strategy Engine without look-ahead.

Package layout lives under ``app/backtesting/`` (TradeLab convention). There is no
``backend/app/`` package in this repository.
"""

from app.backtesting.replay_engine.engine import HistoricalReplayEngine
from app.backtesting.replay_engine.events import (
    NewCandle,
    RecommendationGenerated,
    ReplayCompleted,
    ReplayEvent,
    ReplayEventType,
    ReplayStarted,
    StrategyEvaluation,
)
from app.backtesting.replay_engine.exceptions import (
    ReplayConfigurationError,
    ReplayEngineError,
    ReplayLookAheadError,
    ReplaySessionError,
)
from app.backtesting.replay_engine.replay_session import ReplaySession
from app.backtesting.replay_engine.schemas import (
    ReplayConfig,
    ReplayResult,
    ReplayStepResult,
    ReplaySpeed,
)
from app.backtesting.replay_engine.scheduler import ReplayScheduler
from app.backtesting.replay_engine.state import ReplayStatus

__all__ = [
    "HistoricalReplayEngine",
    "NewCandle",
    "RecommendationGenerated",
    "ReplayCompleted",
    "ReplayConfig",
    "ReplayConfigurationError",
    "ReplayEngineError",
    "ReplayEvent",
    "ReplayEventType",
    "ReplayLookAheadError",
    "ReplayResult",
    "ReplayScheduler",
    "ReplaySession",
    "ReplaySessionError",
    "ReplaySpeed",
    "ReplayStarted",
    "ReplayStatus",
    "ReplayStepResult",
    "StrategyEvaluation",
]
