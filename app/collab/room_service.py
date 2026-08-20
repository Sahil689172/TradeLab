"""Room orchestration: membership, messages, and the shared paper portfolio.

Each room owns exactly one ``PaperTradingBook`` (the existing A5.2
``SimulatedBroker``), so two people in a room act on the same positions and
the same cash balance. Order placement is serialized per room with an
asyncio lock, which prevents two simultaneous clicks from racing on the
broker state or on SQLite writes.

The AI never reaches this class's order path — it is wired only to the
read-only tool surface in ``app.collab.ai.tools``.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from sqlalchemy.orm import Session

from app.backtesting.order_execution.engine import OrderExecutionEngine
from app.backtesting.order_execution.schemas import ExecutionConfig, PositionSizingMode
from app.collab.exceptions import NotARoomMemberError, RoomFullError, RoomNotFoundError
from app.collab.repository import CollabRepository
from app.collab.schemas import (
    AISource,
    ChatMessage,
    MessageKind,
    RoomCreateRequest,
    RoomOrderRequest,
    RoomSummary,
    TradeIdea,
)
from app.core.logging import get_logger
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.services.dashboard.market_service import get_market_service
from app.services.dashboard.paper_trading_service import PaperTradingBook
from app.services.dashboard.portfolio_service import PortfolioService
from app.services.dashboard.schemas import (
    OrderRequest,
    OrderResponse,
    OrderSide as ApiOrderSide,
    PortfolioResponse,
)

logger = get_logger(__name__)


class RoomBookRegistry:
    """Process-local map of ``room_id`` to its shared paper trading book.

    The dashboard's ``get_paper_book()`` singleton stays untouched so the
    existing single-user dashboard keeps its own book; rooms are isolated
    from it and from each other.
    """

    def __init__(self) -> None:
        self._books: dict[str, PaperTradingBook] = {}
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def get_or_create(self, room_id: str, *, initial_capital: float) -> PaperTradingBook:
        """Return the room's book, creating it on first access."""
        book = self._books.get(room_id)
        if book is None:
            book = PaperTradingBook(
                initial_capital=initial_capital,
                execution=OrderExecutionEngine(
                    ExecutionConfig(
                        initial_capital=initial_capital,
                        position_sizing=PositionSizingMode.PERCENT_OF_CAPITAL,
                        percent=10.0,
                    ),
                ),
            )
            self._books[room_id] = book
            logger.info("Created shared paper book for room=%s capital=%.2f", room_id, initial_capital)
        return book

    def lock(self, room_id: str) -> asyncio.Lock:
        """Return the per-room order lock."""
        return self._locks[room_id]

    def drop(self, room_id: str) -> None:
        """Forget a room's book and lock."""
        self._books.pop(room_id, None)
        self._locks.pop(room_id, None)

    def clear(self) -> None:
        """Drop every book (tests only)."""
        self._books.clear()
        self._locks.clear()


_registry: RoomBookRegistry | None = None


def get_room_book_registry() -> RoomBookRegistry:
    """Return the process-wide room book registry."""
    global _registry
    if _registry is None:
        _registry = RoomBookRegistry()
    return _registry


def reset_room_books() -> None:
    """Reset all room books (tests only)."""
    get_room_book_registry().clear()


