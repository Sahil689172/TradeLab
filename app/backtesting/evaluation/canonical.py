"""Canonical EMA evaluation path shared by diagnostic / evaluate / compare tools.

Phase A4Y.1.7.2 — one feature-prep + signal + trade reconstruction pipeline.
Does not change strategy rules or filter thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from app.backtesting.evaluation.backtester import (
    BacktestResult,
    BacktestSettings,
    run_long_only_backtest,
)
from app.backtesting.evaluation.funnel_semantics import (
    build_signal_funnel,
)
from app.backtesting.evaluation.integrity import (
    RawSignalDiagnostic,
    diagnose_raw_signals,
    resolution_for_stride,
)
from app.backtesting.evaluation.schemas import SignalFunnelMetrics
from app.feature_engine.strategy_frame import (
    ensure_strategy_indicators,
    features_include_ohlcv,
    load_strategy_features,
)
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategy_engine.symbols import attach_symbol


@dataclass
class CanonicalModeStats:
    """Executed-trade / signal stats for one mode (raw or professional)."""

    mode: str
    buy_signals: int = 0
    sell_signals: int = 0
    exit_signals: int = 0
    hold_signals: int = 0
    trade_count: int = 0
    funnel: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "buy_signals": self.buy_signals,
            "sell_signals": self.sell_signals,
            "exit_signals": self.exit_signals,
            "hold_signals": self.hold_signals,
            "trade_count": self.trade_count,
            "funnel": dict(self.funnel),
            "errors": list(self.errors),
        }


@dataclass
class CanonicalEMAComparison:
    """Aligned metrics across diagnostic + backtests for one symbol."""

    symbol: str
    bars_in_frame: int
    stride: int
    evaluation_resolution: str
    min_history_bars: int
    # Technical vs strategy vs trades (raw)
    raw_diagnostic: RawSignalDiagnostic
    raw: CanonicalModeStats
    professional: CanonicalModeStats
    semantic_funnel: SignalFunnelMetrics | None = None

    def as_dict(self) -> dict[str, Any]:
        funnel = self.semantic_funnel
        layers = {
            "technical_crossovers": {
                "cross_above": self.raw_diagnostic.cross_above_count,
                "cross_below": self.raw_diagnostic.cross_below_count,
            },
            "raw_strategy_signals": {
                "buy": self.raw_diagnostic.buy_count,
                "sell": self.raw_diagnostic.sell_count,
                "exit": self.raw_diagnostic.exit_count,
                "hold": self.raw_diagnostic.hold_count,
            },
            "professional_buy_candidates": (
                funnel.professional_buy_candidates if funnel is not None else None
            ),
            "professional_filter_rejections_sequential": (
                {
                    "funnel_mode": funnel.funnel_mode,
                    "ema200": funnel.ema200_rejections,
                    "remaining_after_ema200": funnel.remaining_after_ema200,
                    "adx": funnel.adx_rejections,
                    "remaining_after_adx": funnel.remaining_after_adx,
                    "volume": funnel.volume_rejections,
                    "remaining_after_volume": funnel.remaining_after_volume,
                    "atr": funnel.atr_rejections,
                    "other": funnel.other_rejections,
                    "reconciles": funnel.sequential_funnel_reconciles,
                }
                if funnel is not None
                else None
            ),
            "professional_strategy_signals": {
                "buy": self.professional.buy_signals,
                "sell": self.professional.sell_signals,
                "exit": self.professional.exit_signals,
                "hold": self.professional.hold_signals,
            },
            "completed_trades": {
                "raw": self.raw.trade_count,
                "professional": self.professional.trade_count,
                "raw_diagnostic_reconstructed": self.raw_diagnostic.trade_count,
            },
            "executed_trades": {
                "raw": self.raw.trade_count,
                "professional": self.professional.trade_count,
                "raw_diagnostic_reconstructed": self.raw_diagnostic.trade_count,
            },
            "professional_buy_candidate_reduction_pct": (
                funnel.professional_buy_candidate_reduction_pct if funnel is not None else None
            ),
        }
        return {
            "symbol": self.symbol,
            "bars_in_frame": self.bars_in_frame,
            "stride": self.stride,
            "evaluation_resolution": self.evaluation_resolution,
            "min_history_bars": self.min_history_bars,
            "raw_diagnostic": self.raw_diagnostic.as_dict(),
            "raw": self.raw.as_dict(),
            "professional": self.professional.as_dict(),
            "semantic_funnel": funnel.model_dump() if funnel is not None else None,
            "metric_layers": layers,
        }


def load_canonical_features(
    symbol: str,
    storage_dir: Path | str,
) -> pd.DataFrame | None:
    """Same feature preparation used by diagnose + evaluate + compare."""
    frame = load_strategy_features(symbol, storage_dir, ensure_indicators=True)
    if frame is None or not features_include_ohlcv(frame):
        return None
    frame = ensure_strategy_indicators(frame)
    return attach_symbol(frame, symbol.strip().upper())


def _stats_from_backtest(mode: str, result: BacktestResult) -> CanonicalModeStats:
    counts = result.signal_counts or {}
    return CanonicalModeStats(
        mode=mode,
        buy_signals=int(counts.get("BUY", 0)),
        sell_signals=int(counts.get("SELL", 0)),
        exit_signals=int(counts.get("EXIT", 0)),
        hold_signals=int(counts.get("HOLD", 0)),
        trade_count=len(result.trades),
        funnel=dict(result.funnel or {}),
        errors=list(result.errors or []),
    )


def compare_ema_modes_canonical(
    symbol: str,
    features: pd.DataFrame,
    *,
    stride: int = 1,
    min_history_bars: int = 60,
    initial_capital: float = 1_000_000.0,
    percent: float = 95.0,
    slippage_bps: float = 5.0,
    brokerage_rate: float = 0.0003,
) -> CanonicalEMAComparison:
    """Run raw diagnostic + raw/professional long-only backtests on one frame.

    This is the single canonical path. Tools must call this (or
    ``EMAEvaluationEngine`` which uses the same backtester) rather than the
    truncated StrategyAuditor walk (stride + last-N windows).
    """
    resolved = symbol.strip().upper()
    frame = ensure_strategy_indicators(attach_symbol(features.copy(), resolved))
    settings = BacktestSettings(
        initial_capital=initial_capital,
        percent=percent,
        slippage_bps=slippage_bps,
        brokerage_rate=brokerage_rate,
        min_history_bars=min_history_bars,
        stride=max(int(stride), 1),
    )

    raw_strategy = EMATrendStrategy(
        EMATrendConfig(mode="raw", symbol=resolved, min_history_bars=min_history_bars),
    )

    diagnostic = diagnose_raw_signals(
        raw_strategy,
        frame,
        symbol=resolved,
        min_history_bars=min_history_bars,
        stride=settings.stride,
    )
    # Fresh strategy instances for backtests (diagnostic advances internal state)
    raw_bt = run_long_only_backtest(
        EMATrendStrategy(
            EMATrendConfig(mode="raw", symbol=resolved, min_history_bars=min_history_bars),
        ),
        frame,
        mode="raw",
        settings=settings,
        symbol=resolved,
    )
    pro_bt = run_long_only_backtest(
        EMATrendStrategy(
            EMATrendConfig.professional(symbol=resolved, min_history_bars=min_history_bars),
        ),
        frame,
        mode="professional",
        settings=settings,
        symbol=resolved,
    )

    raw_stats = _stats_from_backtest("raw", raw_bt)
    pro_stats = _stats_from_backtest("professional", pro_bt)
    semantic = build_signal_funnel(
        raw=raw_bt,
        professional=pro_bt,
        diagnostic=diagnostic,
        raw_trade_count=len(raw_bt.trades),
        professional_trade_count=len(pro_bt.trades),
    )
    return CanonicalEMAComparison(
        symbol=resolved,
        bars_in_frame=len(frame),
        stride=settings.stride,
        evaluation_resolution=resolution_for_stride(settings.stride).value,
        min_history_bars=min_history_bars,
        raw_diagnostic=diagnostic,
        raw=raw_stats,
        professional=pro_stats,
        semantic_funnel=semantic,
    )
