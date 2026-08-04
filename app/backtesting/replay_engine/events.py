"""Replay lifecycle events emitted by the engine."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from app.services.trade_recommendation.schemas import TradeRecommendation
from app.strategy_engine.models import SignalType


class ReplayEventType(str, Enum):
    REPLAY_STARTED = "ReplayStarted"
    NEW_CANDLE = "NewCandle"
    STRATEGY_EVALUATION = "StrategyEvaluation"
    RECOMMENDATION_GENERATED = "RecommendationGenerated"
    REPLAY_COMPLETED = "ReplayCompleted"


class _EventBase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: ReplayEventType
    timestamp: datetime
    symbol: str


class ReplayStarted(_EventBase):
    event_type: Literal[ReplayEventType.REPLAY_STARTED] = ReplayEventType.REPLAY_STARTED
    total_candles: int = Field(..., ge=0)
    start_index: int = Field(..., ge=0)


class NewCandle(_EventBase):
    event_type: Literal[ReplayEventType.NEW_CANDLE] = ReplayEventType.NEW_CANDLE
    replay_index: int = Field(..., ge=0)
    open: float
    high: float
    low: float
    close: float
    volume: float


class StrategyEvaluation(_EventBase):
    event_type: Literal[ReplayEventType.STRATEGY_EVALUATION] = (
        ReplayEventType.STRATEGY_EVALUATION
    )
    strategy_name: str
    replay_index: int = Field(..., ge=0)
    window_size: int = Field(..., ge=1)


class RecommendationGenerated(_EventBase):
    event_type: Literal[ReplayEventType.RECOMMENDATION_GENERATED] = (
        ReplayEventType.RECOMMENDATION_GENERATED
    )
    strategy_name: str
    signal: SignalType
    confidence: float
    recommendation: TradeRecommendation


class ReplayCompleted(_EventBase):
    event_type: Literal[ReplayEventType.REPLAY_COMPLETED] = ReplayEventType.REPLAY_COMPLETED
    candles_replayed: int = Field(..., ge=0)
    recommendations_generated: int = Field(..., ge=0)


ReplayEvent = Annotated[
    Union[
        ReplayStarted,
        NewCandle,
        StrategyEvaluation,
        RecommendationGenerated,
        ReplayCompleted,
    ],
    Field(discriminator="event_type"),
]
