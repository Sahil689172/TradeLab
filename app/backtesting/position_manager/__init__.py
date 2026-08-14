"""Position Manager (Phase A5.3) — position lifecycle after simulated fills."""

from app.backtesting.position_manager.exceptions import (
    PositionInvariantError,
    PositionLookAheadError,
    PositionManagerError,
)
from app.backtesting.position_manager.manager import PositionManager
from app.backtesting.position_manager.runner import ReplayPositionRunner
from app.backtesting.position_manager.schemas import (
    EndOfBacktestPolicy,
    Position,
    PositionActionResult,
    PositionEvent,
    PositionEventType,
    PositionExitReason,
    PositionManagerConfig,
    PositionRejectReason,
    PositionReplayResult,
    PositionSide,
    PositionStatus,
)

__all__ = [
    "EndOfBacktestPolicy",
    "Position",
    "PositionActionResult",
    "PositionEvent",
    "PositionEventType",
    "PositionExitReason",
    "PositionInvariantError",
    "PositionLookAheadError",
    "PositionManager",
    "PositionManagerConfig",
    "PositionManagerError",
    "PositionRejectReason",
    "PositionReplayResult",
    "PositionSide",
    "PositionStatus",
    "ReplayPositionRunner",
]
