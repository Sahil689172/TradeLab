"""Multi-horizon price bands via bootstrap of historical daily returns.

Uses the same bootstrap sampling method as TradeResamplingMonteCarlo on
real stored OHLCV daily returns. This is a statistical simulation adapter —
not a guaranteed future price forecast and not trade-resampling MC paths.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.backtesting.monte_carlo import MonteCarloConfig, TradeResamplingMonteCarlo
from app.backtesting.monte_carlo.engine import _sample_index_matrix
from app.backtesting.monte_carlo.schemas import SamplingMethod

MIN_DAILY_SAMPLES = 30
HORIZON_LABELS = {1: "Tomorrow (+1 trading day)", 2: "Day After Tomorrow (+2 trading days)", 5: "1 Week (+5 trading days)"}


@dataclass(frozen=True, slots=True)
class HorizonBand:
    trading_days: int
    label: str
    supported: bool
    message: str = ""
    mean_price: float | None = None
    median_price: float | None = None
    lower_price: float | None = None
    upper_price: float | None = None
    expected_return_pct: float | None = None
    lower_return_pct: float | None = None
    upper_return_pct: float | None = None
    probability_negative_return: float | None = None
    method: str = "bootstrap_historical_daily_returns"


def daily_returns_from_frame(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty or "close" not in frame.columns:
        return np.array([], dtype=float)
    closes = frame.sort_values("date")["close"].astype(float).values
    if len(closes) < 2:
        return np.array([], dtype=float)
    prev = closes[:-1]
    curr = closes[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.where(prev > 0, curr / prev - 1.0, 0.0)
    return rets.astype(float)


def compute_horizon_bands(
    daily_returns: np.ndarray,
    *,
    current_price: float,
    horizons: list[int],
    simulations: int,
    random_seed: int,
    lower_pct: float = 5.0,
    upper_pct: float = 95.0,
) -> list[HorizonBand]:
    """Bootstrap compound returns for each horizon using MC sampling utilities."""
    out: list[HorizonBand] = []
    n = len(daily_returns)
    if current_price <= 0 or n < MIN_DAILY_SAMPLES:
        msg = (
            "Not available with current model"
            if n < MIN_DAILY_SAMPLES
            else "Current price unavailable"
        )
        for h in horizons:
            out.append(
                HorizonBand(
                    trading_days=h,
                    label=HORIZON_LABELS.get(h, f"+{h} trading days"),
                    supported=False,
                    message=msg,
                ),
            )
        return out

    mc = TradeResamplingMonteCarlo(
        MonteCarloConfig(
            simulations=simulations,
            random_seed=random_seed,
            sampling_method=SamplingMethod.BOOTSTRAP,
        ),
    )
    rng = np.random.default_rng(random_seed)
    idx_matrix = _sample_index_matrix(
        rng,
        n,
        simulations,
        SamplingMethod.BOOTSTRAP,
        block_size=mc._config.block_size,
    )
    max_h = max(horizons)
    if idx_matrix.shape[1] < max_h:
        idx_matrix = np.resize(idx_matrix, (simulations, max_h))

    for h in horizons:
        label = HORIZON_LABELS.get(h, f"+{h} trading days")
        idx_h = idx_matrix[:, :h]
        sampled = daily_returns[idx_h]
        compounded = np.prod(1.0 + sampled, axis=1) - 1.0

        prices = current_price * (1.0 + compounded)
        p_lo = float(np.percentile(compounded, lower_pct))
        p50 = float(np.percentile(compounded, 50))
        p_hi = float(np.percentile(compounded, upper_pct))
        mean_ret = float(np.mean(compounded))
        out.append(
            HorizonBand(
                trading_days=h,
                label=label,
                supported=True,
                mean_price=float(np.mean(prices)),
                median_price=float(current_price * (1.0 + p50)),
                lower_price=float(current_price * (1.0 + p_lo)),
                upper_price=float(current_price * (1.0 + p_hi)),
                expected_return_pct=mean_ret,
                lower_return_pct=p_lo,
                upper_return_pct=p_hi,
                probability_negative_return=float(np.mean(compounded < 0.0)),
            ),
        )
    return out
