"""Fixtures for collaborative room tests."""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pandas as pd
import pytest

from app.market_data.utils.ohlcv_normalizer import normalize_ohlcv_frame

from app.api.deps import get_market_data_gateway
from app.collab.connection_manager import reset_connection_manager
from app.collab.room_service import reset_room_books
from app.core.config import Settings


@pytest.fixture(autouse=True)
def _reset_collab_state() -> None:
    """Clear room books, sockets, and the cached AI agent between tests."""
    from app.collab.ai.agent import reset_room_ai_agent

    reset_room_books()
    reset_connection_manager()
    reset_room_ai_agent()
    yield
    reset_room_books()
    reset_connection_manager()
    reset_room_ai_agent()


@pytest.fixture()
def ai_settings(test_settings: Settings) -> Settings:
    """Settings with a Gemini key present so the provider chain is non-empty."""
    return test_settings.model_copy(
        update={
            "gemini_api_key": "test-gemini-key",
            "groq_api_key": "test-groq-key",
            "ai_enabled": True,
        },
    )


def make_history(rows: int = 30, start_close: float = 100.0) -> pd.DataFrame:
    """Build a deterministic OHLCV frame in canonical storage schema."""
    base = date(2024, 1, 1)
    records = []
    for index in range(rows):
        close = start_close + index
        records.append(
            {
                "date": base + timedelta(days=index),
                "open": close - 1.0,
                "high": close + 2.0,
                "low": close - 2.0,
                "close": close,
                "adj_close": close,
                "volume": 1000 + index,
            },
        )
    return normalize_ohlcv_frame(pd.DataFrame(records))


@pytest.fixture()
def seeded_client(client, api_gateway, test_settings: Settings):
    """TestClient with the market gateway overridden and RELIANCE history saved."""
    client.app.dependency_overrides[get_market_data_gateway] = api_gateway
    gateway = api_gateway()
    gateway.save_history("RELIANCE.NS", make_history())
    yield client
    client.app.dependency_overrides.clear()


@pytest.fixture()
def patch_httpx(monkeypatch: pytest.MonkeyPatch):
    """Route every AsyncClient created by providers through a mock transport."""

    def _apply(handler) -> None:
        original = httpx.AsyncClient.__init__

        def _init(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            original(self, *args, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)

    return _apply
