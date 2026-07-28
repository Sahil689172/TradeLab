"""API request and response schemas for market ingestion endpoints."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.market_data.schemas.company_metadata import CompanyMetadata
from app.market_data.schemas.ingestion_state import IngestionState


class SymbolBatchRequest(BaseModel):
    """Request body for batch bootstrap or update operations."""

    model_config = ConfigDict(extra="forbid")

    symbols: list[str] = Field(..., min_length=1)


class IngestionOperationResult(BaseModel):
    """Public response for bootstrap, update, and metadata refresh operations."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    status: str
    rows_downloaded: int = 0
    rows_added: int = 0
    message: str
    metadata: CompanyMetadata | None = None
    ingestion_state: IngestionState | None = None


class MarketStatusResponse(BaseModel):
    """Current storage and ingestion status for a symbol."""

    model_config = ConfigDict(extra="forbid")

    symbol: str
    history_exists: bool
    metadata: CompanyMetadata | None = None
    ingestion_state: IngestionState | None = None
