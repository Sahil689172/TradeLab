"""Pydantic contracts for collaborative rooms, chat, and AI replies."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)


class MessageKind(str, Enum):
    """Discriminates the type of a persisted chat message."""

    CHAT = "CHAT"
    TRADE_IDEA = "TRADE_IDEA"
    ORDER_EVENT = "ORDER_EVENT"
    AI_REPLY = "AI_REPLY"
    SYSTEM = "SYSTEM"


class TradeDirection(str, Enum):
    """Direction of a structured trade idea."""

    LONG = "LONG"
    SHORT = "SHORT"


class AISource(str, Enum):
    """Which provider produced an AI reply."""

    GEMINI = "gemini"
    GROQ = "groq"
    NONE = "none"


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------


class RoomCreateRequest(BaseModel):
    """Payload for creating a collaborative room."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    created_by: str = Field(..., min_length=1, max_length=40)
    initial_capital: float = Field(default=1_000_000.0, gt=0.0)
    capacity: int = Field(default=2, ge=1, le=10)


class RoomSummary(BaseModel):
    """Public view of a room."""

    model_config = ConfigDict(extra="forbid")

    room_id: str
    name: str
    created_by: str
    created_at: datetime
    capacity: int
    initial_capital: float
    members: list[str] = Field(default_factory=list)
    online_members: list[str] = Field(default_factory=list)
    message_count: int = 0


class RoomListResponse(BaseModel):
    """Envelope for a list of rooms."""

    model_config = ConfigDict(extra="forbid")

    total: int
    rooms: list[RoomSummary]


# ---------------------------------------------------------------------------
# Trade ideas
# ---------------------------------------------------------------------------


class TradeIdea(BaseModel):
    """Structured, accountable trade call posted into a room.

    Stored alongside the price at posting time so the idea can be scored
    later without re-deriving history.
    """

    model_config = ConfigDict(extra="forbid")

    symbol: str = Field(..., min_length=1, max_length=32)
    direction: TradeDirection = TradeDirection.LONG
    thesis: str = Field(default="", max_length=2000)
    entry: float | None = Field(default=None, gt=0.0)
    stop_loss: float | None = Field(default=None, gt=0.0)
    target: float | None = Field(default=None, gt=0.0)
    price_at_post: float | None = Field(default=None, gt=0.0)


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """A single persisted message in a room."""

    model_config = ConfigDict(extra="forbid")

    message_id: str
    room_id: str
    author: str
    kind: MessageKind = MessageKind.CHAT
    text: str = ""
    created_at: datetime
    trade_idea: TradeIdea | None = None
    ai_source: AISource | None = None
    ai_tools_used: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageListResponse(BaseModel):
    """Envelope for paginated room history."""

    model_config = ConfigDict(extra="forbid")

    room_id: str
    total: int
    messages: list[ChatMessage]


class PostMessageRequest(BaseModel):
    """REST payload for posting a chat message."""

    model_config = ConfigDict(extra="forbid")

    author: str = Field(..., min_length=1, max_length=40)
    text: str = Field(..., min_length=1, max_length=4000)


class PostTradeIdeaRequest(BaseModel):
    """REST payload for posting a structured trade idea."""

    model_config = ConfigDict(extra="forbid")

    author: str = Field(..., min_length=1, max_length=40)
    idea: TradeIdea


# ---------------------------------------------------------------------------
# Room orders (shared paper portfolio)
# ---------------------------------------------------------------------------


class RoomOrderRequest(BaseModel):
    """Payload for placing a paper order against a room's shared book."""

    model_config = ConfigDict(extra="forbid")

    author: str = Field(..., min_length=1, max_length=40)
    side: Literal["BUY", "SELL"]
    symbol: str = Field(..., min_length=1, max_length=32)
    quantity: float = Field(..., gt=0.0)
    price: float | None = Field(default=None, gt=0.0)
    stop_loss: float | None = Field(default=None, gt=0.0)
    target: float | None = Field(default=None, gt=0.0)


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------


class AIAskRequest(BaseModel):
    """REST payload for asking the room assistant a question."""

    model_config = ConfigDict(extra="forbid")

    author: str = Field(..., min_length=1, max_length=40)
    question: str = Field(..., min_length=1, max_length=4000)


class AIReply(BaseModel):
    """Result of one grounded AI turn."""

    model_config = ConfigDict(extra="forbid")

    text: str
    source: AISource
    model: str | None = None
    tools_used: list[str] = Field(default_factory=list)
    fell_back: bool = False
    error: str | None = None


class AIStatus(BaseModel):
    """Reports which providers are usable without exposing key material."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool
    primary: str
    fallback: str | None = None
    gemini_configured: bool = False
    groq_configured: bool = False
    gemini_model: str | None = None
    groq_model: str | None = None
    trigger: str
    read_only: bool = True


# ---------------------------------------------------------------------------
# WebSocket envelopes
# ---------------------------------------------------------------------------


class WSEventType(str, Enum):
    """Server-to-client websocket event types."""

    MESSAGE = "message"
    HISTORY = "history"
    PRESENCE = "presence"
    PORTFOLIO = "portfolio"
    AI_THINKING = "ai_thinking"
    ERROR = "error"
    PONG = "pong"


class WSOutbound(BaseModel):
    """Envelope for every server-to-client websocket frame."""

    model_config = ConfigDict(extra="forbid")

    type: WSEventType
    data: Any = None
    sent_at: datetime = Field(default_factory=utc_now)


class WSInbound(BaseModel):
    """Envelope for every client-to-server websocket frame.

    ``type`` selects which optional block is read, keeping a single
    permissive shape rather than a discriminated union over the wire.
    """

    model_config = ConfigDict(extra="forbid")

    type: Literal["chat", "trade_idea", "order", "ping", "history"] = "chat"
    text: str | None = Field(default=None, max_length=4000)
    idea: TradeIdea | None = None
    order: RoomOrderRequest | None = None
    limit: int | None = Field(default=None, ge=1, le=500)
