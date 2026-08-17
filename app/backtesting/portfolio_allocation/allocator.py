"""A7 capital allocation: weights from training inputs, then constraints.

Determinism: every function is a pure transform of its inputs. Given the same
per-symbol training returns / volatilities and the same constraints, the output
is byte-for-byte identical. No randomness is used.

Leakage: callers pass *training-window* returns only. This module never reads
out-of-sample data, timestamps, or future outcomes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import numpy as np

from app.backtesting.portfolio_allocation.exceptions import AllocationError
from app.backtesting.portfolio_allocation.schemas import (
    AllocationConstraints,
    AllocationMethod,
    AllocationResult,
    SymbolAllocation,
)


def estimate_volatilities(
    returns_by_symbol: Mapping[str, Sequence[float]],
) -> dict[str, float]:
    """Sample standard deviation (ddof=1) of each symbol's training returns."""
    vols: dict[str, float] = {}
    for symbol, returns in returns_by_symbol.items():
        arr = np.asarray(list(returns), dtype=float)
        arr = arr[np.isfinite(arr)]
        vols[symbol] = float(np.std(arr, ddof=1)) if arr.size >= 2 else 0.0
    return vols


def _covariance_matrix(
    symbols: Sequence[str],
    returns_by_symbol: Mapping[str, Sequence[float]],
) -> np.ndarray:
    """Covariance over the common (truncated) length of the training returns."""
    series = [np.asarray(list(returns_by_symbol[s]), dtype=float) for s in symbols]
    lengths = [a.size for a in series]
    min_len = min(lengths) if lengths else 0
    if min_len < 2:
        # Fall back to a diagonal matrix of per-symbol variances.
        vols = estimate_volatilities({s: returns_by_symbol[s] for s in symbols})
        diag = np.array([max(vols[s], 0.0) ** 2 for s in symbols], dtype=float)
        return np.diag(diag)
    trimmed = np.vstack([a[-min_len:] for a in series])
    cov = np.cov(trimmed, ddof=1)
    return np.atleast_2d(cov)


def _inverse_volatility_weights(cov: np.ndarray) -> np.ndarray:
    vols = np.sqrt(np.clip(np.diag(cov), 1e-16, None))
    w = 1.0 / vols
    return w / w.sum()


def _risk_parity_weights(cov: np.ndarray, *, max_iter: int = 500, tol: float = 1e-12) -> np.ndarray:
    """Equal-risk-contribution weights (variance-based, budget 1/n each).

    Cyclical coordinate descent (Griveau-Billion et al.) on the full covariance
    matrix. Inverse-volatility seeds the iteration; each pass updates one weight
    at a time from a closed-form quadratic root so all symbols stay positive.
    """
    n = cov.shape[0]
    if n == 0:
        return np.asarray([], dtype=float)
    if n == 1:
        return np.asarray([1.0], dtype=float)

    cov = np.asarray(cov, dtype=float)
    budget = 1.0 / n
    w = _inverse_volatility_weights(cov)
    eps = 1e-16

    for _ in range(max_iter):
        w_old = w.copy()
        port_var = float(w @ cov @ w)
        if port_var <= 0.0:
            return np.ones(n) / n
        for i in range(n):
            ci = float(cov[i, i])
            if ci <= 0.0:
                continue
            beta = float(cov[i, :] @ w - ci * w[i])
            radicand = beta * beta + 4.0 * ci * budget * port_var
            w[i] = (-beta + float(np.sqrt(max(radicand, 0.0)))) / (2.0 * ci)
        w = np.maximum(w, eps)
        s = float(w.sum())
        if s <= 0.0:
            return np.ones(n) / n
        w = w / s
        # Converge on risk-contribution fractions, not just weight movement.
        marginal = cov @ w
        rc_frac = (w * marginal) / float(w @ marginal)
        if float(np.max(np.abs(rc_frac - budget))) < tol:
            break
        if float(np.max(np.abs(w - w_old))) < tol:
            break
    return w


def compute_raw_weights(
    method: AllocationMethod,
    symbols: Sequence[str],
    *,
    volatilities: Mapping[str, float] | None = None,
    returns_by_symbol: Mapping[str, Sequence[float]] | None = None,
) -> dict[str, float]:
    """Unconstrained target weights (sum to 1) from training inputs."""
    ordered = list(symbols)
    n = len(ordered)
    if n == 0:
        return {}
    if method is AllocationMethod.EQUAL_WEIGHT:
        return {s: 1.0 / n for s in ordered}

    if method is AllocationMethod.INVERSE_VOLATILITY:
        vols = dict(volatilities) if volatilities is not None else None
        if vols is None:
            if returns_by_symbol is None:
                raise AllocationError(
                    "inverse_volatility requires volatilities or returns_by_symbol",
                )
            vols = estimate_volatilities(returns_by_symbol)
        inv = np.array([1.0 / vols[s] if vols.get(s, 0.0) > 0 else 0.0 for s in ordered])
        if float(inv.sum()) <= 0.0:
            return {s: 1.0 / n for s in ordered}
        inv = inv / inv.sum()
        return {s: float(inv[i]) for i, s in enumerate(ordered)}

    if method is AllocationMethod.RISK_PARITY:
        if returns_by_symbol is None:
            # Diagonal risk parity reduces to inverse volatility.
            return compute_raw_weights(
                AllocationMethod.INVERSE_VOLATILITY,
                ordered,
                volatilities=volatilities,
            )
        cov = _covariance_matrix(ordered, returns_by_symbol)
        w = _risk_parity_weights(cov)
        if w.size == 0 or float(w.sum()) <= 0.0:
            return {s: 1.0 / n for s in ordered}
        return {s: float(w[i]) for i, s in enumerate(ordered)}

    raise AllocationError(f"unsupported allocation method: {method}")


