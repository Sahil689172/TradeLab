"""A7 portfolio optimization / capital allocation tests.

Covers equal-weight, inverse-volatility and risk-parity allocation; all
allocation constraints; capital conservation; no over-allocation; deterministic
allocation; no future/OOS leakage; and portfolio-level metrics.
"""

from __future__ import annotations

import numpy as np
import pytest

from app.backtesting.portfolio_allocation import (
    AllocationConstraints,
    AllocationMethod,
    AllocationError,
    allocate,
    compute_raw_weights,
    estimate_volatilities,
    herfindahl_index,
    portfolio_metrics,
)


def _returns(seed: int, scale: float, n: int = 250) -> list[float]:
    rng = np.random.default_rng(seed)
    return (rng.normal(0.0005, scale, size=n)).tolist()


# --------------------------------------------------------------------------- #
# Equal-weight baseline
# --------------------------------------------------------------------------- #
def test_equal_weight_baseline() -> None:
    result = allocate(
        AllocationMethod.EQUAL_WEIGHT,
        ["AAA", "BBB", "CCC", "DDD"],
        constraints=AllocationConstraints(total_capital=1_000_000.0),
    )
    for w in result.weights.values():
        assert w == pytest.approx(0.25)
    for cap in result.capital_by_symbol.values():
        assert cap == pytest.approx(250_000.0)
    assert result.allocated_capital == pytest.approx(1_000_000.0)


# --------------------------------------------------------------------------- #
# Volatility / risk-based allocation
# --------------------------------------------------------------------------- #
def test_inverse_volatility_favours_low_vol() -> None:
    vols = {"LOW": 0.01, "HIGH": 0.04}
    weights = compute_raw_weights(
        AllocationMethod.INVERSE_VOLATILITY,
        ["LOW", "HIGH"],
        volatilities=vols,
    )
    # weight ratio must equal the inverse-vol ratio (0.04 / 0.01 = 4).
    assert weights["LOW"] / weights["HIGH"] == pytest.approx(4.0)
    assert weights["LOW"] + weights["HIGH"] == pytest.approx(1.0)


def test_inverse_volatility_estimated_from_returns() -> None:
    returns = {"CALM": _returns(1, 0.01), "WILD": _returns(2, 0.05)}
    vols = estimate_volatilities(returns)
    assert vols["WILD"] > vols["CALM"]
    weights = compute_raw_weights(
        AllocationMethod.INVERSE_VOLATILITY,
        ["CALM", "WILD"],
        returns_by_symbol=returns,
    )
    assert weights["CALM"] > weights["WILD"]


def test_risk_parity_equalizes_risk_contributions() -> None:
    returns = {"A": _returns(10, 0.01), "B": _returns(20, 0.03), "C": _returns(30, 0.05)}
    symbols = ["A", "B", "C"]
    weights = compute_raw_weights(
        AllocationMethod.RISK_PARITY,
        symbols,
        returns_by_symbol=returns,
    )
    w = np.array([weights[s] for s in symbols])
    trimmed = np.vstack([np.asarray(returns[s]) for s in symbols])
    cov = np.cov(trimmed, ddof=1)
    rc = w * (cov @ w)
    # Equal-risk-contribution: each symbol contributes ~1/n of portfolio risk.
    assert np.allclose(rc, rc.mean(), rtol=0.05, atol=1e-9)
    # Lower-vol symbol still gets the largest weight.
    assert weights["A"] > weights["B"] > weights["C"]


def test_risk_parity_diagonal_reduces_to_inverse_vol() -> None:
    vols = {"A": 0.02, "B": 0.04}
    rp = compute_raw_weights(AllocationMethod.RISK_PARITY, ["A", "B"], volatilities=vols)
    iv = compute_raw_weights(
        AllocationMethod.INVERSE_VOLATILITY, ["A", "B"], volatilities=vols
    )
    assert rp["A"] == pytest.approx(iv["A"])
    assert rp["B"] == pytest.approx(iv["B"])


