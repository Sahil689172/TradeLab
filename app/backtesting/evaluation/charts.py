"""PNG chart generation for evaluation reports."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pandas as pd


def _plt():
    try:
        import matplotlib
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ImportError(
            "matplotlib is required for chart generation. "
            "Install with: pip install 'matplotlib>=3.8.0,<4.0.0'",
        ) from exc

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    return plt


def matplotlib_available() -> bool:
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return False
    return True


def generate_all_charts(
    *,
    out_dir: Path,
    raw_equity: pd.Series | None,
    pro_equity: pd.Series | None,
    raw_pnls: Sequence[float],
    pro_pnls: Sequence[float],
    funnel_labels: Sequence[str],
    funnel_values: Sequence[int],
    filter_labels: Sequence[str],
    filter_values: Sequence[int],
) -> dict[str, Path]:
    if not matplotlib_available():
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "equity_curve": plot_equity_curve(raw_equity, pro_equity, out_dir / "equity_curve.png"),
        "drawdown_raw": plot_drawdown_curve(
            raw_equity,
            out_dir / "drawdown_raw.png",
            title="Drawdown — Raw EMA",
        ),
        "drawdown_professional": plot_drawdown_curve(
            pro_equity,
            out_dir / "drawdown_professional.png",
            title="Drawdown — Professional EMA",
        ),
        "drawdown_timeline": plot_drawdown_curve(
            pro_equity,
            out_dir / "drawdown_timeline.png",
            title="Drawdown Timeline — Professional",
        ),
        "trade_distribution_raw": plot_trade_distribution(
            raw_pnls,
            out_dir / "trade_distribution_raw.png",
            title="Trade Distribution — Raw",
        ),
        "trade_distribution_professional": plot_trade_distribution(
            pro_pnls,
            out_dir / "trade_distribution_professional.png",
            title="Trade Distribution — Professional",
        ),
        "monthly_returns": plot_monthly_returns(
            pro_equity,
            out_dir / "monthly_returns.png",
            title="Monthly Returns — Professional",
        ),
        "yearly_returns": plot_yearly_returns(
            pro_equity,
            out_dir / "yearly_returns.png",
            title="Yearly Returns — Professional",
        ),
        "signal_funnel": plot_funnel_bars(
            funnel_labels,
            funnel_values,
            out_dir / "signal_funnel.png",
            title="Signal Funnel",
        ),
        "filter_funnel": plot_funnel_bars(
            filter_labels,
            filter_values,
            out_dir / "filter_funnel.png",
            title="Filter Funnel (Rejected)",
        ),
        "capital_curve": plot_equity_curve(
            raw_equity,
            pro_equity,
            out_dir / "capital_curve.png",
        ),
        "rolling_sharpe": plot_rolling_metric(
            pro_equity,
            out_dir / "rolling_sharpe.png",
            title="Rolling Sharpe — Professional",
            metric="sharpe",
        ),
        "rolling_win_rate": plot_rolling_metric(
            pro_equity,
            out_dir / "rolling_win_rate.png",
            title="Rolling Positive-Day Rate — Professional",
            metric="win_rate",
        ),
    }
    return paths


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    _plt().close(fig)
    return path


def plot_equity_curve(
    raw: pd.Series | None,
    professional: pd.Series | None,
    path: Path,
) -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 5))
    if raw is not None and len(raw):
        ax.plot(raw.index, raw.values, label="Raw EMA", linewidth=1.5)
    if professional is not None and len(professional):
        ax.plot(professional.index, professional.values, label="Professional EMA", linewidth=1.5)
    ax.set_title("Equity Curve")
    ax.set_ylabel("Equity")
    ax.legend()
    ax.grid(True, alpha=0.3)
    return _save(fig, path)


def plot_drawdown_curve(equity: pd.Series | None, path: Path, *, title: str) -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 4))
    if equity is not None and len(equity):
        peak = equity.cummax()
        dd = (equity - peak) / peak.replace(0, pd.NA)
        ax.fill_between(dd.index, dd.values, 0, alpha=0.4)
        ax.plot(dd.index, dd.values, linewidth=1.0)
    ax.set_title(title)
    ax.set_ylabel("Drawdown")
    ax.grid(True, alpha=0.3)
    return _save(fig, path)


def plot_trade_distribution(pnls: Sequence[float], path: Path, *, title: str) -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8, 4))
    if pnls:
        ax.hist(list(pnls), bins=min(30, max(5, len(pnls) // 2)), edgecolor="black", alpha=0.75)
    ax.set_title(title)
    ax.set_xlabel("Net Profit")
    ax.set_ylabel("Count")
    ax.grid(True, alpha=0.3)
    return _save(fig, path)


def plot_monthly_returns(equity: pd.Series | None, path: Path, *, title: str) -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 4))
    if equity is not None and len(equity) >= 2:
        monthly = equity.resample("ME").last().pct_change().dropna()
        colors = ["#2ca02c" if v >= 0 else "#d62728" for v in monthly.values]
        ax.bar(monthly.index.strftime("%Y-%m"), monthly.values, color=colors)
        ax.tick_params(axis="x", rotation=45)
    ax.set_title(title)
    ax.set_ylabel("Monthly Return")
    ax.grid(True, alpha=0.3)
    return _save(fig, path)


def plot_yearly_returns(equity: pd.Series | None, path: Path, *, title: str) -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(8, 4))
    if equity is not None and len(equity) >= 2:
        yearly = equity.resample("YE").last().pct_change().dropna()
        colors = ["#2ca02c" if v >= 0 else "#d62728" for v in yearly.values]
        ax.bar(yearly.index.strftime("%Y"), yearly.values, color=colors)
    ax.set_title(title)
    ax.set_ylabel("Yearly Return")
    ax.grid(True, alpha=0.3)
    return _save(fig, path)


def plot_funnel_bars(
    labels: Sequence[str],
    values: Sequence[int],
    path: Path,
    *,
    title: str,
) -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(list(labels), list(values), color="#1f77b4")
    ax.set_title(title)
    ax.tick_params(axis="x", rotation=30)
    ax.grid(True, axis="y", alpha=0.3)
    return _save(fig, path)


def plot_rolling_metric(
    equity: pd.Series | None,
    path: Path,
    *,
    title: str,
    window: int = 60,
    metric: str = "sharpe",
) -> Path:
    plt = _plt()
    fig, ax = plt.subplots(figsize=(10, 4))
    if equity is not None and len(equity) > window + 2:
        rets = equity.pct_change()
        if metric == "sharpe":
            roll = (
                rets.rolling(window).mean()
                / rets.rolling(window).std().replace(0, pd.NA)
                * (252**0.5)
            )
        else:  # win rate proxy from positive daily returns
            roll = rets.rolling(window).apply(lambda x: (x > 0).mean(), raw=False)
        ax.plot(roll.index, roll.values, linewidth=1.2)
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    return _save(fig, path)
