"""Research-based default filter profiles for all 12 strategies.

Profiles declare mandatory / default / optional / configurable slots.
Strategy signal logic is unchanged — the pipeline wraps TradePlan output.
"""

from __future__ import annotations

from app.strategy_engine.filters.profiles import FilterRole, FilterSpec, StrategyFilterProfile


def _spec(
    filter_id: str,
    role: FilterRole,
    *,
    priority: int,
    enabled: bool | None = None,
    **params: object,
) -> FilterSpec:
    return FilterSpec(
        filter_id=filter_id,
        role=role,
        enabled=enabled,
        priority=priority,
        params=dict(params),
    )


def _m(filter_id: str, priority: int, **params: object) -> FilterSpec:
    return _spec(filter_id, FilterRole.MANDATORY, priority=priority, **params)


def _d(filter_id: str, priority: int, **params: object) -> FilterSpec:
    return _spec(filter_id, FilterRole.DEFAULT, priority=priority, **params)


def _o(filter_id: str, priority: int, **params: object) -> FilterSpec:
    return _spec(filter_id, FilterRole.OPTIONAL, priority=priority, enabled=False, **params)


def _c(filter_id: str, priority: int, **params: object) -> FilterSpec:
    return _spec(filter_id, FilterRole.CONFIGURABLE, priority=priority, **params)


