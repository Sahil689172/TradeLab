"""CRUD persistence for rooms, members, and chat messages.

This layer performs no orchestration: it maps ORM rows to Pydantic
contracts and back. ``RoomService`` is the only intended caller, mirroring
how ``MarketDataGateway`` fronts the market-data repositories.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.collab.models import ChatMessageModel, ChatRoomModel, RoomMemberModel
from app.collab.schemas import (
    AISource,
    ChatMessage,
    MessageKind,
    RoomSummary,
    TradeIdea,
)


def _new_id() -> str:
    return uuid4().hex[:24]


def _as_aware(value: datetime | None) -> datetime:
    """Return a timezone-aware UTC datetime.

    SQLite drops tzinfo on round-trip, so naive values are re-stamped as UTC.
    """
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class CollabRepository:
    """SQLAlchemy-backed storage for the collaboration module."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -- rooms ----------------------------------------------------------

    def create_room(
        self,
        *,
        name: str,
        created_by: str,
        capacity: int,
        initial_capital: float,
    ) -> RoomSummary:
        """Insert a room and register its creator as the first member."""
        room = ChatRoomModel(
            room_id=_new_id(),
            name=name,
            created_by=created_by,
            capacity=capacity,
            initial_capital=initial_capital,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(room)
        self._session.flush()
        self._session.add(RoomMemberModel(room_id=room.room_id, user=created_by))
        self._session.commit()
        return self.get_room(room.room_id)  # type: ignore[return-value]

    def get_room(self, room_id: str) -> RoomSummary | None:
        """Return a room summary with members and message count, or None."""
        room = self._session.get(ChatRoomModel, room_id)
        if room is None:
            return None
        return RoomSummary(
            room_id=room.room_id,
            name=room.name,
            created_by=room.created_by,
            created_at=_as_aware(room.created_at),
            capacity=room.capacity,
            initial_capital=room.initial_capital,
            members=self.list_members(room_id),
            message_count=self.count_messages(room_id),
        )

    def room_exists(self, room_id: str) -> bool:
        """Return True when the room id is present."""
        return self._session.get(ChatRoomModel, room_id) is not None

    def list_rooms(self, limit: int = 100) -> list[RoomSummary]:
        """Return the most recently created rooms."""
        stmt = select(ChatRoomModel).order_by(ChatRoomModel.created_at.desc()).limit(limit)
        rooms = self._session.execute(stmt).scalars().all()
        return [
            RoomSummary(
                room_id=r.room_id,
                name=r.name,
                created_by=r.created_by,
                created_at=_as_aware(r.created_at),
                capacity=r.capacity,
                initial_capital=r.initial_capital,
                members=self.list_members(r.room_id),
                message_count=self.count_messages(r.room_id),
            )
            for r in rooms
        ]

    def delete_room(self, room_id: str) -> bool:
        """Delete a room with its members and messages. Returns True if removed."""
        room = self._session.get(ChatRoomModel, room_id)
        if room is None:
            return False
        self._session.execute(delete(ChatMessageModel).where(ChatMessageModel.room_id == room_id))
        self._session.execute(delete(RoomMemberModel).where(RoomMemberModel.room_id == room_id))
        self._session.delete(room)
        self._session.commit()
        return True

    # -- members --------------------------------------------------------

    def list_members(self, room_id: str) -> list[str]:
        """Return member handles ordered by join time."""
        stmt = (
            select(RoomMemberModel.user)
            .where(RoomMemberModel.room_id == room_id)
            .order_by(RoomMemberModel.joined_at.asc())
        )
        return list(self._session.execute(stmt).scalars().all())

    def is_member(self, room_id: str, user: str) -> bool:
        """Return True when the user has joined the room."""
        stmt = select(RoomMemberModel).where(
            RoomMemberModel.room_id == room_id,
            RoomMemberModel.user == user,
        )
        return self._session.execute(stmt).scalar_one_or_none() is not None

    def add_member(self, room_id: str, user: str) -> list[str]:
        """Add a member idempotently and return the resulting member list."""
        if not self.is_member(room_id, user):
            self._session.add(RoomMemberModel(room_id=room_id, user=user))
            self._session.commit()
        return self.list_members(room_id)

    def remove_member(self, room_id: str, user: str) -> list[str]:
        """Remove a member and return the resulting member list."""
        self._session.execute(
            delete(RoomMemberModel).where(
                RoomMemberModel.room_id == room_id,
                RoomMemberModel.user == user,
            ),
        )
        self._session.commit()
        return self.list_members(room_id)

    # -- messages -------------------------------------------------------

    def add_message(
        self,
        *,
        room_id: str,
        author: str,
        kind: MessageKind,
        text: str,
        trade_idea: TradeIdea | None = None,
        ai_source: AISource | None = None,
        ai_tools_used: list[str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> ChatMessage:
        """Persist one message and return its Pydantic contract."""
        payload: dict[str, object] = {}
        if trade_idea is not None:
            payload["trade_idea"] = trade_idea.model_dump(mode="json")
        if ai_source is not None:
            payload["ai_source"] = ai_source.value
        if ai_tools_used:
            payload["ai_tools_used"] = list(ai_tools_used)
        if metadata:
            payload["metadata"] = metadata

        row = ChatMessageModel(
            message_id=_new_id(),
            room_id=room_id,
            author=author,
            kind=kind.value,
            text=text,
            created_at=datetime.now(timezone.utc),
            payload_json=json.dumps(payload) if payload else None,
        )
        self._session.add(row)
        self._session.commit()
        return _to_message(row)

    def list_messages(self, room_id: str, limit: int = 50) -> list[ChatMessage]:
        """Return the newest ``limit`` messages in chronological order."""
        stmt = (
            select(ChatMessageModel)
            .where(ChatMessageModel.room_id == room_id)
            .order_by(ChatMessageModel.created_at.desc(), ChatMessageModel.message_id.desc())
            .limit(limit)
        )
        rows = list(self._session.execute(stmt).scalars().all())
        rows.reverse()
        return [_to_message(row) for row in rows]

    def list_messages_by_kind(
        self,
        room_id: str,
        kind: MessageKind,
        limit: int = 20,
    ) -> list[ChatMessage]:
        """Return the newest messages of one kind, chronologically ordered."""
        stmt = (
            select(ChatMessageModel)
            .where(
                ChatMessageModel.room_id == room_id,
                ChatMessageModel.kind == kind.value,
            )
            .order_by(ChatMessageModel.created_at.desc(), ChatMessageModel.message_id.desc())
            .limit(limit)
        )
        rows = list(self._session.execute(stmt).scalars().all())
        rows.reverse()
        return [_to_message(row) for row in rows]

    def count_messages(self, room_id: str) -> int:
        """Return the total message count for a room."""
        stmt = select(func.count()).select_from(ChatMessageModel).where(
            ChatMessageModel.room_id == room_id,
        )
        return int(self._session.execute(stmt).scalar_one())


def _to_message(row: ChatMessageModel) -> ChatMessage:
    """Map an ORM row to the ``ChatMessage`` contract."""
    payload: dict[str, object] = {}
    if row.payload_json:
        try:
            payload = json.loads(row.payload_json)
        except (ValueError, TypeError):
            payload = {}

    raw_idea = payload.get("trade_idea")
    idea = TradeIdea.model_validate(raw_idea) if isinstance(raw_idea, dict) else None

    raw_source = payload.get("ai_source")
    source = AISource(raw_source) if isinstance(raw_source, str) else None

    raw_tools = payload.get("ai_tools_used")
    tools = [str(t) for t in raw_tools] if isinstance(raw_tools, list) else []

    raw_meta = payload.get("metadata")
    meta = raw_meta if isinstance(raw_meta, dict) else {}

    return ChatMessage(
        message_id=row.message_id,
        room_id=row.room_id,
        author=row.author,
        kind=MessageKind(row.kind),
        text=row.text,
        created_at=_as_aware(row.created_at),
        trade_idea=idea,
        ai_source=source,
        ai_tools_used=tools,
        metadata=meta,
    )
