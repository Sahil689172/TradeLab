"""Tests for system endpoints and application bootstrap."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.core.database import Base, check_database_connection, get_engine, init_db, reset_db_state
from app.main import create_app


def test_root_endpoint(client) -> None:
    """Root endpoint returns project metadata and documentation links."""
    response = client.get("/")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["name"] == "TradeLab"
    assert payload["data"]["version"] == "0.1.0"
    assert "description" in payload["data"]
    docs = payload["data"]["documentation"]
    assert docs["swagger_ui"] == "/docs"
    assert docs["redoc"] == "/redoc"
    assert docs["openapi_json"] == "/openapi.json"


def test_health_endpoint(client) -> None:
    """Health endpoint reports status, app info, and database connectivity."""
    response = client.get("/health")
    assert response.status_code == 200

    payload = response.json()
    assert payload["success"] is True
    data = payload["data"]
    assert data["status"] == "healthy"
    assert data["application"] == "TradeLab"
    assert data["version"] == "0.1.0"
    assert data["environment"] == "test"
    assert data["database"] == "connected"
    assert "timestamp" in data


def test_api_v1_root(client) -> None:
    """Versioned API root confirms the v1 surface is mounted."""
    response = client.get("/api/v1/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["api_version"] == "v1"
    assert payload["data"]["status"] == "ok"


def test_openapi_and_docs_available(client) -> None:
    """OpenAPI schema and Swagger UI are served."""
    openapi = client.get("/openapi.json")
    assert openapi.status_code == 200
    schema = openapi.json()
    assert schema["info"]["title"] == "TradeLab"
    assert "/health" in schema["paths"]
    assert "/" in schema["paths"]

    docs = client.get("/docs")
    assert docs.status_code == 200

    redoc = client.get("/redoc")
    assert redoc.status_code == 200


def test_application_startup(test_settings) -> None:
    """Application factory starts and initializes without error."""
    application = create_app(settings=test_settings)
    assert application.title == "TradeLab"
    assert application.version == "0.1.0"

    with TestClient(application) as test_client:
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json()["data"]["database"] == "connected"


def test_database_initialization(test_settings) -> None:
    """Database engine initializes and responds to connectivity checks."""
    reset_db_state()
    engine = init_db(test_settings)

    assert check_database_connection(engine) is True
    assert get_engine() is engine

    # Metadata tables for market data storage are created on init.
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert table_names == {"company_metadata", "ingestion_state"}
    assert Base.metadata is not None

    reset_db_state()
