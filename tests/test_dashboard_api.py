"""Dashboard API integration tests."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from app.api.deps import get_market_data_gateway
from app.backtesting.monte_carlo.schemas import MonteCarloTrade
from app.services.dashboard.paper_trading_service import reset_paper_book

# HTTP Monte Carlo tests mock replay trades; simulation count is validated separately.
_MC_TEST_SIMULATIONS = 50


def _override(client, api_gateway) -> None:
    client.app.dependency_overrides[get_market_data_gateway] = api_gateway


def _clear(client) -> None:
    client.app.dependency_overrides.clear()
    reset_paper_book()


def _sample_replay_trades(count: int = 12) -> list[MonteCarloTrade]:
    return [
        MonteCarloTrade(
            pnl=100.0 if index % 2 == 0 else -40.0,
            return_pct=0.02 if index % 2 == 0 else -0.008,
        )
        for index in range(count)
    ]


@pytest.fixture
def fast_mc_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid full A5 replay during dashboard API tests (minutes per call otherwise)."""
    trades = _sample_replay_trades()

    def _fake_replay(*_args: Any, **_kwargs: Any) -> tuple[list[MonteCarloTrade], dict[str, Any]]:
        return trades, {"period": "2020-01-01 → 2020-06-01", "replay_errors": []}

    monkeypatch.setattr(
        "app.services.dashboard.monte_carlo_service.load_trades_from_replay",
        _fake_replay,
    )


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


def _write_daily_parquet(test_settings, rows: int = 40) -> None:
    ohlcv_dir = test_settings.parquet_storage_dir
    ohlcv_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "date": pd.date_range("2020-01-01", periods=rows, freq="B"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "adj_close": 100.5,
            "volume": 1_000_000.0,
        },
    )
    frame.to_parquet(ohlcv_dir / "RELIANCE.parquet", index=False)


def test_list_stocks_returns_complete_universe(client, api_gateway) -> None:
    _override(client, api_gateway)
    response = client.get("/api/v1/stocks?limit=501")
    _clear(client)
    payload = response.json()["data"]
    assert payload["total"] == 501
    assert len(payload["stocks"]) == 501
    assert len({row["symbol"] for row in payload["stocks"]}) == 501


def test_ohlcv_default_latest_20_days(client, api_gateway, test_settings) -> None:
    _override(client, api_gateway)
    client.post("/api/v1/market/bootstrap/RELIANCE")
    _write_daily_parquet(test_settings, rows=40)
    response = client.get("/api/v1/stocks/RELIANCE/ohlcv?interval=1D")
    _clear(client)
    data = response.json()["data"]
    assert len(data["bars"]) == 20
    assert data["has_more"] is True
    dates = [bar["date"][:10] for bar in data["bars"]]
    assert dates == sorted(dates)
    assert len(set(dates)) == 20


def test_ohlcv_fetch_older_no_duplicate_candles(client, api_gateway, test_settings) -> None:
    _override(client, api_gateway)
    client.post("/api/v1/market/bootstrap/RELIANCE")
    _write_daily_parquet(test_settings, rows=40)
    first = client.get("/api/v1/stocks/RELIANCE/ohlcv?interval=1D&limit=20")
    oldest = first.json()["data"]["oldest_bar_timestamp"]
    older = client.get(
        "/api/v1/stocks/RELIANCE/ohlcv",
        params={"interval": "1D", "limit": 20, "before": oldest},
    )
    _clear(client)
    first_dates = [bar["date"][:10] for bar in first.json()["data"]["bars"]]
    older_dates = [bar["date"][:10] for bar in older.json()["data"]["bars"]]
    assert older.json()["data"]["bars"]
    assert set(first_dates).isdisjoint(set(older_dates))
    combined = older_dates + first_dates
    assert len(combined) == len(set(combined))
    assert combined == sorted(combined)


def test_strategy_analysis_includes_all_registry_strategies(
    client, api_gateway, test_settings,
) -> None:
    _override(client, api_gateway)
    client.post("/api/v1/market/bootstrap/RELIANCE")
    _write_daily_parquet(test_settings, rows=120)
    response = client.get("/api/v1/strategies/RELIANCE/analysis?timeframe=1D")
    _clear(client)
    rows = response.json()["data"]["strategies"]
    names = {row["strategy"] for row in rows}
    assert len(names) >= 12
    assert "recommended_action" in rows[0]
    assert rows[0]["confidence_label"] == "Historical/Model Confidence"


def test_buy_rejected_invalid_stop_loss(client, api_gateway) -> None:
    _override(client, api_gateway)
    reset_paper_book()
    response = client.post(
        "/api/v1/orders/buy",
        json={
            "symbol": "RELIANCE",
            "quantity": 1,
            "order_type": "MARKET",
            "price": 2500.0,
            "stop_loss": 2600.0,
            "target": 2700.0,
        },
    )
    _clear(client)
    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["accepted"] is False
    assert "Stop loss" in payload["message"]


