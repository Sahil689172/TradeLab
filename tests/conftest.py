"""Shared pytest fixtures for TradeLab Phase A1 tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, clear_settings_cache
from app.db.session import reset_db_state
from app.main import create_app


@pytest.fixture()
def test_settings(tmp_path) -> Settings:
    """Provide isolated settings using a temporary SQLite database."""
    clear_settings_cache()
    reset_db_state()
    db_file = tmp_path / "test_tradlab.db"
    settings = Settings(
        app_name="TradeLab",
        app_version="0.1.0",
        app_description="TradeLab Quant Engine — Indian Stock Market Analysis Platform",
        app_env="test",
        debug=True,
        api_v1_prefix="/api/v1",
        database_url=f"sqlite:///{db_file.as_posix()}",
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
