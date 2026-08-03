"""Instrumented validation profiler — measure only, no business-logic changes."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

import pandas as pd

from app.core.config import get_settings
from app.core.logging import get_logger
from app.feature_engine.strategy_frame import (
    features_include_ohlcv,
    merge_ohlcv_features,
)
from app.market_data.utils.symbols import parquet_basename
from app.services.profiling.schemas import (
    HotspotEntry,
    PerformanceProfileReport,
    RuntimeEstimate,
    StockTimingBreakdown,
    TimingStats,
)
from app.services.profiling.progress import ProgressReporter
from app.services.profiling.timers import ResourceMonitor, TimingCollector, TimingRecord
from app.services.strategy_context import (
    ContextProviderConfig,
    StrategyContext,
    StrategyContextError,
    StrategyContextProvider,
)
from app.services.strategy_context.context_cache import ContextRunCache
from app.services.strategy_context.context_factory import requirements_for
from app.services.strategy_context.schemas import ContextRequirement
from app.services.trade_recommendation.engine import TradeRecommendationEngine
from app.services.trade_recommendation.schemas import RecommendationConfig
from app.services.trade_recommendation.strategy_validation import (
    StrategyValidationFramework,
)
from app.services.trade_recommendation.trade_recommendation import (
    build_trade_recommendation,
    enrich_from_detailed_plan,
)
from app.services.trade_recommendation.validator import (
    TradeRecommendationValidationError,
)
from app.services.universe_validation.config import UniverseValidationConfig
from app.services.universe_validation.discovery import resolve_universe_symbols
from app.strategy_engine.base import BaseStrategy
from app.strategy_engine.exceptions import StrategyEngineError, StrategyValidationError
from app.strategy_engine.runner import StrategyRunner
from app.strategy_engine.symbols import attach_symbol

logger = get_logger(__name__)

# Nested timers that duplicate child samples — exclude from hotspot totals.
_NESTED_CONTEXT_NAMES = frozenset({"prepare_total"})
_NESTED_RECOMMENDATION_NAMES = frozenset({"total"})


class ProfilingContextProvider(StrategyContextProvider):
    """Context provider that records stage timings without changing assemble logic."""

    def __init__(
        self,
        collector: TimingCollector,
        config: ContextProviderConfig | None = None,
        *,
        storage_dir: Path | str | None = None,
        runner: StrategyRunner | None = None,
        run_cache: object | None = None,
    ) -> None:
        super().__init__(
            config,
            storage_dir=storage_dir,
            runner=runner,
            run_cache=run_cache,  # type: ignore[arg-type]
        )
        self._collector = collector

    def prepare(
        self,
        strategy: BaseStrategy,
        symbol: str,
        *,
        features: pd.DataFrame | None = None,
    ) -> StrategyContext:
        from app.strategy_engine.symbols import normalize_symbol

        sym = normalize_symbol(symbol)
        requirements = requirements_for(strategy.name)
        notes: list[str] = []

        with self._collector.measure(
            "context",
            "sanitize_indicators",
            symbol=sym,
            strategy=strategy.name,
        ):
            run_features = self._prepare_base_features(sym, features, notes)

        needs_daily = (
            ContextRequirement.DAILY_OHLCV in requirements
            or ContextRequirement.LEVELS in requirements
            or ContextRequirement.RS_RANKING in requirements
            or ContextRequirement.MOMENTUM_RANKING in requirements
            or ContextRequirement.INTRADAY_FEATURES in requirements
        )
        daily = None
        if needs_daily:
            with self._collector.measure(
                "context",
                "daily",
                symbol=sym,
                strategy=strategy.name,
            ):
                daily = self._prepare_daily(sym, run_features, notes)

        if ContextRequirement.INTRADAY_FEATURES in requirements:
            with self._collector.measure(
                "context",
                "session",
                symbol=sym,
                strategy=strategy.name,
            ):
                run_features = self._prepare_session_features(
                    run_features,
                    daily=daily,
                    symbol=sym,
                    notes=notes,
                )

        levels = None
        if ContextRequirement.LEVELS in requirements:
            source = daily if daily is not None else run_features
            with self._collector.measure(
                "context",
                "cpr_levels",
                symbol=sym,
                strategy=strategy.name,
            ):
                levels = self._prepare_levels(source, sym, notes)

        structure = None
        if ContextRequirement.MARKET_STRUCTURE in requirements:
            with self._collector.measure(
                "context",
                "market_structure",
                symbol=sym,
                strategy=strategy.name,
            ):
                structure = self._prepare_structure(run_features, sym, notes)

        if ContextRequirement.VWAP_READY in requirements:
            with self._collector.measure(
                "context",
                "vwap",
                symbol=sym,
                strategy=strategy.name,
            ):
                run_features = self._prepare_vwap(sym, run_features, notes)
        if ContextRequirement.RELATIVE_VOLUME in requirements:
            with self._collector.measure(
                "context",
                "relative_volume",
                symbol=sym,
                strategy=strategy.name,
            ):
                run_features = self._prepare_relative_volume(sym, run_features, notes)

        rs_ranking = None
        if ContextRequirement.RS_RANKING in requirements:
            with self._collector.measure(
                "context",
                "ranking_rs",
                symbol=sym,
                strategy=strategy.name,
            ):
                rs_ranking = self._prepare_rs_ranking(
                    sym,
                    daily if daily is not None else run_features,
                    notes,
                )

        momentum_ranking = None
        if ContextRequirement.MOMENTUM_RANKING in requirements:
            with self._collector.measure(
                "context",
                "ranking_momentum",
                symbol=sym,
                strategy=strategy.name,
            ):
                momentum_ranking = self._prepare_momentum_ranking(
                    sym,
                    daily if daily is not None else run_features,
                    notes,
                )

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


class ProfilingRecommendationEngine(TradeRecommendationEngine):
    """Recommendation engine that times construction vs validation stages."""

    def __init__(
        self,
        collector: TimingCollector,
        config: RecommendationConfig | None = None,
        *,
        symbol: str | None = None,
        strategy: str | None = None,
    ) -> None:
        super().__init__(config=config)
        self._collector = collector
        self._symbol = symbol
        self._strategy = strategy

    def recommend(self, plan, **kwargs):  # type: ignore[no-untyped-def, override]
        detailed_plan = kwargs.get("detailed_plan")
        timeframe = kwargs.get("timeframe")
        timestamp = kwargs.get("timestamp")
        trend_direction = kwargs.get("trend_direction")
        market_structure = kwargs.get("market_structure")
        indicators_used = kwargs.get("indicators_used")
        warnings = kwargs.get("warnings")
        holding_note = kwargs.get("holding_note", "")
        volume_score = float(kwargs.get("volume_score", 50.0))
        confluence_score = float(kwargs.get("confluence_score", 50.0))
        recompute_confidence = bool(kwargs.get("recompute_confidence", True))
        strategy_label = self._strategy or plan.strategy_name

        with self._collector.measure(
            "recommendation",
            "construction",
            symbol=self._symbol,
            strategy=strategy_label,
        ):
            if detailed_plan is not None:
                recommendation = enrich_from_detailed_plan(
                    plan,
                    detailed_plan,
                    timeframe=timeframe,
                    config=self._config,
                )
                updates: dict[str, object] = {}
                if trend_direction is not None:
                    updates["trend_direction"] = trend_direction
                if market_structure is not None:
                    updates["market_structure"] = market_structure
                if indicators_used is not None:
                    updates["indicators_used"] = indicators_used
                if warnings is not None:
                    updates["warnings"] = warnings
                if holding_note:
                    updates["holding_note"] = holding_note
                if timestamp is not None:
                    updates["timestamp"] = timestamp
                if updates:
                    recommendation = recommendation.model_copy(update=updates)
            else:
                recommendation = build_trade_recommendation(
                    plan,
                    timeframe=timeframe,
                    timestamp=timestamp,
                    trend_direction=trend_direction,
                    market_structure=market_structure,
                    indicators_used=indicators_used,
                    warnings=warnings,
                    holding_note=holding_note or "",
                    config=self._config,
                )

            if recompute_confidence:
                breakdown = self.score_confidence(
                    recommendation,
                    volume_score=volume_score,
                    confluence_score=confluence_score,
                )
                recommendation = recommendation.model_copy(
                    update={"confidence": breakdown.total},
                )

        with self._collector.measure(
            "recommendation",
            "validation",
            symbol=self._symbol,
            strategy=strategy_label,
        ):
            return self._validator.validate(recommendation)


class ValidationProfiler:
    """Run universe validation under timers and build a performance report.

    Does not alter strategy math, validation rules, or recommendation contracts.
    """

    def __init__(
        self,
        config: UniverseValidationConfig | None = None,
        *,
        progress: ProgressReporter | None = None,
        show_progress: bool = True,
    ) -> None:
        settings = get_settings()
        self._config = config or UniverseValidationConfig()
        storage = self._config.storage_dir or Path(settings.parquet_storage_dir)
        output = self._config.output_dir or Path(settings.log_directory)
        self._storage_dir = Path(storage)
        self._output_dir = Path(output)
        self._collector = TimingCollector()
        self._resources = ResourceMonitor()
        self._run_cache = ContextRunCache()
        self._progress = progress
        self._show_progress = show_progress

    @property
    def collector(self) -> TimingCollector:
        return self._collector

    @property
    def output_dir(self) -> Path:
        return self._output_dir

    def profile(
        self,
        *,
        symbols: list[str] | None = None,
        strategy_names: list[str] | None = None,
    ) -> PerformanceProfileReport:
        """Execute an instrumented validation pass and return the profile."""
        self._collector.clear()
        self._run_cache.clear()
        self._resources.start()
        notes: list[str] = [
            "Measurement only — architectural caches enabled when configured.",
            "Section totals are summed timings; with workers>1 they can exceed wall time.",
            "Use --workers 1 for additive section totals closest to wall clock.",
        ]

        with self._collector.measure("discovery", "universe_discovery"):
            resolved = resolve_universe_symbols(
                self._storage_dir,
                symbols=symbols,
                limit=self._config.limit,
            )

        framework = StrategyValidationFramework(timeframe=self._config.timeframe)
        strategies = framework.resolve_strategies(strategy_names)
        strategy_order = [strategy.name for strategy in strategies]

        if not resolved:
            resources = self._resources.stop()
            return self._build_report(
                symbols=[],
                strategies=strategy_order,
                resources=resources,
                discovery_ms=0.0,
                notes=notes + ["No symbols discovered."],
            )

        logger.info(
            "Profiling validation: %d symbols × %d strategies (workers=%d)",
            len(resolved),
            len(strategy_order),
            self._config.workers,
        )

        progress = self._progress
        if progress is None and self._show_progress:
            progress = ProgressReporter(len(resolved), label="Profiling")
            progress.start()

        workers = min(self._config.workers, max(1, len(resolved)))
        if workers == 1 or len(resolved) == 1:
            for symbol in resolved:
                self._profile_symbol(symbol, strategy_names=strategy_names or ["all"])
                if progress is not None:
                    progress.tick(symbol)
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        self._profile_symbol,
                        symbol,
                        strategy_names=strategy_names or ["all"],
                    ): symbol
                    for symbol in resolved
                }
                for future in as_completed(futures):
                    symbol = futures[future]
                    future.result()
                    if progress is not None:
                        progress.tick(symbol)

        # Aggregation is unused on the per-cell validation path; record placeholder.
        self._collector.record("recommendation", "aggregation", 0.0)

        resources = self._resources.stop()
        discovery_ms = _sum_category_name(
            self._collector.snapshot(),
            "discovery",
            "universe_discovery",
        )
        return self._build_report(
            symbols=resolved,
            strategies=strategy_order,
            resources=resources,
            discovery_ms=discovery_ms,
            notes=notes,
        )

    def _profile_symbol(self, symbol: str, *, strategy_names: list[str]) -> None:
        collector = self._collector
        frame, _error = self._timed_load(symbol)

        provider = ProfilingContextProvider(
            collector,
            ContextProviderConfig(
                timeframe=self._config.timeframe,
                storage_dir=str(self._storage_dir),
                allow_synthetic_features=self._config.allow_synthetic,
                enable_context_cache=True,
            ),
            storage_dir=self._storage_dir,
            runner=StrategyRunner(),
            run_cache=self._run_cache,
        )
        engine = ProfilingRecommendationEngine(
            collector,
            RecommendationConfig(),
            symbol=symbol,
        )
        framework = StrategyValidationFramework(
            timeframe=self._config.timeframe,
            context_provider=provider,
            engine=engine,
            runner=StrategyRunner(),
        )
        strategies = framework.resolve_strategies(strategy_names)

        if frame is None:
            return

        for strategy in strategies:
            engine._symbol = symbol  # noqa: SLF001 — per-strategy labels
            engine._strategy = strategy.name  # noqa: SLF001
            self._profile_strategy_cell(framework, strategy, frame, symbol=symbol)

    def _profile_strategy_cell(
        self,
        framework: StrategyValidationFramework,
        strategy: BaseStrategy,
        features: pd.DataFrame,
        *,
        symbol: str,
    ) -> None:
        collector = self._collector
        try:
            context = framework._context_provider.prepare(  # noqa: SLF001
                strategy,
                symbol,
                features=features,
            )
            with collector.measure(
                "strategy_execution",
                strategy.name,
                symbol=symbol,
                strategy=strategy.name,
            ):
                plan = framework._context_provider.execute_context(  # noqa: SLF001
                    strategy,
                    context,
                )

            detailed = getattr(strategy, "last_detailed_plan", None)
            framework._engine.recommend(  # noqa: SLF001
                plan,
                timeframe=framework._timeframe,  # noqa: SLF001
                detailed_plan=detailed,
                recompute_confidence=True,
            )
        except (
            StrategyContextError,
            StrategyValidationError,
            StrategyEngineError,
            TradeRecommendationValidationError,
            ValueError,
            TypeError,
            Exception,  # noqa: BLE001 — profiling must continue across cell failures
        ):
            logger.debug(
                "Profiled cell failed for %s / %s",
                symbol,
                strategy.name,
                exc_info=True,
            )

    def _timed_load(self, symbol: str) -> tuple[pd.DataFrame | None, str | None]:
        root = self._storage_dir
        stem = parquet_basename(symbol)
        features_path = root / f"{stem}_features.parquet"
        ohlcv_path = root / f"{stem}.parquet"

        features: pd.DataFrame | None = None
        ohlcv: pd.DataFrame | None = None

        with self._collector.measure("parquet_load", "ohlcv", symbol=symbol):
            if ohlcv_path.exists():
                ohlcv = pd.read_parquet(ohlcv_path, engine="pyarrow")

        with self._collector.measure("parquet_load", "features", symbol=symbol):
            if features_path.exists():
                features = pd.read_parquet(features_path, engine="pyarrow")

        if features is None and ohlcv is None:
            if self._config.allow_synthetic:
                from app.services.universe_validation.loaders import (
                    synthetic_session_features,
                )

                return synthetic_session_features(symbol=symbol), None
            return None, f"{symbol}: no OHLCV parquet in {root}"

        if features is not None and features_include_ohlcv(features):
            return attach_symbol(features, symbol), None
        if features is not None and ohlcv is not None:
            return attach_symbol(merge_ohlcv_features(ohlcv, features), symbol), None
        if ohlcv is not None:
            return attach_symbol(ohlcv, symbol), None
        return None, (
            f"{symbol}: feature file missing OHLCV and no mergeable "
            f"{symbol}.parquet found"
        )

    def _build_report(
        self,
        *,
        symbols: list[str],
        strategies: list[str],
        resources: object,
        discovery_ms: float,
        notes: list[str],
    ) -> PerformanceProfileReport:
        records = self._collector.snapshot()
        measured_total = _non_nested_total(records) or 1.0

        parquet_stats = [
            _stats_for(
                records,
                category="parquet_load",
                name=name,
                measured_total=measured_total,
            )
            for name in ("ohlcv", "features")
        ]
        context_names = sorted(
            {
                r.name
                for r in records
                if r.category == "context" and r.name not in _NESTED_CONTEXT_NAMES
            },
        )
        context_stats = [
            _stats_for(
                records,
                category="context",
                name=name,
                measured_total=measured_total,
            )
            for name in context_names
        ]
        strategy_stats = [
            _stats_for(
                records,
                category="strategy_execution",
                name=name,
                measured_total=measured_total,
            )
            for name in strategies
        ]
        recommendation_names = sorted(
            {
                r.name
                for r in records
                if r.category == "recommendation"
                and r.name not in _NESTED_RECOMMENDATION_NAMES
            },
        )
        recommendation_stats = [
            _stats_for(
                records,
                category="recommendation",
                name=name,
                measured_total=measured_total,
            )
            for name in recommendation_names
        ]

        stock_breakdowns = _stock_breakdowns(
            records,
            symbols=symbols,
            strategies=strategies,
        )
        hotspots = _hotspots(records, measured_total=measured_total, limit=15)
        top_slowest = hotspots[:10]
        top_fastest = _fastest(records, limit=10)

        avg_stock = (
            mean([row.total_ms for row in stock_breakdowns]) if stock_breakdowns else 0.0
        )
        strategy_avgs = [row.average_ms for row in strategy_stats if row.count > 0]
        avg_strategy = mean(strategy_avgs) if strategy_avgs else 0.0

        estimates = [
            RuntimeEstimate(
                stocks=n,
                estimated_wall_ms=avg_stock * n,
                estimated_wall_minutes=(avg_stock * n) / 60_000.0,
            )
            for n in (100, 449, 1000)
        ]

        return PerformanceProfileReport(
            generated_at=datetime.now(timezone.utc),
            storage_dir=str(self._storage_dir),
            workers=self._config.workers,
            symbols=list(symbols),
            strategies=list(strategies),
            wall_time_ms=float(getattr(resources, "wall_ms", 0.0)),
            cpu_time_ms=float(getattr(resources, "cpu_ms", 0.0)),
            memory_current_bytes=int(getattr(resources, "memory_current_bytes", 0)),
            memory_peak_bytes=int(getattr(resources, "memory_peak_bytes", 0)),
            discovery_ms=discovery_ms,
            report_generation_ms=0.0,
            parquet_stats=parquet_stats,
            context_stats=context_stats,
            strategy_stats=strategy_stats,
            recommendation_stats=recommendation_stats,
            report_stats=[],
            stock_breakdowns=stock_breakdowns,
            hotspots=hotspots,
            top_slowest=top_slowest,
            top_fastest=top_fastest,
            average_stock_ms=avg_stock,
            average_strategy_ms=avg_strategy,
            runtime_estimates=estimates,
            notes=notes,
        )


def _sum_category_name(records: list[TimingRecord], category: str, name: str) -> float:
    return sum(
        record.elapsed_ms
        for record in records
        if record.category == category and record.name == name
    )


def _is_nested(record: TimingRecord) -> bool:
    if record.category == "context" and record.name in _NESTED_CONTEXT_NAMES:
        return True
    if (
        record.category == "recommendation"
        and record.name in _NESTED_RECOMMENDATION_NAMES
    ):
        return True
    return False


def _non_nested_total(records: list[TimingRecord]) -> float:
    return sum(record.elapsed_ms for record in records if not _is_nested(record))


def _stats_for(
    records: list[TimingRecord],
    *,
    category: str,
    name: str,
    measured_total: float,
) -> TimingStats:
    samples = [
        r.elapsed_ms
        for r in records
        if r.category == category and r.name == name
    ]
    if not samples:
        return TimingStats(
            name=name,
            category=category,
            count=0,
            total_ms=0.0,
            average_ms=0.0,
            minimum_ms=0.0,
            maximum_ms=0.0,
            share_of_measured_pct=0.0,
        )
    total = sum(samples)
    return TimingStats(
        name=name,
        category=category,
        count=len(samples),
        total_ms=total,
        average_ms=total / len(samples),
        minimum_ms=min(samples),
        maximum_ms=max(samples),
        share_of_measured_pct=(total / measured_total) * 100.0 if measured_total else 0.0,
    )


def _stock_breakdowns(
    records: list[TimingRecord],
    *,
    symbols: list[str],
    strategies: list[str],
) -> list[StockTimingBreakdown]:
    rows: list[StockTimingBreakdown] = []
    for symbol in symbols:
        sym_records = [r for r in records if r.symbol == symbol and not _is_nested(r)]
        load_ohlcv = sum(
            r.elapsed_ms
            for r in sym_records
            if r.category == "parquet_load" and r.name == "ohlcv"
        )
        load_features = sum(
            r.elapsed_ms
            for r in sym_records
            if r.category == "parquet_load" and r.name == "features"
        )
        context = sum(r.elapsed_ms for r in sym_records if r.category == "context")
        strategy_ms = {
            name: sum(
                r.elapsed_ms
                for r in sym_records
                if r.category == "strategy_execution" and r.name == name
            )
            for name in strategies
        }
        recommendation = sum(
            r.elapsed_ms for r in sym_records if r.category == "recommendation"
        )
        total = (
            load_ohlcv
            + load_features
            + context
            + sum(strategy_ms.values())
            + recommendation
        )
        rows.append(
            StockTimingBreakdown(
                symbol=symbol,
                load_ohlcv_ms=load_ohlcv,
                load_features_ms=load_features,
                context_ms=context,
                strategy_ms=strategy_ms,
                recommendation_ms=recommendation,
                total_ms=total,
            ),
        )
    return rows


def _hotspots(
    records: list[TimingRecord],
    *,
    measured_total: float,
    limit: int,
) -> list[HotspotEntry]:
    """Category rollups plus individual strategies for the hotspot pie."""
    buckets: dict[tuple[str, str], float] = {}
    for record in records:
        if _is_nested(record):
            continue
        if record.category == "strategy_execution":
            key = (record.category, record.name)
        elif record.category == "parquet_load":
            key = ("parquet_load", "Parquet Loading")
        elif record.category == "context":
            key = ("context", "Strategy Context")
        elif record.category == "recommendation":
            key = ("recommendation", "Trade Recommendation")
        elif record.category == "discovery":
            key = ("discovery", "Universe Discovery")
        elif record.category == "report":
            key = ("report", "Report Generation")
        else:
            key = (record.category, record.name)
        buckets[key] = buckets.get(key, 0.0) + record.elapsed_ms

    entries = [
        HotspotEntry(
            name=label,
            category=category,
            total_ms=total,
            share_pct=(total / measured_total) * 100.0 if measured_total else 0.0,
        )
        for (category, label), total in buckets.items()
    ]
    entries.sort(key=lambda item: item.total_ms, reverse=True)
    return entries[:limit]


def _fastest(records: list[TimingRecord], *, limit: int = 10) -> list[HotspotEntry]:
    buckets: dict[tuple[str, str], list[float]] = {}
    for record in records:
        if _is_nested(record) or record.elapsed_ms <= 0:
            continue
        key = (record.category, record.name)
        buckets.setdefault(key, []).append(record.elapsed_ms)
    entries: list[HotspotEntry] = []
    for (category, name), samples in buckets.items():
        avg = sum(samples) / len(samples)
        entries.append(
            HotspotEntry(
                name=name,
                category=category,
                total_ms=avg,
                share_pct=0.0,
            ),
        )
    entries.sort(key=lambda item: item.total_ms)
    return entries[:limit]
