"""SQLAlchemy ORM models for collaborative rooms and chat history.

These tables live in the same metadata database as ``company_metadata``
and ``ingestion_state`` so no second datastore is required for local runs.
The repository layer is the only consumer; everything else goes through
``RoomService``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChatRoomModel(Base):
    """A collaborative room owning one shared paper portfolio."""

    __tablename__ = "chat_rooms"

    room_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )
    capacity: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    initial_capital: Mapped[float] = mapped_column(Float, default=1_000_000.0, nullable=False)


class RoomMemberModel(Base):
    """Membership record binding a user handle to a room."""

    __tablename__ = "chat_room_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("chat_rooms.room_id", ondelete="CASCADE"),
        nullable=False,
    )
    user: Mapped[str] = mapped_column(String(40), nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )

    __table_args__ = (
        Index("ix_room_members_room_user", "room_id", "user", unique=True),
    )


class ChatMessageModel(Base):
    """A single message row.

    ``payload_json`` carries the structured trade-idea block and AI metadata
    so the schema stays stable as those payloads evolve.
    """

    __tablename__ = "chat_messages"

    message_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    room_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("chat_rooms.room_id", ondelete="CASCADE"),
        nullable=False,
    )
    author: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="CHAT", nullable=False)
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utc_now,
        nullable=False,
    )
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_chat_messages_room_created", "room_id", "created_at"),
    )


__all__ = ["ChatRoomModel", "RoomMemberModel", "ChatMessageModel"]
