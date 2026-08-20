"""Per-room WebSocket fan-out.

Connections are held in process memory. A single uvicorn worker is assumed;
running multiple workers would need a shared pub/sub broker, which is out of
scope here (and unnecessary for a two-person room).
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

from fastapi import WebSocket

from app.collab.schemas import WSEventType, WSOutbound
from app.core.logging import get_logger

logger = get_logger(__name__)


class ConnectionManager:
    """Track live sockets per room and broadcast frames to them."""

    def __init__(self) -> None:
        self._rooms: dict[str, dict[str, set[WebSocket]]] = defaultdict(lambda: defaultdict(set))
        self._lock = asyncio.Lock()

    async def connect(self, room_id: str, user: str, websocket: WebSocket) -> None:
        """Accept the socket and register it under ``room_id``/``user``."""
        await websocket.accept()
        async with self._lock:
            self._rooms[room_id][user].add(websocket)
        logger.info("WS connected room=%s user=%s", room_id, user)

    async def disconnect(self, room_id: str, user: str, websocket: WebSocket) -> None:
        """Deregister a socket, pruning empty user and room entries."""
        async with self._lock:
            sockets = self._rooms.get(room_id, {}).get(user)
            if sockets is not None:
                sockets.discard(websocket)
                if not sockets:
                    self._rooms[room_id].pop(user, None)
            if room_id in self._rooms and not self._rooms[room_id]:
                self._rooms.pop(room_id, None)
        logger.info("WS disconnected room=%s user=%s", room_id, user)

    def online_members(self, room_id: str) -> list[str]:
        """Return handles with at least one live socket in the room."""
        return sorted(self._rooms.get(room_id, {}).keys())

    def connection_count(self, room_id: str) -> int:
        """Return the number of live sockets in the room."""
        return sum(len(s) for s in self._rooms.get(room_id, {}).values())

    async def send_personal(self, websocket: WebSocket, event: WSOutbound) -> None:
        """Send one frame to a single socket, swallowing transport errors."""
        try:
            await websocket.send_text(event.model_dump_json())
        except Exception:  # noqa: BLE001 - socket may already be closing
            logger.debug("Failed personal send; socket likely closed")

    async def broadcast(self, room_id: str, event: WSOutbound) -> None:
        """Send one frame to every socket in the room.

        Dead sockets are collected and pruned rather than raising, so one
        stale peer cannot break delivery for the other.
        """
        async with self._lock:
            targets = [
                (user, socket)
                for user, sockets in self._rooms.get(room_id, {}).items()
                for socket in sockets
            ]
        if not targets:
            return

        payload = event.model_dump_json()
        dead: list[tuple[str, WebSocket]] = []
        for user, socket in targets:
            try:
                await socket.send_text(payload)
            except Exception:  # noqa: BLE001 - prune below
                dead.append((user, socket))

        for user, socket in dead:
            await self.disconnect(room_id, user, socket)

    async def broadcast_presence(self, room_id: str) -> None:
        """Broadcast the current online roster for a room."""
        await self.broadcast(
            room_id,
            WSOutbound(
                type=WSEventType.PRESENCE,
                data={"online_members": self.online_members(room_id)},
            ),
        )


_manager: ConnectionManager | None = None


def get_connection_manager() -> ConnectionManager:
    """Return the process-wide connection manager."""
    global _manager
    if _manager is None:
        _manager = ConnectionManager()
    return _manager


def reset_connection_manager() -> None:
    """Drop all tracked connections (tests only)."""
    global _manager
    _manager = ConnectionManager()
