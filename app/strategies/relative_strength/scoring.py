"""Batch Relative Strength scoring vs a benchmark index (not RSI).

Optimized for NIFTY500-scale universes via an aligned close matrix.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd

from app.strategies.relative_strength.config import RelativeStrengthConfig
from app.strategies.relative_strength.schemas import RelativeStrengthScore


class RelativeStrengthScoringError(ValueError):
    """Invalid inputs for RS scoring."""


def period_return(closes: pd.Series, lookback: int) -> float | None:
    """Simple return over ``lookback`` bars: close[-1]/close[-1-lookback] − 1."""
    if lookback < 1:
        raise RelativeStrengthScoringError("lookback must be >= 1")
    clean = pd.to_numeric(closes, errors="coerce").dropna()
    if len(clean) <= lookback:
        return None
    start = float(clean.iloc[-1 - lookback])
    end = float(clean.iloc[-1])
    if start <= 0 or end <= 0:
        return None
    return end / start - 1.0


def build_close_matrix(
    frames: dict[str, pd.DataFrame],
    *,
    date_column: str = "date",
    close_column: str = "close",
    as_of: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Align symbol closes on a shared date index (columns = symbols)."""
    if not frames:
        raise RelativeStrengthScoringError("frames must not be empty")

    series_map: dict[str, pd.Series] = {}
    for symbol, frame in frames.items():
        if date_column not in frame.columns or close_column not in frame.columns:
            continue
        work = frame[[date_column, close_column]].copy()
        work[date_column] = pd.to_datetime(work[date_column])
        work[close_column] = pd.to_numeric(work[close_column], errors="coerce")
        work = (
            work.dropna()
            .drop_duplicates(subset=[date_column], keep="last")
            .sort_values(date_column)
        )
        if as_of is not None:
            work = work.loc[work[date_column] <= pd.Timestamp(as_of)]
        if work.empty:
            continue
        series_map[symbol.upper()] = work.set_index(date_column)[close_column]

    if not series_map:
        raise RelativeStrengthScoringError("No usable close series in frames")
    matrix = pd.DataFrame(series_map).sort_index()
    return matrix


def batch_period_returns(close_matrix: pd.DataFrame, lookback: int) -> pd.Series:
    """Vectorized period returns for every column at the latest row."""
    if lookback < 1:
        raise RelativeStrengthScoringError("lookback must be >= 1")
    if len(close_matrix) <= lookback:
        return pd.Series(dtype="float64")
    start = close_matrix.iloc[-1 - lookback]
    end = close_matrix.iloc[-1]
    returns = end / start.replace(0.0, pd.NA) - 1.0
    return returns.astype("float64")


