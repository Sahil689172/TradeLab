"""Orchestrate Raw vs Professional EMA evaluation (Phase A4Y.1.5)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from app.backtesting.evaluation.backtester import BacktestSettings, run_long_only_backtest
from app.backtesting.evaluation.charts import generate_all_charts
from app.backtesting.evaluation.export import (
    export_evaluation_json,
    export_evaluation_markdown,
    export_filter_csv,
    export_metrics_csv,
    export_trades_csv,
)
from app.backtesting.evaluation.integrity import (
    CapitalAllocationMode,
    diagnose_raw_signals,
    merge_equal_weight_equity,
    merge_per_symbol_full_equity,
    periods_per_year_for_stride,
    resolution_for_stride,
    validate_evaluation_metrics,
)
from app.backtesting.evaluation.metrics import compute_performance
from app.backtesting.evaluation.reports import format_console_report
from app.backtesting.evaluation.schemas import EvaluationReport
from app.backtesting.evaluation.signals import build_filter_effectiveness, build_signal_funnel
from app.backtesting.evaluation.statistics import (
    compare_metrics,
    overall_recommendation,
    paired_trade_delta,
)
from app.strategies.ema_trend import EMATrendConfig, EMATrendStrategy
from app.strategy_engine.symbols import attach_symbol


@dataclass
class EvaluationConfig:
    initial_capital: float = 1_000_000.0
    percent: float = 95.0
    slippage_bps: float = 5.0
    brokerage_rate: float = 0.0003
    min_history_bars: int = 60
    stride: int = 1
    out_dir: Path = Path("backend/data/evaluation")
    generate_charts: bool = True
    # A4Y.1.7: multi-stock capital policy (default = institutional equal-weight sleeves)
    capital_mode: CapitalAllocationMode = CapitalAllocationMode.EQUAL_WEIGHT
    # Transaction-cost model intentionally limited to brokerage + slippage (no STT/GST/etc.)
    cost_model: str = "brokerage_and_slippage_only"


def load_symbol_features(symbol: str, storage_dir: Path) -> pd.DataFrame | None:
    """Load OHLCV+indicators for evaluation; compute missing indicators canonically."""
    from app.feature_engine.strategy_frame import (
        features_include_ohlcv,
        load_strategy_features,
    )

    frame = load_strategy_features(symbol, storage_dir, ensure_indicators=True)
    if frame is None or not features_include_ohlcv(frame):
        return None
    return attach_symbol(frame, symbol)


def synthetic_features(*, bars: int = 260, symbol: str = "RELIANCE") -> pd.DataFrame:
    """Daily synthetic OHLCV+indicators with true EMA crosses for raw and professional."""
    dates = pd.bdate_range("2018-01-02", periods=bars, freq="B")
    rows = []
    price = 100.0
    for index, ts in enumerate(dates):
        # Slow regime oscillation so both 9/21 and 20/50 produce crosses
        bull = (index // 25) % 2 == 0
        price = price + (0.35 if bull else -0.28)
        close = max(price, 5.0)

        # Build lagged EMAs with intentional true crosses every ~25 bars
        cross_up = index % 25 == 24
        cross_down = index % 25 == 12
        if cross_up:
            ema9, ema21 = close * 0.997, close * 0.999
            ema20, ema50 = close * 0.996, close * 0.998
        elif cross_down:
            ema9, ema21 = close * 1.003, close * 0.999
            ema20, ema50 = close * 1.004, close * 0.998
        elif bull:
            ema9, ema21 = close * 1.002, close * 0.999
            ema20, ema50 = close * 1.003, close * 0.997
        else:
            ema9, ema21 = close * 0.997, close * 0.999
            ema20, ema50 = close * 0.996, close * 0.998

        rows.append(
            {
                "date": ts,
                "open": close - 0.2,
                "high": close + 0.8,
                "low": close - 0.8,
                "close": close,
                "volume": 180_000 + index * 400,
                "volume_sma_20": 150_000,
                "relative_volume_20": 1.4,
                "atr_14": 1.8,
                "ema_9": ema9,
                "ema_20": ema20,
                "ema_21": ema21,
                "ema_50": ema50,
                "ema_200": close * 0.93,
                "adx_14": 28.0 if not cross_down else 18.0,
                "rsi_14": 55.0,
            },
        )
    return attach_symbol(pd.DataFrame(rows), symbol)


def _merge_equity(
    curves: list[pd.Series],
    initial: float,
    *,
    mode: CapitalAllocationMode,
) -> pd.Series | None:
    if mode is CapitalAllocationMode.PER_SYMBOL_FULL:
        return merge_per_symbol_full_equity(curves, initial)
    return merge_equal_weight_equity(curves, initial)


class EMAEvaluationEngine:
    """Evaluate Raw vs Professional EMA on one or many symbols."""

    def __init__(self, config: EvaluationConfig | None = None) -> None:
        self.config = config or EvaluationConfig()

    def _sleeve_capital(self, n_symbols: int) -> float:
        n = max(int(n_symbols), 1)
        if (
            self.config.capital_mode is CapitalAllocationMode.EQUAL_WEIGHT
            and n > 1
        ):
            return float(self.config.initial_capital) / float(n)
        return float(self.config.initial_capital)

    def evaluate_symbol(
        self,
        symbol: str,
        features: pd.DataFrame,
        *,
        sleeve_capital: float | None = None,
    ) -> dict[str, Any]:
        capital = (
            float(sleeve_capital)
            if sleeve_capital is not None
            else float(self.config.initial_capital)
        )
        settings = BacktestSettings(
            initial_capital=capital,
            percent=self.config.percent,
            slippage_bps=self.config.slippage_bps,
            brokerage_rate=self.config.brokerage_rate,
            min_history_bars=self.config.min_history_bars,
            stride=self.config.stride,
        )
        raw_strategy = EMATrendStrategy(
            EMATrendConfig(mode="raw", symbol=symbol, min_history_bars=self.config.min_history_bars),
        )
        pro_strategy = EMATrendStrategy(
            EMATrendConfig.professional(symbol=symbol, min_history_bars=self.config.min_history_bars),
        )
        raw_bt = run_long_only_backtest(
            raw_strategy,
            features,
            mode="raw",
            settings=settings,
            symbol=symbol,
        )
        pro_bt = run_long_only_backtest(
            pro_strategy,
            features,
            mode="professional",
            settings=settings,
            symbol=symbol,
        )
        return {"symbol": symbol, "raw": raw_bt, "professional": pro_bt}

    def evaluate_universe(
        self,
        symbol_frames: dict[str, pd.DataFrame],
    ) -> EvaluationReport:
        raw_trades: list[dict] = []
        pro_trades: list[dict] = []
        raw_curves: list[pd.Series] = []
        pro_curves: list[pd.Series] = []
        raw_counts = {"BUY": 0, "SELL": 0, "HOLD": 0, "EXIT": 0}
        # Aggregate professional funnel + signal counts via last merged result
        from app.backtesting.evaluation.backtester import BacktestResult

        agg_raw = BacktestResult(mode="raw", symbol="UNIVERSE")
        agg_pro = BacktestResult(mode="professional", symbol="UNIVERSE")

        period_start = None
        period_end = None
        total = len(symbol_frames)
        n_symbols = max(total, 1)
        sleeve_capital = self._sleeve_capital(n_symbols)
        resolution = resolution_for_stride(self.config.stride)
        ppy = periods_per_year_for_stride(self.config.stride)
        print(
            f"Evaluation mode: {resolution.value} | capital_mode="
            f"{self.config.capital_mode.value} | sleeve_capital={sleeve_capital:.2f} "
            f"| stride={self.config.stride} | periods_per_year={ppy:.4f}",
            flush=True,
        )
        for index, (symbol, frame) in enumerate(symbol_frames.items(), start=1):
            print(
                f"[{index}/{total}] {symbol} "
                f"({len(frame)} bars, stride={self.config.stride}) ...",
                flush=True,
            )
            result = self.evaluate_symbol(
                symbol,
                frame,
                sleeve_capital=sleeve_capital,
            )
            raw_bt = result["raw"]
            pro_bt = result["professional"]
            print(
                f"  done — raw trades={len(raw_bt.trades)} "
                f"pro trades={len(pro_bt.trades)}",
                flush=True,
            )
            raw_trades.extend(t.as_dict() for t in raw_bt.trades)
            pro_trades.extend(t.as_dict() for t in pro_bt.trades)
            if raw_bt.equity_curve is not None:
                raw_curves.append(raw_bt.equity_curve)
            if pro_bt.equity_curve is not None:
                pro_curves.append(pro_bt.equity_curve)
            for key, val in raw_bt.signal_counts.items():
                raw_counts[key] = raw_counts.get(key, 0) + val
            for key, val in pro_bt.signal_counts.items():
                agg_pro.signal_counts[key] = agg_pro.signal_counts.get(key, 0) + val
            if pro_bt.funnel:
                for key, val in pro_bt.funnel.items():
                    agg_pro.funnel[key] = int(agg_pro.funnel.get(key, 0)) + int(val)
            if "date" in frame.columns and len(frame):
                start = str(pd.Timestamp(frame["date"].iloc[0]).date())
                end = str(pd.Timestamp(frame["date"].iloc[-1]).date())
                period_start = start if period_start is None else min(period_start, start)
                period_end = end if period_end is None else max(period_end, end)

        agg_raw.signal_counts = raw_counts
        diagnostic = None
        if n_symbols == 1:
            only_symbol, only_frame = next(iter(symbol_frames.items()))
            diagnostic = diagnose_raw_signals(
                EMATrendStrategy(
                    EMATrendConfig(
                        mode="raw",
                        symbol=only_symbol,
                        min_history_bars=self.config.min_history_bars,
                    ),
                ),
                only_frame,
                symbol=only_symbol,
                min_history_bars=self.config.min_history_bars,
                stride=self.config.stride,
            )
        capital = self.config.initial_capital
        raw_equity = _merge_equity(
            raw_curves,
            capital,
            mode=self.config.capital_mode,
        )
        pro_equity = _merge_equity(
            pro_curves,
            capital,
            mode=self.config.capital_mode,
        )

        raw_perf = compute_performance(
            mode="raw",
            trades=raw_trades,
            equity_curve=raw_equity,
            initial_capital=capital,
            symbols_evaluated=n_symbols,
            periods_per_year=ppy,
        )
        pro_perf = compute_performance(
            mode="professional",
            trades=pro_trades,
            equity_curve=pro_equity,
            initial_capital=capital,
            symbols_evaluated=n_symbols,
            periods_per_year=ppy,
        )
        funnel = build_signal_funnel(
            raw=agg_raw,
            professional=agg_pro,
            diagnostic=diagnostic,
            raw_trade_count=len(raw_trades),
            professional_trade_count=len(pro_trades),
        )
        filters = build_filter_effectiveness(funnel, raw_perf=raw_perf, pro_perf=pro_perf)
        comparisons = compare_metrics(raw_perf, pro_perf)
        stats = paired_trade_delta(
            [float(t["net_profit"]) for t in raw_trades],
            [float(t["net_profit"]) for t in pro_trades],
        )
        validity = validate_evaluation_metrics(
            raw_trades=raw_perf.total_trades,
            professional_trades=pro_perf.total_trades,
            raw_max_dd=raw_perf.max_drawdown,
            pro_max_dd=pro_perf.max_drawdown,
            raw_sharpe=raw_perf.sharpe_ratio,
            pro_sharpe=pro_perf.sharpe_ratio,
            raw_final_equity=raw_perf.final_equity,
            pro_final_equity=pro_perf.final_equity,
            stride=self.config.stride,
        )
        overall, recommended, summary = overall_recommendation(
            comparisons,
            stats,
            raw=raw_perf,
            professional=pro_perf,
            validity_ok=validity.ok,
            validity_reasons=validity.reasons,
        )

        report = EvaluationReport(
            symbols=tuple(sorted(symbol_frames)),
            period_start=period_start,
            period_end=period_end,
            raw=raw_perf,
            professional=pro_perf,
            signal_funnel=funnel,
            filter_effectiveness=tuple(filters),
            metric_comparisons=tuple(comparisons),
            statistics=stats,
            overall_improvement=overall,
            professional_recommended=recommended,
            executive_summary=summary,
            metadata={
                "initial_capital": capital,
                "sleeve_capital": sleeve_capital,
                "capital_mode": self.config.capital_mode.value,
                "evaluation_resolution": resolution.value,
                "stride": self.config.stride,
                "periods_per_year": ppy,
                "slippage_bps": self.config.slippage_bps,
                "brokerage_rate": self.config.brokerage_rate,
                "percent": self.config.percent,
                "cost_model": self.config.cost_model,
                "validity": validity.as_dict(),
            },
        )
        # stash trades/curves for export helpers
        report_meta = {
            "raw_trades": raw_trades,
            "pro_trades": pro_trades,
            "raw_equity": raw_equity,
            "pro_equity": pro_equity,
        }
        self._last_artifacts = report_meta
        self._last_report = report
        return report

    def export_all(self, report: EvaluationReport, *, out_dir: Path | None = None) -> dict[str, Path]:
        out = Path(out_dir or self.config.out_dir)
        out.mkdir(parents=True, exist_ok=True)
        artifacts = getattr(self, "_last_artifacts", {})
        paths: dict[str, Path] = {
            "json": export_evaluation_json(report, out / "evaluation_report.json"),
            "markdown": export_evaluation_markdown(report, out / "evaluation_report.md"),
            "metrics_csv": export_metrics_csv(report, out / "metrics_comparison.csv"),
            "filters_csv": export_filter_csv(report, out / "filter_effectiveness.csv"),
            "raw_trades_csv": export_trades_csv(
                artifacts.get("raw_trades", []),
                out / "trades_raw.csv",
            ),
            "pro_trades_csv": export_trades_csv(
                artifacts.get("pro_trades", []),
                out / "trades_professional.csv",
            ),
        }
        # Additional named reports
        paths["comparison_md"] = export_evaluation_markdown(
            report,
            out / "raw_vs_professional_comparison.md",
        )
        # Risk / trade / executive extracts as markdown sections (same content files)
        (out / "executive_summary.md").write_text(
            f"# Executive Summary\n\n{report.executive_summary}\n",
            encoding="utf-8",
        )
        paths["executive_md"] = out / "executive_summary.md"

        if self.config.generate_charts:
            funnel = report.signal_funnel
            chart_dir = out / "charts"
            chart_paths = generate_all_charts(
                out_dir=chart_dir,
                raw_equity=artifacts.get("raw_equity"),
                pro_equity=artifacts.get("pro_equity"),
                raw_pnls=[float(t["net_profit"]) for t in artifacts.get("raw_trades", [])],
                pro_pnls=[float(t["net_profit"]) for t in artifacts.get("pro_trades", [])],
                funnel_labels=[
                    "Pro BUY candidates",
                    "Final BUY signals",
                    "Raw completed trades",
                    "Pro completed trades",
                ],
                funnel_values=[
                    funnel.professional_buy_candidates,
                    funnel.professional_buy_signals,
                    funnel.raw_completed_trades,
                    funnel.professional_completed_trades,
                ],
                filter_labels=["EMA200", "ADX", "Volume", "ATR", "Other"],
                filter_values=[
                    funnel.rejected_ema200,
                    funnel.rejected_adx,
                    funnel.rejected_volume,
                    funnel.rejected_atr,
                    funnel.rejected_other,
                ],
            )
            if chart_paths:
                paths.update({f"chart_{k}": v for k, v in chart_paths.items()})
            else:
                skip_note = out / "charts_skipped.txt"
                skip_note.write_text(
                    "Charts skipped: matplotlib is not installed.\n"
                    "Install with: pip install \"matplotlib>=3.8.0,<4.0.0\"\n",
                    encoding="utf-8",
                )
                paths["charts_skipped"] = skip_note
        return paths


def format_report(report: EvaluationReport) -> str:
    return format_console_report(report)
