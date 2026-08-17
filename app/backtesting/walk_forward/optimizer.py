"""Train-only candidate selection. Test data is never passed in."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date

from app.backtesting.walk_forward.exceptions import WalkForwardLeakageError
from app.backtesting.walk_forward.execution import PeriodRun, run_period, score_train_grid
from app.backtesting.walk_forward.schemas import (
    CandidateMetrics,
    SelectionEligibility,
    TrainSelectionDiagnostic,
    WalkForwardConfig,
)
from app.backtesting.walk_forward.search import config_key, iter_candidates
from app.strategies.ema_trend import EMATrendConfig

Runner = Callable[..., PeriodRun]
RankRow = tuple[float, str, EMATrendConfig, CandidateMetrics, date]


def _pick_candidate(
    ranked: list[RankRow],
    *,
    minimum_training_trades: int,
) -> tuple[EMATrendConfig, CandidateMetrics, date, TrainSelectionDiagnostic]:
    evaluated = len(ranked)
    zero_trade = sum(1 for row in ranked if row[3].trade_count == 0)
    eligible = [row for row in ranked if row[3].trade_count >= minimum_training_trades]
    ineligible = evaluated - len(eligible)
    pool = eligible if eligible else ranked
    if eligible:
        eligibility = SelectionEligibility.ELIGIBLE
        note = (
            f"{len(eligible)}/{evaluated} candidate(s) met "
            f"minimum_training_trades>={minimum_training_trades}."
        )
        fallback_count = 0
    else:
        eligibility = SelectionEligibility.FALLBACK_INELIGIBLE
        fallback_count = ineligible
        note = (
            f"No candidate met minimum_training_trades>={minimum_training_trades}; "
            f"selected best score among {evaluated} ineligible candidate(s) "
            "(diagnostic only — minimum NOT satisfied)."
        )
    pool = sorted(pool)
    _neg, _key, chosen, metrics, used_max = pool[0]
    diagnostic = TrainSelectionDiagnostic(
        minimum_training_trades=minimum_training_trades,
        candidates_evaluated=evaluated,
        eligible_count=len(eligible),
        ineligible_count=ineligible,
        zero_trade_candidates=zero_trade,
        selected_training_trade_count=metrics.trade_count,
        fallback_count=fallback_count,
        selected_eligibility=eligibility,
        note=note,
    )
    return chosen, metrics, used_max, diagnostic


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
) -> tuple[EMATrendConfig, CandidateMetrics, int, date, TrainSelectionDiagnostic]:
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
    ranked: list[RankRow] = []
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
            ranked.append(
                (-period.metrics.score, period.metrics.config_key, candidate, period.metrics, period.used_max),
            )
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
            ranked.append(
                (-period.metrics.score, period.metrics.config_key, candidate, period.metrics, period.used_max),
            )
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
        meets = period.metrics.trade_count >= wf_config.minimum_training_trades
        diagnostic = TrainSelectionDiagnostic(
            minimum_training_trades=wf_config.minimum_training_trades,
            candidates_evaluated=1,
            eligible_count=1 if meets else 0,
            ineligible_count=0 if meets else 1,
            zero_trade_candidates=1 if period.metrics.trade_count == 0 else 0,
            selected_training_trade_count=period.metrics.trade_count,
            fallback_count=0 if meets else 1,
            selected_eligibility=(
                SelectionEligibility.ELIGIBLE if meets else SelectionEligibility.FALLBACK_INELIGIBLE
            ),
            note=(
                "fallback single candidate"
                if meets
                else (
                    f"No candidate met minimum_training_trades>={wf_config.minimum_training_trades}; "
                    "fallback single candidate selected (diagnostic only — minimum NOT satisfied)."
                )
            ),
        )
        return fallback, period.metrics, 1, period.used_max, diagnostic
    chosen, metrics, used_max, diagnostic = _pick_candidate(
        ranked,
        minimum_training_trades=wf_config.minimum_training_trades,
    )
    return chosen, metrics, len(candidates) or len(ranked), used_max, diagnostic


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
) -> tuple[EMATrendConfig, CandidateMetrics, int, date, TrainSelectionDiagnostic]:
    """One configuration scored on every symbol's TRAIN window only."""
    names = [s.strip().upper() for s in symbols]
    ranked: list[tuple[float, str, EMATrendConfig, CandidateMetrics, date, int]] = []
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
        total_trades = 0
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
            total_trades += period.metrics.trade_count
            last = period.metrics
        assert last is not None
        joint_metrics = last.model_copy(update={"trade_count": total_trades, "config_key": config_key(candidate)})
        ranked.append((-score, config_key(candidate), candidate, joint_metrics, used_max, total_trades))
    if not ranked:
        raise WalkForwardLeakageError("joint search produced no candidates")
    rows: list[RankRow] = [(a, b, c, d, e) for a, b, c, d, e, _ in ranked]
    chosen, metrics, latest, diagnostic = _pick_candidate(
        rows,
        minimum_training_trades=wf_config.minimum_training_trades,
    )
    return chosen, metrics, count, latest, diagnostic
