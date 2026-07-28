"""Market data ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_market_data_gateway
from app.market_data.schemas import (
    IngestionOperationResult,
    MarketStatusResponse,
    SymbolBatchRequest,
)
from app.market_data.services import MarketDataGateway
from app.schemas.responses import SuccessResponse

router = APIRouter(prefix="/market", tags=["Market Data"])


@router.post("/bootstrap/all", response_model=SuccessResponse[list[IngestionOperationResult]])
def bootstrap_all(
    request: SymbolBatchRequest,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[list[IngestionOperationResult]]:
    """Bootstrap multiple symbols via the market data gateway."""
    result = gateway.bootstrap_all(request.symbols)
    return SuccessResponse(success=True, data=result, message="Batch bootstrap completed")


@router.post("/bootstrap/{symbol}", response_model=SuccessResponse[IngestionOperationResult])
def bootstrap_symbol(
    symbol: str,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[IngestionOperationResult]:
    """Bootstrap one symbol via the market data gateway."""
    result = gateway.bootstrap_symbol(symbol)
    return SuccessResponse(success=True, data=result, message="Bootstrap completed")


@router.post("/update/all", response_model=SuccessResponse[list[IngestionOperationResult]])
def update_all(
    request: SymbolBatchRequest,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[list[IngestionOperationResult]]:
    """Incrementally update multiple symbols via the market data gateway."""
    result = gateway.update_all(request.symbols)
    return SuccessResponse(success=True, data=result, message="Batch update completed")


@router.post("/update/{symbol}", response_model=SuccessResponse[IngestionOperationResult])
def update_symbol(
    symbol: str,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[IngestionOperationResult]:
    """Incrementally update one symbol via the market data gateway."""
    result = gateway.update_symbol(symbol)
    return SuccessResponse(success=True, data=result, message="Update completed")


@router.post("/metadata/{symbol}", response_model=SuccessResponse[IngestionOperationResult])
def refresh_metadata(
    symbol: str,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[IngestionOperationResult]:
    """Refresh metadata for one symbol via the market data gateway."""
    result = gateway.refresh_metadata(symbol)
    return SuccessResponse(success=True, data=result, message="Metadata refreshed")


@router.get("/status/{symbol}", response_model=SuccessResponse[MarketStatusResponse])
def get_status(
    symbol: str,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[MarketStatusResponse]:
    """Return current market data storage status for one symbol."""
    result = gateway.get_status(symbol)
    return SuccessResponse(success=True, data=result, message="Status retrieved")
