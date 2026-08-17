"""Pydantic contracts for the TradeLab trading dashboard API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DashboardSignal(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


class AssumptionBias(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderStatus(str, Enum):
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


class StockSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    yahoo_symbol: str
    company_name: str
    sector: str | None = None
    industry: str | None = None
    last_price: float | None = None
    daily_change_pct: float | None = None
    history_available: bool = False
    last_data_date: datetime | None = None
    is_watchlist: bool = False
    is_favorite: bool = False
    is_holding: bool = False


class StockListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total: int
    stocks: list[StockSummary]


class OHLCVBar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    adj_close: float | None = None


class OHLCVResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    interval: str
    interval_label: str
    bars: list[OHLCVBar]
    source: str = "local_parquet"
    delayed: bool = True
    last_bar_timestamp: datetime | None = None
    message: str = ""


class StrategyCatalogItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    display_name: str
    description: str = ""


class StrategySignalRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: str
    display_name: str
    best_timeframe: str
    signal: DashboardSignal
    confidence: float = Field(..., ge=0.0, le=100.0, description="Historical/model confidence (0–100), not future profit probability")
    confidence_label: str = "Historical/Model Confidence"
    strength: str
    status: str
    sample_size: int = 0
    evaluation_window: str = ""
    last_evaluated: datetime | None = None
    reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: str | None = None


class TimeframeBestStrategy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval: str
    interval_label: str
    supported: bool
    best_strategy: str | None = None
    best_strategy_display: str | None = None
    signal: DashboardSignal | None = None
    confidence: float | None = None
    confidence_label: str = "Historical/Model Confidence"
    supporting_metric: str = ""
    sample_size: int = 0
    last_evaluated: datetime | None = None
    message: str = ""


class CurrentAssumption(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    timeframe: str
    bias: AssumptionBias
    confidence: float | None = None
    confidence_label: str = "Historical/Model Confidence"
    supporting_strategies: list[str] = Field(default_factory=list)
    supporting_indicators: list[str] = Field(default_factory=list)
    evaluation_window: str = ""
    sample_size: int = 0
    last_updated: datetime | None = None
    explanation: str = ""


class StrategyAnalysisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    timeframe: str
    generated_at: datetime
    strategies: list[StrategySignalRow]
    timeframe_matrix: list[TimeframeBestStrategy]
    assumption: CurrentAssumption
    data_note: str = ""


class PortfolioKPIs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_invested: float
    current_value: float
    unrealized_pnl: float
    realized_pnl: float
    available_cash: float
    todays_pnl: float
    initial_capital: float
    exposure_pct: float
    max_drawdown_pct: float = 0.0


class PositionRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    quantity: float
    average_price: float
    ltp: float | None = None
    invested_value: float
    current_value: float
    pnl: float
    pnl_pct: float
    stop_loss: float | None = None
    target: float | None = None
    exposure_pct: float = 0.0
    strategy_name: str = ""


class PortfolioResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kpis: PortfolioKPIs
    positions: list[PositionRow]
    per_symbol_pnl: dict[str, float] = Field(default_factory=dict)


class OrderRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: str
    timestamp: datetime
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    order_type: str = "MARKET"
    status: OrderStatus
    rejection_reason: str | None = None
    strategy_name: str = "paper_manual"


class OrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    quantity: float = Field(..., gt=0.0)
    order_type: str = "MARKET"
    price: float | None = Field(default=None, gt=0.0)
    stop_loss: float | None = Field(default=None, gt=0.0)
    target: float | None = Field(default=None, gt=0.0)


class OrderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool
    status: OrderStatus
    message: str
    order: OrderRow | None = None
    portfolio: PortfolioKPIs | None = None


class RefreshStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    success: bool
    in_progress: bool = False
    message: str
    last_refresh: datetime | None = None
    symbols_updated: int = 0
    symbols_failed: int = 0


class SystemStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    backend_connected: bool = True
    market_data_source: str = "yfinance"
    yfinance_status: str = "unknown"
    universe_size: int = 0
    paper_trading: bool = True
    last_refresh: datetime | None = None
    environment: str = "development"