class RoomService:
    """Public entry point for everything a room can do."""

    def __init__(self, session: Session) -> None:
        self._repo = CollabRepository(session)
        self._registry = get_room_book_registry()

    # -- rooms ----------------------------------------------------------

    def create_room(self, request: RoomCreateRequest) -> RoomSummary:
        """Create a room and eagerly allocate its shared book."""
        room = self._repo.create_room(
            name=request.name,
            created_by=request.created_by,
            capacity=request.capacity,
            initial_capital=request.initial_capital,
        )
        self._registry.get_or_create(room.room_id, initial_capital=room.initial_capital)
        return room

    def list_rooms(self, limit: int = 100) -> list[RoomSummary]:
        """Return recently created rooms."""
        return self._repo.list_rooms(limit=limit)

    def get_room(self, room_id: str) -> RoomSummary:
        """Return a room or raise ``RoomNotFoundError``."""
        room = self._repo.get_room(room_id)
        if room is None:
            raise RoomNotFoundError(room_id)
        return room

    def delete_room(self, room_id: str) -> bool:
        """Delete a room and release its in-memory book."""
        removed = self._repo.delete_room(room_id)
        if removed:
            self._registry.drop(room_id)
        return removed

    def join(self, room_id: str, user: str) -> RoomSummary:
        """Add a user to a room, respecting capacity."""
        room = self.get_room(room_id)
        if user not in room.members and len(room.members) >= room.capacity:
            raise RoomFullError(room_id, room.capacity)
        self._repo.add_member(room_id, user)
        return self.get_room(room_id)

    def leave(self, room_id: str, user: str) -> RoomSummary:
        """Remove a user from a room."""
        self.get_room(room_id)
        self._repo.remove_member(room_id, user)
        return self.get_room(room_id)

    def require_member(self, room_id: str, user: str) -> None:
        """Raise unless ``user`` has joined ``room_id``."""
        if not self._repo.room_exists(room_id):
            raise RoomNotFoundError(room_id)
        if not self._repo.is_member(room_id, user):
            raise NotARoomMemberError(room_id, user)

    def book_for(self, room_id: str) -> PaperTradingBook:
        """Return the shared paper book for a room."""
        room = self.get_room(room_id)
        return self._registry.get_or_create(room.room_id, initial_capital=room.initial_capital)

    # -- messages -------------------------------------------------------

    def history(self, room_id: str, limit: int = 50) -> list[ChatMessage]:
        """Return recent messages in chronological order."""
        self.get_room(room_id)
        return self._repo.list_messages(room_id, limit=limit)

    def post_chat(self, room_id: str, author: str, text: str) -> ChatMessage:
        """Persist a plain chat message from a member."""
        self.require_member(room_id, author)
        return self._repo.add_message(
            room_id=room_id,
            author=author,
            kind=MessageKind.CHAT,
            text=text,
        )

    def post_system(self, room_id: str, text: str) -> ChatMessage:
        """Persist a system notice (joins, errors, order events)."""
        return self._repo.add_message(
            room_id=room_id,
            author="system",
            kind=MessageKind.SYSTEM,
            text=text,
        )

    def post_ai_reply(
        self,
        room_id: str,
        text: str,
        *,
        source: AISource,
        tools_used: list[str],
        model: str | None = None,
        fell_back: bool = False,
    ) -> ChatMessage:
        """Persist an AI reply along with the tools it consulted."""
        return self._repo.add_message(
            room_id=room_id,
            author="AI",
            kind=MessageKind.AI_REPLY,
            text=text,
            ai_source=source,
            ai_tools_used=tools_used,
            metadata={"model": model, "fell_back": fell_back},
        )

    def post_trade_idea(
        self,
        room_id: str,
        author: str,
        idea: TradeIdea,
        *,
        gateway: MarketDataGateway | None = None,
    ) -> ChatMessage:
        """Persist a structured trade idea, stamping the current price.

        Stamping ``price_at_post`` at write time is what later makes the
        idea scoreable without guessing when it was called.
        """
        self.require_member(room_id, author)
        stamped = idea
        if idea.price_at_post is None and gateway is not None:
            price = get_market_service().latest_close(idea.symbol, gateway=gateway)
            if price:
                stamped = idea.model_copy(update={"price_at_post": price})
        summary = f"{stamped.direction.value} {stamped.symbol.upper()}"
        if stamped.thesis:
            summary = f"{summary} — {stamped.thesis}"
        return self._repo.add_message(
            room_id=room_id,
            author=author,
            kind=MessageKind.TRADE_IDEA,
            text=summary,
            trade_idea=stamped,
        )

    def recent_trade_ideas(self, room_id: str, limit: int = 10) -> list[ChatMessage]:
        """Return the newest structured trade ideas in the room."""
        return self._repo.list_messages_by_kind(room_id, MessageKind.TRADE_IDEA, limit=limit)

    # -- shared portfolio ----------------------------------------------

    def portfolio(self, room_id: str, *, gateway: MarketDataGateway) -> PortfolioResponse:
        """Return the room's shared portfolio snapshot."""
        book = self.book_for(room_id)
        return PortfolioService(book).build(gateway=gateway)

    def orders(self, room_id: str, limit: int = 50) -> list:
        """Return recent paper orders placed in the room."""
        from app.services.dashboard.paper_trading_service import _to_order_row

        book = self.book_for(room_id)
        return [_to_order_row(record) for record in book.orders[:limit]]

    async def place_order(
        self,
        room_id: str,
        request: RoomOrderRequest,
        *,
        gateway: MarketDataGateway,
    ) -> tuple[OrderResponse, ChatMessage]:
        """Execute a paper order against the room's shared book.

        Serialized per room so two members clicking buy at the same instant
        cannot interleave broker mutations. Every outcome — filled or
        rejected — is written into the chat as an ``ORDER_EVENT``, which is
        what turns the room into a decision log rather than just talk.
        """
        self.require_member(room_id, request.author)
        book = self.book_for(room_id)
        side = ApiOrderSide.BUY if request.side == "BUY" else ApiOrderSide.SELL

        async with self._registry.lock(room_id):
            market = get_market_service()
            price = request.price or market.latest_close(request.symbol, gateway=gateway)
            if price is None or price <= 0:
                message = (
                    f"No local price for {request.symbol.upper()}. "
                    "Bootstrap or refresh the symbol first, or pass an explicit price."
                )
                event = self._repo.add_message(
                    room_id=room_id,
                    author=request.author,
                    kind=MessageKind.ORDER_EVENT,
                    text=message,
                    metadata={"accepted": False, "reason": "NO_PRICE"},
                )
                from app.services.dashboard.schemas import OrderStatus as ApiOrderStatus

                return (
                    OrderResponse(
                        accepted=False,
                        status=ApiOrderStatus.REJECTED,
                        message=message,
                    ),
                    event,
                )

            result = book.place_order(
                side=side,
                request=OrderRequest(
                    symbol=request.symbol,
                    quantity=request.quantity,
                    order_type="MARKET",
                    price=request.price,
                    stop_loss=request.stop_loss,
                    target=request.target,
                ),
                market_price=price,
            )

        verb = "bought" if side is ApiOrderSide.BUY else "sold"
        if result.accepted and result.order is not None:
            text = (
                f"{request.author} {verb} {result.order.quantity:g} "
                f"{result.order.symbol} @ {result.order.price:,.2f} (paper)"
            )
        else:
            text = (
                f"{request.author}'s {request.side} {request.quantity:g} "
                f"{request.symbol.upper()} was rejected: {result.message}"
            )

        event = self._repo.add_message(
            room_id=room_id,
            author=request.author,
            kind=MessageKind.ORDER_EVENT,
            text=text,
            metadata={
                "accepted": result.accepted,
                "status": result.status.value,
                "side": request.side,
                "symbol": request.symbol.upper(),
                "quantity": request.quantity,
                "order_id": result.order.order_id if result.order else None,
            },
        )
        return result, event
