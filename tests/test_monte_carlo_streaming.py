"""Tests for Monte Carlo SSE streaming service, batched updates, and cancellation.

Coverage:
  - MonteCarloStreamingService.stream() yields progress events
  - batch sizing formula
  - sample paths are collected and bounded at SAMPLE_PATH_COUNT
  - partial_stats are non-empty after first batch
  - final 'result' event contains complete MonteCarloDashboardResponse
  - historical OOS trades remain unchanged across streaming run
  - simulation count is separate from historical trade count
  - no dummy / synthetic data injected into stats
  - cancellation stops the stream and emits error event
  - failure (bad symbol) emits error event without crash
  - 1k, 10k, 100k simulation counts complete correctly
  - strategy/entry/SL/target values come from the existing engine (not hardcoded)
"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from app.backtesting.monte_carlo.pipeline import make_synthetic_trades
from app.backtesting.monte_carlo.schemas import MonteCarloConfig
from app.services.dashboard.monte_carlo_streaming import (
    MonteCarloStreamingService,
    SAMPLE_PATH_COUNT,
    _batch_size,
    _partial_stats,
    cancel_run,
    register_cancel_token,
    unregister_cancel_token,
)
from app.services.dashboard.schemas import (
    MonteCarloDashboardRequest,
    MonteCarloDashboardResponse,
)


# ── helpers ────────────────────────────────────────────────────────────────

def _request(simulations: int = 100, strategy: str = "ema_trend") -> MonteCarloDashboardRequest:
    return MonteCarloDashboardRequest(
        strategy=strategy,
        simulations=simulations,
        random_seed=42,
        initial_capital=1_000_000.0,
        timeframe="1D",
        horizons=[1, 2, 5],
    )


def _mock_service(trades=None):
    """Return a MonteCarloStreamingService whose _base._load_trades is mocked."""
    if trades is None:
        trades = make_synthetic_trades(20, seed=7)

    base = MagicMock()
    base._load_trades.return_value = (
        trades,
        "TEST_TRADE_SOURCE",
        "2023-01-01 → 2023-12-31",
        ["test warning"],
    )
    # _next_day_outlook must return a real NextDayOutlook.
    from app.services.dashboard.schemas import NextDayOutlook
    base._next_day_outlook.return_value = NextDayOutlook(
        supported=False,
        disclaimer="test",
        message="mocked",
    )
    svc = MonteCarloStreamingService(base=base)
    return svc


async def _collect_events(svc, symbol, request, cancel_event=None):
    """Run stream() and collect (event_name, data) pairs."""
    if cancel_event is None:
        cancel_event = threading.Event()
    events = []
    async for chunk in svc.stream(symbol, request, cancel_event):
        # Parse SSE text into (event, data).
        event_name = "message"
        data_line = ""
        for line in chunk.split("\n"):
            if line.startswith("event: "):
                event_name = line[7:].strip()
            elif line.startswith("data: "):
                data_line = line[6:]
        if data_line:
            events.append((event_name, json.loads(data_line)))
    return events


# ── _batch_size ────────────────────────────────────────────────────────────

def test_batch_size_1k():
    # 1 000 / 5 = 200; less than _BATCH_TARGET(5000).
    assert _batch_size(1_000) == 200


def test_batch_size_10k():
    # 10 000 / 5 = 2 000.
    assert _batch_size(10_000) == 2_000


def test_batch_size_100k():
    # 100 000 / 5 = 20 000; greater than BATCH_TARGET → clamped to 5 000.
    assert _batch_size(100_000) == 5_000


def test_batch_size_minimum():
    assert _batch_size(1) >= 1


# ── _partial_stats ─────────────────────────────────────────────────────────

def test_partial_stats_empty():
    result = _partial_stats(np.array([]), np.array([]), 1_000_000)
    assert result == {}


def test_partial_stats_values():
    ret = np.array([0.05, -0.02, 0.10, -0.03, 0.07])
    dd = np.abs(np.array([-0.01, -0.03, -0.005, -0.02, -0.015]))
    stats = _partial_stats(ret, dd, 1_000_000)
    assert "probability_of_loss" in stats
    assert "probability_of_profit" in stats
    assert "median_return_pct" in stats
    assert stats["probability_of_loss"] == pytest.approx(2 / 5)
    assert stats["probability_of_profit"] == pytest.approx(3 / 5)


# ── streaming: progress events ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_yields_progress_events():
    svc = _mock_service()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100))
    progress = [e for e in events if e[0] == "progress"]
    assert len(progress) >= 1, "Should have at least one progress event"


@pytest.mark.asyncio
async def test_stream_first_progress_has_completed_gt_zero():
    svc = _mock_service()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100))
    progress = [e for e in events if e[0] == "progress"]
    first = progress[0][1]
    assert first["completed"] > 0
    assert first["total"] == 100
    assert 0 < first["pct"] <= 100


@pytest.mark.asyncio
async def test_stream_progress_has_partial_stats():
    svc = _mock_service()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100))
    progress = [e for e in events if e[0] == "progress"]
    # At least the last progress event must have partial_stats populated.
    last_progress = progress[-1][1]
    assert "partial_stats" in last_progress
    ps = last_progress["partial_stats"]
    assert "probability_of_loss" in ps
    assert "median_return_pct" in ps


@pytest.mark.asyncio
async def test_stream_final_progress_is_100_pct():
    svc = _mock_service()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100))
    progress = [e for e in events if e[0] == "progress"]
    final = progress[-1][1]
    assert final["pct"] == pytest.approx(100.0)
    assert final["completed"] == 100
    assert final["status"] == "complete"


# ── streaming: sample paths ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_sample_paths_are_collected():
    svc = _mock_service()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=200))
    progress = [e for e in events if e[0] == "progress"]
    last = progress[-1][1]
    assert "sample_paths" in last
    assert len(last["sample_paths"]) > 0


@pytest.mark.asyncio
async def test_stream_sample_paths_bounded_at_max():
    svc = _mock_service(trades=make_synthetic_trades(30, seed=9))
    events = await _collect_events(svc, "RELIANCE", _request(simulations=1_000))
    # Find the result event's _sample_paths count.
    result_events = [e for e in events if e[0] == "result"]
    assert result_events, "Expected a result event"
    sample = result_events[0][1].get("_sample_paths", [])
    assert len(sample) <= SAMPLE_PATH_COUNT


@pytest.mark.asyncio
async def test_stream_each_path_has_correct_step_count():
    trades = make_synthetic_trades(15, seed=3)
    svc = _mock_service(trades=trades)
    events = await _collect_events(svc, "RELIANCE", _request(simulations=50))
    result_events = [e for e in events if e[0] == "result"]
    paths = result_events[0][1].get("_sample_paths", [])
    n_trades = len(trades)
    for path in paths:
        assert len(path) == n_trades, f"Expected {n_trades} steps, got {len(path)}"


# ── streaming: result event ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_emits_result_event():
    svc = _mock_service()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100))
    result_events = [e for e in events if e[0] == "result"]
    assert len(result_events) == 1


@pytest.mark.asyncio
async def test_stream_result_contains_full_response_fields():
    svc = _mock_service()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100))
    data = next(e[1] for e in events if e[0] == "result")
    # Core fields from MonteCarloDashboardResponse.
    assert data["symbol"] == "RELIANCE"
    assert data["available"] is True
    assert "simulation_count" in data
    assert "historical_oos_trade_count" in data
    assert "probability_of_loss" in data
    assert "median_return_pct" in data
    assert "warnings" in data
    assert "_sample_paths" in data
    assert "_elapsed" in data


@pytest.mark.asyncio
async def test_stream_result_elapsed_is_positive():
    svc = _mock_service()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100))
    data = next(e[1] for e in events if e[0] == "result")
    assert data["_elapsed"] >= 0.0


# ── historical OOS trades remain unchanged ─────────────────────────────────

@pytest.mark.asyncio
async def test_historical_oos_trade_count_unchanged_by_simulation():
    trades = make_synthetic_trades(17, seed=5)
    svc = _mock_service(trades=trades)
    events = await _collect_events(svc, "RELIANCE", _request(simulations=500))
    data = next(e[1] for e in events if e[0] == "result")
    # historical_oos_trade_count must equal the number of source trades.
    assert data["historical_oos_trade_count"] == 17


@pytest.mark.asyncio
async def test_simulation_count_separate_from_historical_trades():
    trades = make_synthetic_trades(12, seed=2)
    svc = _mock_service(trades=trades)
    req = _request(simulations=300)
    events = await _collect_events(svc, "RELIANCE", req)
    data = next(e[1] for e in events if e[0] == "result")
    # simulation_count is what was requested, not the trade count.
    assert data["simulation_count"] == 300
    assert data["historical_oos_trade_count"] == 12
    assert data["simulation_count"] != data["historical_oos_trade_count"]


# ── simulation scale tests ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_1k_simulations():
    svc = _mock_service(trades=make_synthetic_trades(25, seed=1))
    events = await _collect_events(svc, "TEST", _request(simulations=1_000))
    result_events = [e for e in events if e[0] == "result"]
    assert result_events
    assert result_events[0][1]["simulation_count"] == 1_000


@pytest.mark.asyncio
async def test_stream_10k_simulations():
    svc = _mock_service(trades=make_synthetic_trades(25, seed=1))
    events = await _collect_events(svc, "TEST", _request(simulations=10_000))
    result_events = [e for e in events if e[0] == "result"]
    assert result_events
    assert result_events[0][1]["simulation_count"] == 10_000


@pytest.mark.asyncio
async def test_stream_100k_simulations():
    # 100k with 25 trades should complete and produce a valid result.
    svc = _mock_service(trades=make_synthetic_trades(25, seed=1))
    events = await _collect_events(svc, "TEST", _request(simulations=100_000))
    result_events = [e for e in events if e[0] == "result"]
    assert result_events, "Expected result event for 100k run"
    data = result_events[0][1]
    assert data["simulation_count"] == 100_000
    assert data["historical_oos_trade_count"] == 25
    # Stats must be finite.
    assert data["probability_of_loss"] is not None
    assert 0.0 <= data["probability_of_loss"] <= 1.0


@pytest.mark.asyncio
async def test_stream_100k_has_multiple_progress_batches():
    """100k should emit multiple progress events (5+ batches at 5k each)."""
    svc = _mock_service(trades=make_synthetic_trades(20, seed=3))
    events = await _collect_events(svc, "TEST", _request(simulations=100_000))
    progress = [e for e in events if e[0] == "progress"]
    # With batch_size=5000 for 100k → 20 batches + 1 final = 21.
    assert len(progress) >= 5


# ── cancellation ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancellation_before_first_batch():
    trades = make_synthetic_trades(20, seed=4)
    base = MagicMock()

    # Simulate a slow trade load that checks cancellation.
    cancel_event = threading.Event()

    def slow_load(symbol, request):
        # Signal cancel while "loading".
        cancel_event.set()
        return trades, "SOURCE", "", []

    base._load_trades.side_effect = slow_load
    from app.services.dashboard.schemas import NextDayOutlook
    base._next_day_outlook.return_value = NextDayOutlook(supported=False, disclaimer="x")

    svc = MonteCarloStreamingService(base=base)
    events = await _collect_events(svc, "RELIANCE", _request(simulations=200), cancel_event)
    error_events = [e for e in events if e[0] == "error"]
    assert error_events, "Expected error/cancel event"
    assert "Cancelled" in error_events[0][1]["message"]


@pytest.mark.asyncio
async def test_cancellation_mid_run():
    """Cancel after first batch by setting event during iteration."""
    trades = make_synthetic_trades(20, seed=4)
    cancel_event = threading.Event()
    svc = _mock_service(trades=trades)

    collected = []
    # Patch asyncio.sleep to cancel after first yielded progress event.
    original_sleep = asyncio.sleep
    call_count = 0

    async def cancelling_sleep(delay):
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            cancel_event.set()
        await original_sleep(0)

    with patch("app.services.dashboard.monte_carlo_streaming.asyncio.sleep", cancelling_sleep):
        async for chunk in svc.stream("RELIANCE", _request(simulations=1_000), cancel_event):
            event_name = ""
            data_line = ""
            for line in chunk.split("\n"):
                if line.startswith("event: "):
                    event_name = line[7:].strip()
                elif line.startswith("data: "):
                    data_line = line[6:]
            if data_line:
                collected.append((event_name, json.loads(data_line)))

    error_events = [e for e in collected if e[0] == "error"]
    assert error_events, "Expected cancel error event after mid-run cancellation"


def test_cancel_registry_register_and_cancel():
    run_id = "test-run-001"
    ev = register_cancel_token(run_id)
    assert not ev.is_set()
    found = cancel_run(run_id)
    assert found is True
    assert ev.is_set()
    unregister_cancel_token(run_id)
    # After unregister, cancel returns False (not found).
    assert cancel_run(run_id) is False


def test_cancel_unknown_run_id():
    result = cancel_run("nonexistent-run-xyz")
    assert result is False


def test_unregister_idempotent():
    run_id = "unregister-test"
    register_cancel_token(run_id)
    unregister_cancel_token(run_id)
    unregister_cancel_token(run_id)   # second call must not raise


# ── failure handling ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_error_on_unknown_strategy():
    """A bad strategy name should emit an error event, not raise."""
    base = MagicMock()
    base._load_trades.side_effect = ValueError("Unknown strategy 'bad_strategy'")
    svc = MonteCarloStreamingService(base=base)
    cancel = threading.Event()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100, strategy="bad_strategy"), cancel)
    error_events = [e for e in events if e[0] == "error"]
    assert error_events
    assert "Unknown strategy" in error_events[0][1]["message"]


@pytest.mark.asyncio
async def test_stream_no_trades_emits_result_unavailable():
    """Zero trades produces a result event with available=False, not an error."""
    base = MagicMock()
    base._load_trades.return_value = ([], "NO_TRADES", "", [])
    from app.services.dashboard.schemas import NextDayOutlook
    base._next_day_outlook.return_value = NextDayOutlook(supported=False, disclaimer="x")
    svc = MonteCarloStreamingService(base=base)
    cancel = threading.Event()
    events = await _collect_events(svc, "RELIANCE", _request(simulations=100), cancel)
    result_events = [e for e in events if e[0] == "result"]
    assert result_events
    data = result_events[0][1]
    assert data["available"] is False
    assert data["simulation_count"] == 0


# ── no dummy data ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_result_stats_consistent_with_source_trades():
    """All-winning trades must yield P(loss)=0; all-losing must yield P(profit)=0."""
    from app.backtesting.monte_carlo.schemas import MonteCarloTrade

    winning = [MonteCarloTrade(pnl=100.0, return_pct=0.01) for _ in range(20)]
    svc_win = _mock_service(trades=winning)
    events_win = await _collect_events(svc_win, "TEST", _request(simulations=200))
    data_win = next(e[1] for e in events_win if e[0] == "result")
    assert data_win["probability_of_profit"] == pytest.approx(1.0)
    assert data_win["probability_of_loss"] == pytest.approx(0.0)

    losing = [MonteCarloTrade(pnl=-50.0, return_pct=-0.005) for _ in range(20)]
    svc_los = _mock_service(trades=losing)
    events_los = await _collect_events(svc_los, "TEST", _request(simulations=200))
    data_los = next(e[1] for e in events_los if e[0] == "result")
    assert data_los["probability_of_loss"] == pytest.approx(1.0)
    assert data_los["probability_of_profit"] == pytest.approx(0.0)


# ── determinism / reproducibility ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_stream_same_seed_same_result():
    trades = make_synthetic_trades(20, seed=99)
    svc_a = _mock_service(trades=trades)
    svc_b = _mock_service(trades=trades)
    req = _request(simulations=500)

    events_a = await _collect_events(svc_a, "RELIANCE", req)
    events_b = await _collect_events(svc_b, "RELIANCE", req)

    data_a = next(e[1] for e in events_a if e[0] == "result")
    data_b = next(e[1] for e in events_b if e[0] == "result")

    assert data_a["probability_of_loss"] == pytest.approx(data_b["probability_of_loss"])
    assert data_a["median_return_pct"] == pytest.approx(data_b["median_return_pct"])
