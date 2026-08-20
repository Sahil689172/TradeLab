"""Read-only tools the room assistant may call.

Every tool here reads from ``MarketDataGateway`` (local Parquet/SQLite) or
from the room's shared paper book. There is deliberately no order-placement
tool: the model can see everything the humans see, but only a human can
press buy or sell. That boundary is enforced by this registry, not by
prompt wording.

Tool schemas are declared once in a provider-neutral form and translated
in ``providers.py`` into Gemini ``functionDeclarations`` or Groq/OpenAI
``tools`` payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd

from app.collab.room_service import RoomService
from app.core.config import Settings
from app.core.logging import get_logger
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.market_data.utils.symbols import parquet_basename
from app.services.dashboard.market_service import get_market_service

logger = get_logger(__name__)

MAX_HISTORY_BARS = 250


@dataclass
class ToolContext:
    """Everything the tools need to answer, bound to one room and turn."""

    room_id: str
    gateway: MarketDataGateway
    room_service: RoomService
    settings: Settings


@dataclass
class ToolSpec:
    """Provider-neutral description of a callable tool."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[[ToolContext, dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------


def _normalize(symbol: str) -> str:
    return parquet_basename(symbol).upper()


def _history(ctx: ToolContext, symbol: str) -> pd.DataFrame | None:
    yahoo = get_market_service().normalize_symbol(symbol)
    if not ctx.gateway.history_exists(yahoo):
        return None
    frame = ctx.gateway.get_history(yahoo)
    return None if frame.empty else frame


