"""Sample-size and distribution warnings. Simulations do not create new evidence."""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from app.backtesting.monte_carlo.schemas import (
    PATH_DEPENDENT_LIMITATION,
    RESAMPLING_LIMITATION,
    CapitalMode,
    MonteCarloConfig,
    MonteCarloTrade,
    MonteCarloVerdict,
    SampleQuality,
    SamplingMethod,
)


def collect_warnings(
    trades: Sequence[MonteCarloTrade],
    config: MonteCarloConfig,
    *,
    capital_mode: CapitalMode,
    sample_quality: SampleQuality,
    verdict: MonteCarloVerdict,
) -> list[str]:
    n = len(trades)
    warnings: list[str] = []
    if n == 0:
        warnings.append(
            "ZERO_TRADES: no completed historical trades. "
            "Monte Carlo was not run on a trade distribution.",
        )
        warnings.append(
            f"SAMPLE_QUALITY={sample_quality.value}; VERDICT={verdict.value} "
            f"(historical_trade_count=0, simulation_count={config.simulations}).",
        )
        if capital_mode is CapitalMode.PATH_DEPENDENT_EQUITY:
            warnings.append(PATH_DEPENDENT_LIMITATION)
        else:
            warnings.append(RESAMPLING_LIMITATION)
        return warnings

    warnings.append(
        f"{config.simulations:,} simulations generated from {n} historical trades. "
        "The simulation count does NOT increase the underlying historical sample size "
        "and must not be presented as independent observations.",
    )
    warnings.append(
        f"SAMPLE_QUALITY={sample_quality.value}; VERDICT={verdict.value} "
        f"(historical_trade_count={n}, simulation_count={config.simulations}). "
        "These labels are reporting quality, not statistical significance.",
    )

    if n <= 10:
        warnings.append(
            f"WARNING: Only {n} historical trades are available. "
            f"{config.simulations:,} simulations were generated from these {n} trades. "
            "The simulation count does NOT increase the underlying historical sample size. "
            "Results should be considered exploratory. "
            "Do not claim statistical significance or call the strategy robust.",
        )
    elif n < 20:
        warnings.append(
            f"LIMITED_SAMPLE: {n} completed trades is a small historical sample. "
            "Treat percentiles as descriptive of this sample, not as future odds.",
        )

    if verdict is MonteCarloVerdict.INSUFFICIENT_EVIDENCE:
        warnings.append(
            "INSUFFICIENT_EVIDENCE: the historical trade count is too small for a "
            "robustness claim, regardless of how favorable the simulated distribution looks.",
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
            "BOOTSTRAP_NOT_FORECAST: bootstrap resamples observed completed trades "
            "independently with replacement, preserving trade count per simulation. "
            "It assumes historical trades are representative. It is not an independent "
            "forecast of future trades.",
        )

    if config.sampling_method is SamplingMethod.BLOCK_BOOTSTRAP:
        warnings.append(
            f"BLOCK_BOOTSTRAP: overlapping circular blocks of size {config.block_size} "
            "are sampled with replacement to preserve short serial dependence. "
            "This is still resampling of historical evidence, not a market-path model.",
        )

    if capital_mode is CapitalMode.ADDITIVE_PNL:
        warnings.append(
            "CAPITAL_MODE=ADDITIVE_PNL: equity[t] = equity[t-1] + trade_net_profit[t]. "
            "This does not re-run position sizing, so path-dependent share counts are not modeled.",
        )
        warnings.append(RESAMPLING_LIMITATION)
    elif capital_mode is CapitalMode.RETURN_BASED:
        warnings.append(
            "CAPITAL_MODE=RETURN_BASED: equity[t] = equity[t-1] * (1 + return[t]). "
            "This is not interchangeable with ADDITIVE_PNL.",
        )
        warnings.append(RESAMPLING_LIMITATION)
    else:
        warnings.append(
            "CAPITAL_MODE=PATH_DEPENDENT_EQUITY: each trade is sized from current cash "
            "using A5.2 percent-of-capital / fixed-amount rules, then filled with A5.2 "
            "slippage and brokerage. Historical rupee net_profit is not added.",
        )
        warnings.append(PATH_DEPENDENT_LIMITATION)
    return warnings


def _skew(values: np.ndarray) -> float:
    if values.size < 3:
        return 0.0
    std = float(values.std(ddof=1))
    if std <= 1e-12:
        return 0.0
    centered = (values - values.mean()) / std
    return float(np.mean(centered ** 3))
