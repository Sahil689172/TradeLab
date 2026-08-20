"""Grounded AI tools, provider selection, and Gemini→Groq fallback."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.collab.ai.agent import RoomAIAgent, is_ai_invocation, strip_trigger
from app.collab.ai.providers import GeminiProvider, GroqProvider
from app.collab.ai.tools import TOOLS_BY_NAME, ToolContext, execute_tool
from app.collab.exceptions import AIProviderError
from app.collab.room_service import RoomService
from app.collab.schemas import AISource, RoomCreateRequest, RoomOrderRequest
from app.core.config import Settings
from app.core.database import get_session_factory, init_db
from app.core.storage_paths import ensure_storage_directories
from app.market_data.services.market_data_gateway import MarketDataGateway
from tests.collab.conftest import make_history
from tests.market_data.conftest import FakeProvider


@pytest.fixture()
def tool_ctx(ai_settings: Settings):
    """A room with seeded RELIANCE history and a bound tool context."""
    ensure_storage_directories(ai_settings)
    init_db(ai_settings)
    session = get_session_factory()()
    gateway = MarketDataGateway(session, settings=ai_settings, provider=FakeProvider())
    gateway.save_history("RELIANCE.NS", make_history())

    service = RoomService(session)
    room = service.create_room(
        RoomCreateRequest(name="Desk", created_by="sahil", initial_capital=500_000.0),
    )
    ctx = ToolContext(
        room_id=room.room_id,
        gateway=gateway,
        room_service=service,
        settings=ai_settings,
    )
    try:
        yield ctx, service, gateway
    finally:
        session.close()


class TestToolSurface:
    def test_no_tool_can_place_an_order(self) -> None:
        """The AI's tool surface is read-only by construction, not by prompt."""
        forbidden = {"place", "order", "buy", "sell", "trade", "execute"}
        for name in TOOLS_BY_NAME:
            verb = name.split("_")[0]
            assert verb not in forbidden, f"Tool '{name}' looks like a write tool"

    def test_latest_price_reads_stored_history(self, tool_ctx) -> None:
        ctx, _service, _gateway = tool_ctx
        result = execute_tool("get_latest_price", {"symbol": "RELIANCE"}, ctx)
        assert result["available"] is True
        assert result["close"] == 129.0
        assert result["previous_close"] == 128.0

    def test_latest_price_reports_missing_symbol(self, tool_ctx) -> None:
        ctx, _service, _gateway = tool_ctx
        result = execute_tool("get_latest_price", {"symbol": "NOSUCH"}, ctx)
        assert result["available"] is False
        assert "error" in result

    def test_price_history_summarises_window(self, tool_ctx) -> None:
        ctx, _service, _gateway = tool_ctx
        result = execute_tool("get_price_history", {"symbol": "RELIANCE", "bars": 10}, ctx)
        assert result["bars_returned"] == 10
        assert result["start_close"] == 120.0
        assert result["end_close"] == 129.0
        assert len(result["recent_closes"]) == 10

    def test_portfolio_tool_sees_room_positions(self, tool_ctx) -> None:
        import asyncio

        ctx, service, gateway = tool_ctx
        asyncio.run(
            service.place_order(
                ctx.room_id,
                RoomOrderRequest(author="sahil", side="BUY", symbol="RELIANCE", quantity=10),
                gateway=gateway,
            ),
        )
        result = execute_tool("get_room_portfolio", {}, ctx)
        assert result["open_position_count"] == 1
        assert result["positions"][0]["symbol"] == "RELIANCE"
        assert result["positions"][0]["quantity"] == 10

    def test_position_tool_reports_not_held(self, tool_ctx) -> None:
        ctx, _service, _gateway = tool_ctx
        result = execute_tool("get_position", {"symbol": "RELIANCE"}, ctx)
        assert result["held"] is False

    def test_unknown_tool_returns_error_not_exception(self, tool_ctx) -> None:
        ctx, _service, _gateway = tool_ctx
        result = execute_tool("delete_everything", {}, ctx)
        assert "Unknown tool" in result["error"]

    def test_trade_ideas_tool_returns_posted_ideas(self, tool_ctx) -> None:
        from app.collab.schemas import TradeDirection, TradeIdea

        ctx, service, gateway = tool_ctx
        service.post_trade_idea(
            ctx.room_id,
            "sahil",
            TradeIdea(symbol="RELIANCE", direction=TradeDirection.LONG, thesis="breakout"),
            gateway=gateway,
        )
        result = execute_tool("get_recent_trade_ideas", {}, ctx)
        assert result["count"] == 1
        assert result["trade_ideas"][0]["price_at_post"] == 129.0


