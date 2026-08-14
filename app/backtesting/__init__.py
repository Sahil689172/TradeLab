"""Historical backtesting building blocks (replay + order execution).

Package layout lives under ``app/backtesting/`` (TradeLab convention). There is no
``backend/app/`` package in this repository.
"""

from app.backtesting.order_execution import (
    ExecutionConfig,
    OrderExecutionEngine,
    SimulatedBroker,
    TradeLogEntry,
)
from app.backtesting.position_manager import (
    PositionManager,
    ReplayPositionRunner,
)
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
    ReplaySpeed,
    ReplayStepResult,
)
from app.backtesting.replay_engine.scheduler import ReplayScheduler
from app.backtesting.replay_engine.state import ReplayStatus

__all__ = [
    "ExecutionConfig",
    "HistoricalReplayEngine",
    "NewCandle",
    "OrderExecutionEngine",
    "PositionManager",
    "RecommendationGenerated",
    "ReplayCompleted",
    "ReplayConfig",
    "ReplayConfigurationError",
    "ReplayEngineError",
    "ReplayEvent",
    "ReplayEventType",
    "ReplayLookAheadError",
    "ReplayPositionRunner",
    "ReplayResult",
    "ReplayScheduler",
    "ReplaySession",
    "ReplaySessionError",
    "ReplaySpeed",
    "ReplayStarted",
    "ReplayStatus",
    "ReplayStepResult",
    "SimulatedBroker",
    "StrategyEvaluation",
    "TradeLogEntry",
]