STRATEGY_FILTER_PROFILES: dict[str, StrategyFilterProfile] = {
    "ema_trend": StrategyFilterProfile(
        strategy_name="ema_trend",
        description="EMA trend: EMA200 + ADX mandatory; ATR + volume default",
        mandatory=(
            _m("ema200", 10),
            _m("adx", 20, min_adx=25.0),
        ),
        default=(
            _d("atr_stop", 30, atr_multiplier=2.0, require_stop_at_least_atr=False, enforce_stop=False),
            _d("relative_volume", 40, min_relative_volume=1.0),
        ),
        configurable=(
            _c("risk_reward", 50, min_risk_reward=1.5),
            _c("atr_trailing_stop", 60, atr_multiplier=2.0, enforce_trail=False),
        ),
        optional=(
            _o("trending_market", 70),
            _o("minimum_confidence", 80, min_confidence=0.5),
            _o("daily_confirmation", 90, only_when_requested=True),
        ),
    ),
    "opening_range_breakout": StrategyFilterProfile(
        strategy_name="opening_range_breakout",
        description="ORB: Stocks in Play + volume mandatory; ATR + VWAP + gap default",
        mandatory=(
            _m("stocks_in_play", 10, min_relative_volume=1.5, min_range_pct=1.0),
            _m("relative_volume", 20, min_relative_volume=1.5),
        ),
        default=(
            _d("atr_stop", 30, atr_multiplier=2.0, require_stop_at_least_atr=False, enforce_stop=False),
            _d("vwap_confirmation", 40),
            _d("gap", 50, max_abs_gap_pct=5.0),
        ),
        configurable=(
            _c("risk_reward", 60, min_risk_reward=1.5),
            _c("minimum_volume", 70, min_volume=50_000),
        ),
        optional=(
            _o("liquidity", 80),
            _o("minimum_confidence", 90, min_confidence=0.45),
        ),
    ),
    "vwap": StrategyFilterProfile(
        strategy_name="vwap",
        description="VWAP: VWAP + RVOL mandatory; ATR + min volume default",
        mandatory=(
            _m("vwap_confirmation", 10),
            _m("relative_volume", 20, min_relative_volume=1.2),
        ),
        default=(
            _d("atr_stop", 30, atr_multiplier=1.5, require_stop_at_least_atr=False, enforce_stop=False),
            _d("minimum_volume", 40, min_volume=100_000),
        ),
        configurable=(
            _c("risk_reward", 50, min_risk_reward=1.5),
            _c("volume_sma", 60, min_volume_vs_sma=1.0),
        ),
        optional=(
            _o("liquidity", 70),
            _o("obv_confirmation", 80),
        ),
    ),
    "supertrend": StrategyFilterProfile(
        strategy_name="supertrend",
        description="SuperTrend: ADX mandatory; ATR trail + volume default",
        mandatory=(
            _m("adx", 10, min_adx=20.0),
            _m("atr_stop", 20, atr_multiplier=1.5, require_stop_at_least_atr=False, enforce_stop=False),
        ),
        default=(
            _d("atr_trailing_stop", 30, atr_multiplier=2.0, enforce_trail=False),
            _d("relative_volume", 40, min_relative_volume=1.0),
        ),
        configurable=(
            _c("risk_reward", 50, min_risk_reward=1.5),
            _c("mtf_supertrend", 60, only_when_requested=True),
        ),
        optional=(
            _o("ema200", 70),
            _o("trending_market", 80),
        ),
    ),
    "momentum": StrategyFilterProfile(
        strategy_name="momentum",
        description="Momentum: RVOL + confidence mandatory; ATR + trend default",
        mandatory=(
            _m("relative_volume", 10, min_relative_volume=1.2),
            _m("minimum_confidence", 20, min_confidence=0.55),
        ),
        default=(
            _d("atr_stop", 30, atr_multiplier=2.0, require_stop_at_least_atr=False, enforce_stop=False),
            _d("trending_market", 40),
        ),
        configurable=(
            _c("risk_reward", 50, min_risk_reward=1.5),
            _c("adx", 60, min_adx=20.0),
        ),
        optional=(
            _o("ema200", 70),
            _o("mtf_rsi", 80, only_when_requested=True),
        ),
    ),
    "break_retest": StrategyFilterProfile(
        strategy_name="break_retest",
        description="Break & retest: volume SMA + ATR mandatory",
        mandatory=(
            _m("volume_sma", 10, min_volume_vs_sma=1.0),
            _m("atr_stop", 20, atr_multiplier=1.5, require_stop_at_least_atr=False, enforce_stop=False),
        ),
        default=(
            _d("relative_volume", 30, min_relative_volume=1.2),
            _d("minimum_confidence", 40, min_confidence=0.5),
        ),
        configurable=(
            _c("risk_reward", 50, min_risk_reward=1.5),
            _c("vwap_confirmation", 60),
        ),
        optional=(
            _o("ema200", 70),
            _o("obv_confirmation", 80),
        ),
    ),
    "cpr": StrategyFilterProfile(
        strategy_name="cpr",
        description="CPR: RVOL mandatory; ATR + VWAP default",
        mandatory=(
            _m("relative_volume", 10, min_relative_volume=1.2),
        ),
        default=(
            _d("atr_stop", 20, atr_multiplier=1.5, require_stop_at_least_atr=False, enforce_stop=False),
            _d("vwap_confirmation", 30),
        ),
        configurable=(
            _c("risk_reward", 40, min_risk_reward=1.5),
            _c("gap", 50, max_abs_gap_pct=4.0),
        ),
        optional=(
            _o("liquidity", 60),
            _o("minimum_volume", 70),
        ),
    ),
    "previous_day_breakout": StrategyFilterProfile(
        strategy_name="previous_day_breakout",
        description="PDB: RVOL + gap mandatory; ATR + SIP default",
        mandatory=(
            _m("relative_volume", 10, min_relative_volume=1.5),
            _m("gap", 20, max_abs_gap_pct=6.0),
        ),
        default=(
            _d("atr_stop", 30, atr_multiplier=2.0, require_stop_at_least_atr=False, enforce_stop=False),
            _d("stocks_in_play", 40, min_relative_volume=1.5, min_range_pct=1.5),
        ),
        configurable=(
            _c("risk_reward", 50, min_risk_reward=1.5),
            _c("vwap_confirmation", 60),
        ),
        optional=(
            _o("liquidity", 70),
            _o("minimum_confidence", 80, min_confidence=0.5),
        ),
    ),
    "volume_breakout": StrategyFilterProfile(
        strategy_name="volume_breakout",
        description="Volume breakout: RVOL + volume SMA + min volume mandatory",
        mandatory=(
            _m("relative_volume", 10, min_relative_volume=1.8),
            _m("volume_sma", 20, min_volume_vs_sma=1.5),
            _m("minimum_volume", 30, min_volume=100_000),
        ),
        default=(
            _d("atr_stop", 40, atr_multiplier=2.0, require_stop_at_least_atr=False, enforce_stop=False),
            _d("vwap_confirmation", 50),
        ),
        configurable=(
            _c("risk_reward", 60, min_risk_reward=1.5),
            _c("stocks_in_play", 70, min_relative_volume=1.8),
        ),
        optional=(
            _o("liquidity", 80),
            _o("obv_confirmation", 90),
        ),
    ),
    "donchian": StrategyFilterProfile(
        strategy_name="donchian",
        description="Donchian: ATR + ADX mandatory; RVOL + trend default",
        mandatory=(
            _m("atr_stop", 10, atr_multiplier=2.0, require_stop_at_least_atr=False, enforce_stop=False),
            _m("adx", 20, min_adx=20.0),
        ),
        default=(
            _d("relative_volume", 30, min_relative_volume=1.0),
            _d("trending_market", 40),
        ),
        configurable=(
            _c("risk_reward", 50, min_risk_reward=1.5),
            _c("atr_trailing_stop", 60, atr_multiplier=2.5, enforce_trail=False),
        ),
        optional=(
            _o("ema200", 70),
            _o("sma200", 80),
        ),
    ),
    "darvas_box": StrategyFilterProfile(
        strategy_name="darvas_box",
        description="Darvas: RVOL + ATR mandatory; volume SMA + confidence default",
        mandatory=(
            _m("relative_volume", 10, min_relative_volume=1.3),
            _m("atr_stop", 20, atr_multiplier=1.5, require_stop_at_least_atr=False, enforce_stop=False),
        ),
        default=(
            _d("volume_sma", 30, min_volume_vs_sma=1.0),
            _d("minimum_confidence", 40, min_confidence=0.5),
        ),
        configurable=(
            _c("risk_reward", 50, min_risk_reward=1.5),
            _c("fixed_stop", 60, stop_pct=0.03, enforce_stop=False),
        ),
        optional=(
            _o("ema200", 70),
            _o("liquidity", 80),
        ),
    ),
    "relative_strength": StrategyFilterProfile(
        strategy_name="relative_strength",
        description="RS: RVOL + confidence mandatory; EMA200 + VWAP + ATR default",
        mandatory=(
            _m("relative_volume", 10, min_relative_volume=1.2),
            _m("minimum_confidence", 20, min_confidence=0.55),
        ),
        default=(
            _d("ema200", 30),
            _d("vwap_confirmation", 40),
            _d("atr_stop", 50, atr_multiplier=2.0, require_stop_at_least_atr=False, enforce_stop=False),
        ),
        configurable=(
            _c("risk_reward", 60, min_risk_reward=1.5),
            _c("trending_market", 70),
        ),
        optional=(
            _o("liquidity", 80),
            _o("daily_confirmation", 90, only_when_requested=True),
        ),
    ),
}


def get_strategy_filter_profile(strategy_name: str) -> StrategyFilterProfile:
    """Return the research-default profile for ``strategy_name``."""
    key = strategy_name.strip()
    try:
        return STRATEGY_FILTER_PROFILES[key]
    except KeyError as exc:
        known = ", ".join(sorted(STRATEGY_FILTER_PROFILES))
        raise KeyError(
            f"No filter profile for strategy '{key}'. Known: {known}",
        ) from exc


def list_strategy_filter_profiles() -> list[str]:
    return list(STRATEGY_FILTER_PROFILES.keys())