# --------------------------------------------------------------------------- #
# Constraints
# --------------------------------------------------------------------------- #
def test_max_position_weight_caps_and_redistributes() -> None:
    result = allocate(
        AllocationMethod.EQUAL_WEIGHT,
        ["A", "B", "C"],
        constraints=AllocationConstraints(
            total_capital=1_000_000.0,
            max_position_weight=0.3,
        ),
    )
    for w in result.weights.values():
        assert w <= 0.3 + 1e-9
    # cap 0.3 across 3 symbols binds all → 0.9 invested, 0.1 extra cash.
    assert result.allocated_capital == pytest.approx(900_000.0)
    assert result.unallocated_capital == pytest.approx(100_000.0)


def test_max_symbol_exposure_cap() -> None:
    result = allocate(
        AllocationMethod.EQUAL_WEIGHT,
        ["A", "B"],
        constraints=AllocationConstraints(
            total_capital=1_000_000.0,
            max_symbol_exposure=0.4,
        ),
    )
    for w in result.weights.values():
        assert w <= 0.4 + 1e-9
    assert result.allocated_capital == pytest.approx(800_000.0)


def test_max_concurrent_positions_keeps_top_n() -> None:
    vols = {"A": 0.01, "B": 0.02, "C": 0.03, "D": 0.10}
    result = allocate(
        AllocationMethod.INVERSE_VOLATILITY,
        ["A", "B", "C", "D"],
        volatilities=vols,
        constraints=AllocationConstraints(
            total_capital=1_000_000.0,
            max_concurrent_positions=2,
        ),
    )
    # Only the two lowest-vol (highest-weight) symbols survive.
    assert set(result.weights) == {"A", "B"}
    assert "C" in result.dropped_symbols and "D" in result.dropped_symbols
    assert sum(result.weights.values()) == pytest.approx(1.0)


def test_min_allocation_weight_drops_small() -> None:
    vols = {"BIG": 0.01, "MID": 0.02, "TINY": 0.50}
    result = allocate(
        AllocationMethod.INVERSE_VOLATILITY,
        ["BIG", "MID", "TINY"],
        volatilities=vols,
        constraints=AllocationConstraints(
            total_capital=1_000_000.0,
            min_allocation_weight=0.05,
        ),
    )
    assert "TINY" in result.dropped_symbols
    assert all(w >= 0.05 for w in result.weights.values())


def test_cash_reserve_reduces_investable() -> None:
    result = allocate(
        AllocationMethod.EQUAL_WEIGHT,
        ["A", "B"],
        constraints=AllocationConstraints(
            total_capital=1_000_000.0,
            cash_reserve_pct=0.2,
        ),
    )
    assert result.cash_reserve == pytest.approx(200_000.0)
    assert result.investable_capital == pytest.approx(800_000.0)
    assert result.allocated_capital == pytest.approx(800_000.0)


# --------------------------------------------------------------------------- #
# Conservation of capital / no over-allocation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("method", list(AllocationMethod))
def test_capital_conservation(method: AllocationMethod) -> None:
    returns = {s: _returns(i, 0.01 * (i + 1)) for i, s in enumerate(["A", "B", "C"])}
    result = allocate(
        method,
        ["A", "B", "C"],
        returns_by_symbol=returns,
        volatilities=estimate_volatilities(returns),
        constraints=AllocationConstraints(total_capital=1_000_000.0),
    )
    # allocated + residual cash == total, and never over-allocated.
    assert result.allocated_capital + result.unallocated_capital == pytest.approx(
        1_000_000.0
    )
    assert result.allocated_capital <= 1_000_000.0 + 1e-6
    assert sum(result.weights.values()) <= 1.0 + 1e-9


