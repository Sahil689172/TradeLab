"""Dashboard REST endpoints for stocks, strategies, portfolio, and paper orders."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_app_settings, get_market_data_gateway
from app.core.config import Settings
from app.market_data.services.market_data_gateway import MarketDataGateway
from app.schemas.responses import SuccessResponse
from app.services.dashboard.market_service import get_market_service
from app.services.dashboard.paper_trading_service import get_paper_book
from app.services.dashboard.portfolio_service import PortfolioService
from app.services.dashboard.schemas import (
    OHLCVResponse,
    OrderRequest,
    OrderResponse,
    OrderRow,
    OrderSide,
    PortfolioResponse,
    RefreshStatus,
    StockListResponse,
    StockSummary,
    StrategyAnalysisResponse,
    StrategyCatalogItem,
    SystemStatus,
)
from app.services.dashboard.strategy_service import get_strategy_service
from app.services.dashboard.universe_service import get_universe_service

router = APIRouter(tags=["dashboard"])


@router.get("/stocks", response_model=SuccessResponse[StockListResponse])
def list_stocks(
    q: str = Query(default="", max_length=64),
    limit: int = Query(default=500, ge=1, le=501),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[StockListResponse]:
    book = get_paper_book()
    holdings = {p.symbol for p in book.broker.snapshot().positions.values() if p.is_open}
    stocks = get_universe_service().list_stocks(
        gateway=gateway,
        query=q,
        holdings=holdings,
        watchlist=book.watchlist,
        favorites=book.favorites,
        limit=limit,
    )
    return SuccessResponse(data=StockListResponse(total=len(stocks), stocks=stocks))


@router.get("/stocks/{symbol}", response_model=SuccessResponse[StockSummary])
def get_stock(
    symbol: str,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[StockSummary]:
    stock = get_universe_service().get_stock(symbol, gateway=gateway)
    if stock is None:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not in supported universe")
    return SuccessResponse(data=stock)


@router.get("/stocks/{symbol}/ohlcv", response_model=SuccessResponse[OHLCVResponse])
def get_ohlcv(
    symbol: str,
    interval: str = Query(default="1D"),
    limit: int = Query(default=300, ge=10, le=2000),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[OHLCVResponse]:
    data = get_market_service().get_ohlcv(symbol, interval=interval, gateway=gateway, limit=limit)
    return SuccessResponse(data=data)


@router.post("/market-data/refresh", response_model=SuccessResponse[RefreshStatus])
def refresh_market_data(
    symbol: str | None = Query(default=None),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[RefreshStatus]:
    market = get_market_service()
    if symbol:
        status = market.refresh_symbol(symbol, gateway=gateway)
    else:
        book = get_paper_book()
        holdings = list({p.symbol for p in book.broker.snapshot().positions.values() if p.is_open})
        sample = holdings[:5] if holdings else ["RELIANCE"]
        status = market.refresh_universe_sample(sample, gateway=gateway)
    return SuccessResponse(data=status, message=status.message)


@router.get("/strategies", response_model=SuccessResponse[list[StrategyCatalogItem]])
def list_strategies() -> SuccessResponse[list[StrategyCatalogItem]]:
    return SuccessResponse(data=get_strategy_service().catalog())


@router.get("/strategies/{symbol}/analysis", response_model=SuccessResponse[StrategyAnalysisResponse])
def strategy_analysis(
    symbol: str,
    timeframe: str = Query(default="1D"),
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[StrategyAnalysisResponse]:
    analysis = get_strategy_service().analyze(
        symbol,
        timeframe=timeframe,
        storage_dir=str(settings.parquet_storage_dir),
    )
    return SuccessResponse(data=analysis)


@router.get("/strategies/{symbol}/timeframes", response_model=SuccessResponse[StrategyAnalysisResponse])
def strategy_timeframes(
    symbol: str,
    settings: Settings = Depends(get_app_settings),
) -> SuccessResponse[StrategyAnalysisResponse]:
    analysis = get_strategy_service().analyze(
        symbol,
        timeframe="1D",
        storage_dir=str(settings.parquet_storage_dir),
    )
    return SuccessResponse(data=analysis)


@router.get("/portfolio", response_model=SuccessResponse[PortfolioResponse])
def get_portfolio(
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[PortfolioResponse]:
    book = get_paper_book()
    data = PortfolioService(book).build(gateway=gateway)
    return SuccessResponse(data=data)


@router.get("/positions", response_model=SuccessResponse[PortfolioResponse])
def get_positions(
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[PortfolioResponse]:
    return get_portfolio(gateway=gateway)


@router.get("/orders", response_model=SuccessResponse[list[OrderRow]])
def list_orders() -> SuccessResponse[list[OrderRow]]:
    book = get_paper_book()
    from app.services.dashboard.paper_trading_service import _to_order_row

    rows = [_to_order_row(record) for record in book.orders]
    return SuccessResponse(data=rows)


@router.post("/orders/buy", response_model=SuccessResponse[OrderResponse])
def buy_order(
    request: OrderRequest,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[OrderResponse]:
    market = get_market_service()
    price = request.price or market.latest_close(request.symbol, gateway=gateway)
    if price is None or price <= 0:
        raise HTTPException(status_code=400, detail="No market price available; bootstrap symbol or pass price")
    result = get_paper_book().place_order(
        side=OrderSide.BUY,
        request=request,
        market_price=price,
    )
    return SuccessResponse(data=result, message=result.message)


@router.post("/orders/sell", response_model=SuccessResponse[OrderResponse])
def sell_order(
    request: OrderRequest,
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[OrderResponse]:
    from app.services.dashboard.schemas import OrderSide as ApiOrderSide

    market = get_market_service()
    price = request.price or market.latest_close(request.symbol, gateway=gateway)
    if price is None or price <= 0:
        raise HTTPException(status_code=400, detail="No market price available; bootstrap symbol or pass price")
    result = get_paper_book().place_order(
        side=ApiOrderSide.SELL,
        request=request,
        market_price=price,
    )
    return SuccessResponse(data=result, message=result.message)


@router.get("/risk", response_model=SuccessResponse[PortfolioResponse])
def get_risk(
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[PortfolioResponse]:
    return get_portfolio(gateway=gateway)


@router.get("/system/status", response_model=SuccessResponse[SystemStatus])
def system_status(
    settings: Settings = Depends(get_app_settings),
    gateway: MarketDataGateway = Depends(get_market_data_gateway),
) -> SuccessResponse[SystemStatus]:
    market = get_market_service()
    return SuccessResponse(
        data=SystemStatus(
            backend_connected=True,
            market_data_source="yfinance",
            yfinance_status="available",
            universe_size=get_universe_service().count(),
            paper_trading=True,
            last_refresh=market.last_refresh,
            environment=settings.app_env,
        ),
    )
