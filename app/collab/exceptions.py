"""Exceptions raised by the collaboration (chat + shared paper trading) module."""

from __future__ import annotations


class CollabError(Exception):
    """Base error for the collaboration module."""


class RoomNotFoundError(CollabError):
    """Raised when a room id does not exist."""

    def __init__(self, room_id: str) -> None:
        super().__init__(f"Room '{room_id}' not found")
        self.room_id = room_id


class RoomFullError(CollabError):
    """Raised when a room has reached its member capacity."""

    def __init__(self, room_id: str, capacity: int) -> None:
        super().__init__(f"Room '{room_id}' is full (capacity {capacity})")
        self.room_id = room_id
        self.capacity = capacity


class NotARoomMemberError(CollabError):
    """Raised when a user acts on a room they have not joined."""

    def __init__(self, room_id: str, user: str) -> None:
        super().__init__(f"User '{user}' is not a member of room '{room_id}'")
        self.room_id = room_id
        self.user = user


class AIDisabledError(CollabError):
    """Raised when the AI assistant is invoked while disabled."""

    def __init__(self) -> None:
        super().__init__("AI assistant is disabled (AI_ENABLED=false)")


class AIProviderError(CollabError):
    """Raised when every configured LLM provider fails."""

    def __init__(self, message: str, *, attempts: list[str] | None = None) -> None:
        super().__init__(message)
        self.attempts = attempts or []


class AINotConfiguredError(AIProviderError):
    """Raised when no provider has an API key configured."""

    def __init__(self) -> None:
        super().__init__(
            "No AI provider configured. Set GEMINI_API_KEY (primary) "
            "and/or GROQ_API_KEY (fallback) in your .env file.",
        )
