"""Train-only candidate selection. Test data is never passed in."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from app.backtesting.walk_forward.exceptions import WalkForwardLeakageError
from app.backtesting.walk_forward.execution import PeriodRun, run_period, score_train_grid
from app.backtesting.walk_forward.schemas import CandidateMetrics, WalkForwardConfig
from app.backtesting.walk_forward.search import config_key, iter_candidates
from app.strategies.ema_trend import EMATrendConfig

Runner = Callable[..., PeriodRun]


def select_on_train(
    *,
    symbol: str,
    wf_config: WalkForwardConfig,
    train_start: date,
    train_end: date,
    market_data: object,
    features: object,
    initial_capital: float,
    runner: Runner = run_period,
    **runner_kwargs: object,
) -> tuple[EMATrendConfig, CandidateMetrics, int, date]:
    """Evaluate declared candidates on TRAIN only. Deterministic tie-break."""
    candidates = list(
        iter_candidates(
            wf_config.search,
            symbol=symbol,
            min_history_bars=wf_config.min_history_bars,
        ),
    )
    use_grid = (
        runner is run_period
        and runner_kwargs.get("evaluator") is None
        and runner_kwargs.get("strategy_factory") is None
        and len(candidates) > 1
    )
    ranked: list[tuple[float, str, EMATrendConfig, CandidateMetrics, date]] = []
    if use_grid:
        scored = score_train_grid(
            symbol=symbol,
            candidates=candidates,
            wf_config=wf_config,
            start=train_start,
            end=train_end,
            market_data=market_data,
            features=features,
            initial_capital=initial_capital,
            frame_cache=runner_kwargs.get("frame_cache"),  # type: ignore[arg-type]
        )
        for candidate, period in scored:
            if period.used_max > train_end:
                raise WalkForwardLeakageError("training run saw data after train_end")
            ranked.append((-period.metrics.score, period.metrics.config_key, candidate, period.metrics, period.used_max))
    else:
        for candidate in candidates:
            period = runner(
                symbol=symbol,
                strategy_config=candidate,
                wf_config=wf_config,
                start=train_start,
                end=train_end,
                market_data=market_data,
                features=features,
                initial_capital=initial_capital,
                **runner_kwargs,
            )
            if period.used_max > train_end:
                raise WalkForwardLeakageError("training run saw data after train_end")
            ranked.append((-period.metrics.score, period.metrics.config_key, candidate, period.metrics, period.used_max))
    if not ranked:
        fallback = EMATrendConfig.professional(
            symbol=symbol,
            min_history_bars=wf_config.min_history_bars,
        )
        period = runner(
            symbol=symbol,
            strategy_config=fallback,
            wf_config=wf_config,
            start=train_start,
            end=train_end,
            market_data=market_data,
            features=features,
            initial_capital=initial_capital,
            **runner_kwargs,
        )
        return fallback, period.metrics, 1, period.used_max
    ranked.sort()
    _neg, _key, chosen, metrics, used_max = ranked[0]
    return chosen, metrics, len(candidates) or len(ranked), used_max


def select_joint(
    *,
    symbols: Sequence[str],
    wf_config: WalkForwardConfig,
    train_start: date,
    train_end: date,
    market_data: object,
    features: object,
    initial_capital: float,
    runner: Runner = run_period,
    **runner_kwargs: object,
) -> tuple[EMATrendConfig, CandidateMetrics, int, date]:
    """One configuration scored on every symbol's TRAIN window only."""
    names = [s.strip().upper() for s in symbols]
    ranked: list[tuple[float, str, EMATrendConfig, CandidateMetrics, date]] = []
    used_max = train_end
    count = 0
    for candidate in iter_candidates(
        wf_config.search,
        symbol=names[0],
        min_history_bars=wf_config.min_history_bars,
    ):
        count += 1
        score = 0.0
        last: CandidateMetrics | None = None
        for symbol in names:
            period = runner(
                symbol=symbol,
                strategy_config=candidate,
                wf_config=wf_config,
                start=train_start,
                end=train_end,
                market_data=market_data,
                features=features,
                initial_capital=initial_capital,
                **runner_kwargs,
            )
            if period.used_max > train_end:
                raise WalkForwardLeakageError(f"{symbol} training run saw data after train_end")
            used_max = max(used_max, period.used_max) if period.used_max else used_max
            score += period.metrics.score
            last = period.metrics
        assert last is not None
        ranked.append((-score, config_key(candidate), candidate, last, used_max))
    if not ranked:
        raise WalkForwardLeakageError("joint search produced no candidates")
    ranked.sort()
    _neg, _key, chosen, metrics, latest = ranked[0]
    return chosen, metrics, count, latest
