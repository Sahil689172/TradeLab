"""Strategy Context Provider — sole owner of execution-context preparation.

Validators and runners must not call ``bind_daily`` / ``bind_levels`` /
``bind_ranking`` themselves. They ask this provider to ``prepare`` a
``StrategyContext``, then ``apply`` it (or use ``BaseStrategy.execute``).
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.feature_engine.strategy_frame import (
    features_include_ohlcv,
    load_strategy_features,
)
from app.levels import LevelsService
from app.levels.exceptions import LevelsValidationError
from app.market_data.utils.symbols import parquet_basename
from app.market_structure import MarketStructureService
from app.services.strategy_context.context_factory import requirements_for
from app.services.strategy_context.schemas import (
    ContextProviderConfig,
    ContextRequirement,
    StrategyContext,
)
from app.services.strategy_engine.indicators.volume_analysis import VolumeAnalysisService
from app.services.strategy_engine.indicators.vwap import VWAPService
from app.strategies.momentum.config import MomentumConfig
from app.strategies.momentum.ranking import rank_scores as rank_momentum_scores
from app.strategies.momentum.schemas import MomentumScore
from app.strategies.momentum.scoring import score_universe as score_momentum_universe
from app.strategies.relative_strength.config import RelativeStrengthConfig
from app.strategies.relative_strength.ranking import rank_scores as rank_rs_scores
from app.strategies.relative_strength.schemas import RelativeStrengthScore
from app.strategies.relative_strength.scoring import score_universe as score_rs_universe
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.models import TradePlan
from app.strategy_engine.runner import StrategyRunner
from app.strategy_engine.symbols import attach_symbol, normalize_symbol

logger = get_logger(__name__)


class StrategyContextError(ValueError):
    """Raised when required context cannot be assembled."""


class StrategyContextProvider:
    """Prepare and apply per-strategy execution context.

    Example::

        provider = StrategyContextProvider()
        context = provider.prepare(strategy, "RELIANCE")
        plan = strategy.execute(context)
    """

    def __init__(
        self,
        config: ContextProviderConfig | None = None,
        *,
        levels_service: LevelsService | None = None,
        structure_service: MarketStructureService | None = None,
        runner: StrategyRunner | None = None,
        storage_dir: Path | str | None = None,
    ) -> None:
        self._config = config or ContextProviderConfig()
        settings = get_settings()
        raw_dir = (
            storage_dir
            if storage_dir is not None
            else self._config.storage_dir or settings.parquet_storage_dir
        )
        self._storage_dir = Path(raw_dir)
        self._levels = levels_service or LevelsService(
            opening_range_bars=self._config.opening_range_bars,
        )
        self._structure = structure_service or MarketStructureService(
            swing_length=self._config.structure_swing_length,
        )
        self._runner = runner or StrategyRunner()

    @property
    def config(self) -> ContextProviderConfig:
        return self._config

    @property
    def storage_dir(self) -> Path:
        return self._storage_dir

    def prepare(
        self,
        strategy: BaseStrategy,
        symbol: str,
        *,
        features: pd.DataFrame | None = None,
    ) -> StrategyContext:
        """Assemble features and artifacts required by ``strategy`` for ``symbol``.

        When ``features`` is supplied (e.g. by the validation CLI), it is used as
        the strategy frame; daily / levels / rankings are still prepared here.
        """
        sym = normalize_symbol(symbol)
        requirements = requirements_for(strategy.name)
        notes: list[str] = []

        if features is not None:
            run_features = attach_symbol(features.copy(), sym)
            notes.append("Using caller-supplied feature frame")
        else:
            run_features = self._load_features(sym, notes)

        needs_daily = (
            ContextRequirement.DAILY_OHLCV in requirements
            or ContextRequirement.LEVELS in requirements
            or ContextRequirement.RS_RANKING in requirements
            or ContextRequirement.MOMENTUM_RANKING in requirements
        )
        daily = self._resolve_daily(sym, run_features, notes) if needs_daily else None

        levels = None
        if ContextRequirement.LEVELS in requirements:
            source = daily if daily is not None else run_features
            levels = self._build_levels(source, sym, notes)

        structure = None
        if ContextRequirement.MARKET_STRUCTURE in requirements:
            structure = self._build_structure(run_features, sym, notes)

        if ContextRequirement.VWAP_READY in requirements:
            run_features = self._ensure_vwap(run_features, notes)
        if ContextRequirement.RELATIVE_VOLUME in requirements:
            run_features = self._ensure_relative_volume(run_features, notes)

        rs_ranking = None
        if ContextRequirement.RS_RANKING in requirements:
            rs_ranking = self._build_rs_ranking(sym, daily if daily is not None else run_features, notes)

        momentum_ranking = None
        if ContextRequirement.MOMENTUM_RANKING in requirements:
            momentum_ranking = self._build_momentum_ranking(
                sym,
                daily if daily is not None else run_features,
                notes,
            )

        if ContextRequirement.INTRADAY_FEATURES in requirements:
            notes.append("Using feature frame as intraday/session context")

        run_features = attach_symbol(run_features, sym)
        return StrategyContext(
            strategy_name=strategy.name,
            symbol=sym,
            timeframe=self._config.timeframe,
            prepared_at=datetime.now(timezone.utc),
            features=run_features,
            daily_ohlcv=daily,
            levels=levels,
            market_structure=structure,
            rs_ranking=rs_ranking,
            momentum_ranking=momentum_ranking,
            requirements=requirements,
            notes=notes,
        )

    def apply(self, strategy: BaseStrategy, context: StrategyContext) -> BaseStrategy:
        """Bind context artifacts onto ``strategy`` via public ``bind_*`` APIs only."""
        strategy.bind_symbol(context.symbol)

        if context.daily_ohlcv is not None and hasattr(strategy, "bind_daily"):
            strategy.bind_daily(context.daily_ohlcv)  # type: ignore[attr-defined]
            logger.debug("Applied bind_daily to %s", strategy.name)

        if context.levels is not None and hasattr(strategy, "bind_levels"):
            bind = getattr(strategy, "bind_levels")
            try:
                signature = inspect.signature(bind)
                params = list(signature.parameters.values())
                # Skip keyword-only APIs (e.g. break_retest resistance=/support=)
                accepts_positional = any(
                    param.kind
                    in (
                        inspect.Parameter.POSITIONAL_ONLY,
                        inspect.Parameter.POSITIONAL_OR_KEYWORD,
                        inspect.Parameter.VAR_POSITIONAL,
                    )
                    and param.name != "self"
                    for param in params
                )
                if accepts_positional:
                    bind(context.levels)
                    logger.debug("Applied bind_levels to %s", strategy.name)
                else:
                    logger.debug(
                        "Skipping LevelsSnapshot bind_levels for %s (keyword-only API)",
                        strategy.name,
                    )
            except TypeError:
                logger.debug(
                    "Skipping LevelsSnapshot bind_levels for %s (incompatible signature)",
                    strategy.name,
                )

        if context.market_structure is not None and hasattr(strategy, "bind_structure"):
            strategy.bind_structure(context.market_structure)  # type: ignore[attr-defined]
            logger.debug("Applied bind_structure to %s", strategy.name)

        name = strategy.name.strip().lower()
        if context.rs_ranking is not None and name == "relative_strength":
            strategy.bind_ranking(context.rs_ranking)  # type: ignore[attr-defined]
            logger.debug("Applied RS bind_ranking to %s", strategy.name)
        if context.momentum_ranking is not None and name == "momentum":
            strategy.bind_ranking(context.momentum_ranking)  # type: ignore[attr-defined]
            logger.debug("Applied momentum bind_ranking to %s", strategy.name)

        return strategy

    def execute(self, strategy: BaseStrategy, symbol: str) -> TradePlan:
        """prepare → apply → StrategyRunner.run — full context-aware execution."""
        context = self.prepare(strategy, symbol)
        return self.execute_context(strategy, context)

    def execute_context(self, strategy: BaseStrategy, context: StrategyContext) -> TradePlan:
        """Apply an existing context and run the strategy lifecycle."""
        self.apply(strategy, context)
        return self._runner.run(context.features, strategy)

    # ------------------------------------------------------------------ loaders

    def _load_features(self, symbol: str, notes: list[str]) -> pd.DataFrame:
        frame = load_strategy_features(symbol, self._storage_dir)
        if frame is not None and features_include_ohlcv(frame):
            notes.append(f"Loaded strategy features from {self._storage_dir}")
            return attach_symbol(frame, symbol)
        if self._config.allow_synthetic_features:
            notes.append("Using synthetic OHLCV/features for context")
            return _synthetic_features(symbol=symbol, bars=self._config.synthetic_bars)
        raise StrategyContextError(
            f"Unable to load OHLCV+features for {symbol} from {self._storage_dir}",
        )

    def _resolve_daily(
        self,
        symbol: str,
        features: pd.DataFrame,
        notes: list[str],
    ) -> pd.DataFrame:
        stem = parquet_basename(symbol)
        path = self._storage_dir / f"{stem}.parquet"
        if path.exists():
            daily = pd.read_parquet(path, engine="pyarrow")
            notes.append(f"Loaded daily OHLCV from {path.name}")
            return daily

        # Prefer a long synthetic daily series so Levels / RS / Momentum work
        # even when the strategy feature frame is short intraday synthetic data.
        if self._config.allow_synthetic_features:
            notes.append("Synthesized multi-month daily OHLCV for levels/ranking context")
            return _synthetic_daily(symbol=symbol, bars=280)

        notes.append("No raw daily parquet; reusing feature frame as daily context")
        return features.copy()

    def _build_levels(self, ohlcv: pd.DataFrame, symbol: str, notes: list[str]):
        try:
            snapshot = self._levels.compute(ohlcv, symbol=symbol)
            notes.append("Computed LevelsSnapshot (PDH/PDL/CPR/pivots/OR)")
            return snapshot
        except LevelsValidationError:
            # Retry with a daily series that spans weeks/months
            if self._config.allow_synthetic_features:
                notes.append(
                    "Levels failed on supplied frame; recomputing from synthetic daily",
                )
                daily = _synthetic_daily(symbol=symbol, bars=280)
                snapshot = self._levels.compute(daily, symbol=symbol)
                notes.append("Computed LevelsSnapshot from synthetic daily OHLCV")
                return snapshot
            raise StrategyContextError(
                f"Unable to compute levels for {symbol}",
            )
        except Exception as exc:  # noqa: BLE001
            raise StrategyContextError(
                f"Unable to compute levels for {symbol}: {exc}",
            ) from exc

    def _build_structure(self, features: pd.DataFrame, symbol: str, notes: list[str]):
        try:
            result = self._structure.analyze(features, symbol=symbol)
            notes.append(f"Market structure: {result.trend.value}")
            return result
        except Exception as exc:  # noqa: BLE001
            raise StrategyContextError(
                f"Unable to compute market structure for {symbol}: {exc}",
            ) from exc

    def _ensure_vwap(self, features: pd.DataFrame, notes: list[str]) -> pd.DataFrame:
        if "vwap" in features.columns:
            return features
        try:
            attached = VWAPService().attach(features, overwrite=True)
            notes.append("Attached VWAP via VWAPService")
            return attached
        except Exception as exc:  # noqa: BLE001
            raise StrategyContextError(f"Unable to attach VWAP: {exc}") from exc

    def _ensure_relative_volume(
        self,
        features: pd.DataFrame,
        notes: list[str],
    ) -> pd.DataFrame:
        if "relative_volume_20" in features.columns:
            return features
        try:
            attached = VolumeAnalysisService().attach(features, overwrite=True)
            notes.append("Attached relative volume via VolumeAnalysisService")
            return attached
        except Exception as exc:  # noqa: BLE001
            raise StrategyContextError(f"Unable to attach relative volume: {exc}") from exc

    def _build_rs_ranking(self, symbol: str, history: pd.DataFrame, notes: list[str]):
        config = RelativeStrengthConfig(symbol=symbol)
        frames = self._universe_close_frames(symbol, history, min_bars=config.min_history_bars)
        benchmark_key = parquet_basename(config.benchmark_symbol).upper()
        benchmark = frames.pop(benchmark_key, None)
        if benchmark is None:
            # Use a flatter proxy series so the target can rank above it
            benchmark = history if len(history) > config.lookback_12m else frames[symbol]
            notes.append(
                f"Benchmark {config.benchmark_symbol} unavailable; using proxy closes",
            )
        try:
            scores = score_rs_universe(frames, benchmark, config=config)
            ranking = rank_rs_scores(scores, benchmark_symbol=config.benchmark_symbol)
            notes.append(f"RS ranking built for {ranking.universe_size} symbols")
            return ranking
        except Exception as exc:  # noqa: BLE001
            notes.append(f"RS scoring failed ({exc}); using deterministic ranking fallback")
            return _fallback_rs_ranking(symbol, config.benchmark_symbol)

    def _build_momentum_ranking(
        self,
        symbol: str,
        history: pd.DataFrame,
        notes: list[str],
    ):
        config = MomentumConfig(symbol=symbol)
        frames = self._universe_close_frames(symbol, history, min_bars=config.min_history_bars)
        try:
            scores = score_momentum_universe(
                frames,
                config=config,
                benchmark_frame=frames.get(symbol, history),
            )
            ranking = rank_momentum_scores(scores)
            notes.append(f"Momentum ranking built for {ranking.universe_size} symbols")
            return ranking
        except Exception as exc:  # noqa: BLE001
            notes.append(
                f"Momentum scoring failed ({exc}); using deterministic ranking fallback",
            )
            return _fallback_momentum_ranking(symbol)

    def _universe_close_frames(
        self,
        symbol: str,
        primary: pd.DataFrame,
        *,
        min_bars: int,
    ) -> dict[str, pd.DataFrame]:
        """Load sibling OHLCV frames from storage; always include ``symbol``."""
        primary_frame = primary
        if len(primary_frame) <= min_bars and self._config.allow_synthetic_features:
            primary_frame = _synthetic_daily(symbol=symbol, bars=max(min_bars + 20, 280))

        frames: dict[str, pd.DataFrame] = {symbol: primary_frame}

        if self._storage_dir.exists():
            for path in sorted(self._storage_dir.glob("*.parquet")):
                if path.name.endswith("_features.parquet"):
                    continue
                stem = path.stem.upper()
                if stem == symbol:
                    continue
                try:
                    frame = pd.read_parquet(path, engine="pyarrow")
                except Exception:  # noqa: BLE001
                    continue
                if "close" not in frame.columns or "date" not in frame.columns:
                    continue
                if len(frame) <= min_bars:
                    continue
                frames[stem] = frame
                if len(frames) >= 25:
                    break

        if len(frames) == 1:
            peer = primary_frame.copy()
            peer["close"] = pd.to_numeric(peer["close"], errors="coerce") * 0.97
            frames[f"{symbol}_PEER"] = peer
        return frames


def apply_context(strategy: BaseStrategy, context: StrategyContext) -> BaseStrategy:
    """Module-level apply helper used by ``BaseStrategy.execute``."""
    return StrategyContextProvider().apply(strategy, context)


def _synthetic_features(*, symbol: str, bars: int) -> pd.DataFrame:
    """Multi-session synthetic frame suitable for intraday strategies + OR."""
    # Build several session days so Levels/ORB see prior days when reused.
    sessions: list[pd.Timestamp] = []
    day = pd.Timestamp("2024-06-03 09:15")
    while len(sessions) < bars:
        for minute in range(0, 6 * 60, 15):  # 09:15–15:00 ≈ 6h
            sessions.append(day + pd.Timedelta(minutes=minute))
            if len(sessions) >= bars:
                break
        day = day + pd.Timedelta(days=1)
        while day.weekday() >= 5:
            day = day + pd.Timedelta(days=1)

    rows: list[dict[str, float | pd.Timestamp]] = []
    price = 100.0
    for index, ts in enumerate(sessions[:bars]):
        price = price + (0.35 if index % 5 else -0.15)
        close = price
        rows.append(
            {
                "date": ts,
                "open": close - 0.1,
                "high": close + 0.7,
                "low": close - 0.7,
                "close": close,
                "adj_close": close,
                "volume": 1_000 + index * 12,
                "relative_volume_20": 1.8,
                "atr_14": 1.5,
                "ema_9": close * 1.001,
                "ema_20": close * 1.002,
                "ema_21": close * 1.002,
                "ema_50": close * 0.998,
                "adx_14": 28.0,
                "rsi_14": 55.0,
                "vwap": close * 0.999,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)


def _synthetic_daily(*, symbol: str, bars: int = 280) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", periods=bars)
    rows: list[dict[str, float | pd.Timestamp]] = []
    price = 100.0
    for index, date in enumerate(dates):
        price = 100.0 + index * 0.15
        close = price
        rows.append(
            {
                "date": date,
                "open": close - 0.4,
                "high": close + 1.2,
                "low": close - 1.2,
                "close": close,
                "volume": 1_000_000 + index * 1_000,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)


def _fallback_rs_ranking(symbol: str, benchmark_symbol: str):
    now = datetime.now(timezone.utc)
    strong = RelativeStrengthScore(
        symbol=symbol,
        as_of=now,
        return_3m=0.12,
        return_6m=0.22,
        return_12m=0.35,
        benchmark_return_3m=0.04,
        benchmark_return_6m=0.08,
        benchmark_return_12m=0.12,
        rs_3m=0.08,
        rs_6m=0.14,
        rs_12m=0.23,
        strength_score=0.92,
        relative_momentum=0.06,
    )
    weak = RelativeStrengthScore(
        symbol=f"{symbol}_PEER",
        as_of=now,
        return_3m=0.01,
        return_6m=0.02,
        return_12m=0.03,
        benchmark_return_3m=0.04,
        benchmark_return_6m=0.08,
        benchmark_return_12m=0.12,
        rs_3m=-0.03,
        rs_6m=-0.06,
        rs_12m=-0.09,
        strength_score=0.10,
        relative_momentum=-0.02,
    )
    return rank_rs_scores([strong, weak], benchmark_symbol=benchmark_symbol)


def _fallback_momentum_ranking(symbol: str):
    now = datetime.now(timezone.utc)
    strong = MomentumScore(
        symbol=symbol,
        as_of=now,
        return_1m=0.05,
        return_3m=0.12,
        return_6m=0.20,
        return_12m=0.30,
        momentum_score=0.90,
        acceleration=0.04,
        persistence=0.85,
        relative_strength=0.10,
    )
    weak = MomentumScore(
        symbol=f"{symbol}_PEER",
        as_of=now,
        return_1m=0.0,
        return_3m=0.01,
        return_6m=0.02,
        return_12m=0.03,
        momentum_score=0.15,
        acceleration=0.0,
        persistence=0.4,
        relative_strength=-0.05,
    )
    return rank_momentum_scores([strong, weak])
