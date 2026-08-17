"""Dashboard API integration tests."""

from __future__ import annotations

import pandas as pd

from app.api.deps import get_market_data_gateway
from app.services.dashboard.paper_trading_service import reset_paper_book


def _override(client, api_gateway) -> None:
    client.app.dependency_overrides[get_market_data_gateway] = api_gateway


def _clear(client) -> None:
    client.app.dependency_overrides.clear()
    reset_paper_book()


def test_list_stocks_universe(client, api_gateway) -> None:
    _override(client, api_gateway)
    response = client.get("/api/v1/stocks?q=RELIANCE&limit=10")
    _clear(client)
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["data"]["total"] >= 1
    assert any(s["symbol"] == "RELIANCE" for s in payload["data"]["stocks"])


def test_get_stock_lookup(client, api_gateway) -> None:
    _override(client, api_gateway)
    response = client.get("/api/v1/stocks/RELIANCE")
    _clear(client)
    assert response.status_code == 200
    assert response.json()["data"]["symbol"] == "RELIANCE"


def test_ohlcv_after_bootstrap(client, api_gateway) -> None:
    _override(client, api_gateway)
    client.post("/api/v1/market/bootstrap/RELIANCE")
    response = client.get("/api/v1/stocks/RELIANCE/ohlcv?interval=1D&limit=50")
    _clear(client)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["interval"] == "1D"
    assert len(data["bars"]) > 0


def test_intraday_interval_unsupported(client, api_gateway) -> None:
    _override(client, api_gateway)
    client.post("/api/v1/market/bootstrap/RELIANCE")
    response = client.get("/api/v1/stocks/RELIANCE/ohlcv?interval=5m")
    _clear(client)
    data = response.json()["data"]
    assert data["bars"] == []
    assert "Intraday" in data["message"]


def test_list_strategies_twelve(client, api_gateway) -> None:
    _override(client, api_gateway)
    response = client.get("/api/v1/strategies")
    _clear(client)
    names = {item["name"] for item in response.json()["data"]}
    assert len(names) >= 12
    assert "ema_trend" in names
    assert "supertrend" in names


def test_strategy_analysis_returns_confidence_label(client, api_gateway, test_settings, tmp_path) -> None:
    _override(client, api_gateway)
    client.post("/api/v1/market/bootstrap/RELIANCE")
    ohlcv_dir = test_settings.parquet_storage_dir
    ohlcv_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=120, freq="B"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "adj_close": 100.5,
            "volume": 1_000_000.0,
        },
    )
    frame.to_parquet(ohlcv_dir / "RELIANCE.parquet", index=False)
    response = client.get("/api/v1/strategies/RELIANCE/analysis?timeframe=1D")
    _clear(client)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["symbol"] == "RELIANCE"
    assert "Historical/Model Confidence" in data["data_note"] or any(
        row.get("confidence_label") == "Historical/Model Confidence" for row in data["strategies"]
    )


def test_paper_buy_rejected_without_price(client, api_gateway) -> None:
    _override(client, api_gateway)
    reset_paper_book()
    response = client.post(
        "/api/v1/orders/buy",
        json={"symbol": "RELIANCE", "quantity": 10, "order_type": "MARKET"},
    )
    _clear(client)
    assert response.status_code == 400


def test_paper_buy_and_sell_flow(client, api_gateway) -> None:
    _override(client, api_gateway)
    reset_paper_book()
    client.post("/api/v1/market/bootstrap/RELIANCE")
    buy = client.post(
        "/api/v1/orders/buy",
        json={
            "symbol": "RELIANCE",
            "quantity": 5,
            "order_type": "MARKET",
            "price": 2500.0,
            "stop_loss": 2400.0,
            "target": 2600.0,
        },
    )
    assert buy.status_code == 200
    assert buy.json()["data"]["accepted"] is True
    sell = client.post(
        "/api/v1/orders/sell",
        json={"symbol": "RELIANCE", "quantity": 5, "order_type": "MARKET", "price": 2550.0},
    )
    assert sell.status_code == 200
    portfolio = client.get("/api/v1/portfolio")
    _clear(client)
    assert portfolio.json()["data"]["kpis"]["available_cash"] > 0


def test_buy_rejected_insufficient_cash(client, api_gateway) -> None:
    _override(client, api_gateway)
    reset_paper_book()
    response = client.post(
        "/api/v1/orders/buy",
        json={"symbol": "RELIANCE", "quantity": 10000, "order_type": "MARKET", "price": 5000.0},
    )
    _clear(client)
    assert response.json()["data"]["accepted"] is False


def test_refresh_endpoint(client, api_gateway) -> None:
    _override(client, api_gateway)
    response = client.post("/api/v1/market-data/refresh?symbol=RELIANCE")
    _clear(client)
    assert response.status_code == 200
    assert "last_refresh" in response.json()["data"]


def test_system_status(client, api_gateway) -> None:
    _override(client, api_gateway)
    response = client.get("/api/v1/system/status")
    _clear(client)
    data = response.json()["data"]
    assert data["paper_trading"] is True
    assert data["universe_size"] == 501
