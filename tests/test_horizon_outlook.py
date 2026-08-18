"""Unit tests for multi-horizon bootstrap adapter."""

from __future__ import annotations

import numpy as np

from app.services.dashboard.horizon_outlook import compute_horizon_bands


def test_horizon_bands_supported_with_enough_returns() -> None:
    rng = np.random.default_rng(42)
    daily_returns = rng.normal(0.001, 0.02, size=60)
    bands = compute_horizon_bands(
        daily_returns,
        current_price=1000.0,
        horizons=[1, 2, 5],
        simulations=500,
        random_seed=7,
    )
    assert len(bands) == 3
    for band in bands:
        assert band.supported is True
        assert band.median_price is not None
        assert band.lower_price <= band.median_price <= band.upper_price


def test_horizon_bands_unsupported_insufficient_history() -> None:
    daily_returns = np.array([0.01, -0.01], dtype=float)
    bands = compute_horizon_bands(
        daily_returns,
        current_price=100.0,
        horizons=[1, 2, 5],
        simulations=100,
        random_seed=1,
    )
    assert all(not band.supported for band in bands)
    assert all("Not available" in band.message for band in bands)
