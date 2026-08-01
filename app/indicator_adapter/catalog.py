"""Name resolution from friendly indicator keys to feature columns."""

from __future__ import annotations

from dataclasses import dataclass

from app.indicator_adapter.exceptions import IndicatorNotFoundError

# Friendly aliases → exact Feature Engineering Engine column names.
# No recalculation: aliases only remap labels to existing columns.
ALIASES: dict[str, str] = {
    "rsi": "rsi_14",
    "atr": "atr_14",
    "adx": "adx_14",
    "roc": "roc_12",
    "momentum": "momentum_10",
    "cci": "cci_20",
    "williams_r": "williams_r_14",
    "williams": "williams_r_14",
    "obv": "obv",
    "mfi": "money_flow_index_14",
    "money_flow_index": "money_flow_index_14",
    "macd_line": "macd",
    "macd_signal": "macd_signal",
    "macd_hist": "macd_histogram",
    "macd_histogram": "macd_histogram",
    # Attached by VWAPService (app.services.strategy_engine.indicators.vwap)
    "vwap": "vwap",
    "vwap_daily": "vwap",
    "vwap_slope": "vwap_slope",
}

MACD_COLUMNS: tuple[str, str, str] = ("macd", "macd_signal", "macd_histogram")


@dataclass(frozen=True, slots=True)
class ResolvedIndicator:
    """Result of resolving a requested indicator name."""

    request: str
    is_macd_bundle: bool
    column: str | None = None
    columns: tuple[str, str, str] | None = None


def normalize_name(name: str) -> str:
    cleaned = name.strip().lower().replace("-", "_").replace(" ", "_")
    if not cleaned:
        raise IndicatorNotFoundError("Indicator name must not be blank")
    return cleaned


def resolve_indicator_name(name: str, available_columns: set[str]) -> ResolvedIndicator:
    """Resolve a friendly or exact name against available feature columns.

    Raises:
        IndicatorNotFoundError: When the name cannot be mapped to existing columns.
    """
    request = normalize_name(name)
    columns = {column.lower() for column in available_columns}

    if request == "macd":
        missing = [column for column in MACD_COLUMNS if column not in columns]
        if missing:
            raise IndicatorNotFoundError(
                f"MACD requires columns {list(MACD_COLUMNS)}; missing {missing}",
            )
        return ResolvedIndicator(request=request, is_macd_bundle=True, columns=MACD_COLUMNS)

    resolved = ALIASES.get(request, request)
    if resolved in columns:
        return ResolvedIndicator(request=request, is_macd_bundle=False, column=resolved)

    suggestions = sorted(
        column
        for column in columns
        if column == request or column.startswith(f"{request}_") or request in column
    )
    hint = f" Did you mean: {', '.join(suggestions[:8])}?" if suggestions else ""
    available_preview = ", ".join(sorted(columns)[:12])
    raise IndicatorNotFoundError(
        f"Indicator '{name}' not found in feature columns.{hint} "
        f"Available (sample): {available_preview}",
    )


def list_aliases() -> dict[str, str]:
    """Return a copy of supported friendly aliases."""
    return dict(ALIASES)
