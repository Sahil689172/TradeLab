"""Optional walk-forward charts. Reuses matplotlib when installed."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.backtesting.evaluation.charts import matplotlib_available
from app.backtesting.evaluation.metrics import max_drawdown
from app.backtesting.walk_forward.equity import assert_market_timestamps_only, combined_oos_end
from app.backtesting.walk_forward.schemas import WalkForwardResult


def write_charts(result: WalkForwardResult, *, output_dir: Path) -> dict[str, Path]:
    if not matplotlib_available():
        return {}
    from app.backtesting.evaluation.charts import _plt

    plt = _plt()
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    equity = _equity_series(result)
    oos_end = combined_oos_end(result.windows)
    assert_market_timestamps_only(equity, max_date=oos_end, generated_at=result.generated_at)
    if len(equity):
        path = output_dir / "oos_equity_curve.png"
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot(equity.index, equity.values, color="#1f4e79")
        ax.set_title("Combined OOS equity (market timestamps only)")
        ax.set_ylabel("Equity")
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths["oos_equity"] = path
        dd_path = output_dir / "oos_drawdown.png"
        peak = equity.cummax()
        dd = (peak - equity) / peak.replace(0, pd.NA)
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.fill_between(dd.index, dd.fillna(0.0).values, color="#9c2a2a", alpha=0.7)
        ax.set_title("OOS drawdown (canonical equity series)")
        fig.tight_layout()
        fig.savefig(dd_path, dpi=120)
        plt.close(fig)
        paths["oos_drawdown"] = dd_path
        plotted_dd, _, _ = max_drawdown(equity.tolist())
        if abs(plotted_dd - result.oos_max_drawdown) > 1e-6:
            raise AssertionError("plotted max drawdown does not match reported OOS max drawdown")
    if result.windows:
        path = output_dir / "train_vs_oos_return.png"
        fig, ax = plt.subplots(figsize=(8, 4))
        labels = [f"{w.window.window_id}/{w.symbol}" for w in result.windows]
        ax.bar([i - 0.2 for i in range(len(labels))], [w.train.return_pct for w in result.windows], width=0.4, label="Train")
        ax.bar([i + 0.2 for i in range(len(labels))], [w.oos.return_pct for w in result.windows], width=0.4, label="OOS")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_title("Train vs OOS return")
        ax.legend()
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths["train_vs_oos_return"] = path
        path = output_dir / "train_vs_oos_sharpe.png"
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar([i - 0.2 for i in range(len(labels))], [w.train.sharpe for w in result.windows], width=0.4, label="Train")
        ax.bar([i + 0.2 for i in range(len(labels))], [w.oos.sharpe for w in result.windows], width=0.4, label="OOS (raw)")
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.set_title("Train vs OOS Sharpe")
        ax.legend()
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths["train_vs_oos_sharpe"] = path
        path = output_dir / "per_window_oos_return.png"
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.bar(labels, [w.oos.return_pct for w in result.windows], color="#2e7d32")
        ax.set_title("Per-window OOS return")
        ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths["per_window_oos_return"] = path
    freq = result.parameter_stability.frequency
    if freq:
        path = output_dir / "parameter_stability.png"
        fig, ax = plt.subplots(figsize=(8, 4))
        keys = list(freq.keys())
        ax.bar(keys, [freq[k] for k in keys], color="#1565c0")
        ax.set_title("Parameter frequency")
        ax.tick_params(axis="x", rotation=45)
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        paths["parameter_stability"] = path
    return paths


def _equity_series(result: WalkForwardResult) -> pd.Series:
    if not result.equity_curve:
        return pd.Series(dtype=float)
    index = [pd.Timestamp(p.timestamp) for p in result.equity_curve]
    values = [p.equity for p in result.equity_curve]
    series = pd.Series(values, index=pd.DatetimeIndex(index), dtype=float)
    return series.sort_index()
