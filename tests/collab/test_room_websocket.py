"""WebSocket channel: chat fan-out, trade ideas, shared orders, AI trigger."""

from __future__ import annotations

import json

import httpx
import pytest

PREFIX = "/api/v1/collab"


def _create_room(client, capacity: int = 2) -> str:
    response = client.post(
        f"{PREFIX}/rooms",
        json={
            "name": "Nifty Desk",
            "created_by": "sahil",
            "initial_capital": 500_000.0,
            "capacity": capacity,
        },
    )
    return response.json()["data"]["room_id"]


def _drain_until(socket, event_type: str, limit: int = 12) -> dict:
    """Read frames until one matches ``event_type``."""
    for _ in range(limit):
        frame = json.loads(socket.receive_text())
        if frame["type"] == event_type:
            return frame
    raise AssertionError(f"No '{event_type}' frame within {limit} frames")


class TestWebSocketBasics:
    def test_history_and_presence_on_connect(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        seeded_client.post(
            f"{PREFIX}/rooms/{room_id}/messages",
            json={"author": "sahil", "text": "earlier message"},
        )
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=sahil",
        ) as socket:
            history = _drain_until(socket, "history")
            assert [m["text"] for m in history["data"]["messages"]] == ["earlier message"]
            presence = _drain_until(socket, "presence")
            assert presence["data"]["online_members"] == ["sahil"]

    def test_unknown_room_closes_socket(self, seeded_client) -> None:
        from starlette.websockets import WebSocketDisconnect

        with pytest.raises(WebSocketDisconnect):
            with seeded_client.websocket_connect(
                f"{PREFIX}/ws/rooms/missing?user=sahil",
            ) as socket:
                socket.receive_text()

    def test_ping_pong(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=sahil",
        ) as socket:
            _drain_until(socket, "history")
            socket.send_text(json.dumps({"type": "ping"}))
            assert _drain_until(socket, "pong")["type"] == "pong"

    def test_invalid_frame_returns_error_not_disconnect(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=sahil",
        ) as socket:
            _drain_until(socket, "history")
            socket.send_text(json.dumps({"type": "not_a_real_type"}))
            assert _drain_until(socket, "error")["data"]["message"] == "Invalid frame"
            # Socket is still usable afterwards.
            socket.send_text(json.dumps({"type": "ping"}))
            assert _drain_until(socket, "pong")["type"] == "pong"


class TestTwoPersonFanOut:
    def test_chat_reaches_the_other_member(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=sahil",
        ) as first:
            _drain_until(first, "history")
            with seeded_client.websocket_connect(
                f"{PREFIX}/ws/rooms/{room_id}?user=arjun",
            ) as second:
                _drain_until(second, "history")
                first.send_text(json.dumps({"type": "chat", "text": "watching RELIANCE"}))
                received = _drain_until(second, "message")
                assert received["data"]["text"] == "watching RELIANCE"
                assert received["data"]["author"] == "sahil"

    def test_order_broadcasts_event_and_portfolio(self, seeded_client) -> None:
        """One member's fill updates the other's view of the shared book."""
        room_id = _create_room(seeded_client)
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=sahil",
        ) as first:
            _drain_until(first, "history")
            with seeded_client.websocket_connect(
                f"{PREFIX}/ws/rooms/{room_id}?user=arjun",
            ) as second:
                _drain_until(second, "history")
                first.send_text(
                    json.dumps(
                        {
                            "type": "order",
                            "order": {
                                "author": "sahil",
                                "side": "BUY",
                                "symbol": "RELIANCE",
                                "quantity": 10,
                            },
                        },
                    ),
                )
                event = _drain_until(second, "message")
                assert event["data"]["kind"] == "ORDER_EVENT"
                assert "bought" in event["data"]["text"]

                portfolio = _drain_until(second, "portfolio")
                positions = portfolio["data"]["positions"]
                assert positions[0]["symbol"] == "RELIANCE"
                assert positions[0]["quantity"] == 10

    def test_order_author_is_forced_to_socket_user(self, seeded_client) -> None:
        """A client cannot place an order in someone else's name."""
        room_id = _create_room(seeded_client)
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=arjun",
        ) as socket:
            _drain_until(socket, "history")
            socket.send_text(
                json.dumps(
                    {
                        "type": "order",
                        "order": {
                            "author": "someone_else",
                            "side": "BUY",
                            "symbol": "RELIANCE",
                            "quantity": 1,
                        },
                    },
                ),
            )
            event = _drain_until(socket, "message")
            assert event["data"]["author"] == "arjun"

    def test_trade_idea_frame_broadcasts(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=sahil",
        ) as socket:
            _drain_until(socket, "history")
            socket.send_text(
                json.dumps(
                    {
                        "type": "trade_idea",
                        "idea": {
                            "symbol": "RELIANCE",
                            "direction": "LONG",
                            "thesis": "range breakout",
                        },
                    },
                ),
            )
            frame = _drain_until(socket, "message")
            assert frame["data"]["kind"] == "TRADE_IDEA"
            assert frame["data"]["trade_idea"]["price_at_post"] == 129.0


class TestAITrigger:
    def test_mention_triggers_grounded_reply(
        self,
        seeded_client,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """@ai in chat produces an AI_REPLY message citing the tool it used."""
        seeded_client.app.state.settings = seeded_client.app.state.settings.model_copy(
            update={"gemini_api_key": "k", "ai_enabled": True},
        )

        calls: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                return httpx.Response(
                    200,
                    json={
                        "candidates": [
                            {
                                "content": {
                                    "role": "model",
                                    "parts": [
                                        {
                                            "functionCall": {
                                                "name": "get_latest_price",
                                                "args": {"symbol": "RELIANCE"},
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                )
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {"content": {"role": "model", "parts": [{"text": "It last closed at 129.00."}]}},
                    ],
                },
            )

        original = httpx.AsyncClient.__init__

        def _init(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)

        room_id = _create_room(seeded_client)
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=sahil",
        ) as socket:
            _drain_until(socket, "history")
            socket.send_text(
                json.dumps({"type": "chat", "text": "@ai what did RELIANCE close at?"}),
            )
            _drain_until(socket, "message")  # the human message
            _drain_until(socket, "ai_thinking")
            reply = _drain_until(socket, "message")
            assert reply["data"]["kind"] == "AI_REPLY"
            assert reply["data"]["ai_source"] == "gemini"
            assert reply["data"]["ai_tools_used"] == ["get_latest_price"]
            assert "129" in reply["data"]["text"]

    def test_plain_chat_does_not_call_ai(self, seeded_client) -> None:
        room_id = _create_room(seeded_client)
        with seeded_client.websocket_connect(
            f"{PREFIX}/ws/rooms/{room_id}?user=sahil",
        ) as socket:
            _drain_until(socket, "history")
            socket.send_text(json.dumps({"type": "chat", "text": "just talking"}))
            _drain_until(socket, "message")
            socket.send_text(json.dumps({"type": "ping"}))
            # A pong arrives with no AI frames in between.
            assert _drain_until(socket, "pong", limit=3)["type"] == "pong"


class TestAIStatusEndpoint:
    def test_status_reports_unconfigured(self, seeded_client) -> None:
        response = seeded_client.get(f"{PREFIX}/ai/status")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["read_only"] is True
        assert data["trigger"] == "@ai"
