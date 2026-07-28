"""Tests for market data ingestion API endpoints."""

from __future__ import annotations

from app.api.deps import get_market_data_gateway


def test_bootstrap_symbol_endpoint(client, api_gateway) -> None:
    """POST bootstrap endpoint returns a bootstrapped result."""
    client.app.dependency_overrides[get_market_data_gateway] = api_gateway
    response = client.post("/api/v1/market/bootstrap/RELIANCE")
    client.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["symbol"] == "RELIANCE"
    assert payload["data"]["status"] in {"bootstrapped", "skipped"}


def test_bootstrap_all_endpoint(client, api_gateway) -> None:
    """POST batch bootstrap endpoint returns one result per symbol."""
    client.app.dependency_overrides[get_market_data_gateway] = api_gateway
    response = client.post(
        "/api/v1/market/bootstrap/all",
        json={"symbols": ["RELIANCE", "TCS"]},
    )
    client.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert len(payload["data"]) == 2


def test_update_endpoint(client, api_gateway) -> None:
    """POST update endpoint works after bootstrap."""
    client.app.dependency_overrides[get_market_data_gateway] = api_gateway
    client.post("/api/v1/market/bootstrap/INFY")
    response = client.post("/api/v1/market/update/INFY")
    client.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["symbol"] == "INFY"


def test_metadata_endpoint(client, api_gateway) -> None:
    """POST metadata endpoint refreshes SQLite metadata."""
    client.app.dependency_overrides[get_market_data_gateway] = api_gateway
    response = client.post("/api/v1/market/metadata/HDFCBANK")
    client.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["data"]["status"] == "metadata_refreshed"


def test_status_endpoint(client, api_gateway) -> None:
    """GET status endpoint returns current storage state."""
    client.app.dependency_overrides[get_market_data_gateway] = api_gateway
    client.post("/api/v1/market/bootstrap/SBIN")
    response = client.get("/api/v1/market/status/SBIN")
    client.app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["symbol"] == "SBIN"
    assert payload["data"]["history_exists"] is True
