"""Sample-size and distribution warnings. Simulations do not create new evidence."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from app.backtesting.monte_carlo.schemas import MonteCarloConfig, MonteCarloTrade, SamplingMethod


def collect_warnings(
    trades: Sequence[MonteCarloTrade],
    config: MonteCarloConfig,
) -> list[str]:
    n = len(trades)
    warnings: list[str] = []
    if n == 0:
        warnings.append(
            "ZERO_TRADES: no completed historical trades. "
            "Monte Carlo was not run on a trade distribution.",
        )
        return warnings

    if n <= 10:
        warnings.append(
            f"WARNING: Only {n} historical trades are available. "
            f"{config.simulations:,} simulations were generated from these {n} trades. "
            "The simulation count does NOT increase the underlying historical sample size. "
            "Results should be considered exploratory.",
        )
    elif n < 20:
        warnings.append(
            f"LIMITED_SAMPLE: {n} completed trades is a small historical sample. "
            "Treat percentiles as descriptive of this sample, not as future odds.",
        )

    pnls = np.asarray([t.pnl for t in trades], dtype=float)
    if n >= 3:
        skew = _skew(pnls)
        if abs(skew) >= 2.0:
            warnings.append(
                f"SKEWED_PNL: trade P&L skewness is {skew:.2f}. "
                "A small number of outliers can dominate resampled outcomes.",
            )

    positive = pnls[pnls > 0]
    if positive.size and float(positive.max()) >= 0.5 * float(positive.sum()):
        warnings.append(
            "CONCENTRATED_WINS: the largest winning trade is at least 50% of "
            "gross winning P&L. Results depend heavily on a small number of trades.",
        )

    if config.sampling_method is SamplingMethod.TRADE_SHUFFLE and n <= 12:
        unique = math.factorial(n)
        if config.simulations > unique:
            warnings.append(
                f"SHUFFLE_OVERSAMPLE: {n} trades have only {unique} unique orderings, "
                f"but {config.simulations:,} simulations were requested. Extra draws repeat sequences.",
            )

    if config.sampling_method is SamplingMethod.BOOTSTRAP:
        warnings.append(
            "BOOTSTRAP_NOT_FORECAST: bootstrap resamples the observed trade P&L "
            "distribution with replacement. It is not an independent forecast of future trades.",
        )

    warnings.append(
        "ADDITIVE_PNL: simulations apply historical rupee net_profit additively. "
        "They do not re-run position sizing, so path-dependent share counts are not modeled.",
    )
    return warnings


def _skew(values: np.ndarray) -> float:
    if values.size < 3:
        return 0.0
    std = float(values.std(ddof=1))
    if std <= 1e-12:
        return 0.0
    centered = (values - values.mean()) / std
    return float(np.mean(centered ** 3))