class TestTriggerParsing:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("@ai what is RELIANCE doing", True),
            ("hey @AI check this", True),
            ("no mention here", False),
            ("email me at ai@x.com", False),
        ],
    )
    def test_trigger_detection(self, text: str, expected: bool) -> None:
        assert is_ai_invocation(text, "@ai") is expected

    def test_strip_trigger_removes_token(self) -> None:
        assert strip_trigger("@ai should we book profit?", "@ai") == "should we book profit?"

    def test_strip_trigger_keeps_text_when_only_trigger(self) -> None:
        assert strip_trigger("@ai", "@ai") == "@ai"


# ---------------------------------------------------------------------------
# Provider transport (mocked HTTP)
# ---------------------------------------------------------------------------


def _mock_transport(handler) -> Any:
    return httpx.MockTransport(handler)


@pytest.fixture()
def patch_httpx(monkeypatch: pytest.MonkeyPatch):
    """Route every AsyncClient created by providers through a mock transport."""

    def _apply(handler) -> None:
        original = httpx.AsyncClient.__init__

        def _init(self, *args, **kwargs):
            kwargs["transport"] = _mock_transport(handler)
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)

    return _apply


def _gemini_text_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"role": "model", "parts": [{"text": text}]}}]},
    )


def _gemini_tool_response(name: str, args: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "candidates": [
                {"content": {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}},
            ],
        },
    )


def _groq_text_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": text}}]},
    )


class TestGeminiProvider:
    @pytest.mark.anyio
    async def test_plain_text_reply(self, tool_ctx, patch_httpx) -> None:
        ctx, _service, _gateway = tool_ctx
        patch_httpx(lambda request: _gemini_text_response("Reliance closed at 129."))
        provider = GeminiProvider(api_key="k", model="gemini-2.0-flash")
        reply = await provider.run(
            question="price?",
            recent_context=None,
            ctx=ctx,
            max_iterations=3,
            timeout=5.0,
            max_output_tokens=200,
        )
        assert reply.source is AISource.GEMINI
        assert "129" in reply.text
        assert reply.tools_used == []

    @pytest.mark.anyio
    async def test_tool_call_then_answer(self, tool_ctx, patch_httpx) -> None:
        """The model asks for a price, gets real stored data, then answers."""
        ctx, _service, _gateway = tool_ctx
        seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen.append(body)
            if len(seen) == 1:
                return _gemini_tool_response("get_latest_price", {"symbol": "RELIANCE"})
            return _gemini_text_response("It closed at 129.00, up 0.78%.")

        patch_httpx(handler)
        provider = GeminiProvider(api_key="k", model="gemini-2.0-flash")
        reply = await provider.run(
            question="what did RELIANCE do?",
            recent_context=None,
            ctx=ctx,
            max_iterations=3,
            timeout=5.0,
            max_output_tokens=200,
        )
        assert reply.tools_used == ["get_latest_price"]
        # The second request must carry the real tool result back to the model.
        function_response = seen[1]["contents"][-1]["parts"][0]["functionResponse"]
        assert function_response["response"]["close"] == 129.0

    @pytest.mark.anyio
    async def test_http_error_raises_provider_error(self, tool_ctx, patch_httpx) -> None:
        ctx, _service, _gateway = tool_ctx
        patch_httpx(lambda request: httpx.Response(429, text="rate limited"))
        provider = GeminiProvider(api_key="k", model="gemini-2.0-flash")
        with pytest.raises(AIProviderError):
            await provider.run(
                question="hi",
                recent_context=None,
                ctx=ctx,
                max_iterations=2,
                timeout=5.0,
                max_output_tokens=100,
            )


