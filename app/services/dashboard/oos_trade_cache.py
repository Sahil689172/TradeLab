"""Disk cache for walk-forward out-of-sample trade sets.

Why this exists
---------------
Producing the OOS trade population for a symbol means running a full
walk-forward pass: every window replays its train span once per candidate
parameter set, then replays its test span with the frozen winner.  That is a
batch computation measured in minutes, and the dashboard was re-running it from
scratch on *every* Monte Carlo request.

The trade set is a pure function of (symbol, strategy, walk-forward settings,
underlying OHLCV data), so it is safe to memoize on disk.  The cache key
includes the OHLCV file's size and modification time, so refreshing or
re-bootstrapping a symbol invalidates its entry automatically rather than
serving trades derived from stale bars.

What is cached is only *completed out-of-sample trades* -- the same objects the
walk-forward engine returns from its test windows.  Nothing about train/test
isolation changes: the isolation is enforced upstream while the trades are
produced, and this layer just avoids paying for that work twice.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.backtesting.monte_carlo.schemas import MonteCarloTrade
from app.core.logging import get_logger

logger = get_logger(__name__)

# Bump when the cached payload shape or the semantics of what is stored change,
# so stale entries written by an older build are ignored rather than trusted.
CACHE_VERSION = "a5.10-oos-1"


@dataclass(frozen=True)
class CachedOOSTrades:
    """A cached OOS trade set plus the provenance needed to explain it."""

    trades: list[MonteCarloTrade]
    period: str
    window_count: int
    strategy_alias: str
    created_at: str

    @property
    def trade_count(self) -> int:
        return len(self.trades)


def _data_fingerprint(parquet: Path) -> str:
    """Identify the underlying bars without reading them.

    ``st_mtime_ns`` plus size changes whenever the symbol is refreshed or
    re-bootstrapped, which is exactly when previously derived trades stop being
    valid.
    """
    try:
        stat = parquet.stat()
    except OSError:
        return "missing"
    return f"{stat.st_size}:{stat.st_mtime_ns}"


def cache_key(
    *,
    symbol: str,
    strategy_alias: str,
    config_fingerprint: str,
    parquet: Path,
) -> str:
    raw = "|".join(
        (
            CACHE_VERSION,
            symbol.strip().upper(),
            strategy_alias.strip().lower(),
            config_fingerprint,
            _data_fingerprint(parquet),
        ),
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{symbol.strip().upper()}_{strategy_alias.strip().lower()}_{digest}"


class OOSTradeCache:
    """JSON-file cache of walk-forward OOS trade sets."""

    def __init__(self, directory: Path) -> None:
        self._directory = Path(directory)

    def _path(self, key: str) -> Path:
        return self._directory / f"{key}.json"

    def get(self, key: str) -> CachedOOSTrades | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Discarding unreadable OOS cache entry %s", path.name)
            return None
        if payload.get("cache_version") != CACHE_VERSION:
            return None
        try:
            trades = [MonteCarloTrade(**row) for row in payload.get("trades", [])]
        except (TypeError, ValueError):
            logger.warning("Discarding OOS cache entry with bad trades: %s", path.name)
            return None
        return CachedOOSTrades(
            trades=trades,
            period=str(payload.get("period", "")),
            window_count=int(payload.get("window_count", 0)),
            strategy_alias=str(payload.get("strategy_alias", "")),
            created_at=str(payload.get("created_at", "")),
        )

    def put(
        self,
        key: str,
        *,
        trades: list[MonteCarloTrade],
        period: str,
        window_count: int,
        strategy_alias: str,
    ) -> CachedOOSTrades:
        entry = CachedOOSTrades(
            trades=list(trades),
            period=period,
            window_count=window_count,
            strategy_alias=strategy_alias,
            created_at=datetime.now(UTC).isoformat(),
        )
        payload = {
            "cache_version": CACHE_VERSION,
            "created_at": entry.created_at,
            "strategy_alias": strategy_alias,
            "period": period,
            "window_count": window_count,
            "trade_count": len(entry.trades),
            "trades": [trade.model_dump(mode="json") for trade in entry.trades],
        }
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
            # Write via a temp file so a crash mid-write cannot leave a
            # half-written entry that later reads would treat as valid.
            tmp = self._path(key).with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(payload, sort_keys=True, allow_nan=False),
                encoding="utf-8",
            )
            tmp.replace(self._path(key))
        except OSError as exc:
            # A cache that cannot be written must not break the request.
            logger.warning("Could not write OOS cache entry %s: %s", key, exc)
        return entry

    def clear(self) -> None:
        if not self._directory.exists():
            return
        for path in self._directory.glob("*.json"):
            try:
                path.unlink()
            except OSError:
                continue
