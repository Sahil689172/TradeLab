"""Collaborative rooms: shared chat, shared paper portfolio, grounded AI.

Public surface is ``RoomService`` (rooms, messages, shared orders) and
``RoomAIAgent`` (read-only assistant). Repositories and ORM models are
internal implementation details, mirroring the market_data module.
"""

from app.collab.room_service import RoomService, get_room_book_registry, reset_room_books

__all__ = ["RoomService", "get_room_book_registry", "reset_room_books"]
