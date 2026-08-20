"""Collaborative room endpoints: REST management plus a WebSocket channel.

Chat, structured trade ideas, shared paper orders, and the grounded AI
assistant all flow through here. The WebSocket is the primary interface;
the REST routes exist so the same actions are scriptable and testable
without a socket client.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_app_settings, get_market_data_gateway
from app.collab.ai.agent import (
    RoomAIAgent,
    get_room_ai_agent,
    is_ai_invocation,
    strip_trigger,
)
from app.collab.connection_manager import ConnectionManager, get_connection_manager
from app.collab.exceptions import (
    AIDisabledError,
    AINotConfiguredError,
    CollabError,
    NotARoomMemberError,
    RoomFullError,
    RoomNotFoundError,
)
from app.collab.room_service import RoomService
from app.collab.schemas import (
    AIAskRequest,
    AIReply,
    AIStatus,
    ChatMessage,
    MessageListResponse,
    PostMessageRequest,
    PostTradeIdeaRequest,
    RoomCreateRequest,
    RoomListResponse,
    RoomOrderRequest,
    RoomSummary,
    WSEventType,
    WSInbound,
    WSOutbound,
)
from app.core.config import Settings
from app.core.database import get_db, get_session_factory
from app.core.logging import get_logger
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.schemas.responses import SuccessResponse
from app.services.dashboard.schemas import OrderResponse, OrderRow, PortfolioResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/collab", tags=["collab"])


def get_room_service(session: Session = Depends(get_db)) -> RoomService:
    """Return a room service bound to the request session."""
    return RoomService(session)


def get_ai_agent(settings: Settings = Depends(get_app_settings)) -> RoomAIAgent:
    """Return the grounded room assistant."""
    return get_room_ai_agent(settings)


def _http_error(exc: CollabError) -> HTTPException:
    """Map a domain error onto the right HTTP status."""
    if isinstance(exc, RoomNotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, RoomFullError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, NotARoomMemberError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, (AIDisabledError, AINotConfiguredError)):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Rooms
# ---------------------------------------------------------------------------


@router.post("/rooms", response_model=SuccessResponse[RoomSummary], status_code=201)
def create_room(
    request: RoomCreateRequest,
    service: RoomService = Depends(get_room_service),
) -> SuccessResponse[RoomSummary]:
    """Create a room with its own shared paper portfolio."""
    room = service.create_room(request)
    return SuccessResponse(data=room, message=f"Room '{room.name}' created")


@router.get("/rooms", response_model=SuccessResponse[RoomListResponse])
def list_rooms(
    limit: int = Query(default=50, ge=1, le=200),
    service: RoomService = Depends(get_room_service),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> SuccessResponse[RoomListResponse]:
    """List rooms with their current online rosters."""
    rooms = service.list_rooms(limit=limit)
    for room in rooms:
        room.online_members = manager.online_members(room.room_id)
    return SuccessResponse(data=RoomListResponse(total=len(rooms), rooms=rooms))


@router.get("/rooms/{room_id}", response_model=SuccessResponse[RoomSummary])
def get_room(
    room_id: str,
    service: RoomService = Depends(get_room_service),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> SuccessResponse[RoomSummary]:
    """Return one room."""
    try:
        room = service.get_room(room_id)
    except CollabError as exc:
        raise _http_error(exc) from exc
    room.online_members = manager.online_members(room_id)
    return SuccessResponse(data=room)


@router.delete("/rooms/{room_id}", response_model=SuccessResponse[dict])
def delete_room(
    room_id: str,
    service: RoomService = Depends(get_room_service),
) -> SuccessResponse[dict]:
    """Delete a room, its messages, and its shared book."""
    removed = service.delete_room(room_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Room '{room_id}' not found")
    return SuccessResponse(data={"room_id": room_id, "deleted": True})


@router.post("/rooms/{room_id}/join", response_model=SuccessResponse[RoomSummary])
def join_room(
    room_id: str,
    user: str = Query(..., min_length=1, max_length=40),
    service: RoomService = Depends(get_room_service),
) -> SuccessResponse[RoomSummary]:
    """Join a room, subject to its capacity."""
    try:
        room = service.join(room_id, user)
    except CollabError as exc:
        raise _http_error(exc) from exc
    return SuccessResponse(data=room, message=f"{user} joined {room.name}")


@router.post("/rooms/{room_id}/leave", response_model=SuccessResponse[RoomSummary])
def leave_room(
    room_id: str,
    user: str = Query(..., min_length=1, max_length=40),
    service: RoomService = Depends(get_room_service),
) -> SuccessResponse[RoomSummary]:
    """Leave a room."""
    try:
        room = service.leave(room_id, user)
    except CollabError as exc:
        raise _http_error(exc) from exc
    return SuccessResponse(data=room, message=f"{user} left {room.name}")


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------


@router.get("/rooms/{room_id}/messages", response_model=SuccessResponse[MessageListResponse])
def list_messages(
    room_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    service: RoomService = Depends(get_room_service),
) -> SuccessResponse[MessageListResponse]:
    """Return recent room history, oldest first."""
    try:
        messages = service.history(room_id, limit=limit)
    except CollabError as exc:
        raise _http_error(exc) from exc
    return SuccessResponse(
        data=MessageListResponse(room_id=room_id, total=len(messages), messages=messages),
    )


@router.post("/rooms/{room_id}/messages", response_model=SuccessResponse[ChatMessage])
async def post_message(
    room_id: str,
    request: PostMessageRequest,
    service: RoomService = Depends(get_room_service),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> SuccessResponse[ChatMessage]:
    """Post a chat message and broadcast it to live sockets."""
    try:
        message = service.post_chat(room_id, request.author, request.text)
    except CollabError as exc:
        raise _http_error(exc) from exc
    await manager.broadcast(room_id, WSOutbound(type=WSEventType.MESSAGE, data=message))
    return SuccessResponse(data=message)


@router.post("/rooms/{room_id}/trade-ideas", response_model=SuccessResponse[ChatMessage])
async def post_trade_idea(
    room_id: str,
    request: PostTradeIdeaRequest,
    service: RoomService = Depends(get_room_service),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> SuccessResponse[ChatMessage]:
    """Post a structured trade idea, stamped with the current stored price."""
    try:
        message = service.post_trade_idea(room_id, request.author, request.idea, gateway=gateway)
    except CollabError as exc:
        raise _http_error(exc) from exc
    await manager.broadcast(room_id, WSOutbound(type=WSEventType.MESSAGE, data=message))
    return SuccessResponse(data=message)


# ---------------------------------------------------------------------------
# Shared portfolio
# ---------------------------------------------------------------------------


@router.get("/rooms/{room_id}/portfolio", response_model=SuccessResponse[PortfolioResponse])
def room_portfolio(
    room_id: str,
    service: RoomService = Depends(get_room_service),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[PortfolioResponse]:
    """Return the room's shared paper portfolio."""
    try:
        data = service.portfolio(room_id, gateway=gateway)
    except CollabError as exc:
        raise _http_error(exc) from exc
    return SuccessResponse(data=data)