def _tool_get_latest_price(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return {"error": "symbol is required"}
    frame = _history(ctx, symbol)
    if frame is None:
        return {
            "symbol": _normalize(symbol),
            "available": False,
            "error": "No local history stored for this symbol. It must be bootstrapped first.",
        }
    last = frame.iloc[-1]
    prev_close = float(frame.iloc[-2]["close"]) if len(frame) > 1 else None
    close = float(last["close"])
    change_pct = ((close - prev_close) / prev_close * 100.0) if prev_close else None
    return {
        "symbol": _normalize(symbol),
        "available": True,
        "date": str(last.get("date")),
        "open": float(last["open"]),
        "high": float(last["high"]),
        "low": float(last["low"]),
        "close": close,
        "volume": float(last.get("volume", 0.0)),
        "previous_close": prev_close,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "note": "End-of-day stored history, not a live tick.",
    }


def _tool_get_price_history(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return {"error": "symbol is required"}
    try:
        bars = int(args.get("bars", 20))
    except (TypeError, ValueError):
        bars = 20
    bars = max(2, min(bars, MAX_HISTORY_BARS))

    frame = _history(ctx, symbol)
    if frame is None:
        return {
            "symbol": _normalize(symbol),
            "available": False,
            "error": "No local history stored for this symbol.",
        }

    window = frame.tail(bars)
    first_close = float(window.iloc[0]["close"])
    last_close = float(window.iloc[-1]["close"])
    change_pct = ((last_close - first_close) / first_close * 100.0) if first_close else 0.0

    # Summarise rather than dumping raw bars: keeps the prompt small and
    # stops the model from doing arithmetic it gets wrong.
    return {
        "symbol": _normalize(symbol),
        "available": True,
        "bars_returned": int(len(window)),
        "start_date": str(window.iloc[0].get("date")),
        "end_date": str(window.iloc[-1].get("date")),
        "start_close": round(first_close, 2),
        "end_close": round(last_close, 2),
        "change_pct": round(change_pct, 2),
        "period_high": round(float(window["high"].max()), 2),
        "period_low": round(float(window["low"].min()), 2),
        "average_close": round(float(window["close"].mean()), 2),
        "average_volume": round(float(window["volume"].mean()), 2) if "volume" in window else None,
        "recent_closes": [round(float(c), 2) for c in window["close"].tail(10).tolist()],
    }


def _tool_get_room_portfolio(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    _ = args
    portfolio = ctx.room_service.portfolio(ctx.room_id, gateway=ctx.gateway)
    kpis = portfolio.kpis
    return {
        "shared_portfolio": True,
        "initial_capital": round(kpis.initial_capital, 2),
        "available_cash": round(kpis.available_cash, 2),
        "total_invested": round(kpis.total_invested, 2),
        "current_value": round(kpis.current_value, 2),
        "unrealized_pnl": round(kpis.unrealized_pnl, 2),
        "realized_pnl": round(kpis.realized_pnl, 2),
        "exposure_pct": round(kpis.exposure_pct, 2),
        "open_position_count": len(portfolio.positions),
        "positions": [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "average_price": round(p.average_price, 2),
                "ltp": round(p.ltp, 2),
                "pnl": round(p.pnl, 2),
                "pnl_pct": round(p.pnl_pct * 100.0, 2),
                "stop_loss": p.stop_loss,
                "target": p.target,
            }
            for p in portfolio.positions
        ],
    }


def _tool_get_position(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    symbol = _normalize(str(args.get("symbol", "")).strip())
    if not symbol:
        return {"error": "symbol is required"}
    portfolio = ctx.room_service.portfolio(ctx.room_id, gateway=ctx.gateway)
    for p in portfolio.positions:
        if p.symbol.upper() == symbol:
            return {
                "symbol": p.symbol,
                "held": True,
                "quantity": p.quantity,
                "average_price": round(p.average_price, 2),
                "ltp": round(p.ltp, 2),
                "invested_value": round(p.invested_value, 2),
                "current_value": round(p.current_value, 2),
                "pnl": round(p.pnl, 2),
                "pnl_pct": round(p.pnl_pct * 100.0, 2),
                "stop_loss": p.stop_loss,
                "target": p.target,
            }
    return {"symbol": symbol, "held": False, "message": "This room holds no open position in this symbol."}


def _tool_get_recent_orders(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 50))
    rows = ctx.room_service.orders(ctx.room_id, limit=limit)
    return {
        "count": len(rows),
        "orders": [
            {
                "timestamp": str(r.timestamp),
                "symbol": r.symbol,
                "side": r.side.value if hasattr(r.side, "value") else str(r.side),
                "quantity": r.quantity,
                "price": round(r.price, 2),
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "rejection_reason": r.rejection_reason,
            }
            for r in rows
        ],
    }


def _tool_get_recent_trade_ideas(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 25))
    messages = ctx.room_service.recent_trade_ideas(ctx.room_id, limit=limit)
    ideas = []
    for message in messages:
        idea = message.trade_idea
        if idea is None:
            continue
        ideas.append(
            {
                "author": message.author,
                "posted_at": str(message.created_at),
                "symbol": idea.symbol.upper(),
                "direction": idea.direction.value,
                "thesis": idea.thesis,
                "entry": idea.entry,
                "stop_loss": idea.stop_loss,
                "target": idea.target,
                "price_at_post": idea.price_at_post,
            },
        )
    return {"count": len(ideas), "trade_ideas": ideas}


def _tool_get_strategy_analysis(ctx: ToolContext, args: dict[str, Any]) -> dict[str, Any]:
    symbol = str(args.get("symbol", "")).strip()
    if not symbol:
        return {"error": "symbol is required"}
    timeframe = str(args.get("timeframe", "1D")) or "1D"
    try:
        from app.services.dashboard.strategy_service import get_strategy_service

        analysis = get_strategy_service().analyze(
            symbol,
            timeframe=timeframe,
            storage_dir=str(ctx.settings.parquet_storage_dir),
            include_matrix=False,
        )
    except Exception as exc:  # noqa: BLE001 - surface as tool error, not a crash
        logger.warning("Strategy analysis tool failed for %s: %s", symbol, exc)
        return {"symbol": _normalize(symbol), "available": False, "error": str(exc)}

    signals = getattr(analysis, "signals", None) or []
    return {
        "symbol": _normalize(symbol),
        "timeframe": timeframe,
        "available": True,
        "signal_count": len(signals),
        "signals": [
            {
                "strategy": getattr(s, "strategy_name", None) or getattr(s, "name", None),
                "direction": _enum_value(getattr(s, "direction", None)),
                "triggered": getattr(s, "triggered", None),
                "confidence": getattr(s, "confidence", None),
            }
            for s in signals[:12]
        ],
    }


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="get_latest_price",
        description=(
            "Get the most recent stored end-of-day OHLCV bar for one Indian "
            "stock symbol, plus its change versus the previous close. Use this "
            "whenever a price is mentioned — never estimate a price yourself."
        ),
        parameters={
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "NSE symbol without suffix, e.g. RELIANCE, TCS, INFY.",
                },
            },
            "required": ["symbol"],
        },
        handler=_tool_get_latest_price,
    ),
    ToolSpec(
        name="get_price_history",
        description=(
            "Summarise recent stored price action for a symbol over the last N "
            "daily bars: start/end close, percentage change, period high/low, "
            "average close and volume, and the last ten closes."
        ),
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "NSE symbol, e.g. RELIANCE."},
                "bars": {
                    "type": "integer",
                    "description": "Number of recent daily bars to summarise (2-250, default 20).",
                },
            },
            "required": ["symbol"],
        },
        handler=_tool_get_price_history,
    ),
    ToolSpec(
        name="get_room_portfolio",
        description=(
            "Get this room's shared paper portfolio: cash, invested value, "
            "realised and unrealised P&L, exposure, and every open position. "
            "Use this before answering anything about what 'we' hold."
        ),
        parameters={"type": "object", "properties": {}},
        handler=_tool_get_room_portfolio,
    ),
    ToolSpec(
        name="get_position",
        description=(
            "Check whether this room holds an open position in one symbol, and "
            "if so at what average price, quantity, and current P&L."
        ),
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "NSE symbol, e.g. RELIANCE."},
            },
            "required": ["symbol"],
        },
        handler=_tool_get_position,
    ),
    ToolSpec(
        name="get_recent_orders",
        description="List the most recent paper orders placed in this room, filled or rejected.",
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many orders to return (1-50)."},
            },
        },
        handler=_tool_get_recent_orders,
    ),
    ToolSpec(
        name="get_recent_trade_ideas",
        description=(
            "List structured trade ideas members posted in this room, including "
            "the price at the time each was posted, so calls can be reviewed."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "How many ideas to return (1-25)."},
            },
        },
        handler=_tool_get_recent_trade_ideas,
    ),
    ToolSpec(
        name="get_strategy_analysis",
        description=(
            "Run TradeLab's own strategy engine on a symbol and return which "
            "strategies currently signal, with direction and confidence."
        ),
        parameters={
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "NSE symbol, e.g. RELIANCE."},
                "timeframe": {"type": "string", "description": "Timeframe code, default 1D."},
            },
            "required": ["symbol"],
        },
        handler=_tool_get_strategy_analysis,
    ),
]

TOOLS_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}


def execute_tool(name: str, args: dict[str, Any], ctx: ToolContext) -> dict[str, Any]:
    """Run one tool by name, returning a JSON-serialisable result.

    Unknown names and handler exceptions are returned as ``error`` payloads
    so a bad tool call degrades into a correction the model can read,
    rather than failing the whole turn.
    """
    spec = TOOLS_BY_NAME.get(name)
    if spec is None:
        return {"error": f"Unknown tool '{name}'. Available: {sorted(TOOLS_BY_NAME)}"}
    try:
        return spec.handler(ctx, args or {})
    except Exception as exc:  # noqa: BLE001 - tool errors must not kill the turn
        logger.exception("Tool %s failed", name)
        return {"error": f"Tool '{name}' failed: {exc}"}
