"""Tests for the walk-forward OOS trade disk cache.

The cache exists purely to avoid re-running a multi-minute walk-forward pass on
every Monte Carlo request.  These tests pin the two properties that make that
safe: a round trip must preserve the trade population exactly, and the entry
must stop being used the moment anything it was derived from changes.
"""

from __future__ import annotations

import json

import pytest

from app.backtesting.monte_carlo.schemas import MonteCarloTrade
from app.services.dashboard.oos_trade_cache import (
    CACHE_VERSION,
    OOSTradeCache,
    cache_key,
)


def _trade(pnl: float, *, trade_id: str = "t1") -> MonteCarloTrade:
    return MonteCarloTrade(
        pnl=pnl,
        return_pct=pnl / 100_000.0,
        costs=12.5,
        brokerage=7.5,
        slippage=5.0,
        gross_pnl=pnl + 12.5,
        holding_period=4,
        win_loss=1 if pnl > 0 else -1,
        source_trade_id=trade_id,
        symbol="RELIANCE",
        quantity=10.0,
        entry_price=2500.0,
        exit_price=2500.0 + pnl / 10.0,
    )


@pytest.fixture
def parquet(tmp_path):
    path = tmp_path / "RELIANCE.parquet"
    path.write_bytes(b"bars-v1")
    return path


@pytest.fixture
def cache(tmp_path):
    return OOSTradeCache(tmp_path / "oos_cache")


def _key(parquet, **overrides):
    params = {
        "symbol": "RELIANCE",
        "strategy_alias": "ema_professional",
        "config_fingerprint": "wf:y2:1:1:cap100000",
        "parquet": parquet,
    }
    params.update(overrides)
    return cache_key(**params)


# ── round trip ────────────────────────────────────────────────────────────────


def test_miss_on_empty_cache(cache, parquet):
    assert cache.get(_key(parquet)) is None


def test_round_trip_preserves_trades(cache, parquet):
    trades = [_trade(150.0, trade_id="a"), _trade(-80.0, trade_id="b")]
    key = _key(parquet)
    cache.put(
        key,
        trades=trades,
        period="2019-01-01 → 2024-12-31",
        window_count=7,
        strategy_alias="ema_professional",
    )

    loaded = cache.get(key)
    assert loaded is not None
    assert loaded.trade_count == 2
    assert [t.pnl for t in loaded.trades] == [150.0, -80.0]
    assert [t.source_trade_id for t in loaded.trades] == ["a", "b"]
    assert loaded.period == "2019-01-01 → 2024-12-31"
    assert loaded.window_count == 7


def test_round_trip_preserves_every_field(cache, parquet):
    original = _trade(42.0)
    key = _key(parquet)
    cache.put(key, trades=[original], period="p", window_count=1,
              strategy_alias="ema_professional")

    restored = cache.get(key).trades[0]
    assert restored.model_dump() == original.model_dump()


def test_empty_trade_set_is_cacheable(cache, parquet):
    """A symbol that legitimately produced zero OOS trades must not re-run."""
    key = _key(parquet)
    cache.put(key, trades=[], period="", window_count=5,
              strategy_alias="ema_professional")

    loaded = cache.get(key)
    assert loaded is not None
    assert loaded.trade_count == 0
    assert loaded.window_count == 5


# ── invalidation ──────────────────────────────────────────────────────────────


def test_changed_bars_invalidate_entry(cache, parquet):
    """Refreshing a symbol must not serve trades derived from the old bars."""
    key_before = _key(parquet)
    cache.put(key_before, trades=[_trade(10.0)], period="p", window_count=1,
              strategy_alias="ema_professional")

    parquet.write_bytes(b"bars-v2-longer-history")

    assert _key(parquet) != key_before
    assert cache.get(_key(parquet)) is None


def test_distinct_keys_per_symbol_strategy_and_config(parquet):
    base = _key(parquet)
    assert _key(parquet, symbol="TCS") != base
    assert _key(parquet, strategy_alias="supertrend") != base
    assert _key(parquet, config_fingerprint="wf:y5:1:1:cap100000") != base


def test_initial_capital_is_part_of_identity(parquet):
    """Capital scales trade P&L, so it cannot be shared across cache entries."""
    a = _key(parquet, config_fingerprint="wf:y2:1:1:cap100000")
    b = _key(parquet, config_fingerprint="wf:y2:1:1:cap1000000")
    assert a != b


def test_key_is_stable_for_identical_inputs(parquet):
    assert _key(parquet) == _key(parquet)


def test_missing_parquet_does_not_raise(tmp_path):
    key = cache_key(
        symbol="GHOST",
        strategy_alias="ema_professional",
        config_fingerprint="wf:y2:1:1:cap100000",
        parquet=tmp_path / "absent.parquet",
    )
    assert isinstance(key, str) and key


# ── resilience ────────────────────────────────────────────────────────────────


def test_stale_cache_version_is_ignored(cache, parquet):
    key = _key(parquet)
    cache.put(key, trades=[_trade(10.0)], period="p", window_count=1,
              strategy_alias="ema_professional")

    path = cache._path(key)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["cache_version"] = "older-build"
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert cache.get(key) is None


def test_corrupt_entry_is_ignored_not_raised(cache, parquet):
    key = _key(parquet)
    cache.put(key, trades=[_trade(10.0)], period="p", window_count=1,
              strategy_alias="ema_professional")
    cache._path(key).write_text("{not valid json", encoding="utf-8")

    assert cache.get(key) is None


def test_entry_with_malformed_trade_is_ignored(cache, parquet):
    key = _key(parquet)
    cache.put(key, trades=[_trade(10.0)], period="p", window_count=1,
              strategy_alias="ema_professional")

    path = cache._path(key)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["trades"] = [{"unexpected_field": 1}]
    path.write_text(json.dumps(payload), encoding="utf-8")

    assert cache.get(key) is None


def test_written_payload_declares_current_version(cache, parquet):
    key = _key(parquet)
    cache.put(key, trades=[_trade(10.0)], period="p", window_count=1,
              strategy_alias="ema_professional")

    payload = json.loads(cache._path(key).read_text(encoding="utf-8"))
    assert payload["cache_version"] == CACHE_VERSION
    assert payload["trade_count"] == 1


def test_no_temp_files_left_behind(cache, parquet):
    key = _key(parquet)
    cache.put(key, trades=[_trade(10.0)], period="p", window_count=1,
              strategy_alias="ema_professional")

    assert list(cache._directory.glob("*.tmp")) == []


def test_clear_removes_entries(cache, parquet):
    key = _key(parquet)
    cache.put(key, trades=[_trade(10.0)], period="p", window_count=1,
              strategy_alias="ema_professional")
    assert cache.get(key) is not None

    cache.clear()
    assert cache.get(key) is None


def test_clear_on_missing_directory_is_safe(tmp_path):
    OOSTradeCache(tmp_path / "never_created").clear()
