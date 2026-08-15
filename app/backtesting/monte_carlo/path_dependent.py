"""Future A5.x path-dependent Monte Carlo (not implemented).

Intended pipeline (do not wire yet):

    Strategy → Signal → Order Execution → Position Manager → Portfolio → Equity
"""

from __future__ import annotations

from collections.abc import Sequence

from app.backtesting.monte_carlo.exceptions import PathDependentNotImplementedError
from app.backtesting.monte_carlo.schemas import MonteCarloConfig, MonteCarloResult


class PathDependentMonteCarlo:
    """Extension point only. Full market-path Monte Carlo is a later phase."""

    def __init__(self, config: MonteCarloConfig | None = None) -> None:
        self._config = config or MonteCarloConfig()

    @property
    def config(self) -> MonteCarloConfig:
        return self._config

    def run(self, sources: Sequence[object] | None = None, **kwargs: object) -> MonteCarloResult:
        raise PathDependentNotImplementedError(
            "PathDependentMonteCarlo is an A5.x extension point. "
            "A5.6 implements TradeResamplingMonteCarlo only: it resamples completed "
            "historical trades and does not re-run strategy, execution, or position management.",
        )