def score_universe(
    frames: dict[str, pd.DataFrame],
    benchmark_frame: pd.DataFrame,
    *,
    config: RelativeStrengthConfig,
    sector_by_symbol: dict[str, str] | None = None,
    as_of: pd.Timestamp | datetime | None = None,
) -> list[RelativeStrengthScore]:
    """Score every symbol vs the benchmark in one batch pass."""
    as_of_ts = pd.Timestamp(as_of) if as_of is not None else None
    stock_matrix = build_close_matrix(
        frames,
        date_column=config.date_column,
        close_column=config.close_column,
        as_of=as_of_ts,
    )
    bench_matrix = build_close_matrix(
        {config.benchmark_symbol: benchmark_frame},
        date_column=config.date_column,
        close_column=config.close_column,
        as_of=as_of_ts,
    )
    if config.benchmark_symbol.upper() not in bench_matrix.columns:
        # basename may differ
        bench_col = bench_matrix.columns[0]
    else:
        bench_col = config.benchmark_symbol.upper()

    bench_closes = bench_matrix[bench_col]
    # Align stocks to benchmark dates (inner join on index)
    aligned = stock_matrix.join(bench_closes.rename("__BENCH__"), how="inner")
    if aligned.empty or len(aligned) <= config.lookback_12m:
        raise RelativeStrengthScoringError(
            f"Need more than {config.lookback_12m} aligned bars for RS scoring",
        )

    bench_series = aligned["__BENCH__"]
    stock_only = aligned.drop(columns=["__BENCH__"])

    ret_3 = batch_period_returns(stock_only, config.lookback_3m)
    ret_6 = batch_period_returns(stock_only, config.lookback_6m)
    ret_12 = batch_period_returns(stock_only, config.lookback_12m)
    b3 = period_return(bench_series, config.lookback_3m)
    b6 = period_return(bench_series, config.lookback_6m)
    b12 = period_return(bench_series, config.lookback_12m)
    if b3 is None or b6 is None or b12 is None:
        raise RelativeStrengthScoringError("Insufficient benchmark history for RS windows")

    as_of_dt = pd.Timestamp(aligned.index[-1]).to_pydatetime()
    sectors = {key.upper(): value for key, value in (sector_by_symbol or {}).items()}

    # First pass: compute raw RS per symbol
    raw: list[dict[str, object]] = []
    for symbol in stock_only.columns:
        r3 = ret_3.get(symbol)
        r6 = ret_6.get(symbol)
        r12 = ret_12.get(symbol)
        if pd.isna(r3) or pd.isna(r6) or pd.isna(r12):
            continue
        rs3 = float(r3) - b3
        rs6 = float(r6) - b6
        rs12 = float(r12) - b12
        strength = (
            config.weight_3m * rs3
            + config.weight_6m * rs6
            + config.weight_12m * rs12
        ) / config.weight_total
        momentum = rs3 - rs6  # near-term acceleration vs medium window
        raw.append(
            {
                "symbol": symbol,
                "return_3m": float(r3),
                "return_6m": float(r6),
                "return_12m": float(r12),
                "rs_3m": rs3,
                "rs_6m": rs6,
                "rs_12m": rs12,
                "strength_score": strength,
                "relative_momentum": momentum,
                "sector": sectors.get(symbol),
            },
        )

    if not raw:
        return []

    # Sector strength = mean strength_score of peers
    sector_means: dict[str, float] = {}
    by_sector: dict[str, list[float]] = {}
    for row in raw:
        sector = row["sector"]
        if not isinstance(sector, str) or not sector:
            continue
        by_sector.setdefault(sector, []).append(float(row["strength_score"]))  # type: ignore[arg-type]
    for sector, values in by_sector.items():
        sector_means[sector] = sum(values) / len(values)

    scores: list[RelativeStrengthScore] = []
    for row in raw:
        sector = row["sector"] if isinstance(row["sector"], str) else None
        scores.append(
            RelativeStrengthScore(
                symbol=str(row["symbol"]),
                as_of=as_of_dt,
                return_3m=float(row["return_3m"]),  # type: ignore[arg-type]
                return_6m=float(row["return_6m"]),  # type: ignore[arg-type]
                return_12m=float(row["return_12m"]),  # type: ignore[arg-type]
                benchmark_return_3m=b3,
                benchmark_return_6m=b6,
                benchmark_return_12m=b12,
                rs_3m=float(row["rs_3m"]),  # type: ignore[arg-type]
                rs_6m=float(row["rs_6m"]),  # type: ignore[arg-type]
                rs_12m=float(row["rs_12m"]),  # type: ignore[arg-type]
                strength_score=float(row["strength_score"]),  # type: ignore[arg-type]
                relative_momentum=float(row["relative_momentum"]),  # type: ignore[arg-type]
                sector=sector,
                sector_strength=sector_means.get(sector) if sector else None,
            ),
        )
    return scores


def score_symbol(
    frame: pd.DataFrame,
    benchmark_frame: pd.DataFrame,
    *,
    symbol: str,
    config: RelativeStrengthConfig,
    sector: str | None = None,
    sector_strength: float | None = None,
    as_of: pd.Timestamp | datetime | None = None,
) -> RelativeStrengthScore:
    """Score a single symbol (thin wrapper over batch scoring)."""
    scores = score_universe(
        {symbol: frame},
        benchmark_frame,
        config=config,
        sector_by_symbol={symbol: sector} if sector else None,
        as_of=as_of,
    )
    if not scores:
        raise RelativeStrengthScoringError(f"Unable to score symbol '{symbol}'")
    scored = scores[0]
    if sector_strength is not None:
        return scored.model_copy(update={"sector_strength": sector_strength})
    return scored