def test_filled_order_persists_stop_and_target(client, api_gateway) -> None:
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
    orders = client.get("/api/v1/orders")
    portfolio = client.get("/api/v1/portfolio")
    _clear(client)
    assert buy.json()["data"]["accepted"] is True
    row = orders.json()["data"][0]
    assert row["stop_loss"] == 2400.0
    assert row["target"] == 2600.0
    assert row["status"] == "FILLED"
    holding = portfolio.json()["data"]["positions"][0]
    assert holding["symbol"] == "RELIANCE"
    assert holding["stop_loss"] == 2400.0
    assert holding["target"] == 2600.0


def test_monte_carlo_invalid_strategy(client, api_gateway) -> None:
    _override(client, api_gateway)
    response = client.post(
        "/api/v1/stocks/RELIANCE/monte-carlo",
        json={"strategy": "not_a_real_strategy", "simulations": 1000},
    )
    _clear(client)
    assert response.status_code == 400


def test_monte_carlo_no_history(client, api_gateway) -> None:
    _override(client, api_gateway)
    response = client.post(
        "/api/v1/stocks/NOTREAL/monte-carlo",
        json={"strategy": "ema_trend", "simulations": 1000},
    )
    _clear(client)
    assert response.status_code in {400, 404}


def test_monte_carlo_replay_path(
    client,
    api_gateway,
    test_settings,
    fast_mc_replay,
) -> None:
    _override(client, api_gateway)
    client.post("/api/v1/market/bootstrap/RELIANCE")
    _write_daily_parquet(test_settings, rows=120)
    response = client.post(
        "/api/v1/stocks/RELIANCE/monte-carlo",
        json={
            "strategy": "supertrend",
            "simulations": _MC_TEST_SIMULATIONS,
            "random_seed": 42,
            "horizons": [1, 2, 5],
        },
    )
    _clear(client)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["symbol"] == "RELIANCE"
    assert data["simulation_count"] in {0, _MC_TEST_SIMULATIONS}
    assert "historical_oos_trade_count" in data
    assert data["historical_oos_trade_count"] != data["simulation_count"] or data["simulation_count"] == 0
    if data["available"]:
        assert data["next_day_outlook"] is not None
        assert "NOT a guaranteed" in data["next_day_outlook"]["disclaimer"]
        assert len(data["horizon_outlook"]) == 3
        horizons = {row["trading_days"]: row for row in data["horizon_outlook"]}
        assert horizons[1]["supported"] is True
        assert horizons[1]["median_price"] is not None
        assert data["historical_daily_return_count"] >= 30
        assert data["current_price"] is not None
        assert data["simulation_count"] == _MC_TEST_SIMULATIONS
        assert data["historical_oos_trade_count"] != _MC_TEST_SIMULATIONS


def test_favorites_add_remove_persist(client, api_gateway, test_settings) -> None:
    from app.services.dashboard.favorites_service import reset_favorites_service

    _override(client, api_gateway)
    reset_favorites_service()
    empty = client.get("/api/v1/favorites")
    assert empty.json()["data"]["symbols"] == []
    add = client.post("/api/v1/favorites/RELIANCE")
    assert add.status_code == 200
    assert add.json()["data"]["symbols"] == ["RELIANCE"]
    dup = client.post("/api/v1/favorites/reliance")
    assert dup.json()["data"]["symbols"] == ["RELIANCE"]
    listed = client.get("/api/v1/favorites")
    assert listed.json()["data"]["symbols"] == ["RELIANCE"]
    removed = client.delete("/api/v1/favorites/RELIANCE")
    assert removed.json()["data"]["symbols"] == []
    _clear(client)
    reset_favorites_service()


def test_monte_carlo_horizons_unsupported_without_history() -> None:
    import numpy as np

    from app.services.dashboard.horizon_outlook import compute_horizon_bands

    bands = compute_horizon_bands(
        np.array([0.01, -0.01], dtype=float),
        current_price=100.0,
        horizons=[1, 2, 5],
        simulations=_MC_TEST_SIMULATIONS,
        random_seed=1,
    )
    assert len(bands) == 3
    assert all(not band.supported for band in bands)
    assert all("Not available" in band.message for band in bands)


def test_monte_carlo_accepts_large_simulation_counts() -> None:
    from app.services.dashboard.schemas import MonteCarloDashboardRequest

    for sims in (1_000, 10_000, 100_000):
        req = MonteCarloDashboardRequest(strategy="supertrend", simulations=sims)
        assert req.simulations == sims

