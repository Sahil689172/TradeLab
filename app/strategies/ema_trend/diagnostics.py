"""Filter rejection diagnostics for professional EMA (reusable pattern)."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class RejectionFilter(str, Enum):
    """Named gate that rejected a raw crossover signal."""

    EMA200 = "EMA200"
    ADX = "ADX"
    VOLUME = "Volume"
    ATR = "ATR"
    CONFIRM_ON_CLOSE = "ConfirmOnClose"
    DUPLICATE = "Duplicate"
    OTHER = "Other"


class FilterRejection(BaseModel):
    """One rejected raw signal with audit trail."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime
    symbol: str
    raw_signal: str
    reason: str
    rejected_by: RejectionFilter


class SignalFunnel(BaseModel):
    """Raw → filter → final signal funnel for one evaluation or aggregate."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    raw_buy: int = Field(default=0, ge=0)
    raw_sell: int = Field(default=0, ge=0)
    rejected_ema200: int = Field(default=0, ge=0)
    rejected_adx: int = Field(default=0, ge=0)
    rejected_volume: int = Field(default=0, ge=0)
    rejected_atr: int = Field(default=0, ge=0)
    rejected_other: int = Field(default=0, ge=0)
    final_buy: int = Field(default=0, ge=0)
    final_sell: int = Field(default=0, ge=0)

    @property
    def raw_actionable(self) -> int:
        return self.raw_buy + self.raw_sell

    @property
    def final_actionable(self) -> int:
        return self.final_buy + self.final_sell

    @property
    def total_rejected(self) -> int:
        return (
            self.rejected_ema200
            + self.rejected_adx
            + self.rejected_volume
            + self.rejected_atr
            + self.rejected_other
        )

    @property
    def buy_rejected_total(self) -> int:
        """Entry (BUY) rejections. After A4Y.1.6 exits never reach these gates,
        so all rejection buckets belong to the BUY entry funnel."""
        return self.total_rejected

    @property
    def buy_acceptance_rate(self) -> float:
        if self.raw_buy <= 0:
            return 0.0
        return self.final_buy / self.raw_buy

    @property
    def sell_exit_rate(self) -> float:
        """Fraction of raw SELL crossovers that became exits (should be ~1.0)."""
        if self.raw_sell <= 0:
            return 0.0
        return self.final_sell / self.raw_sell

    @property
    def acceptance_rate(self) -> float:
        raw = self.raw_actionable
        if raw <= 0:
            return 0.0
        return self.final_actionable / raw

    @property
    def rejection_rate(self) -> float:
        raw = self.raw_actionable
        if raw <= 0:
            return 0.0
        return self.total_rejected / raw

    def merge(self, other: SignalFunnel) -> SignalFunnel:
        return SignalFunnel(
            raw_buy=self.raw_buy + other.raw_buy,
            raw_sell=self.raw_sell + other.raw_sell,
            rejected_ema200=self.rejected_ema200 + other.rejected_ema200,
            rejected_adx=self.rejected_adx + other.rejected_adx,
            rejected_volume=self.rejected_volume + other.rejected_volume,
            rejected_atr=self.rejected_atr + other.rejected_atr,
            rejected_other=self.rejected_other + other.rejected_other,
            final_buy=self.final_buy + other.final_buy,
            final_sell=self.final_sell + other.final_sell,
        )


def empty_funnel() -> SignalFunnel:
    return SignalFunnel()


def format_buy_sell_funnels(funnel: SignalFunnel) -> str:
    """Render separate BUY (entry) and SELL (exit) funnels (A4Y.1.6 #4).

    Entry filters only ever reject BUY signals; SELL signals are exits and are
    never blocked by EMA200 / ADX / Volume / Duplicate suppression.
    """
    lines = [
        "BUY Funnel (entry filters):",
        f"  Raw BUY:            {funnel.raw_buy}",
        f"  - Rejected EMA200:  {funnel.rejected_ema200}",
        f"  - Rejected ADX:     {funnel.rejected_adx}",
        f"  - Rejected Volume:  {funnel.rejected_volume}",
        f"  - Rejected ATR:     {funnel.rejected_atr}",
        f"  - Rejected Other:   {funnel.rejected_other}",
        f"  Final BUY:          {funnel.final_buy}",
        f"  Acceptance rate:    {funnel.buy_acceptance_rate:.1%}",
        "SELL Funnel (exits — never blocked by entry filters):",
        f"  Raw SELL:           {funnel.raw_sell}",
        f"  Final SELL (exits): {funnel.final_sell}",
        f"  Exit rate:          {funnel.sell_exit_rate:.1%}",
    ]
    return "\n".join(lines)
