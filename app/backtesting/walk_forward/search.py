"""Declared candidate grid. Does not invent extra parameters."""

from __future__ import annotations

from collections.abc import Iterator

from app.backtesting.walk_forward.exceptions import WalkForwardConfigError
from app.backtesting.walk_forward.schemas import SearchSpace
from app.strategies.ema_trend import EMATrendConfig
from app.strategies.ema_trend.presets import EMA_PAIR_PRESETS


def iter_candidates(space: SearchSpace, *, symbol: str, min_history_bars: int) -> Iterator[EMATrendConfig]:
    produced = 0
    pairs: list[tuple[int, int]] = []
    if space.fast_emas and space.slow_emas:
        for fast in space.fast_emas:
            for slow in space.slow_emas:
                if fast < slow:
                    pairs.append((int(fast), int(slow)))
    else:
        for preset in space.ema_pair_presets:
            key = str(preset).strip().lower().replace("/", "_").replace("-", "_")
            if key not in EMA_PAIR_PRESETS:
                raise WalkForwardConfigError(
                    f"Unknown ema_pair_preset '{preset}'. Known: {sorted(EMA_PAIR_PRESETS)}",
                )
            pairs.append(EMA_PAIR_PRESETS[key])
    seen: set[tuple[int, int, float, bool]] = set()
    adx_values = space.adx_thresholds or (20.0,)
    ema200_values = space.ema200_filters or (True,)
    for fast, slow in pairs:
        for adx in adx_values:
            for ema200 in ema200_values:
                key = (fast, slow, float(adx), bool(ema200))
                if key in seen:
                    continue
                seen.add(key)
                produced += 1
                if produced > space.max_candidates:
                    raise WalkForwardConfigError(
                        f"search space has more than {space.max_candidates} candidates; "
                        "narrow --fast/--slow/--adx or raise max_candidates",
                    )
                yield EMATrendConfig.professional(
                    symbol=symbol,
                    fast_ema=fast,
                    slow_ema=slow,
                    ema_pair_preset=None,
                    adx_threshold=float(adx),
                    ema200_filter=bool(ema200),
                    min_history_bars=min_history_bars,
                )


def config_key(config: EMATrendConfig) -> str:
    return (
        f"fast={config.fast_ema},slow={config.slow_ema},"
        f"adx={config.adx_threshold:g},ema200={int(config.ema200_filter)}"
    )


def config_params(config: EMATrendConfig) -> dict[str, str | int | float | bool]:
    return {
        "fast_ema": config.fast_ema,
        "slow_ema": config.slow_ema,
        "adx_threshold": config.adx_threshold,
        "ema200_filter": config.ema200_filter,
        "mode": config.mode,
    }