@router.get("/rooms/{room_id}/orders", response_model=SuccessResponse[list[OrderRow]])
def room_orders(
    room_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    service: RoomService = Depends(get_room_service),
) -> SuccessResponse[list[OrderRow]]:
    """Return recent paper orders placed in the room."""
    try:
        rows = service.orders(room_id, limit=limit)
    except CollabError as exc:
        raise _http_error(exc) from exc
    return SuccessResponse(data=rows)


@router.post("/rooms/{room_id}/orders", response_model=SuccessResponse[OrderResponse])
async def place_room_order(
    room_id: str,
    request: RoomOrderRequest,
    service: RoomService = Depends(get_room_service),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> SuccessResponse[OrderResponse]:
    """Place a paper order against the room's shared book (humans only)."""
    try:
        result, event = await service.place_order(room_id, request, gateway=gateway)
    except CollabError as exc:
        raise _http_error(exc) from exc
    await manager.broadcast(room_id, WSOutbound(type=WSEventType.MESSAGE, data=event))
    await manager.broadcast(
        room_id,
        WSOutbound(
            type=WSEventType.PORTFOLIO,
            data=service.portfolio(room_id, gateway=gateway),
        ),
    )
    return SuccessResponse(data=result, message=result.message)


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------


@router.get("/ai/status", response_model=SuccessResponse[AIStatus])
def ai_status(agent: RoomAIAgent = Depends(get_ai_agent)) -> SuccessResponse[AIStatus]:
    """Report which providers are configured, without exposing keys."""
    return SuccessResponse(data=agent.status())


@router.post("/rooms/{room_id}/ai", response_model=SuccessResponse[AIReply])
async def ask_ai(
    room_id: str,
    request: AIAskRequest,
    service: RoomService = Depends(get_room_service),
    agent: RoomAIAgent = Depends(get_ai_agent),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
    session: Session = Depends(get_db),
    manager: ConnectionManager = Depends(get_connection_manager),
) -> SuccessResponse[AIReply]:
    """Ask the grounded assistant a question and persist its reply."""
    try:
        service.require_member(room_id, request.author)
        reply = await agent.ask(
            room_id=room_id,
            question=request.question,
            gateway=gateway,
            session=session,
        )
    except CollabError as exc:
        raise _http_error(exc) from exc

    message = service.post_ai_reply(
        room_id,
        reply.text,
        source=reply.source,
        tools_used=reply.tools_used,
        model=reply.model,
        fell_back=reply.fell_back,
    )
    await manager.broadcast(room_id, WSOutbound(type=WSEventType.MESSAGE, data=message))
    return SuccessResponse(data=reply)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------


@router.websocket("/ws/rooms/{room_id}")
async def room_socket(
    websocket: WebSocket,
    room_id: str,
    user: str = Query(..., min_length=1, max_length=40),
) -> None:
    """Live room channel.

    Inbound frames: ``chat``, ``trade_idea``, ``order``, ``history``, ``ping``.
    Outbound frames: ``message``, ``history``, ``presence``, ``portfolio``,
    ``ai_thinking``, ``error``, ``pong``.

    A session is opened per frame rather than held for the socket's lifetime,
    which keeps SQLite connections short-lived under concurrent members.
    """
    settings: Settings = websocket.app.state.settings
    manager = get_connection_manager()
    session_factory = get_session_factory()
    agent = get_room_ai_agent(settings)

    session = session_factory()
    try:
        service = RoomService(session)
        try:
            service.join(room_id, user)
        except (RoomNotFoundError, RoomFullError) as exc:
            # Accept first: closing before the handshake completes makes the
            # server return a bare HTTP 403, and the browser then reports
            # code 1006 instead of the 4404/4409 the protocol documents.
            code = 4404 if isinstance(exc, RoomNotFoundError) else 4409
            reason = "Room not found" if code == 4404 else str(exc)
            await websocket.accept()
            await websocket.close(code=code, reason=reason)
            return
        history = service.history(room_id, limit=settings.chat_history_limit)
    finally:
        session.close()

    await manager.connect(room_id, user, websocket)
    await manager.send_personal(
        websocket,
        WSOutbound(type=WSEventType.HISTORY, data={"room_id": room_id, "messages": history}),
    )
    await manager.broadcast_presence(room_id)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                inbound = WSInbound.model_validate_json(raw)
            except ValidationError as exc:
                await manager.send_personal(
                    websocket,
                    WSOutbound(
                        type=WSEventType.ERROR,
                        data={"message": "Invalid frame", "detail": exc.errors()[:3]},
                    ),
                )
                continue

            if inbound.type == "ping":
                await manager.send_personal(websocket, WSOutbound(type=WSEventType.PONG))
                continue

            session = session_factory()
            try:
                service = RoomService(session)
                gateway = MarketDataGateway(session, settings=settings)

                if inbound.type == "history":
                    messages = service.history(
                        room_id,
                        limit=inbound.limit or settings.chat_history_limit,
                    )
                    await manager.send_personal(
                        websocket,
                        WSOutbound(
                            type=WSEventType.HISTORY,
                            data={"room_id": room_id, "messages": messages},
                        ),
                    )

                elif inbound.type == "chat":
                    text = (inbound.text or "").strip()
                    if not text:
                        continue
                    message = service.post_chat(room_id, user, text)
                    await manager.broadcast(
                        room_id,
                        WSOutbound(type=WSEventType.MESSAGE, data=message),
                    )
                    if settings.ai_enabled and is_ai_invocation(text, settings.ai_trigger):
                        await _handle_ai_turn(
                            room_id=room_id,
                            question=strip_trigger(text, settings.ai_trigger),
                            asked_by=user,
                            agent=agent,
                            service=service,
                            gateway=gateway,
                            session=session,
                            manager=manager,
                        )

                elif inbound.type == "trade_idea":
                    if inbound.idea is None:
                        await manager.send_personal(
                            websocket,
                            WSOutbound(
                                type=WSEventType.ERROR,
                                data={"message": "trade_idea frame requires an 'idea' block"},
                            ),
                        )
                        continue
                    message = service.post_trade_idea(room_id, user, inbound.idea, gateway=gateway)
                    await manager.broadcast(
                        room_id,
                        WSOutbound(type=WSEventType.MESSAGE, data=message),
                    )

                elif inbound.type == "order":
                    if inbound.order is None:
                        await manager.send_personal(
                            websocket,
                            WSOutbound(
                                type=WSEventType.ERROR,
                                data={"message": "order frame requires an 'order' block"},
                            ),
                        )
                        continue
                    order_request = inbound.order.model_copy(update={"author": user})
                    _result, event = await service.place_order(
                        room_id,
                        order_request,
                        gateway=gateway,
                    )
                    await manager.broadcast(
                        room_id,
                        WSOutbound(type=WSEventType.MESSAGE, data=event),
                    )
                    await manager.broadcast(
                        room_id,
                        WSOutbound(
                            type=WSEventType.PORTFOLIO,
                            data=service.portfolio(room_id, gateway=gateway),
                        ),
                    )

            except CollabError as exc:
                await manager.send_personal(
                    websocket,
                    WSOutbound(type=WSEventType.ERROR, data={"message": str(exc)}),
                )
            except Exception as exc:  # noqa: BLE001 - one bad frame must not drop the socket
                logger.exception("Room socket frame failed room=%s user=%s", room_id, user)
                await manager.send_personal(
                    websocket,
                    WSOutbound(
                        type=WSEventType.ERROR,
                        data={"message": f"Failed to process frame: {exc}"},
                    ),
                )
            finally:
                session.close()

    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(room_id, user, websocket)
        await manager.broadcast_presence(room_id)


async def _handle_ai_turn(
    *,
    room_id: str,
    question: str,
    asked_by: str,
    agent: RoomAIAgent,
    service: RoomService,
    gateway: MarketDataGateway,
    session: Session,
    manager: ConnectionManager,
) -> None:
    """Run one assistant turn and broadcast the reply into the room."""
    await manager.broadcast(
        room_id,
        WSOutbound(type=WSEventType.AI_THINKING, data={"asked_by": asked_by}),
    )
    try:
        reply = await agent.ask(
            room_id=room_id,
            question=question,
            gateway=gateway,
            session=session,
        )
    except (AIDisabledError, AINotConfiguredError) as exc:
        await manager.broadcast(
            room_id,
            WSOutbound(type=WSEventType.ERROR, data={"message": str(exc)}),
        )
        return

    message = service.post_ai_reply(
        room_id,
        reply.text,
        source=reply.source,
        tools_used=reply.tools_used,
        model=reply.model,
        fell_back=reply.fell_back,
    )
    await manager.broadcast(room_id, WSOutbound(type=WSEventType.MESSAGE, data=message))