def _cap_weights(weights: dict[str, float], cap: float) -> dict[str, float]:
    """Cap each weight at ``cap``, redistributing excess to uncapped symbols.

    If ``cap * n < 1`` all symbols hit the cap and the remainder is left
    unallocated (guaranteeing no over-allocation).
    """
    w = {s: float(v) for s, v in weights.items()}
    if not w:
        return w
    if cap >= 1.0:
        return w
    capped: set[str] = set()
    for _ in range(len(w) + 1):
        free = [s for s in w if s not in capped]
        if not free:
            break
        capped_sum = sum(w[s] for s in capped)
        free_target = max(0.0, 1.0 - capped_sum)
        free_sum = sum(w[s] for s in free)
        if free_sum <= 0.0:
            break
        scale = free_target / free_sum
        for s in free:
            w[s] *= scale
        violators = sorted(s for s in free if w[s] > cap + 1e-12)
        if not violators:
            break
        for s in violators:
            w[s] = cap
            capped.add(s)
    return w


def apply_constraints(
    raw_weights: Mapping[str, float],
    constraints: AllocationConstraints,
) -> tuple[dict[str, float], list[str], list[str]]:
    """Apply min-allocation, concurrency, and per-symbol caps.

    Returns ``(weights, dropped_symbols, notes)``. Weights sum to <= 1.
    """
    notes: list[str] = []
    dropped: list[str] = []
    weights = {s: float(v) for s, v in raw_weights.items() if v > 0}
    if not weights:
        return {}, list(raw_weights.keys()), ["no positive raw weights to allocate"]

    def _renorm(w: dict[str, float]) -> dict[str, float]:
        total = sum(w.values())
        if total <= 0:
            return w
        return {s: v / total for s, v in w.items()}

    weights = _renorm(weights)

    # 1. Minimum allocation: drop symbols below the floor, then renormalize.
    if constraints.min_allocation_weight > 0.0:
        below = sorted(s for s, v in weights.items() if v < constraints.min_allocation_weight)
        if below and len(below) < len(weights):
            for s in below:
                dropped.append(s)
                del weights[s]
            notes.append(
                f"dropped {len(below)} symbol(s) below min_allocation_weight="
                f"{constraints.min_allocation_weight:g}",
            )
            weights = _renorm(weights)
        elif below and len(below) == len(weights):
            notes.append(
                "all symbols below min_allocation_weight; allocation left in cash",
            )
            return {}, sorted(raw_weights.keys()), notes

    # 2. Concurrency cap: keep the top-N by weight (ties broken by symbol name).
    max_n = constraints.max_concurrent_positions
    if max_n is not None and len(weights) > max_n:
        ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
        keep = dict(ranked[:max_n])
        for s, _ in ranked[max_n:]:
            dropped.append(s)
        notes.append(
            f"kept top {max_n} symbol(s) for max_concurrent_positions; "
            f"dropped {len(weights) - max_n}",
        )
        weights = _renorm(keep)

    # 3. Per-symbol weight cap with excess redistribution.
    cap = constraints.effective_weight_cap
    if cap < 1.0:
        weights = _cap_weights(weights, cap)
        if sum(weights.values()) < 1.0 - 1e-9:
            notes.append(
                f"per-symbol cap {cap:g} binds all symbols; "
                f"{(1.0 - sum(weights.values())) * 100:.2f}% left as extra cash",
            )

    return {s: v for s, v in sorted(weights.items())}, sorted(set(dropped)), notes


def allocate(
    method: AllocationMethod,
    symbols: Sequence[str],
    *,
    constraints: AllocationConstraints | None = None,
    volatilities: Mapping[str, float] | None = None,
    returns_by_symbol: Mapping[str, Sequence[float]] | None = None,
) -> AllocationResult:
    """Build a deterministic, constraint-respecting capital allocation.

    ``symbols`` fixes the ordering. ``volatilities`` / ``returns_by_symbol`` must
    be estimated from the training window only.
    """
    constraints = constraints or AllocationConstraints()
    ordered = list(symbols)
    if not ordered:
        raise AllocationError("cannot allocate with no symbols")

    raw = compute_raw_weights(
        method,
        ordered,
        volatilities=volatilities,
        returns_by_symbol=returns_by_symbol,
    )
    weights, dropped, notes = apply_constraints(raw, constraints)

    investable = constraints.total_capital * (1.0 - constraints.cash_reserve_pct)
    capital_by_symbol = {s: weights[s] * investable for s in weights}
    allocated = float(sum(capital_by_symbol.values()))
    cash_reserve = constraints.total_capital * constraints.cash_reserve_pct
    unallocated = constraints.total_capital - allocated

    cap = constraints.effective_weight_cap
    allocations = [
        SymbolAllocation(
            symbol=s,
            weight=weights[s],
            capital=capital_by_symbol[s],
            volatility=(volatilities or {}).get(s) if volatilities else None,
            capped=(cap < 1.0 and abs(weights[s] - cap) < 1e-9),
        )
        for s in sorted(weights)
    ]

    return AllocationResult(
        method=method,
        total_capital=constraints.total_capital,
        cash_reserve_pct=constraints.cash_reserve_pct,
        cash_reserve=cash_reserve,
        investable_capital=investable,
        allocated_capital=allocated,
        unallocated_capital=unallocated,
        allocations=allocations,
        weights=weights,
        capital_by_symbol=capital_by_symbol,
        dropped_symbols=dropped,
        constraints=constraints,
        notes=notes,
    )