class TestGroqProvider:
    @pytest.mark.anyio
    async def test_plain_text_reply(self, tool_ctx, patch_httpx) -> None:
        ctx, _service, _gateway = tool_ctx
        patch_httpx(lambda request: _groq_text_response("Answer from Groq."))
        provider = GroqProvider(api_key="k", model="llama-3.3-70b-versatile")
        reply = await provider.run(
            question="price?",
            recent_context=None,
            ctx=ctx,
            max_iterations=3,
            timeout=5.0,
            max_output_tokens=200,
        )
        assert reply.source is AISource.GROQ

    @pytest.mark.anyio
    async def test_tool_call_round_trip(self, tool_ctx, patch_httpx) -> None:
        ctx, _service, _gateway = tool_ctx
        seen: list[dict[str, Any]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            seen.append(body)
            if len(seen) == 1:
                return httpx.Response(
                    200,
                    json={
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": None,
                                    "tool_calls": [
                                        {
                                            "id": "call_1",
                                            "type": "function",
                                            "function": {
                                                "name": "get_room_portfolio",
                                                "arguments": "{}",
                                            },
                                        },
                                    ],
                                },
                            },
                        ],
                    },
                )
            return _groq_text_response("You hold nothing yet.")

        patch_httpx(handler)
        provider = GroqProvider(api_key="k", model="llama-3.3-70b-versatile")
        reply = await provider.run(
            question="what do we hold?",
            recent_context=None,
            ctx=ctx,
            max_iterations=3,
            timeout=5.0,
            max_output_tokens=200,
        )
        assert reply.tools_used == ["get_room_portfolio"]
        tool_message = seen[1]["messages"][-1]
        assert tool_message["role"] == "tool"
        assert json.loads(tool_message["content"])["shared_portfolio"] is True


class TestProviderChainAndFallback:
    def test_chain_prefers_gemini_by_default(self, ai_settings: Settings) -> None:
        agent = RoomAIAgent(ai_settings)
        chain = agent.provider_chain()
        assert [p.source for p in chain] == [AISource.GEMINI, AISource.GROQ]

    def test_chain_respects_primary_override(self, ai_settings: Settings) -> None:
        agent = RoomAIAgent(ai_settings.model_copy(update={"ai_primary_provider": "groq"}))
        assert agent.provider_chain()[0].source is AISource.GROQ

    def test_unconfigured_providers_are_dropped(self, test_settings: Settings) -> None:
        agent = RoomAIAgent(test_settings.model_copy(update={"groq_api_key": "only-groq"}))
        chain = agent.provider_chain()
        assert [p.source for p in chain] == [AISource.GROQ]

    def test_status_never_leaks_keys(self, ai_settings: Settings) -> None:
        status = RoomAIAgent(ai_settings).status()
        dumped = status.model_dump_json()
        assert "test-gemini-key" not in dumped
        assert status.gemini_configured is True
        assert status.read_only is True

    @pytest.mark.anyio
    async def test_falls_back_to_groq_when_gemini_fails(
        self,
        tool_ctx,
        ai_settings: Settings,
        patch_httpx,
    ) -> None:
        ctx, _service, _gateway = tool_ctx

        def handler(request: httpx.Request) -> httpx.Response:
            if "generativelanguage" in str(request.url):
                return httpx.Response(500, text="gemini down")
            return _groq_text_response("Groq handled it.")

        patch_httpx(handler)
        agent = RoomAIAgent(ai_settings)
        session = get_session_factory()()
        try:
            reply = await agent.ask(
                room_id=ctx.room_id,
                question="price?",
                gateway=ctx.gateway,
                session=session,
            )
        finally:
            session.close()

        assert reply.source is AISource.GROQ
        assert reply.fell_back is True

    @pytest.mark.anyio
    async def test_both_providers_down_degrades_gracefully(
        self,
        tool_ctx,
        ai_settings: Settings,
        patch_httpx,
    ) -> None:
        """A dead key must never take the room down or invent numbers."""
        ctx, _service, _gateway = tool_ctx
        patch_httpx(lambda request: httpx.Response(503, text="unavailable"))
        agent = RoomAIAgent(ai_settings)
        session = get_session_factory()()
        try:
            reply = await agent.ask(
                room_id=ctx.room_id,
                question="price?",
                gateway=ctx.gateway,
                session=session,
            )
        finally:
            session.close()

        assert reply.source is AISource.NONE
        assert reply.error is not None
        assert "guess" in reply.text.lower()


@pytest.fixture()
def anyio_backend() -> str:
    return "asyncio"