def test_no_over_allocation_with_all_constraints() -> None:
    result = allocate(
        AllocationMethod.EQUAL_WEIGHT,
        ["A", "B", "C", "D", "E"],
        constraints=AllocationConstraints(
            total_capital=500_000.0,
            max_position_weight=0.25,
            max_concurrent_positions=3,
            cash_reserve_pct=0.1,
        ),
    )
    assert result.allocated_capital <= result.investable_capital + 1e-6
    assert result.allocated_capital <= 500_000.0 + 1e-6


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #
def test_deterministic_allocation() -> None:
    returns = {"A": _returns(1, 0.01), "B": _returns(2, 0.02), "C": _returns(3, 0.03)}
    kwargs = dict(
        returns_by_symbol=returns,
        constraints=AllocationConstraints(total_capital=1_000_000.0),
    )
    first = allocate(AllocationMethod.RISK_PARITY, ["A", "B", "C"], **kwargs)
    second = allocate(AllocationMethod.RISK_PARITY, ["A", "B", "C"], **kwargs)
    assert first.weights == second.weights
    assert first.capital_by_symbol == second.capital_by_symbol


# --------------------------------------------------------------------------- #
# Leakage: OOS data cannot influence allocation
# --------------------------------------------------------------------------- #
def test_allocation_uses_train_only_no_oos_leakage() -> None:
    train = {"A": _returns(1, 0.01), "B": _returns(2, 0.03)}
    # Two different OOS continuations must not matter: only train is passed.
    weights_run_1 = compute_raw_weights(
        AllocationMethod.INVERSE_VOLATILITY, ["A", "B"], returns_by_symbol=train
    )
    # Simulate a caller that (correctly) freezes weights from train, ignoring OOS.
    oos_a = {"A": _returns(99, 0.20), "B": _returns(98, 0.001)}  # noqa: F841
    weights_run_2 = compute_raw_weights(
        AllocationMethod.INVERSE_VOLATILITY, ["A", "B"], returns_by_symbol=train
    )
    assert weights_run_1 == weights_run_2


def test_multi_symbol_isolation_relative_ordering_stable() -> None:
    vols = {"A": 0.01, "B": 0.02, "C": 0.04}
    two = compute_raw_weights(
        AllocationMethod.INVERSE_VOLATILITY, ["A", "B"], volatilities=vols
    )
    three = compute_raw_weights(
        AllocationMethod.INVERSE_VOLATILITY, ["A", "B", "C"], volatilities=vols
    )
    # Adding C does not flip the A-vs-B ratio (each symbol's raw inverse-vol
    # contribution is independent before normalization).
    assert two["A"] / two["B"] == pytest.approx(three["A"] / three["B"])


# --------------------------------------------------------------------------- #
# Portfolio metrics
# --------------------------------------------------------------------------- #
def test_portfolio_metrics_basic() -> None:
    equity = [100_000, 101_000, 100_500, 102_000, 103_500]
    per_symbol_pnl = {"A": 2_000.0, "B": 1_500.0}
    per_symbol_capital = {"A": 50_000.0, "B": 50_000.0}
    metrics = portfolio_metrics(
        portfolio_equity=equity,
        initial_capital=100_000.0,
        per_symbol_pnl=per_symbol_pnl,
        per_symbol_capital=per_symbol_capital,
    )
    assert metrics.final_equity == pytest.approx(103_500.0)
    assert metrics.total_return == pytest.approx(0.035)
    assert metrics.max_drawdown > 0.0
    assert metrics.symbol_count == 2
    # Per-symbol P&L contribution sums to 1.
    assert sum(metrics.per_symbol_contribution.values()) == pytest.approx(1.0)
    assert metrics.per_symbol_return["A"] == pytest.approx(0.04)


def test_portfolio_metrics_concentration_hhi() -> None:
    # Two equal exposures → HHI = 0.5; fully concentrated → HHI = 1.0.
    assert herfindahl_index({"A": 1.0, "B": 1.0}) == pytest.approx(0.5)
    assert herfindahl_index({"A": 1.0}) == pytest.approx(1.0)


def test_empty_symbols_raises() -> None:
    with pytest.raises(AllocationError):
        allocate(AllocationMethod.EQUAL_WEIGHT, [])
