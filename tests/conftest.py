"""Shared pytest fixtures for TradeLab tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_market_data_gateway
from app.core.config import Settings, clear_settings_cache
from app.core.database import reset_db_state
from tests.market_data.conftest import FakeProvider
from app.main import create_app
from app.market_data.services.market_data_gateway import MarketDataGateway


@pytest.fixture(autouse=True)
def _reset_favorites_singleton() -> None:
    from app.services.dashboard.favorites_service import reset_favorites_service

    reset_favorites_service()
    yield
    reset_favorites_service()


@pytest.fixture()
def test_settings(tmp_path: Path) -> Settings:
    """Provide isolated settings using a temporary SQLite database."""
    clear_settings_cache()
    reset_db_state()

    data_root = tmp_path / "backend" / "data"
    metadata_db = data_root / "metadata.db"
    # Keep a developer's real credentials out of the test run: _env_file=None
    # ignores .env, and the explicit key overrides beat an exported
    # GEMINI_API_KEY/GROQ_API_KEY in the ambient environment. Provider tests
    # opt in via the ai_settings fixture instead.
    settings = Settings(
        _env_file=None,
        gemini_api_key=None,
        groq_api_key=None,
        app_name="TradeLab",
        app_version="0.1.0",
        app_description="TradeLab Quant Engine — Indian Stock Market Analysis Platform",
        app_env="test",
        debug=True,
        api_v1_prefix="/api/v1",
        metadata_database_url=f"sqlite:///{metadata_db.as_posix()}",
        database_url=f"sqlite:///{metadata_db.as_posix()}",
        parquet_storage_dir=data_root / "ohlcv",
        log_directory=data_root / "logs",
        log_level="WARNING",
        log_format="console",
    )
    yield settings
    reset_db_state()
    clear_settings_cache()


@pytest.fixture()
def app(test_settings: Settings):
    """Create a FastAPI app bound to test settings."""
    return create_app(settings=test_settings)


@pytest.fixture()
def client(app) -> TestClient:
    """Return a TestClient with lifespan events enabled."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def api_gateway(test_settings: Settings):
    """Override the API gateway dependency with a fake provider-backed gateway."""

    def _factory():
        from app.core.database import get_session_factory

        session = get_session_factory()()
        return MarketDataGateway(session, settings=test_settings, provider=FakeProvider())

    return _factory
