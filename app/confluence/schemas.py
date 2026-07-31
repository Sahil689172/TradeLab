"""Pydantic contracts for configurable confluence scoring."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ConfluenceVerdict(str, Enum):
    """Discrete confluence recommendation."""

    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class ConfluenceModule(str, Enum):
    """Scorable confluence modules."""

    EMA = "EMA"
    RSI = "RSI"
    VOLUME = "VOLUME"
    STRUCTURE = "STRUCTURE"
    ATR = "ATR"
    LEVELS = "LEVELS"
    TREND = "TREND"
    PRICE_ACTION = "PRICE_ACTION"
    INDICATOR_SIGNALS = "INDICATOR_SIGNALS"


class ModuleWeights(BaseModel):
    """Relative module weights (normalized to 100 at evaluation time).

    Defaults match the requested scorecard (sum 120) and are normalized so the
    final confluence total is expressed on a -100..100 scale.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ema: float = Field(default=20.0, ge=0.0)
    rsi: float = Field(default=15.0, ge=0.0)
    volume: float = Field(default=20.0, ge=0.0)
    structure: float = Field(default=20.0, ge=0.0)
    atr: float = Field(default=10.0, ge=0.0)
    levels: float = Field(default=15.0, ge=0.0)
    trend: float = Field(default=20.0, ge=0.0)
    price_action: float = Field(default=0.0, ge=0.0)
    indicator_signals: float = Field(default=0.0, ge=0.0)

    def as_mapping(self) -> dict[ConfluenceModule, float]:
        return {
            ConfluenceModule.EMA: self.ema,
            ConfluenceModule.RSI: self.rsi,
            ConfluenceModule.VOLUME: self.volume,
            ConfluenceModule.STRUCTURE: self.structure,
            ConfluenceModule.ATR: self.atr,
            ConfluenceModule.LEVELS: self.levels,
            ConfluenceModule.TREND: self.trend,
            ConfluenceModule.PRICE_ACTION: self.price_action,
            ConfluenceModule.INDICATOR_SIGNALS: self.indicator_signals,
        }

    @model_validator(mode="after")
    def require_positive_total(self) -> ModuleWeights:
        if sum(self.as_mapping().values()) <= 0:
            raise ValueError("At least one module weight must be > 0")
        return self


class VerdictThresholds(BaseModel):
    """Score thresholds on the normalized -100..100 total."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strong_buy: float = Field(default=60.0)
    buy: float = Field(default=25.0)
    sell: float = Field(default=-25.0)
    strong_sell: float = Field(default=-60.0)

    @model_validator(mode="after")
    def validate_order(self) -> VerdictThresholds:
        if not (
            self.strong_buy > self.buy > 0 > self.sell > self.strong_sell
        ):
            raise ValueError(
                "Thresholds must satisfy strong_buy > buy > 0 > sell > strong_sell",
            )
        return self


class ConfluenceConfig(BaseModel):
    """Fully configurable confluence scoring parameters."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    weights: ModuleWeights = Field(default_factory=ModuleWeights)
    thresholds: VerdictThresholds = Field(default_factory=VerdictThresholds)

    ema_fast_column: str = "ema_9"
    ema_slow_column: str = "ema_21"
    ema_trend_column: str = "ema_50"
    rsi_column: str = "rsi_14"
    volume_column: str = "relative_volume_20"
    atr_column: str = "atr_14"
    adx_column: str = "adx_14"
    close_column: str = "close"

    rsi_oversold: float = Field(default=30.0, ge=0.0, le=100.0)
    rsi_overbought: float = Field(default=70.0, ge=0.0, le=100.0)
    volume_high: float = Field(default=1.5, gt=0.0)
    volume_low: float = Field(default=0.8, gt=0.0)
    atr_expand_ratio: float = Field(default=1.2, gt=0.0)
    atr_lookback: int = Field(default=14, ge=2)
    levels_proximity_pct: float = Field(
        default=0.005,
        gt=0.0,
        lt=1.0,
        description="Fraction of price used to treat a level as nearby",
    )
    adx_trend_threshold: float = Field(default=20.0, ge=0.0)

    @model_validator(mode="after")
    def validate_rsi_bands(self) -> ConfluenceConfig:
        if self.rsi_oversold >= self.rsi_overbought:
            raise ValueError("rsi_oversold must be < rsi_overbought")
        if self.volume_low >= self.volume_high:
            raise ValueError("volume_low must be < volume_high")
        return self


class SignalContribution(BaseModel):
    """External indicator or price-action signal feeding confluence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(..., min_length=1)
    score: float = Field(..., ge=-1.0, le=1.0, description="Bearish -1 .. Bullish +1")
    reason: str = Field(..., min_length=1)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class ModuleScore(BaseModel):
    """Scorecard row for one confluence module."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    module: ConfluenceModule
    weight: float = Field(..., ge=0.0)
    normalized_weight: float = Field(..., ge=0.0, le=100.0)
    raw_score: float = Field(..., ge=-1.0, le=1.0)
    contribution: float = Field(
        ...,
        description="Weighted contribution toward the -100..100 total",
    )
    reason: str = Field(..., min_length=1)


class ConfluenceResult(BaseModel):
    """Final confluence verdict with explainable module breakdown."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    verdict: ConfluenceVerdict
    total_score: float = Field(..., ge=-100.0, le=100.0)
    modules: list[ModuleScore]
    explanation: str = Field(..., min_length=1)
    symbol: str | None = None
